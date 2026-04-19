import asyncio
import json
import logging
import argparse

import websockets
from bleak import BleakScanner

from artisan_sandboxsmart.config import configure_logging
from artisan_sandboxsmart.controller import RoasterController

logger = logging.getLogger(__name__)

class RoasterWebSocketServer:
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.controller = None
        self.clients = set()
        self.current_status = {
            "data": {
                "ET": None,
                "BT": None,
                "ET_ror": None,
                "BT_ror": None,
                "status": ""
            },
            "last_command": "Hello",
            "id": 0,
        }
        self.running = False
        self._notification_queue = asyncio.Queue()
        self._websocket_message_queue = asyncio.Queue()  # Nouvelle queue pour les messages WebSocket

    def convert_data_for_json(self, data):
        """Convertit les données en format JSON-sérialisable"""
        if isinstance(data, bytearray):
            return list(data)  # Convertit bytearray en liste
        elif isinstance(data, bytes):
            return list(data)  # Convertit bytes en liste
        elif isinstance(data, dict):
            return {k: self.convert_data_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.convert_data_for_json(item) for item in data]
        return data

    async def handle_ble_notification(self, sender, data):
        """Met les notifications BLE dans une queue au lieu de les traiter directement"""
        await self._notification_queue.put((sender, data))

    async def process_notifications(self):
        """Traite les notifications BLE depuis la queue"""
        while self.running:
            try:
                sender, data = await self._notification_queue.get()
                converted_data = self.convert_data_for_json(data)
                # Mettre à jour les températures dans le controller
                self.controller.update_temperatures(data)
                self.current_status["data"].update({
                    "ET": self.controller.environment_temperature,
                    "BT": self.controller.bean_temperature,
                    "ET_ror": self.controller.et_ror,
                    "BT_ror": self.controller.bt_ror,
                })
                self.current_status["data"]["status"] = converted_data                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erreur lors du traitement de la notification: {e}")

    async def process_websocket_messages(self):
        """Traite les messages WebSocket depuis la queue"""
        while self.running:
            try:
                ws_client, message = await self._websocket_message_queue.get()
                try:
                    json_message = json.loads(message)
                    logger.info(f"Nouveau message reçu: {json_message}")
                    
                    self.current_status["data"].update({
                        "ET": self.controller.environment_temperature,
                        "BT": self.controller.bean_temperature,
                        "ET_ror": self.controller.et_ror,
                        "BT_ror": self.controller.bt_ror,
                    })

                    response = self.current_status

                    if "id" in json_message:
                        response["id"] = json_message["id"]
                    if "command" in json_message:
                        response["last_command"] = json_message["command"]
                        await ws_client.send(json.dumps(response))
                    if "pushMessage" in json_message:
                        if self.controller:
                            response["last_command"] = json_message["pushMessage"]
                            self.controller.add_command(json_message["pushMessage"])
                            await ws_client.send(json.dumps({"success": True}))
                    logger.info(f"Reponse: {response}")
                except json.JSONDecodeError:
                    await ws_client.send(json.dumps({"error": "Invalid JSON"}))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Erreur lors du traitement du message WebSocket: {e}")

    async def register(self, websocket):
        self.clients.add(websocket)
        logger.info(f"Client connecté. Nombre de clients: {len(self.clients)}")

    async def unregister(self, websocket):
        self.clients.discard(websocket)
        logger.info(f"Client déconnecté. Nombre de clients: {len(self.clients)}")

    async def handle_client(self, websocket):
        await self.register(websocket)
        try:
            async for message in websocket:
                await self._websocket_message_queue.put((websocket, message))  # Ajouter le message à la queue
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)

    async def start_server(self, device_name: str = None, device_address: str = None):
        # Connexion BLE
        device = None
        if device_address:
            device = await BleakScanner.find_device_by_address(
                device_address,
                cb=dict(use_bdaddr=True))
        elif device_name:
            device = await BleakScanner.find_device_by_name(device_name)

        if not device:
            logger.error("Dispositif BLE non trouvé")
            return

        # Initialize controller avec le callback modifié
        self.controller = RoasterController()
        self.controller.notification_callback = self.handle_ble_notification
                
        if not await self.controller.connect(device):
            logger.error("Échec de connexion au dispositif BLE")
            return

        self.running = True

        # Démarrer les tâches
        tasks = [
            asyncio.create_task(self.process_notifications()),
            asyncio.create_task(self.process_websocket_messages()),  # Ajouter la tâche de traitement des messages WebSocket
            asyncio.create_task(self.controller.start()),
        ]

        # Démarrer le serveur websocket
        async with websockets.serve(self.handle_client, self.host, self.port):
            logger.info(f"Serveur WebSocket démarré sur ws://{self.host}:{self.port}")
            try:
                await asyncio.Future()  # run forever
            finally:
                self.running = False
                for task in tasks:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

async def _async_main():
    # Configuration des arguments de ligne de commande
    parser = argparse.ArgumentParser()
    parser.add_argument('--mac', '-m', 
                        required=True,
                        help='Adresse MAC du dispositif BLE (ex: cf:03:01:00:00:00)')
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()
    configure_logging(debug=args.debug)

    server = RoasterWebSocketServer()
    await server.start_server(device_address=args.mac)


def main():
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()