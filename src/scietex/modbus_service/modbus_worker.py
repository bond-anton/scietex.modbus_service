"""Worker module for modbus service."""

import msgspec

import asyncio
import time
import importlib
from typing import Type, Any
import logging
from uuid import uuid4

from scietex.hal.qcm.base.rs485 import RS485GatedFTM

from scietex.service import ValkeyWorker
from scietex.service.task_handlers import TaskData, TaskTimeout
from scietex.hal.serial import (
    SerialConnectionConfig,
    ModbusSerialConnectionConfig,
    VirtualSerialNetwork,
    RS485Client,
)

from .version import __version__

from .schemas.configuration import ModbusConfiguration, ModbusDevice
from .schemas.tasks import Tasks

from .handlers.configuration import ReadConfigurationHandler
from .handlers.connection import (
    DisconnectModbusHandler,
    ConnectModbusHandler,
    CheckModbusConnectionHandler,
)
from .handlers.devices import DisconnectDeviceHandler, DisconnectDevicesHandler


# pylint: disable=too-many-instance-attributes
class ModbusWorker(ValkeyWorker[Tasks]):
    """Worker class for modbus service."""

    def __init__(self, **kwargs) -> None:
        super().__init__(
            service_name="modbus",
            version=__version__,
            queue_size=100,
            max_concurrent_tasks=1,
            **kwargs,
        )

        self.modbus_configuration: ModbusConfiguration | None = None
        self.modbus_port: SerialConnectionConfig | None = None
        self.devices: dict[str, dict[str, RS485Client | int | float | str]] = {}
        self.vsn: VirtualSerialNetwork = VirtualSerialNetwork(
            virtual_ports_num=0, logger=self.logger, loopback=False
        )
        self.encoder = msgspec.msgpack.Encoder()

    async def initialize(self) -> bool:
        if self.initialized:
            await self.log("Already initialized", level=logging.DEBUG)
            return True

        if not await super().initialize():
            return False

        self.vsn.start()

        self.register_task_handler(Tasks.CONFIGURATION_READ, ReadConfigurationHandler)

        self.register_task_handler(Tasks.MODBUS_DISCONNECT, DisconnectModbusHandler)
        self.register_task_handler(Tasks.MODBUS_CONNECT, ConnectModbusHandler)
        self.register_task_handler(Tasks.MODBUS_MONITOR, CheckModbusConnectionHandler)

        self.register_task_handler(Tasks.DEVICE_DISCONNECT, DisconnectDeviceHandler)
        self.register_task_handler(Tasks.DEVICES_DISCONNECT, DisconnectDevicesHandler)

        await self.schedule_configuration_read()

        return True

    async def schedule_configuration_read(self):
        await self.task_queue.put((uuid4(), ReadConfigurationHandler.generate_task()))

    async def schedule_modbus_disconnect(self):
        await self.task_queue.put((uuid4(), DisconnectModbusHandler.generate_task()))

    async def schedule_modbus_connect(self):
        await self.task_queue.put((uuid4(), ConnectModbusHandler.generate_task()))

    async def schedule_modbus_monitor(self):
        await self.task_queue.put(
            (uuid4(), CheckModbusConnectionHandler.generate_task())
        )

    async def schedule_device_disconnect(self, device: ModbusDevice):
        await self.task_queue.put(
            (uuid4(), DisconnectDeviceHandler.generate_task(device))
        )

    async def schedule_devices_disconnect(self):
        await self.task_queue.put((uuid4(), DisconnectDevicesHandler.generate_task()))

    async def cleanup(self):
        """
        Handles cleanup tasks upon termination, including closing any open connections.
        """
        self.vsn.stop()
        await asyncio.sleep(5)
        await super().cleanup()
