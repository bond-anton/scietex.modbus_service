"""``serial:list`` data-plane task: enumerate serial ports on the worker host.

The worker runs on the machine that owns the serial bus, so it is the only
process that can see the host's ``/dev/tty*`` devices. The UI submits this task
on demand (when the operator opens the port picker) and reads the result back
through the task tracking record.
"""

from typing import ClassVar

import msgspec
from scietex.hal.serial import list_serial_ports
from scietex.service.task_handler import (
    TaskCapabilities,
    TaskData,
    TaskHandler,
    TaskResult,
)

#: Task name for the serial-port enumeration data task.
SERIAL_LIST_TASK_NAME = "serial:list"


class SerialPortInfo(msgspec.Struct, frozen=True, omit_defaults=True):
    """One enumerated serial port.

    Args:
        device: Device path (e.g. ``/dev/ttyUSB0``).
        description: Human-readable description; empty when pyserial reports
            none.
    """

    device: str
    description: str = ""


class SerialListResponse(msgspec.Struct, frozen=True):
    """Result payload of a ``serial:list`` task.

    Args:
        ports: Every serial port the host exposes; empty is a normal result.
    """

    ports: list[SerialPortInfo] = msgspec.field(default_factory=list)


class SerialListHandler(TaskHandler):
    """Handle ``serial:list`` on the data lane.

    The task takes no parameters, so the request payload is ignored. The
    response is JSON-encoded (not msgpack) because the API serializes the
    result bytes as base64 and the UI decodes them without a msgpack
    dependency.
    """

    control: ClassVar[bool] = False

    @property
    def supported_tasks(self) -> list[str]:
        """Task types this handler serves."""
        return [SERIAL_LIST_TASK_NAME]

    async def handle(self, task_data: TaskData, *, capabilities: TaskCapabilities) -> TaskResult:
        """Enumerate the host's serial ports.

        An empty list is a normal success, not an error. A host enumeration
        failure is terminal for this call (retrying cannot help).
        """
        try:
            ports = list_serial_ports()
        except Exception as exc:
            return TaskResult(
                status="error",
                error=str(exc),
                error_code="SERIAL_LIST_FAILED",
                retryable=False,
            )
        response = SerialListResponse(
            ports=[SerialPortInfo(device=port.device, description=port.description) for port in ports]
        )
        return TaskResult(status="success", payload=msgspec.json.encode(response))
