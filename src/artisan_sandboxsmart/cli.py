import argparse
import asyncio
import logging
import threading
from bleak import BleakScanner
from controller import RoasterController

logger = logging.getLogger(__name__)

class RoasterCLI:
    def __init__(self, controller: RoasterController):
        self.controller = controller
        self.menu_thread = None

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

    def menu_thread_func(self):
        """Thread pour gérer le menu et les entrées utilisateur"""
        while self.controller.running:
            try:
                choice = self.print_menu()
                self.controller.add_command(choice)
            except Exception as e:
                logger.error(f"Error in menu thread: {e}")

    def start_menu(self):
        """Démarre le thread du menu"""
        self.menu_thread = threading.Thread(target=self.menu_thread_func)
        self.menu_thread.start()

    def stop_menu(self):
        """Arrête le thread du menu"""
        if self.menu_thread and self.menu_thread.is_alive():
            self.menu_thread.join()

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
    cli = RoasterCLI(controller)

    try:
        # Connexion au périphérique
        connected = await controller.connect(device)
        if not connected:
            logger.error("Failed to connect to device")
            return

        # Démarrage du thread du menu
        cli.start_menu()

        # Démarrage du processeur de commandes
        await controller.start()

    except Exception as e:
        logger.error(f"Error in main: {e}")

    finally:
        # Nettoyage
        await controller.disconnect()
        cli.stop_menu()

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