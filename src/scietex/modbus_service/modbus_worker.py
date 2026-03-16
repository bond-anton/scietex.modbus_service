"""Worker module for modbus service."""

import msgspec

import asyncio
import time
import importlib
from typing import Type, Any
import logging
from uuid import uuid4
from serial.tools import list_ports

from scietex.hal.qcm.base.rs485 import RS485GatedFTM

from scietex.service import ValkeyWorker
from scietex.hal.serial import (
    SerialConnectionConfig,
    ModbusSerialConnectionConfig,
    VirtualSerialNetwork,
    RS485Client,
)
from scietex.hal.serial.utilities.serial_port_finder import find_serial_ports

from .version import __version__
from .schemas.configuration import ModbusConfiguration, ModbusDevice, decoder
from .schemas.tasks import Tasks
from .schemas.data_types import DataTypes

TASKS = [
    {"task": Tasks.CONFIGURATION_READ, "timeout": 10.0},
]


# pylint: disable=too-many-instance-attributes
class ModbusWorker(ValkeyWorker):
    """Worker class for modbus service."""

    tasks = asyncio.Queue()

    def __init__(self, **kwargs) -> None:
        super().__init__(service_name="modbus", version=__version__, **kwargs)
        self.modbus_configuration: ModbusConfiguration | None = None
        self.modbus_port: SerialConnectionConfig | None = None
        self.devices: dict[str, dict[str, RS485Client | int | float | str]] = {}
        self.vsn: VirtualSerialNetwork = VirtualSerialNetwork(
            virtual_ports_num=0, logger=self.logger, loopback=False
        )
        self.encoder = msgspec.msgpack.Encoder()

    async def initialize(self) -> bool:
        if not await super().initialize():
            return False
        self.vsn.start()
        for task in TASKS:
            await self.tasks.put((uuid4(), task))
        return True

    async def fetch_tasks(self) -> None:
        try:
            task_id, task_data = await asyncio.wait_for(self.tasks.get(), timeout=1)
            await self.task_queue.put((task_id, task_data))
        except TimeoutError:
            pass

    async def process_task(
        self, task_id: int | str, task_data: dict[str, Any]
    ) -> dict[str, Any]:
        task_started = time.time_ns()
        elapsed: int = 0
        result: dict[str, str | dict[str, Any] | None] = {"data": None}
        while elapsed < int(task_data.get("timeout", 10.0) * 1e9):
            if task_data.get("task") == Tasks.CONFIGURATION_READ:
                if configuration := await self.read_configuration():
                    result["data"] = {
                        "type": DataTypes.CONFIGURATION,
                        "payload": configuration,
                    }
                    break

            elif task_data.get("task") == Tasks.DEVICES_DISCONNECT:
                count = await self.disconnect_devices()
                result["data"] = {
                    "type": DataTypes.COUNT,
                    "payload": count,
                }
                break

            elif task_data.get("task") == Tasks.MODBUS_DISCONNECT:
                count = await self.disconnect_modbus()
                result["data"] = {
                    "type": DataTypes.COUNT,
                    "payload": count,
                }
                break

            elif task_data.get("task") == Tasks.MODBUS_CONNECT:
                if count := await self.connect_modbus():
                    result["data"] = {
                        "type": DataTypes.MODBUS_CONNECTIONS_COUNT,
                        "payload": count,
                    }
                    break
                else:
                    await asyncio.sleep(5)
            elif task_data.get("task") == Tasks.MODBUS_MONITOR:
                await asyncio.sleep(0.5)
                status = await self.check_modbus_connection()
                result["data"] = {
                    "type": DataTypes.MODBUS_STATUS,
                    "payload": status,
                }
                break

            elif task_data.get("task") == Tasks.DEVICES_CONNECT:
                if count := await self.connect_devices():
                    result["data"] = {
                        "type": DataTypes.COUNT,
                        "payload": count,
                    }
                    break
                else:
                    await asyncio.sleep(5)

            elif task_data.get("task") == Tasks.DEVICE_MONITOR:
                device_name = task_data.get("data")
                if not device_name:
                    await self.log(
                        "Missing device name in device monitor task", logging.ERROR
                    )
                    break
                device = self.devices.get(device_name)
                if not device:
                    await self.log(
                        "Invalid device name %s in device monitor task" % device_name,
                        logging.ERROR,
                    )
                    break
                if isinstance(device["device"], RS485GatedFTM):
                    if isinstance(device["polling_interval"], (int, float)):
                        await asyncio.sleep(device["polling_interval"] / 1000)
                    else:
                        await asyncio.sleep(1)
                    data = await device["device"].read_parameters()
                    print("MODBUS PORT HEALTHY:", await self.check_modbus_connection())
                else:
                    await self.log(
                        "Unsupported device type %s" % type(device["device"]),
                        logging.ERROR,
                    )
                    break
                result["data"] = {
                    "type": DataTypes.DEVICE_DATA,
                    "payload": {"device": device_name, "data": data},
                }
                if device["enabled"]:
                    await self.tasks.put(
                        (
                            uuid4(),
                            {
                                "task": Tasks.DEVICE_MONITOR,
                                "data": device_name,
                                "timeout": 1000.0,
                            },
                        )
                    )
                break
            await asyncio.sleep(1.0)
            elapsed = task_started - time.time_ns()
        return result

    async def return_task_to_queue(
        self, task_id: int | str, task_data: dict[str, Any]
    ) -> None:
        """Return a task to queue."""
        await self.tasks.put((task_id, task_data))

    async def read_configuration(self) -> ModbusConfiguration | None:
        """Read Modbus configuration from Valkey."""
        if self.client:
            if configuration_encoded := await self.client.get(
                f"scietex:{DataTypes.CONFIGURATION.value}:{self.service_name}:{self.worker_id}"
            ):
                return decoder.decode(configuration_encoded)
        return None

    async def process_result(self, task_id: int | str, result: dict[str, Any]) -> None:
        """Process a completed task result."""
        print(f"\nGonna have some work on task result {task_id}")
        if not result.get("data"):
            await self.log("Incompatible result format", level=logging.WARN)
            return
        if data_type := result["data"].get("type", None):
            if data_type == DataTypes.CONFIGURATION:
                if self.modbus_configuration != result["data"].get("payload"):
                    print("We have a new Configuration here. UPDATING")
                    self.modbus_configuration = result["data"].get("payload")
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.DEVICES_DISCONNECT, "timeout": 10.0})
                    )
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_DISCONNECT, "timeout": 10.0})
                    )
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_CONNECT, "timeout": 10.0})
                    )
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.DEVICES_CONNECT, "timeout": 10.0})
                    )
                else:
                    print("The Configuration has not been changed. SKIP")
            elif data_type == DataTypes.COUNT:
                await self.log(
                    "Task %s processed %i items"
                    % (task_id, result["data"].get("payload")),
                    level=logging.DEBUG,
                )
            elif data_type == DataTypes.MODBUS_CONNECTIONS_COUNT:
                if result["data"].get("payload") > 0:
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_MONITOR, "timeout": 10.0})
                    )
            elif data_type == DataTypes.MODBUS_STATUS:
                if result["data"].get("payload"):
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_MONITOR, "timeout": 10.0})
                    )
                else:
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_DISCONNECT, "timeout": 10.0})
                    )
                    await self.tasks.put(
                        (uuid4(), {"task": Tasks.MODBUS_CONNECT, "timeout": 10.0})
                    )
            elif data_type == DataTypes.DEVICE_DATA:
                print(result["data"].get("payload"))
            else:
                await self.log(
                    "Unknown result data type: %s" % data_type, level=logging.WARN
                )
        else:
            await self.log("No data type found in result", level=logging.WARN)

    async def disconnect_devices(self) -> int:
        count: int = 0
        if self.devices:
            for device_name in self.devices:
                self.devices[device_name]["enabled"] = False
                await asyncio.sleep(1)
                await self.log(
                    "Disconnecting Modbus Device %s" % device_name, level=logging.INFO
                )
                device = self.devices[device_name].get("device")
                if device and isinstance(device, RS485Client):
                    self.vsn.remove([device.con_params.port])
                count += 1
        self.devices = {}
        return count

    async def disconnect_modbus(self) -> int:
        if self.modbus_port:
            for port in self.vsn.external_ports:
                if port.port == self.modbus_port.port:
                    self.vsn.remove([self.modbus_port.port])
                    self.modbus_port = None
                    return 1
        self.modbus_port = None
        return 0

    async def check_modbus_connection(self) -> bool:
        if self.modbus_port is None or self.modbus_configuration is None:
            return False
        if self.modbus_port not in self.vsn.external_ports:
            return False
        ports = list_ports.comports()
        port_exist = False
        for port in ports:
            if port.device == self.modbus_port.port:
                port_exist = True
                break
        if not port_exist:
            return False

        return True

    async def connect_modbus(self) -> int:
        if self.modbus_port is None:
            if self.modbus_configuration:
                modbus_port = self.modbus_configuration.serial_port_config.port
                usb_match = False
                if self.modbus_configuration.serial_port_config.usb_device:
                    ports = find_serial_ports(
                        {
                            self.modbus_configuration.serial_port_config.usb_device.vendor_id: [
                                self.modbus_configuration.serial_port_config.usb_device.product_id
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
                    self.modbus_port = SerialConnectionConfig(
                        port=modbus_port,
                        baudrate=self.modbus_configuration.serial_port_config.baudrate,
                        bytesize=self.modbus_configuration.serial_port_config.bytesize,
                        parity=self.modbus_configuration.serial_port_config.parity,
                        stopbits=self.modbus_configuration.serial_port_config.stopbits,
                        timeout=self.modbus_configuration.serial_port_config.timeout,
                    )
                    self.vsn.add([self.modbus_port])
                    for port in self.vsn.external_ports:
                        if self.modbus_port.port == port.port:
                            print("==========================")
                            print("Connected MODBUS to PORT")
                            print(self.vsn.serial_ports, self.vsn.external_ports)
                            print("==========================")
                            return 1
        return 0

    async def connect_devices(self) -> int:
        count = 0
        if self.modbus_configuration and self.modbus_port:
            for device in self.modbus_configuration.devices:
                count += await self.connect_device(device)
        return count

    async def connect_device(self, device: ModbusDevice) -> int:
        if self.modbus_configuration and self.modbus_port:
            if device.name in self.devices:
                await self.log(
                    "Modbus device %s already connected. Disconnect it first."
                    % device.name,
                    level=logging.INFO,
                )
                return 0
            ports = self.vsn.create(1)
            if not ports:
                await self.log(
                    "Can not create VSN port for modbus device", level=logging.ERROR
                )
                return 0
            print("=== Connecting to port", ports[0])
            modbus_config = ModbusSerialConnectionConfig(
                port=ports[0],
                baudrate=self.modbus_configuration.serial_port_config.baudrate,
                bytesize=self.modbus_configuration.serial_port_config.bytesize,
                parity=self.modbus_configuration.serial_port_config.parity,
                stopbits=self.modbus_configuration.serial_port_config.stopbits,
                timeout=self.modbus_configuration.serial_port_config.timeout,
                framer=None,
            )
            print("CONF:", modbus_config)
            if device.modbus_device_driver.device_type.name in (
                "Quartz Crystal Microbalance (QCM)",
                "Quartz Crystal Microbalance",
                "QCM",
                "FTM",
            ):
                module_name = "scietex.hal.qcm"
                module_addon, driver_class_name = (
                    device.modbus_device_driver.name.rsplit(".", 1)
                )
                if module_addon:
                    module_name += "." + module_addon
                try:
                    module = importlib.import_module(module_name)
                    Driver: Type[RS485GatedFTM] = getattr(module, driver_class_name)
                    qcm = Driver(
                        modbus_config, address=device.address, label=device.name
                    )
                    print("GOT NEW QCM", qcm)
                    if isinstance(qcm, RS485GatedFTM):
                        print("=== QCM Starting measurement")
                        await qcm.start_measurement()
                        print("=== QCM Started measurement")
                    self.devices[device.name] = {
                        "device_type": device.modbus_device_driver.device_type.name,
                        "device": qcm,
                        "address": device.address,
                        "polling_interval": device.polling_interval,
                        "enabled": True,
                    }

                except Exception as exc:
                    print("=== QCM Excepti0n")
                    await self.log(
                        "Can not create modbus device: %s" % exc,
                        level=logging.ERROR,
                    )
                    self.vsn.remove(ports)
                    return 0
        await self.tasks.put(
            (
                uuid4(),
                {
                    "task": Tasks.DEVICE_MONITOR,
                    "data": device.name,
                    "timeout": 1000.0,
                },
            )
        )
        return 1

    async def cleanup(self):
        """
        Handles cleanup tasks upon termination, including closing any open connections.
        """
        await self.disconnect_devices()
        await self.disconnect_modbus()
        self.vsn.stop()
        await asyncio.sleep(5)
        await super().cleanup()
