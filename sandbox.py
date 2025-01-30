import argparse
import asyncio
import json
import logging
import threading
from queue import Queue
from typing import Optional, Set, Dict

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
        self.latest_temperature: Optional[float] = None
        self.latest_data: Dict = {}
        
    def print_menu(self) -> str:
        menu = """---MENU---
        Heat power: HEAT 0-100
        Drum speed: DRUM 0-100
        Fan speed: DRAW 0-100
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

    def parse_temperature(self, data: bytearray) -> Optional[float]:
        """Parse la température depuis les données reçues"""
        try:
            # Exemple de parsing - à adapter selon le format réel des données
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
        # Conversion du paramètre en bytes
        command = parameter.encode('ascii')
        
        if values and values[0]:  # Vérifier que values n'est pas vide
            # Ignorer le dernier élément s'il est un booléen (is_value_two_bytes)
            actual_values = values[0] if isinstance(values[0], tuple) else (values[0],)
            
            # Cas avec une seule valeur entre 0-100
            if len(actual_values) == 1:
                try:
                    if 0 <= int(actual_values[0]) <= 100:
                        value_int = int(actual_values[0])
                        command += bytes([value_int])

                except ValueError: # par example value: ON
                    command += ' '
                    command += actual_values[0].encode('ascii')
                
            # Cas avec plusieurs valeurs ou valeur > 100
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

    def menu_thread(self):
        """Thread pour gérer le menu et les entrées utilisateur"""
        while self.running:
            try:
                choice = self.print_menu()
                if choice.upper() == "EXIT":
                    self.running = False
                    self.command_queue.put(HSTOP)
                    break
                
                self.command_queue.put(choice)
                
            except Exception as e:
                logger.error(f"Error in menu thread: {e}")

    async def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Gestionnaire de notifications BLE"""
        
        # Parser et stocker la température si présente
        temp = self.parse_temperature(data)
        if temp is not None:
            logger.info(f"Temperature updated: {temp}")
            self.latest_temperature = temp
        else:
            logger.info(f"Notification: {data} {data.hex(':')}")


    async def command_processor(self):
        """Traite les commandes de la queue et les envoie au périphérique BLE"""
        while self.running:
            try:
                if not self.command_queue.empty():
                    command: str = self.command_queue.get()

                    if self.client and self.client.is_connected:
                        if self.has_numbers(command):
                            parameter, *values = command.split(" ")
                            await self.send_command(parameter, *values)
                        else:
                            await self.send_command(command)

                await asyncio.sleep(0.1)
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
