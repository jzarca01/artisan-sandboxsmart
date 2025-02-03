import asyncio
import json
import websockets
import argparse
import logging

logging.basicConfig(level=logging.INFO)
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
        required=False, 
        help="WebSocket server URL"
    )
    args = parser.parse_args()

    cli = WebSocketRoasterCLI(args.url)
    asyncio.run(cli.run())

if __name__ == "__main__":
    main()