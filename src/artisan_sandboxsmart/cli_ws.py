import asyncio
import json
import argparse
import logging

import websockets

from artisan_sandboxsmart.config import configure_logging

logger = logging.getLogger(__name__)

class WebSocketRoasterCLI:
    def __init__(self, websocket_url):
        self.websocket_url = websocket_url

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
        Preheat with soak check: PREHEAT 200 (target temp) [soak_duration] [tolerance] [timeout]
        Stop preheating: PREHEAT_STOP
        Start roasting: HSTART
        Exit: EXIT
        """
        print(menu)
        return input("Enter your choice: ")

    async def run(self):
        try:
            async with websockets.connect(self.websocket_url, logger=logging.getLogger("websockets.client"), ping_timeout=None, ping_interval=10) as websocket:
                while True:
                    try:
                        choice = self.print_menu()
                        
                        if choice.upper() == 'EXIT':
                            break

                        await websocket.send(json.dumps({"pushMessage": choice}))
                        
                        response = await asyncio.wait_for(websocket.recv(), timeout=300)
                        print("Server response:", json.loads(response))

                    except Exception as e:
                        logger.error(f"Error processing command: {e}")

        except websockets.exceptions.ConnectionRefusedError:
            logger.error("Could not connect to WebSocket server")

def main():
    parser = argparse.ArgumentParser(description="WebSocket Roaster CLI")
    parser.add_argument(
        "--url", 
        default="ws://localhost:8765",
        help="WebSocket server URL (default: ws://localhost:8765)"
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()
    configure_logging(debug=args.debug)

    cli = WebSocketRoasterCLI(args.url)
    asyncio.run(cli.run())

if __name__ == "__main__":
    main()