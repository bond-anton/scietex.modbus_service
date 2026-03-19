"""QCM Monitoring Handler for Modbus Service."""

from scietex.hal.serial import RS485Client
from scietex.hal.qcm.base.rs485 import RS485GatedFTM
from scietex.hal.qcm.base.data import FTMParameters

import msgspec


encoder = msgspec.msgpack.Encoder()


async def monitor_qcm_device(device: RS485Client[RS485GatedFTM]) -> bytes:
    """Monitor the QCM device and return its parameters."""
    try:
        parameters: FTMParameters = await device.read_parameters()
        return encoder.encode(parameters)
    except Exception as e:
        raise RuntimeError(f"Failed to monitor QCM device: {e}")
