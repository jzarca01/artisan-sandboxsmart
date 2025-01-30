import asyncio
import json
import logging
import websockets
from websockets.server import WebSocketServerProtocol
from typing import Set
from bleak import BleakScanner
from src.artisan_sandboxsmart.controller import RoasterController

logger = logging.getLogger(__name__)

class RoasterWebSocketServer:
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.controller: RoasterController = None
        self.clients: Set[WebSocketServerProtocol] = set()
        self.current_status = {
            "connected": False,
            "temperature": None,
            "last_command": None
        }
        self.update_task = None

    async def register(self, websocket: WebSocketServerProtocol):
        """Enregistre un nouveau client websocket"""
        self.clients.add(websocket)
        # Envoie l'état actuel au nouveau client
        await websocket.send(json.dumps(self.current_status))

    async def unregister(self, websocket: WebSocketServerProtocol):
        """Désinscrit un client websocket"""
        self.clients.remove(websocket)

    async def broadcast_status(self):
        """Envoie l'état actuel à tous les clients connectés"""
        if not self.clients:
            return

        # Met à jour le statut avec les dernières informations du contrôleur
        if self.controller:
            self.current_status.update({
                "connected": self.controller.client and self.controller.client.is_connected,
                "temperature": self.controller.latest_temperature
            })

        message = json.dumps(self.current_status)
        websockets_tasks = [client.send(message) for client in self.clients]
        await asyncio.gather(*websockets_tasks)

    async def status_updater(self):
        """Tâche périodique pour mettre à jour le statut"""
        while True:
            await self.broadcast_status()
            await asyncio.sleep(1)  # Met à jour toutes les secondes

    async def handle_command(self, command: str):
        """Traite une commande reçue via websocket"""
        if not self.controller:
            logger.error("No controller available")
            return {"error": "No controller available"}

        try:
            self.current_status["last_command"] = command
            self.controller.add_command(command)
            return {"success": True, "message": f"Command {command} sent"}
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            return {"error": str(e)}

    async def handle_client(self, websocket: WebSocketServerProtocol):
        """Gère la connexion d'un client websocket"""
        await self.register(websocket)
        try:
            async for message in websocket:
                try:
                    # Parse le message JSON reçu
                    data = json.loads(message)
                    if "command" in data:
                        response = await self.handle_command(data["command"])
                        await websocket.send(json.dumps(response))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "Invalid JSON format"}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)

    async def start_server(self, device_name: str = None, device_address: str = None):
        """Démarre le serveur websocket et initialise le contrôleur"""
        # Recherche et connexion au dispositif BLE
        device = None
        if device_address:
            device = await BleakScanner.find_device_by_address(device_address)
        elif device_name:
            device = await BleakScanner.find_device_by_name(device_name)

        if not device:
            logger.error("Could not find BLE device")
            return

        # Initialise et connecte le contrôleur
        self.controller = RoasterController()
        connected = await self.controller.connect(device)
        
        if not connected:
            logger.error("Failed to connect to BLE device")
            return

        # Démarre le processeur de commandes du contrôleur
        controller_task = asyncio.create_task(self.controller.start())
        
        # Démarre la tâche de mise à jour du statut
        self.update_task = asyncio.create_task(self.status_updater())

        # Démarre le serveur websocket
        async with websockets.serve(self.handle_client, self.host, self.port):
            logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever

async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # Paramètres du dispositif BLE (à adapter selon vos besoins)
    # DEVICE_NAME = "YourDeviceName"  # ou utiliser l'adresse
    SANDBOX_MAC_ADDRESS = "cf:03:01:00:06:8c"

    server = RoasterWebSocketServer()
    await server.start_server(device_address=SANDBOX_MAC_ADDRESS)

if __name__ == "__main__":
    asyncio.run(main())