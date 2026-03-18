"""Handler for monitoring Modbus serial port connection."""

from typing import TYPE_CHECKING
import asyncio
import logging
import msgspec

from serial.tools import list_ports
from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.results import StatusResult

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class CheckModbusConnectionHandler(TaskHandler):
    """Handler for monitoring Modbus serial port connection."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to monitor Modbus connection."""
        return TaskData(
            task=Tasks.MODBUS_MONITOR.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Monitor Modbus serial port connection."""
        from ...modbus_worker import ModbusWorker

        result = await self.monitor_modbus(task_data)
        if not isinstance(self.worker, ModbusWorker):
            return result
        if result.status == "error":
            if self.worker.modbus_port:
                await self.worker.schedule_modbus_disconnect()
                await asyncio.sleep(1)  # wait before retrying to connect Modbus
            else:
                await asyncio.sleep(2)  # wait before retrying to connect Modbus
            await self.worker.schedule_modbus_connect()
            return result
        await asyncio.sleep(0.5)  # wait before the next monitor check
        await self.worker.schedule_modbus_monitor()  # Schedule the next monitor task
        return result

    async def monitor_modbus(self, task_data: TaskData) -> TaskResult:
        """Check Modbus serial port connection status."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
                payload=self.encoder.encode(StatusResult(False)),
            )

        status = await self.check_modbus_connection()
        await self.worker.log(
            f"Modbus Connection healthy: {status}",
            level=logging.DEBUG,
        )
        if status:
            return TaskResult(
                status="success",
                error="No error",
                payload=self.encoder.encode(StatusResult(status)),
            )
        else:
            return TaskResult(
                status="error",
                error="Modbus serial port connection failed",
                payload=self.encoder.encode(StatusResult(status)),
            )

    async def check_modbus_connection(self) -> bool:
        """Check if Modbus serial port is connected and healthy."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return False

        if self.worker.modbus_port is None or self.worker.modbus_configuration is None:
            return False
        if self.worker.modbus_port not in self.worker.vsn.external_ports:
            return False
        ports = list_ports.comports()
        port_exist = False
        for port in ports:
            if port.device == self.worker.modbus_port.port:
                port_exist = True
                break
        if not port_exist:
            return False

        return True

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.MODBUS_MONITOR.value
