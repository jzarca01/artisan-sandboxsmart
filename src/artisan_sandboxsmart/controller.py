import asyncio
import logging
import time
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
        self.command_queue = asyncio.Queue()
        self.running = True
        self.notification_callback = None
        self.environment_temperature: Optional[float] = None
        self.bean_temperature: Optional[float] = None
        self.et_ror: Optional[float] = None
        self.bt_ror: Optional[float] = None
        self._last_et: Optional[float] = None
        self._last_bt: Optional[float] = None
        self._last_et_time: Optional[float] = None
        self._last_bt_time: Optional[float] = None
        self.latest_data: Dict = {}

    def has_numbers(self, inputString: str) -> bool:
        return any(char.isdigit() for char in inputString)

    def _compute_ror(self, current_temp: float, last_temp: Optional[float], last_time: Optional[float], now: float) -> Optional[float]:
        """Calcule le Rate of Rise en °/min"""
        if last_temp is not None and last_time is not None:
            dt = now - last_time
            if dt > 0:
                return round((current_temp - last_temp) / dt * 60, 1)
        return None

    def update_temperatures(self, data: bytearray) -> Optional[float]:
        """Met a jour les températures depuis les données reçues"""
        try:
            hex_temp = data.hex()
            now = time.monotonic()
            if hex_temp.startswith('5054'):  # Preheating phase 'PT'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                self.et_ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                self._last_et = temp
                self._last_et_time = now
                self.environment_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
            elif hex_temp.startswith('4354'):  # Roasting phase 'CT'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                self.bt_ror = self._compute_ror(temp, self._last_bt, self._last_bt_time, now)
                self._last_bt = temp
                self._last_bt_time = now
                self.bean_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
            elif hex_temp.startswith('434c'):  # Cooling phase 'CL'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                self.et_ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                self._last_et = temp
                self._last_et_time = now
                self.environment_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
            if hex_temp.startswith('4854'):  # 'HT' en hex
                temp_bytes = hex_temp[4:8]
                temp = int(temp_bytes, 16)
                self.et_ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                self._last_et = temp
                self._last_et_time = now
                self.environment_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
        except Exception as e:
            logger.error(f"Error parsing temperature: {e}")
        return None

    async def send_command(self, parameter: str, *values):
        """Envoie des commandes au format 'PARAM', 'PARAM VALUE' ou 'PARAM VALUE1 VALUE2' en hexadécimal au client bluetooth"""
        command = parameter.encode('ascii')

        logger.info(f"send_command: {command}: {values}")

        
        if values and values[0]:
            actual_values = values[0] if isinstance(values[0], tuple) else values

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
        temp = self.update_temperatures(data)
        if temp is not None:
            logger.info(f"Temperatures updated: ET: {self.environment_temperature} BT: {self.bean_temperature}")
        else:
            try:
                self.latest_data = data.decode("utf-8")
            except Exception as e:
                self.latest_data = data
            logger.info(f"Notification: {data} {data.hex(':')}")

    async def process_command(self, command):
        """Traite une commande unique"""
        if self.client and self.client.is_connected:
            if isinstance(command, (bytes, bytearray)):
                await self.client.write_gatt_char(
                    ROASTER_CHARACTERISTIC_UUID,
                    command,
                    response=False
                )
            elif self.has_numbers(command):
                parameter, *values = command.split(" ")
                await self.send_command(parameter, *values)
            else:
                await self.send_command(command)

    async def command_processor(self):
        """Traite les commandes de la queue et les envoie au périphérique BLE"""
        while self.running:
            try:
                command = await asyncio.wait_for(self.command_queue.get(), timeout=0.1)
                await self.process_command(command)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in command processor: {e}")

    def add_command(self, command: str):
        """Ajoute une commande à la queue"""
        if command.upper() == "EXIT":
            self.running = False
            self.command_queue.put_nowait(HSTOP)
        else:
            if command.upper() == "COOLING":
                self.bean_temperature = None
            if "HPSTART" in command.upper():
                self.bean_temperature = None
            self.command_queue.put_nowait(command)



    async def connect(self, device):
        """Établit la connexion avec le périphérique BLE"""
        try:
            self.client = BleakClient(device)
            await self.client.connect()
            logger.info("Connected to device")
            callback = self.notification_callback or self.notification_handler
            await self.client.start_notify(NOTIFY_UUID, callback)
            return self.client.is_connected
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

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