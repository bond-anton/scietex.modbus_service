"""Handler for disconnecting Modbus devices."""

import asyncio
from typing import TYPE_CHECKING
import logging
import msgspec

from scietex.hal.serial import RS485Client
from scietex.service.task_handlers import TaskHandler, TaskData, TaskResult, TaskTimeout
from ...schemas.tasks import Tasks
from ...schemas.results import CountResult
from ...schemas.configuration import ModbusDevice


if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class DisconnectDeviceHandler(TaskHandler):
    """Handler for disconnecting Modbus device."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()
        self.decoder = msgspec.msgpack.Decoder(ModbusDevice)

    @classmethod
    def generate_task(self, device: ModbusDevice) -> TaskData:
        """Generate a task to disconnect Modbus device."""
        return TaskData(
            task=Tasks.DEVICE_DISCONNECT.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
            payload=msgspec.msgpack.encode(device),
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Disconnect Modbus device."""
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
                self.worker.devices[device.name]["enabled"] = False
                await asyncio.sleep(0.1)
                await self.worker.log(
                    f"Disconnecting Modbus Device {device.name}", level=logging.INFO
                )
                device_instance = self.worker.devices[device.name].get("device")
                if device_instance and isinstance(device_instance, RS485Client):
                    self.worker.vsn.remove([device_instance.con_params.port])
                del self.worker.devices[device.name]
                return TaskResult(
                    status="success",
                    error="No error",
                    payload=self.encoder.encode(CountResult(count=1)),
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
        return task_type == Tasks.DEVICE_DISCONNECT.value


class DisconnectDevicesHandler(TaskHandler):
    """Handler for disconnecting Modbus devices."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to disconnect Modbus devices."""
        return TaskData(
            task=Tasks.DEVICES_DISCONNECT.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Disconnect Modbus devices."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        count = await self.disconnect_devices()
        await self.worker.log(
            f"Disconnected {count} devices totally",
            level=logging.DEBUG,
        )

        return TaskResult(
            status="success",
            error="No error",
            payload=self.encoder.encode(CountResult(count=count)),
        )

    async def disconnect_devices(self) -> int:
        """Disconnect Modbus devices and return the count of disconnected devices."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0

        count: int = 0
        if self.worker.devices:
            for device_name in self.worker.devices:
                scheduled = False
                if (
                    self.worker.modbus_configuration
                ):  # Check if modbus_configuration is available
                    for device in (
                        self.worker.modbus_configuration.devices
                    ):  # Check if the device is in the modbus_configuration
                        if (
                            device.name == device_name
                        ):  # If the device is in the modbus_configuration, schedule the disconnect task
                            await self.worker.schedule_device_disconnect(device)
                            await asyncio.sleep(0.1)
                            scheduled = True
                            break
                if not scheduled:  # If the device is not in the modbus_configuration, disconnect it directly
                    self.worker.devices[device_name]["enabled"] = False
                    await asyncio.sleep(1)
                    await self.worker.log(
                        f"Disconnecting Modbus Device {device_name}", level=logging.INFO
                    )
                    device = self.worker.devices[device_name].get("device")
                    if device and isinstance(device, RS485Client):
                        self.worker.vsn.remove([device.con_params.port])
                count += 1
        self.worker.devices = {}
        return count

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.DEVICES_DISCONNECT.value
