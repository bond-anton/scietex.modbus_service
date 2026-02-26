"""Microservice for GPIO control"""

from .version import __version__
from .modbus_worker import ModbusWorker

__all__ = ["__version__", "ModbusWorker"]
