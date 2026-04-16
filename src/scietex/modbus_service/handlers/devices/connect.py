"""Handler for connecting Modbus devices."""

import asyncio
import logging
from typing import TYPE_CHECKING

import msgspec
from scietex.hal.serial import ModbusSerialConnectionConfig, RS485Client
from scietex.service.task_handlers import TaskData, TaskHandler, TaskResult, TaskTimeout

from ...schemas.configuration import ModbusDevice
from ...schemas.results import CountResult
from ...schemas.tasks import Tasks
from .drivers import get_driver

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class ConnectDeviceHandler(TaskHandler):
    """Handler for connecting Modbus device."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()
        self.decoder = msgspec.msgpack.Decoder(ModbusDevice)

    @classmethod
    def generate_task(self, device: ModbusDevice) -> TaskData:
        """Generate a task to connect Modbus device."""
        return TaskData(
            task=Tasks.DEVICE_CONNECT.value,
            timeout=TaskTimeout(5, "requeue"),
            canceled_action="discard",
            payload=msgspec.msgpack.encode(device),
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Connect Modbus device."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        try:
            device = self.decoder.decode(task_data.payload)
            if not device and isinstance(device, ModbusDevice):
                return TaskResult(
                    status="error",
                    error="Failed to decode device information",
                )

            count = await self.connect_device(device)

            return TaskResult(
                status="success",
                error="No error",
                payload=self.encoder.encode(CountResult(count=count)),
            )
        except Exception as e:
            await self.worker.log(
                f"Failed to decode device information: {e}",
                level=logging.ERROR,
            )
            return TaskResult(
                status="error",
                error=f"Failed to decode device information: {e}",
            )

    async def connect_device(self, device: ModbusDevice) -> int:
        """Connect a Modbus device and return 1 if connected successfully, otherwise return 0."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0

        if not self.worker.modbus_configuration or not self.worker.modbus_port:
            return 0

        ports = self.worker.vsn.create(1)
        if not ports:
            await self.worker.log("Can not create VSN port for modbus device", level=logging.ERROR)
            return 0
        print("=== Connecting to port", ports[0])
        modbus_config = ModbusSerialConnectionConfig(
            port=ports[0],
            baudrate=self.worker.modbus_configuration.serial_port_config.baudrate,
            bytesize=self.worker.modbus_configuration.serial_port_config.bytesize,
            parity=self.worker.modbus_configuration.serial_port_config.parity,
            stopbits=self.worker.modbus_configuration.serial_port_config.stopbits,
            timeout=self.worker.modbus_configuration.serial_port_config.timeout,
            framer=None,
        )
        print("CONF:", modbus_config)
        driver = get_driver(
            device.modbus_device_driver.device_type.name,
            device.modbus_device_driver.name,
        )
        if not driver:
            await self.worker.log(
                f"Driver {device.modbus_device_driver.name} for device {device.name} not found.",
                level=logging.ERROR,
            )
            return 0
        try:
            client: RS485Client = driver(modbus_config, address=device.address, label=device.name)
            self.worker.devices[device.name] = {
                "device_type": device.modbus_device_driver.device_type.name,
                "device": client,
                "address": device.address,
                "polling_interval": device.polling_interval,
                "enabled": True,
            }
            await self.worker.log(
                f"Connected to modbus device {device.name} successfully.",
                level=logging.INFO,
            )
            await asyncio.sleep(0.25)  # Small delay to ensure the device is properly initialized
            await self.worker.schedule_device_monitor(device)
            return 1
        except Exception as e:
            await self.worker.log(
                f"Failed to connect to modbus device {device.name}: {e}",
                level=logging.ERROR,
            )
            self.worker.vsn.remove(ports)

        return 0

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICE_CONNECT.value


class ConnectDevicesHandler(TaskHandler):
    """Handler for connecting Modbus devices."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to connect Modbus devices."""
        return TaskData(
            task=Tasks.DEVICES_CONNECT.value,
            timeout=TaskTimeout(30, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Connect Modbus devices."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        count = await self.connect_devices()
        await self.worker.log(
            f"Scheduled connection of {count} devices",
            level=logging.DEBUG,
        )

        return TaskResult(
            status="success",
            error="No error",
            payload=self.encoder.encode(CountResult(count=count)),
        )

    async def connect_devices(self) -> int:
        """Connect Modbus devices and return the count of connected devices."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0

        count = 0
        if self.worker.modbus_configuration and self.worker.modbus_port:
            for device in self.worker.modbus_configuration.devices:
                if device.name in self.worker.devices:
                    await self.worker.log(
                        f"Modbus device {device.name} already connected.",
                        level=logging.INFO,
                    )
                    continue
                await self.worker.schedule_device_connect(device)
                count += 1
                await asyncio.sleep(0.1)  # Small delay to avoid overwhelming the system
        return count

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICES_CONNECT.value
