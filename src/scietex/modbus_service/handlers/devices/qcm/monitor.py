"""QCM Monitoring Handler for Modbus Service."""

import msgspec
from scietex.hal.qcm.base.data import FTMParameters
from scietex.hal.qcm.base.rs485 import RS485GatedFTM
from scietex.hal.serial import RS485Client

encoder = msgspec.msgpack.Encoder()


async def monitor_qcm_device(device: RS485Client) -> bytes:
    """Monitor the QCM device and return its parameters."""
    try:
        if not isinstance(device, RS485GatedFTM):
            raise TypeError("device is not a subclass of RS485GatedFTM.")
        parameters: FTMParameters = await device.read_parameters()
        return encoder.encode(parameters)
    except Exception as e:
        raise RuntimeError(f"Failed to monitor QCM device: {e}")
