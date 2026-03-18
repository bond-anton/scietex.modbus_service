"""Handler for disconnecting Modbus serial port."""

from typing import TYPE_CHECKING
import logging
import msgspec

from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.results import CountResult

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class DisconnectModbusHandler(TaskHandler):
    """Handler for disconnecting Modbus serial port."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to disconnect Modbus serial port."""
        return TaskData(
            task=Tasks.MODBUS_DISCONNECT.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Disconnect Modbus serial port."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        count = await self.disconnect_modbus()
        await self.worker.log(
            f"Disconnected {count} serial ports totally",
            level=logging.DEBUG,
        )

        return TaskResult(
            status="success",
            error="No error",
            payload=self.encoder.encode(CountResult(count=count)),
        )

    async def disconnect_modbus(self) -> int:
        """Disconnect Modbus serial port and return the count of disconnected ports."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0

        if self.worker.modbus_port:
            for port in self.worker.vsn.external_ports:
                if port.port == self.worker.modbus_port.port:
                    self.worker.vsn.remove([self.worker.modbus_port.port])
                    self.worker.modbus_port = None
                    return 1
        self.worker.modbus_port = None
        return 0

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.MODBUS_DISCONNECT.value
