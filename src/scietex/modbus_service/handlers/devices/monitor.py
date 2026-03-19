"""Handler for monitoring the Modbus device."""

import asyncio
from typing import TYPE_CHECKING
import logging
import msgspec

from scietex.hal.serial import RS485Client
from scietex.hal.qcm.base.rs485 import RS485GatedFTM
from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.configuration import ModbusDevice

from .qcm import monitor_qcm_device


if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class MonitorDeviceHandler(TaskHandler):
    """Handler for monitoring Modbus device."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()
        self.decoder = msgspec.msgpack.Decoder(ModbusDevice)

    @classmethod
    def generate_task(self, device: ModbusDevice) -> TaskData:
        """Generate a task to monitor Modbus device."""
        return TaskData(
            task=Tasks.DEVICE_MONITOR.value,
            timeout=TaskTimeout(1, "requeue"),
            canceled_action="discard",
            payload=msgspec.msgpack.encode(device),
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Monitor Modbus device."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )

        try:
            device = self.decoder.decode(task_data.payload)
            if not device or not isinstance(device, ModbusDevice):
                return await self.error_decoding_device_info()
        except Exception as e:
            return await self.error_decoding_device_info(e)

        if device.name not in self.worker.devices:
            return TaskResult(
                status="error",
                error=f"Device {device.name} not found",
            )

        while not self.worker.modbus_locked:
            self.worker.modbus_locked = True
            await asyncio.sleep(0.05)
            break

        data: bytes | None = None
        rs485_device = self.worker.devices[device.name]["device"]
        if isinstance(rs485_device, RS485Client):
            data = await self.read_device_data(rs485_device)

        self.worker.modbus_locked = False

        if data == b"":
            await self.worker.log(
                f"No data received from {device.name}",
                level=logging.WARNING,
            )
            result = TaskResult(
                status="error",
                error=f"No data received from {device.name}",
                payload=data,
            )
        elif data is not None:
            result = TaskResult(
                status="success",
                error="No error",
                payload=data,
            )

        if self.worker.devices[device.name]["enabled"]:
            await asyncio.sleep(device.polling_interval)
            await self.worker.schedule_device_monitor(device)

        return result

    async def read_device_data(self, device: RS485Client) -> bytes | None:
        """Read data from the device."""
        if isinstance(device, RS485GatedFTM):
            try:
                return await monitor_qcm_device(device)
            except RuntimeError as e:
                await self.worker.log(
                    f"Failed to get data from {device.label}: {e}",
                    level=logging.ERROR,
                )
                return None
        else:
            await self.worker.log(
                f"Device {device.label} is not a supported device type for monitoring.",
                level=logging.ERROR,
            )
            return None

    async def error_decoding_device_info(
        self, e: Exception | None = None
    ) -> TaskResult:
        """Handle error when decoding device information."""
        error = f": {e}" if e else "."
        await self.worker.log(
            f"Failed to decode device information{error}",
            level=logging.ERROR,
        )
        return TaskResult(
            status="error",
            error=f"Failed to decode device information{error}",
        )

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICE_MONITOR.value
