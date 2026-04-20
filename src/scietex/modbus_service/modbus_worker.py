"""Worker module for modbus service."""

import asyncio
import logging
from uuid import uuid4

import msgspec
from scietex.hal.serial import (
    RS485Client,
    SerialConnectionConfig,
    VirtualSerialNetwork,
)
from scietex.service import ValkeyWorker

from .handlers.configuration import ReadConfigurationHandler
from .handlers.connection import (
    CheckModbusConnectionHandler,
    ConnectModbusHandler,
    DisconnectModbusHandler,
)
from .handlers.devices import (
    ConnectDeviceHandler,
    ConnectDevicesHandler,
    DisableDeviceHandler,
    DisconnectDeviceHandler,
    DisconnectDevicesHandler,
    EnableDeviceHandler,
    MonitorDeviceHandler,
)
from .schemas.configuration import ModbusConfiguration, ModbusDevice
from .schemas.tasks import Tasks
from .version import __version__


# pylint: disable=too-many-instance-attributes
class ModbusWorker(ValkeyWorker[Tasks]):
    """Worker class for modbus service."""

    def __init__(self, **kwargs) -> None:
        super().__init__(
            service_name="modbus",
            version=__version__,
            queue_size=100,
            max_concurrent_tasks=20,
            **kwargs,
        )

        self.modbus_configuration: ModbusConfiguration | None = None
        self.modbus_port: SerialConnectionConfig | None = None
        self.devices: dict[str, dict[str, RS485Client | int | float | str]] = {}
        self.vsn: VirtualSerialNetwork = VirtualSerialNetwork(virtual_ports_num=0, logger=self.logger, loopback=False)
        self.encoder = msgspec.msgpack.Encoder()

        self.modbus_lock = asyncio.Lock()

    async def initialize(self) -> bool:

        if self.initialized:
            await self.log("Already initialized", level=logging.DEBUG)
            return True

        if not await super().initialize():
            return False

        await self.purge_tasks()

        self.vsn.start()

        self.register_task_handler(Tasks.CONFIGURATION_READ, ReadConfigurationHandler)

        self.register_task_handler(Tasks.MODBUS_DISCONNECT, DisconnectModbusHandler)
        self.register_task_handler(Tasks.MODBUS_CONNECT, ConnectModbusHandler)
        self.register_task_handler(Tasks.MODBUS_MONITOR, CheckModbusConnectionHandler)

        self.register_task_handler(Tasks.DEVICE_DISCONNECT, DisconnectDeviceHandler)
        self.register_task_handler(Tasks.DEVICES_DISCONNECT, DisconnectDevicesHandler)
        self.register_task_handler(Tasks.DEVICE_CONNECT, ConnectDeviceHandler)
        self.register_task_handler(Tasks.DEVICES_CONNECT, ConnectDevicesHandler)
        self.register_task_handler(Tasks.DEVICE_ENABLE, EnableDeviceHandler)
        self.register_task_handler(Tasks.DEVICE_DISABLE, DisableDeviceHandler)
        self.register_task_handler(Tasks.DEVICE_MONITOR, MonitorDeviceHandler)

        await self.schedule_configuration_read()

        return True

    async def schedule_configuration_read(self):
        await self.task_queue.put((uuid4(), ReadConfigurationHandler.generate_task()))

    async def schedule_modbus_disconnect(self):
        await self.task_queue.put((uuid4(), DisconnectModbusHandler.generate_task()))

    async def schedule_modbus_connect(self):
        await self.task_queue.put((uuid4(), ConnectModbusHandler.generate_task()))

    async def schedule_modbus_monitor(self):
        await self.task_queue.put((uuid4(), CheckModbusConnectionHandler.generate_task()))

    async def schedule_device_disconnect(self, device: ModbusDevice):
        await self.task_queue.put((uuid4(), DisconnectDeviceHandler.generate_task(device)))

    async def schedule_devices_disconnect(self):
        await self.task_queue.put((uuid4(), DisconnectDevicesHandler.generate_task()))

    async def schedule_device_connect(self, device: ModbusDevice):
        await self.task_queue.put((uuid4(), ConnectDeviceHandler.generate_task(device)))

    async def schedule_devices_connect(self):
        await self.task_queue.put((uuid4(), ConnectDevicesHandler.generate_task()))

    async def schedule_device_monitor(self, device: ModbusDevice):
        await self.task_queue.put((uuid4(), MonitorDeviceHandler.generate_task(device)))

    async def cleanup(self):
        """
        Handles cleanup tasks upon termination, including closing any open connections.
        """
        self.vsn.stop()
        await asyncio.sleep(5)
        await super().cleanup()
