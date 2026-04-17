import asyncio
import logging
import time
from typing import Optional, Dict
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from artisan_sandboxsmart.config import NOTIFY_UUID, ROASTER_CHARACTERISTIC_UUID, HSTOP

logger = logging.getLogger(__name__)

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
        self.preheat_target: Optional[int] = None
        self.preheat_done = asyncio.Event()

    def has_numbers(self, inputString: str) -> bool:
        return any(char.isdigit() for char in inputString)

    def _compute_ror(self, current_temp: float, last_temp: Optional[float], last_time: Optional[float], now: float) -> Optional[float]:
        """Calcule le Rate of Rise en °/min"""
        if last_temp is None or last_time is None:
            return None
        dt = now - last_time
        if dt <= 0:
            return None
        return round((current_temp - last_temp) / dt * 60, 1)

    def update_temperatures(self, data: bytearray) -> Optional[float]:
        """Met a jour les températures depuis les données reçues"""
        try:
            hex_temp = data.hex()
            now = time.monotonic()
            logger.debug(f"hex_temp {hex_temp}")
            logger.debug(f"self {self.__dict__}")
            if hex_temp.startswith('5054'):  # Preheating phase 'PT'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                if temp > 0:
                    ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                    if ror is not None:
                        self.et_ror = ror
                    self._last_et = temp
                    self._last_et_time = now
                    self.environment_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                if self.preheat_target and self.environment_temperature >= self.preheat_target:
                    self.preheat_done.set()
                return temp
            elif hex_temp.startswith('4354'):  # Roasting phase 'CT'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                if temp > 0:
                    ror = self._compute_ror(temp, self._last_bt, self._last_bt_time, now)
                    if ror is not None:
                        self.bt_ror = ror
                    self._last_bt = temp
                    self._last_bt_time = now
                    self.bean_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
            elif hex_temp.startswith('434c'):  # Cooling phase 'CL'
                temp_bytes = hex_temp[8:12]
                temp = int(temp_bytes, 16)
                if temp > 0:
                    ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                    if ror is not None:
                        self.et_ror = ror
                    self._last_et = temp
                    self._last_et_time = now
                    self.environment_temperature = temp
                logger.debug(f"Temp_bytes: {temp_bytes}, int(temp_bytes, 16): {temp}")
                return temp
            elif hex_temp.startswith('4854'):  # 'HT' en hex
                temp_bytes = hex_temp[4:8]
                temp = int(temp_bytes, 16)
                if temp > 0:
                    ror = self._compute_ror(temp, self._last_et, self._last_et_time, now)
                    if ror is not None:
                        self.et_ror = ror
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
            if isinstance(command, tuple) and command[0] == "PREHEAT":
                _, target_temp, timeout = command
                await self.start_preheat(target_temp, timeout=timeout)
            elif isinstance(command, (bytes, bytearray)):
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
            if command.upper().startswith("PREHEAT"):
                parts = command.split()
                if len(parts) >= 2:
                    target_temp = int(parts[1])
                    timeout = int(parts[2]) if len(parts) >= 3 else 1200
                    self.command_queue.put_nowait(("PREHEAT", target_temp, timeout))
                    return
            self.command_queue.put_nowait(command)



    async def start_preheat(self, target_temp: int, timeout: int = 1200, tolerance: int = 5, soak_duration: int = 60):
        """Lance le préchauffage et vérifie le maintien à température cible pendant soak_duration secondes.
        
        Args:
            target_temp: Température cible en degrés
            timeout: Temps max de préchauffage en secondes
            tolerance: Tolérance en degrés pour le maintien
            soak_duration: Durée de vérification du maintien en secondes
        """
        self.preheat_target = target_temp
        self.preheat_done.clear()
        self.bean_temperature = None

        logger.info(f"Préchauffage: cible={target_temp}°, timeout={timeout}s")
        await self.send_command("HPSTART", (str(timeout), str(target_temp)))

        # Attendre que la température cible soit atteinte
        try:
            await asyncio.wait_for(self.preheat_done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Préchauffage: température cible {target_temp}° non atteinte dans le délai de {timeout}s")
            self.preheat_target = None
            return False

        logger.info(f"Température cible {target_temp}° atteinte, début du maintien ({soak_duration}s)")

        # Vérifier le maintien à température pendant soak_duration
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < soak_duration:
            await asyncio.sleep(1)
            if self.environment_temperature is None:
                continue
            if abs(self.environment_temperature - target_temp) > tolerance:
                logger.warning(
                    f"Maintien: température hors tolérance "
                    f"({self.environment_temperature}° vs cible {target_temp}° ±{tolerance}°)"
                )
                self.preheat_target = None
                return False

        logger.info(f"Préchauffage terminé: maintien à {target_temp}° vérifié pendant {soak_duration}s")
        self.preheat_target = None
        return True

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