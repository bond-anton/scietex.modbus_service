"""Configuration models and YAML loader for the Modbus gateway service.

`ModbusServiceSettings` is the concrete constructor (L0) base and the validation
target of the framework's four-layer config merge. `modbus.yml` is the L1
bootstrap patch: a field-level map merged onto L0, then overlaid by the
framework's `config.yml` snapshot (L2) and the remote `modbus` section (L3). The
struct is kept deliberately thin: device-id range, framer resolvability, and
plugin dotted-path resolution are delegated to `GatewayConfig.__post_init__` via
`to_gateway_config`, so the YAML schema only constrains types and unknown fields.

The serial settings intentionally omit a ``framer`` field: the gateway selects
framing per device via `GatewayConfig.default_framer` (and each device's own
`framer`), so a framer on the serial connection is dead configuration. The
top-level ``port`` is the TCP listen port, while ``serial.port`` is the device
path — the two are unrelated and must not be conflated.
"""

from pathlib import Path

import msgspec
from scietex.hal.serial import GatewayConfig, GatewayDeviceConfig, ModbusSerialConnectionConfig
from scietex.hal.serial.config.defaults import (
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_TIMEOUT,
)

#: Remote-config section name the settings are registered under.
MODBUS_SECTION: str = "modbus"

#: Subdirectory under the shared config dir that namespaces this service's
#: files. The framework's ``config.yml`` snapshot and the service-owned
#: ``modbus.yml`` both live here, so services sharing one config dir (the
#: framework resolves a single dir for all scietex services) cannot collide.
MODBUS_CONFIG_SUBDIR: str = "modbus"

#: Filename of the service-owned L1 bootstrap patch in the config subdirectory.
MODBUS_CONFIG_FILE: str = "modbus.yml"


class ModbusDeviceSettings(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Per-device routing settings for a single Modbus device id.

    The device id itself is the dict key in `ModbusServiceSettings.devices`, not
    a field here, so the conversion seam can derive `GatewayDeviceConfig.device_id`
    from it and satisfy the gateway's ``key == device.device_id`` invariant.
    """

    framer: str = "RTU"
    decoder: str | None = None
    pdus: list[str] = msgspec.field(default_factory=list)
    translator: str | None = None


class ModbusSerialSettings(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Serial bus connection settings.

    ``port`` is the device path (e.g. ``/dev/ttyUSB0``). There is no ``framer``
    field: the gateway ignores the serial-level framer and selects framing per
    device from `GatewayConfig.default_framer` / `ModbusDeviceSettings.framer`.
    """

    port: str = "/dev/ttyUSB0"
    baudrate: int = DEFAULT_BAUDRATE
    bytesize: int = DEFAULT_BYTESIZE
    parity: str = DEFAULT_PARITY
    stopbits: int | float = DEFAULT_STOPBITS
    timeout: float | None = DEFAULT_TIMEOUT


class ModbusServiceSettings(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Top-level Modbus gateway settings.

    ``port`` is the TCP listen port; ``serial.port`` is the device path. Device
    entries are keyed by device id so the key becomes the `device_id` when
    converted to `GatewayDeviceConfig` objects.
    """

    serial: ModbusSerialSettings = ModbusSerialSettings()
    host: str = "0.0.0.0"
    port: int = 502
    default_framer: str = "RTU"
    devices: dict[int, ModbusDeviceSettings] = msgspec.field(default_factory=dict)
    allow_unknown_devices: bool = False
    bus_retries: int = 0


#: Concrete L0 base for the framework's layered merge. A field absent from every
#: layer, or explicitly cleared with ``null``, resolves to the value here.
MODBUS_SETTINGS_DEFAULTS: ModbusServiceSettings = ModbusServiceSettings()


def read_modbus_config(conf_dir: Path | None, *, create_default: bool = True) -> dict[str, object]:
    """Read the L1 bootstrap patch from ``modbus/modbus.yml`` under the config directory.

    The service's files are namespaced in a ``modbus/`` subdirectory so they do
    not collide with other services sharing the framework's single config dir.
    The file (and, when missing, its directory) is only created when
    ``create_default=True`` (the bootstrap path). A ``None`` or non-directory
    ``conf_dir``, a missing file/directory with ``create_default=False``, or an
    unparseable file each raise `RuntimeError`. An existing-but-invalid file is
    left untouched regardless of ``create_default``.

    The return value is the raw ``modbus.yml`` mapping — the L1 patch the
    framework merges onto the L0 base and validates through
    `ModbusServiceSettings`. When the file is just created, the builtins of the
    default struct are returned so the patch is equivalent to an empty override.

    Args:
        conf_dir: Path to the configuration directory.
        create_default: Whether to create the directory and write a default
            ``modbus.yml`` when missing. Default ``True``.

    Returns:
        The parsed ``modbus.yml`` mapping as the L1 patch, or the builtins of the
        default `ModbusServiceSettings` when the file was just created.

    Raises:
        RuntimeError: If ``conf_dir`` is ``None`` or not a directory, the file
            is missing with ``create_default=False``, or the file cannot be parsed.
    """
    if not isinstance(conf_dir, Path):
        raise RuntimeError("Configuration dir was not set!")
    service_dir = conf_dir / MODBUS_CONFIG_SUBDIR
    if not service_dir.exists():
        if create_default:
            try:
                service_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                raise RuntimeError(f"Failed to create configuration directory {service_dir}!") from exc
        else:
            raise RuntimeError(
                f"Configuration directory {service_dir} does not exist and create_default=False (no default generated)."
            )
    elif not service_dir.is_dir():
        raise RuntimeError(f"Provided configuration directory path {service_dir} is not a directory!")
    modbus_yml = service_dir.joinpath(MODBUS_CONFIG_FILE)
    if not modbus_yml.exists():
        if create_default:
            settings = ModbusServiceSettings()
            with open(modbus_yml, "wb") as f:
                f.write(msgspec.yaml.encode(settings))
            return msgspec.to_builtins(settings)
        raise RuntimeError(
            f"Modbus configuration file {modbus_yml} does not exist and create_default=False "
            "(pass create_default=True to generate defaults)."
        )
    try:
        with open(modbus_yml, "rb") as f:
            return msgspec.yaml.decode(f.read(), type=dict)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse Modbus configuration file {modbus_yml}. Fix the file or remove it to regenerate defaults."
        ) from exc


def to_gateway_config(settings: ModbusServiceSettings) -> GatewayConfig:
    """Convert service settings into a `GatewayConfig` for the gateway core.

    The device id is taken from each dict key so the gateway's invariant
    (``key == device.device_id``) holds. ``framer`` is intentionally not passed
    to `ModbusSerialConnectionConfig` — the gateway ignores it. Validation
    (device-id range, framer/decoder/pdu/translator resolution) is delegated to
    `GatewayConfig.__post_init__`, so `GatewayConfigError` and
    `SerialConnectionConfigError` propagate unchanged to the caller.

    Args:
        settings: The service settings to convert.

    Returns:
        A `GatewayConfig` ready for `ModbusGateway`.
    """
    serial = ModbusSerialConnectionConfig(
        port=settings.serial.port,
        baudrate=settings.serial.baudrate,
        bytesize=settings.serial.bytesize,
        parity=settings.serial.parity,
        stopbits=settings.serial.stopbits,
        timeout=settings.serial.timeout,
    )
    devices = {
        device_id: GatewayDeviceConfig(
            device_id=device_id,
            framer=device.framer,
            decoder=device.decoder,
            pdus=device.pdus,
            translator=device.translator,
        )
        for device_id, device in settings.devices.items()
    }
    return GatewayConfig(
        serial=serial,
        host=settings.host,
        port=settings.port,
        default_framer=settings.default_framer,
        devices=devices,
        allow_unknown_devices=settings.allow_unknown_devices,
        bus_retries=settings.bus_retries,
    )
