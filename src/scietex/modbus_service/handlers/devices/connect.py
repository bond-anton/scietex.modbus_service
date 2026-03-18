"""Handler for connecting Modbus devices."""

import asyncio
from typing import TYPE_CHECKING
import logging
import msgspec

from scietex.hal.serial import RS485Client
from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.results import CountResult

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


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
            f"Connected {count} devices totally",
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
                count += await self.connect_device(device)
        return count

    async def connect_device(self, device) -> int:
        """Connect a Modbus device and return 1 if connected successfully, otherwise return 0."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0
        print(device)

        return 0

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICES_CONNECT.value
