"""ADC Monitoring Handler for Modbus Service."""

import msgspec
from scietex.hal.adc.base.data import ADCParameters
from scietex.hal.adc.base.rs485 import RS485ADC
from scietex.hal.serial import RS485Client

encoder = msgspec.msgpack.Encoder()


async def monitor_adc_device(device: RS485Client) -> bytes:
    """Monitor the ADC device and return its parameters."""
    try:
        if not isinstance(device, RS485ADC):
            raise TypeError("device is not a subclass of RS485ADC.")
        parameters: ADCParameters = await device.read_parameters()
        print(f"Read parameters from ADC device: {parameters}")
        return encoder.encode(parameters)
    except Exception as e:
        raise RuntimeError(
            f"Failed to monitor ADC device: {e}. Parameters: {parameters if 'parameters' in locals() else 'N/A'}"
        ) from e
