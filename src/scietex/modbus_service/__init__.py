"""Microservice for GPIO control"""

from .modbus_worker import ModbusWorker
from .version import __version__

__all__ = ["__version__", "ModbusWorker"]
