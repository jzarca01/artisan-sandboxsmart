import argparse
import asyncio
import logging
import threading
from queue import Queue
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)

SANDBOX_MAC_ADDRESS = "cf:03:01:00:06:8c"
NOTIFY_UUID = "0000ffa1-0000-1000-8000-00805f9b34fb"
ROASTER_CHARACTERISTIC_UUID = "0000ffa0-0000-1000-8000-00805f9b34fb"
HSTOP = bytearray([0x48,0x53,0x54,0x4F,0x50])

class RoasterController:
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.command_queue = Queue()
        self.running = True
        
    def print_menu(self) -> str:
        menu = """---MENU---
        Heat power: D0 1200 0-100 220
        Drum speed: R0 1200 0-100 220
        Fan speed: F0 1200 0-100 220
        Lights on/off: LIGHT ON / LIGHT OFF
        Get temperature: HPTEMP
        Stop: HSTOP
        Cooling: COOLING
        Start preheating: HPSTART 1200 200 (time / temperature)
        Start roasting: HSTART
        Exit: EXIT
        """
        print(menu)
        return input("Enter your choice: ")

    def has_numbers(self, inputString: str) -> bool:
        return any(char.isdigit() for char in inputString)

    def convert_to_bytearray(self, choice: str) -> bytearray:
        if self.has_numbers(choice):
            command = choice.split(" ")
        else:
            command = choice
        result = []
        
        for item in command:
            if item.isdigit():
                num = int(item)
                bytes_value = num.to_bytes(2, byteorder="big")
                for b in bytes_value:
                    result.append(b)
            else:
                for char in item:
                    result.append(ord(char))
        
        return bytearray(result)

    def menu_thread(self):
        """Thread pour gérer le menu et les entrées utilisateur"""
        while self.running:
            try:
                choice = self.print_menu()
                if choice.upper() == "EXIT":
                    self.running = False
                    self.command_queue.put(HSTOP)
                    break
                
                command = self.convert_to_bytearray(choice)
                self.command_queue.put(command)
                
            except Exception as e:
                logger.error(f"Error in menu thread: {e}")

    async def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Gestionnaire de notifications BLE"""
        logger.info(f"Notification: {data} {data.hex(':')}")

    async def command_processor(self):
        """Traite les commandes de la queue et les envoie au périphérique BLE"""
        while self.running:
            try:
                if not self.command_queue.empty():
                    command = self.command_queue.get()
                    if self.client and self.client.is_connected:
                        await self.client.write_gatt_char(
                            ROASTER_CHARACTERISTIC_UUID, 
                            command, 
                            response=False
                        )
                await asyncio.sleep(0.1)  # Évite de surcharger le CPU
            except Exception as e:
                logger.error(f"Error in command processor: {e}")

    async def run(self, device):
        """Fonction principale qui gère la connexion BLE et lance les threads"""
        async with BleakClient(device) as client:
            self.client = client
            logger.info("Connected to device")

            # Démarrage du thread du menu
            menu_thread = threading.Thread(target=self.menu_thread)
            menu_thread.start()

            # Démarrage des tâches asyncio
            notification_task = asyncio.create_task(
                client.start_notify(NOTIFY_UUID, self.notification_handler)
            )
            processor_task = asyncio.create_task(self.command_processor())

            try:
                # Attendre que les tâches se terminent
                await asyncio.gather(notification_task, processor_task)
            except asyncio.CancelledError:
                pass
            finally:
                # Nettoyage
                self.running = False
                if client.is_connected:
                    await client.write_gatt_char(
                        ROASTER_CHARACTERISTIC_UUID, 
                        HSTOP, 
                        response=False
                    )
                menu_thread.join()

async def main(args: argparse.Namespace):
    logger.info("starting scan...")

    device = None
    if args.address:
        device = await BleakScanner.find_device_by_address(
            args.address, 
            cb=dict(use_bdaddr=args.macos_use_bdaddr)
        )
    else:
        device = await BleakScanner.find_device_by_name(
            args.name, 
            cb=dict(use_bdaddr=args.macos_use_bdaddr)
        )

    if device is None:
        logger.error("Could not find device")
        return

    controller = RoasterController()
    await controller.run(device)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    device_group = parser.add_mutually_exclusive_group(required=True)
    device_group.add_argument(
        "--name",
        metavar="<name>",
        help="the name of the bluetooth device to connect to",
    )
    device_group.add_argument(
        "--address",
        metavar="<address>",
        help="the address of the bluetooth device to connect to",
    )
    parser.add_argument(
        "--macos-use-bdaddr",
        action="store_true",
        help="when true use Bluetooth address instead of UUID on macOS",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="sets the log level to debug",
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format="%(message)s")
    
    asyncio.run(main(args))