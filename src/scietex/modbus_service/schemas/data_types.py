"""Data types enums."""

from enum import Enum


class DataTypes(Enum):
    """Modbus worker data types."""

    CONFIGURATION = "configuration"
    COUNT = "count"

    DEVICE_DATA = "Device data"
