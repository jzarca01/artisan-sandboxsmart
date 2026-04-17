import unittest
from unittest.mock import Mock, patch, AsyncMock, call, PropertyMock
import asyncio
import json
import time
from queue import Queue
from websockets.exceptions import ConnectionClosed
from bleak import BleakClient
from bleak.backends.device import BLEDevice
from artisan_sandboxsmart.controller import RoasterController, HSTOP
from artisan_sandboxsmart.server import RoasterWebSocketServer
from artisan_sandboxsmart.cli_ws import WebSocketRoasterCLI

def async_test(coro):
    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))
    return wrapper

class TestRoasterController(unittest.TestCase):
    def setUp(self):
        self.controller = RoasterController()
        
    def test_has_numbers(self):
        self.assertTrue(self.controller.has_numbers("HEAT 50"))
        self.assertFalse(self.controller.has_numbers("HSTOP"))
        self.assertTrue(self.controller.has_numbers("HPSTART 1200 200"))
        self.assertFalse(self.controller.has_numbers("LIGHT ON"))
        self.assertTrue(self.controller.has_numbers("DRAW 75"))
        
    def test_update_temperatures_preheating(self):
        # Test preheating temperature update (PT)
        data = bytearray.fromhex('50540000007800')  # PT with temp 120 (0x78)
        temp = self.controller.update_temperatures(data)
        self.assertEqual(temp, 120)
        self.assertEqual(self.controller.environment_temperature, 120)
        
    def test_update_temperatures_roasting(self):
        # Test roasting temperature update (CT)
        data = bytearray.fromhex('43540000009600')  # CT with temp 150 (0x96)
        temp = self.controller.update_temperatures(data)
        self.assertEqual(temp, 150)
        self.assertEqual(self.controller.bean_temperature, 150)

    def test_update_temperatures_cooling(self):
        # Test cooling temperature update (CL)
        data = bytearray.fromhex('434c0000003200')  # CL with temp 50 (0x32)
        temp = self.controller.update_temperatures(data)
        self.assertEqual(temp, 50)
        self.assertEqual(self.controller.environment_temperature, 50)

    def test_update_temperatures_invalid_data(self):
        # Test invalid data format
        data = bytearray.fromhex('0000')
        temp = self.controller.update_temperatures(data)
        self.assertIsNone(temp)

    def test_et_ror_first_reading_is_none(self):
        data = bytearray.fromhex('50540000007800')  # PT temp=120
        self.controller.update_temperatures(data)
        self.assertIsNone(self.controller.et_ror)

    def test_et_ror_computed_on_second_reading(self):
        # Première lecture : ET=120
        with patch('time.monotonic', return_value=100.0):
            self.controller.update_temperatures(bytearray.fromhex('50540000007800'))  # 0x78 = 120
        # Deuxième lecture 30s plus tard : ET=150 → RoR = (150-120)/30*60 = 60°/min
        with patch('time.monotonic', return_value=130.0):
            self.controller.update_temperatures(bytearray.fromhex('50540000009600'))  # 0x96 = 150
        self.assertEqual(self.controller.et_ror, 60.0)

    def test_bt_ror_first_reading_is_none(self):
        data = bytearray.fromhex('43540000009600')  # CT temp=150
        self.controller.update_temperatures(data)
        self.assertIsNone(self.controller.bt_ror)

    def test_bt_ror_computed_on_second_reading(self):
        # Première lecture : BT=150
        with patch('time.monotonic', return_value=200.0):
            self.controller.update_temperatures(bytearray.fromhex('43540000009600'))  # 0x96 = 150
        # Deuxième lecture 10s plus tard : BT=160 → RoR = (160-150)/10*60 = 60°/min
        with patch('time.monotonic', return_value=210.0):
            self.controller.update_temperatures(bytearray.fromhex('434400000100a000'.replace('4344', '4354')[:14]))
        # Utilisons un hex plus simple : CT avec temp=160 (0x00A0)
        with patch('time.monotonic', return_value=210.0):
            self.controller._last_bt = 150
            self.controller._last_bt_time = 200.0
            self.controller.update_temperatures(bytearray.fromhex('435400000000a0'))  # 0xa0 = 160
        self.assertEqual(self.controller.bt_ror, 60.0)

    def test_et_ror_cooling_phase(self):
        # CL phase aussi met à jour et_ror
        with patch('time.monotonic', return_value=300.0):
            self.controller.update_temperatures(bytearray.fromhex('434c0000006400'))  # CL temp=100
        with patch('time.monotonic', return_value=360.0):
            self.controller.update_temperatures(bytearray.fromhex('434c0000005000'))  # CL temp=80
        # (80-100)/60*60 = -20°/min
        self.assertEqual(self.controller.et_ror, -20.0)

    def test_ror_zero_when_temp_stable(self):
        with patch('time.monotonic', return_value=0.0):
            self.controller.update_temperatures(bytearray.fromhex('50540000007800'))  # PT 120
        with patch('time.monotonic', return_value=30.0):
            self.controller.update_temperatures(bytearray.fromhex('50540000007800'))  # PT 120
        self.assertEqual(self.controller.et_ror, 0.0)

    def test_add_command(self):
        # Test normal command
        self.controller.add_command("HEAT 50")
        self.assertEqual(self.controller.command_queue.get_nowait(), "HEAT 50")
        
        # Test EXIT command
        self.controller.add_command("EXIT")
        self.assertFalse(self.controller.running)
        self.assertEqual(self.controller.command_queue.get_nowait(), HSTOP)

        # Test multiple commands
        self.controller.add_command("DRUM 75")
        self.controller.add_command("DRAW 80")
        self.assertEqual(self.controller.command_queue.get_nowait(), "DRUM 75")
        self.assertEqual(self.controller.command_queue.get_nowait(), "DRAW 80")


    @async_test
    async def test_send_command(self):
        # Create a mock BLEDevice
        mock_device = BLEDevice(
            address="11:22:33:44:55:66",
            name="MockRoaster",
            details={},
            rssi=-60
        )

        with patch('bleak.BleakClient') as mock_client_class:
            # Setup mock client
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            self.controller.client = mock_client

            # Test simple command
            await self.controller.send_command("HSTOP")
            mock_client.write_gatt_char.assert_called_with(
                "0000ffa0-0000-1000-8000-00805f9b34fb",
                b'HSTOP',
                response=False
            )

            # Test command with value
            await self.controller.send_command("HEAT", "50")
            mock_client.write_gatt_char.assert_called_with(
                "0000ffa0-0000-1000-8000-00805f9b34fb",
                b'HEAT2',  # 50 in hex is 0x32
                response=False
            )

            # Test command with multiple values
            await self.controller.send_command("HPSTART", ("1200", "200"))
            mock_client.write_gatt_char.assert_called_with(
                "0000ffa0-0000-1000-8000-00805f9b34fb",
                b'HPSTART\x04\xb0\x00\xc8',  # 1200 and 200 in hex
                response=False
            )

class TestRoasterWebSocketServer(unittest.TestCase):
    def setUp(self):
        self.server = RoasterWebSocketServer()
        
    def test_convert_data_for_json(self):
        # Test bytearray conversion
        data = bytearray([1, 2, 3])
        result = self.server.convert_data_for_json(data)
        self.assertEqual(result, [1, 2, 3])
        
        # Test nested dictionary conversion
        nested_data = {
            'bytes': bytes([4, 5, 6]),
            'list': [bytearray([7, 8]), 'text'],
            'normal': 42
        }
        result = self.server.convert_data_for_json(nested_data)
        expected = {
            'bytes': [4, 5, 6],
            'list': [[7, 8], 'text'],
            'normal': 42
        }
        self.assertEqual(result, expected)

    @async_test
    async def test_register_unregister(self):
        mock_websocket = AsyncMock()
        # Test client registration
        await self.server.register(mock_websocket)
        self.assertEqual(len(self.server.clients), 1)
        self.assertIn(mock_websocket, self.server.clients)
        
        # Test client unregistration
        await self.server.unregister(mock_websocket)
        self.assertEqual(len(self.server.clients), 0)
        self.assertNotIn(mock_websocket, self.server.clients)

    @async_test
    async def test_process_websocket_messages(self):
        self.server.running = True
        self.server.controller = AsyncMock()

        # Test valid command message
        mock_websocket = AsyncMock()
        await self.server._websocket_message_queue.put(
            (mock_websocket, json.dumps({"pushMessage": "HEAT 50"}))
        )
        
        # Start processing task
        task = asyncio.create_task(self.server.process_websocket_messages())
        await asyncio.sleep(0.1)  # Allow task to process message
        
        # Verify controller command was called
        self.server.controller.add_command.assert_called_with("HEAT 50")
        
        # Cleanup
        self.server.running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

class TestWebSocketRoasterCLI(unittest.TestCase):
    def test_print_menu(self):
        with patch('builtins.input', return_value='EXIT'):
            cli = WebSocketRoasterCLI("ws://localhost:8765")
            choice = cli.print_menu()
            self.assertEqual(choice, 'EXIT')

    @async_test
    async def test_run_multiple_commands(self):
        with patch('websockets.connect') as mock_ws_connect:
            with patch('builtins.input', side_effect=['HEAT 50', 'HSTOP', 'EXIT']):
                # Setup mock websocket
                mock_ws = AsyncMock()
                mock_ws_connect.return_value.__aenter__.return_value = mock_ws
                mock_ws.recv.return_value = json.dumps({"status": "ok"})
                
                # Create and run CLI
                cli = WebSocketRoasterCLI("ws://localhost:8765")
                await cli.run()
                
                # Verify commands were sent
                expected_calls = [
                    call(json.dumps({"pushMessage": "HEAT 50"})),
                    call(json.dumps({"pushMessage": "HSTOP"}))
                ]
                mock_ws.send.assert_has_calls(expected_calls)

if __name__ == '__main__':
    unittest.main()