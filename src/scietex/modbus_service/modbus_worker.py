"""Worker module for modbus service."""

from scietex.service import ValkeyWorker

from .version import __version__


# pylint: disable=too-many-instance-attributes
class ModbusWorker(ValkeyWorker):
    """Worker class for modbus service."""

    def __init__(self, **kwargs) -> None:
        super().__init__(service_name="modbus", version=__version__, **kwargs)
