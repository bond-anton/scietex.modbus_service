"""Handler for reading Modbus configuration from Valkey."""

import asyncio
import logging
from typing import TYPE_CHECKING

import msgspec
from scietex.service.task_handlers import TaskData, TaskHandler, TaskResult, TaskTimeout

from ...schemas.configuration import ModbusConfiguration
from ...schemas.tasks import Tasks

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class ReadConfigurationHandler(TaskHandler):
    """Handler for reading Modbus configuration from Valkey."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.decoder = msgspec.msgpack.Decoder(ModbusConfiguration)
        self.conf_key = "scietex:configuration:" + f"{self.worker.service_name}:{self.worker.worker_id}"

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to read the Modbus configuration."""
        return TaskData(
            task=Tasks.CONFIGURATION_READ.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        from ...modbus_worker import ModbusWorker

        result = await self.try_to_read_configuration(task_data)
        if not isinstance(self.worker, ModbusWorker):
            return result
        if result.status == "error":
            await asyncio.sleep(5)  # wait before retrying to read configuration
            await self.worker.schedule_configuration_read()
            return result
        await self.worker.schedule_devices_disconnect()
        await self.worker.schedule_modbus_disconnect()
        await self.worker.schedule_modbus_connect()
        await self.worker.schedule_devices_connect()
        return result

    async def try_to_read_configuration(self, task_data: TaskData) -> TaskResult:
        """Read Modbus configuration from Valkey."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        if not self.worker.client:
            return TaskResult(
                status="error",
                error="Worker is not connected to Valkey",
            )

        configuration_encoded = await self.worker.client.get(self.conf_key)
        if not configuration_encoded:
            return TaskResult(
                status="error",
                error="No configuration found in Valkey",
            )
        try:
            modbus_configuration = self.decoder.decode(configuration_encoded)
            if self.worker.modbus_configuration != modbus_configuration:
                await self.worker.log("We have a new Configuration here. UPDATING", level=logging.INFO)
                self.worker.modbus_configuration = modbus_configuration
            return TaskResult(status="success", error="No error", payload=configuration_encoded)
        except Exception as e:
            return TaskResult(
                status="error",
                error=f"Failed to decode configuration: {str(e)}",
            )

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.CONFIGURATION_READ.value
