"""Handler for enabling Modbus devices."""

import asyncio
from typing import TYPE_CHECKING
import logging
import msgspec

from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.configuration import ModbusDevice


if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class EnableDeviceHandler(TaskHandler):
    """Handler for enabling Modbus device."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()
        self.decoder = msgspec.msgpack.Decoder(ModbusDevice)

    @classmethod
    def generate_task(self, device: ModbusDevice) -> TaskData:
        """Generate a task to enable Modbus device."""
        return TaskData(
            task=Tasks.DEVICE_ENABLE.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
            payload=msgspec.msgpack.encode(device),
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Enable Modbus device."""
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
            if device.name in self.worker.devices:
                self.worker.devices[device.name]["enabled"] = True
                await asyncio.sleep(0.1)
                await self.worker.log(
                    f"Enabled Modbus Device {device.name}", level=logging.INFO
                )
                return TaskResult(
                    status="success",
                    error="No error",
                )
            else:
                return TaskResult(
                    status="error",
                    error=f"Device {device.name} not found",
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

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICE_ENABLE.value
