import asyncio
import logging
from queue import Queue
from typing import Optional, Dict
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)

NOTIFY_UUID = "0000ffa1-0000-1000-8000-00805f9b34fb"
ROASTER_CHARACTERISTIC_UUID = "0000ffa0-0000-1000-8000-00805f9b34fb"
HSTOP = bytearray([0x48, 0x53, 0x54, 0x4F, 0x50])

class RoasterController:
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.command_queue = Queue()
        self.running = True
        self.latest_temperature: Optional[float] = None
        self.latest_data: Dict = {}

    def has_numbers(self, inputString: str) -> bool:
        return any(char.isdigit() for char in inputString)

    def parse_temperature(self, data: bytearray) -> Optional[float]:
        """Parse la température depuis les données reçues"""
        try:
            hex_temp = data.hex()
            if hex_temp.startswith('5054'):  # Preheating phase 'PT'
                temp_bytes = hex_temp[8:12]
                logger.error(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {int(temp_bytes, 16)}")
                return int(temp_bytes, 16)
            elif hex_temp.startswith('4354'):  # Roasting phase 'CT'
                temp_bytes = hex_temp[8:12]
                logger.error(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {int(temp_bytes, 16)}")
                return int(temp_bytes, 16)
            elif hex_temp.startswith('434c'):  # Cooling phase 'CL'
                temp_bytes = hex_temp[8:12]
                logger.error(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {int(temp_bytes, 16)}")
                return int(temp_bytes, 16)           
            if hex_temp.startswith('4854'):  # 'HT' en hex
                temp_bytes = hex_temp[4:8]
                logger.error(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {int(temp_bytes, 16)}")
                return int(temp_bytes, 16)
        except Exception as e:
            logger.error(f"Error parsing temperature: {e}")
        return None

    async def send_command(self, parameter: str, *values):
        """Envoie des commandes au format 'PARAM', 'PARAM VALUE' ou 'PARAM VALUE1 VALUE2' en hexadécimal au client bluetooth"""
        command = parameter.encode('ascii')
        
        if values and values[0]:
            actual_values = values[0] if isinstance(values[0], tuple) else (values[0],)
            
            if len(actual_values) == 1:
                try:
                    if 0 <= int(actual_values[0]) <= 100:
                        value_int = int(actual_values[0])
                        command += bytes([value_int])
                except ValueError:
                    command += ' '
                    command += actual_values[0].encode('ascii')
            else:
                for value in actual_values:
                    value_int = int(value)
                    command += value_int.to_bytes(2, byteorder='big')
        
        logger.info(f"Command hex: {command.hex()}")
        await self.client.write_gatt_char(
            ROASTER_CHARACTERISTIC_UUID,
            command,
            response=False
        )

    async def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Gestionnaire de notifications BLE"""
        temp = self.parse_temperature(data)
        if temp is not None:
            logger.info(f"Temperature updated: {temp}")
            self.latest_temperature = temp
        else:
            logger.info(f"Notification: {data} {data.hex(':')}")

    async def process_command(self, command: str):
        """Traite une commande unique"""
        if self.client and self.client.is_connected:
            if self.has_numbers(command):
                parameter, *values = command.split(" ")
                await self.send_command(parameter, *values)
            else:
                await self.send_command(command)

    async def command_processor(self):
        """Traite les commandes de la queue et les envoie au périphérique BLE"""
        while self.running:
            try:
                if not self.command_queue.empty():
                    command = self.command_queue.get()
                    await self.process_command(command)
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in command processor: {e}")

    def add_command(self, command: str):
        """Ajoute une commande à la queue"""
        if command.upper() == "EXIT":
            self.running = False
            self.command_queue.put(HSTOP)
        else:
            self.command_queue.put(command)

    async def connect(self, device):
        """Établit la connexion avec le périphérique BLE"""
        self.client = BleakClient(device)
        await self.client.connect()
        logger.info("Connected to device")
        await self.client.start_notify(NOTIFY_UUID, self.notification_handler)
        return self.client.is_connected

    async def disconnect(self):
        """Déconnexion propre du périphérique"""
        self.running = False
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(
                ROASTER_CHARACTERISTIC_UUID,
                HSTOP,
                response=False
            )
            await self.client.disconnect()

    async def start(self):
        """Démarre le processeur de commandes"""
        processor_task = asyncio.create_task(self.command_processor())
        await processor_task