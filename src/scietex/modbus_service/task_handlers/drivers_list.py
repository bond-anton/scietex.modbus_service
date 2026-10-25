"""``drivers:list`` control-plane task: report the drivers this worker can serve.

The gateway resolves a device's driver references at startup, so a driver is
only usable if every reference it names is importable in *this* process. The
API cannot answer that question: it runs in a different environment with a
different set of installed packages. The worker therefore reports both the
catalogue it sees and whether each entry actually resolves here.

This is a control-plane task because the answer describes the worker's own
capabilities rather than a measurement, and the API submits it through the
control lane when the operator opens the driver picker.
"""

from typing import ClassVar

import msgspec
from scietex.hal.serial.gateway.drivers import discover_drivers, verify_driver
from scietex.service.task_handler import (
    TaskCapabilities,
    TaskData,
    TaskHandler,
    TaskResult,
)

#: Task name for the driver-availability control task.
DRIVERS_LIST_TASK_NAME = "drivers:list"


class DriverAvailability(msgspec.Struct, frozen=True, omit_defaults=True):
    """One driver and whether this worker can resolve it.

    Args:
        name: Entry-point name of the driver.
        available: Whether every reference the driver names resolves here.
        reason: Why the driver is unavailable; empty when it is available.
    """

    name: str
    available: bool = True
    reason: str = ""


class DriversListResponse(msgspec.Struct, frozen=True):
    """Result payload of a ``drivers:list`` task.

    Args:
        drivers: Every driver the worker's environment advertises, sorted by
            name; empty is a normal result.
    """

    drivers: list[DriverAvailability] = msgspec.field(default_factory=list)


class DriversListHandler(TaskHandler):
    """Handle ``drivers:list`` on the control lane.

    The task takes no parameters, so the request payload is ignored. The
    response is JSON-encoded for the same reason as ``serial:list``: the API
    serializes result bytes as base64 and the UI decodes them without a msgpack
    dependency.
    """

    control: ClassVar[bool] = True

    @property
    def supported_tasks(self) -> list[str]:
        """Task types this handler serves."""
        return [DRIVERS_LIST_TASK_NAME]

    async def handle(self, task_data: TaskData, *, capabilities: TaskCapabilities) -> TaskResult:
        """Report the catalogue and per-driver availability.

        An empty catalogue is a normal success. A discovery failure is terminal
        for this call: retrying cannot make a broken entry point resolve.
        """
        try:
            catalogue = discover_drivers()
        except Exception as exc:
            return TaskResult(
                status="error",
                error=str(exc),
                error_code="DRIVERS_LIST_FAILED",
                retryable=False,
            )
        response = DriversListResponse(
            drivers=[
                DriverAvailability(
                    name=driver.name,
                    available=(reason := verify_driver(driver)) is None,
                    reason=reason or "",
                )
                for driver in catalogue.values()
            ]
        )
        return TaskResult(status="success", payload=msgspec.json.encode(response))
