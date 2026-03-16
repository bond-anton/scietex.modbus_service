"""Data types enums."""

from enum import Enum


class DataTypes(Enum):
    """Modbus worker data types."""

    CONFIGURATION = "configuration"
    COUNT = "count"

    DEVICE_DATA = "Device data"

    MODBUS_CONNECTIONS_COUNT = "Modbus Connections Count"
    MODBUS_STATUS = "Modbus Connection Status"
