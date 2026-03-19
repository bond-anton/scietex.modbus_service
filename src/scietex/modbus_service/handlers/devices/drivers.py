"""Driver factory for creating device drivers."""

import importlib

from scietex.hal.serial import RS485Client


def get_driver(device_type: str, driver_name: str) -> type[RS485Client] | None:
    """Get the driver class for a given device type."""
    module_name, driver_class_name = driver_name.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
        Driver: type[RS485Client] = getattr(module, driver_class_name)
        return Driver
    except (ImportError, AttributeError):
        return None
