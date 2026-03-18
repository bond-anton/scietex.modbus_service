"""Modbus configuration schemas."""

import msgspec


class USBDevice(msgspec.Struct, frozen=True):
    """USB device schema."""

    vendor_id: int
    product_id: int
    name: str
    description: str | None


class SerialPortConfiguration(msgspec.Struct, frozen=True):
    """Serial Port Configuration schema."""

    name: str
    description: str | None
    port: str | None
    baudrate: int | None
    bytesize: int | None
    stopbits: float | None
    parity: str | None
    timeout: float | None
    write_timeout: float | None
    inter_byte_timeout: float | None
    usb_device: USBDevice | None


class ModbusDeviceType(msgspec.Struct, frozen=True):
    """Modbus device type schema."""

    name: str
    description: str | None


class ModbusDeviceDriver(msgspec.Struct, frozen=True):
    """Modbus device driver schema."""

    name: str
    description: str | None
    device_type: ModbusDeviceType


class ModbusDevice(msgspec.Struct, frozen=True):
    """Modbus device schema."""

    name: str
    address: int
    polling_interval: int
    description: str | None
    modbus_device_driver: ModbusDeviceDriver


class ModbusConfiguration(msgspec.Struct, frozen=True):
    """Modbus configuration schema."""

    worker_id: int
    name: str
    description: str | None
    serial_port_config: SerialPortConfiguration
    devices: list[ModbusDevice]


encoder = msgspec.msgpack.Encoder()
