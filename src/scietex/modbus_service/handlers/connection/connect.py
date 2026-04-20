"""Handler for connecting Modbus serial port."""

import asyncio
import logging
from typing import TYPE_CHECKING

import msgspec
from scietex.hal.serial import SerialConnectionConfig
from scietex.hal.serial.utilities.serial_port_finder import find_serial_ports
from scietex.service.task_handlers import TaskData, TaskHandler, TaskResult, TaskTimeout

from ...schemas.results import CountResult
from ...schemas.tasks import Tasks

if TYPE_CHECKING:
    from ...modbus_worker import ModbusWorker


class ConnectModbusHandler(TaskHandler):
    """Handler for connecting Modbus serial port."""

    def __init__(self, worker: "ModbusWorker") -> None:
        """Initialize the handler."""
        super().__init__(worker)
        self._is_initialized = True
        self.encoder = msgspec.msgpack.Encoder()

    @classmethod
    def generate_task(self) -> TaskData:
        """Generate a task to connect Modbus serial port."""
        return TaskData(
            task=Tasks.MODBUS_CONNECT.value,
            timeout=TaskTimeout(10, "requeue"),
            canceled_action="discard",
        )

    async def handle(self, task_data: TaskData) -> TaskResult:
        """Connect Modbus serial port."""
        from ...modbus_worker import ModbusWorker

        result = await self.try_to_connect_modbus(task_data)
        if not isinstance(self.worker, ModbusWorker):
            return result
        if result.status == "error":
            await asyncio.sleep(2)  # wait before retrying to connect Modbus
            await self.worker.schedule_modbus_connect()
            return result
        await self.worker.schedule_devices_connect()
        await self.worker.schedule_modbus_monitor()  # Schedule the monitor task after successful connection
        return result

    async def try_to_connect_modbus(self, task_data: TaskData) -> TaskResult:
        """Try to connect Modbus serial port."""
        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return TaskResult(
                status="error",
                error="Worker is not a ModbusWorker",
            )
        count = await self.connect_modbus()

        if count > 0:
            await self.worker.log(
                f"Connected {count} serial ports totally",
                level=logging.DEBUG,
            )
            return TaskResult(
                status="success",
                error="No error",
                payload=self.encoder.encode(CountResult(count=count)),
            )
        else:
            return TaskResult(
                status="error",
                error="Failed to connect Modbus serial port",
                payload=self.encoder.encode(CountResult(count=count)),
            )

    async def connect_modbus(self) -> int:
        """Connect Modbus serial port and return the count of connected ports."""

        from ...modbus_worker import ModbusWorker

        if not isinstance(self.worker, ModbusWorker):
            return 0

        if self.worker.modbus_port is not None:
            await self.worker.log(
                "Already connected to serial port",
                level=logging.DEBUG,
            )
            return 1

        if self.worker.modbus_configuration:
            modbus_port = self.worker.modbus_configuration.serial_port_config.port
            usb_match = False
            if self.worker.modbus_configuration.serial_port_config.usb_device:
                ports = find_serial_ports(
                    {
                        self.worker.modbus_configuration.serial_port_config.usb_device.vendor_id: [
                            self.worker.modbus_configuration.serial_port_config.usb_device.product_id
                        ]
                    }
                )
                if modbus_port:
                    for port in ports:
                        if port == modbus_port:
                            usb_match = True
                            break
                elif ports:
                    modbus_port = ports[0]
                    usb_match = True
            else:
                usb_match = True
            if modbus_port and usb_match:
                self.worker.modbus_port = SerialConnectionConfig(
                    port=modbus_port,
                    baudrate=self.worker.modbus_configuration.serial_port_config.baudrate,
                    bytesize=self.worker.modbus_configuration.serial_port_config.bytesize,
                    parity=self.worker.modbus_configuration.serial_port_config.parity,
                    stopbits=self.worker.modbus_configuration.serial_port_config.stopbits,
                    timeout=self.worker.modbus_configuration.serial_port_config.timeout,
                )
                self.worker.vsn.add([self.worker.modbus_port])
                for port in self.worker.vsn.external_ports:
                    if self.worker.modbus_port.port == port.port:
                        print("==========================")
                        print("Connected MODBUS to PORT")
                        print(
                            self.worker.vsn.serial_ports,
                            self.worker.vsn.external_ports,
                        )
                        print("==========================")
                        return 1
        return 0

    def supports(self, task_type: str) -> bool:
        """Check if the handler supports the given task type."""
        return task_type == Tasks.MODBUS_CONNECT.value
