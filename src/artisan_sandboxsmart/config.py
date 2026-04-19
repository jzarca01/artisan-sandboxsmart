"""
Configuration module for artisan_sandboxsmart.
Centralizes UUIDs, constants, and logging configuration.
"""

import logging

# BLE UUIDs for Sandbox Smart roaster communication
NOTIFY_UUID = "0000ffa1-0000-1000-8000-00805f9b34fb"
ROASTER_CHARACTERISTIC_UUID = "0000ffa0-0000-1000-8000-00805f9b34fb"

# Command constants
HSTOP = bytearray([0x48, 0x53, 0x54, 0x4F, 0x50])

# Logging configuration defaults
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(level: int = DEFAULT_LOG_LEVEL, debug: bool = False) -> None:
    """
    Configure logging for the application.
    
    Args:
        level: Logging level (default: INFO)
        debug: If True, sets level to DEBUG
    """
    if debug:
        level = logging.DEBUG
    
    logging.basicConfig(
        level=level,
        format=DEFAULT_LOG_FORMAT,
    )
