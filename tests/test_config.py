"""Tests for the Modbus service configuration models and conversion seam."""

from pathlib import Path

import msgspec
import pytest
from scietex.hal.serial import GatewayConfigError

from scietex.modbus_service.config import (
    MODBUS_CONFIG_FILE,
    MODBUS_CONFIG_SUBDIR,
    MODBUS_SETTINGS_DEFAULTS,
    ModbusDeviceSettings,
    ModbusSerialSettings,
    ModbusServiceSettings,
    read_modbus_config,
    to_gateway_config,
)


def _config_path(conf_dir: Path) -> Path:
    """The namespaced path the loader reads and writes."""
    return conf_dir / MODBUS_CONFIG_SUBDIR / MODBUS_CONFIG_FILE


def test_yaml_roundtrip_preserves_int_device_keys() -> None:
    """Device dict keys survive a YAML round-trip as ``int``, not ``str``."""
    settings = ModbusServiceSettings(devices={1: ModbusDeviceSettings(framer="ASCII")})

    encoded = msgspec.yaml.encode(settings)
    assert b"1:" in encoded  # integer key emitted, not a string key

    decoded = msgspec.yaml.decode(encoded, type=ModbusServiceSettings)
    assert decoded.devices[1].framer == "ASCII"
    assert all(isinstance(key, int) for key in decoded.devices)


def test_defaults_constant_is_l0_base() -> None:
    """The exported L0 base is a concrete default struct instance."""
    assert isinstance(MODBUS_SETTINGS_DEFAULTS, ModbusServiceSettings)
    assert MODBUS_SETTINGS_DEFAULTS == ModbusServiceSettings()


def test_read_modbus_config_writes_defaults_when_missing(tmp_path: Path) -> None:
    """A missing file is created under the modbus/ subdir with the default patch."""
    patch = read_modbus_config(tmp_path)

    assert patch == msgspec.to_builtins(ModbusServiceSettings())
    assert _config_path(tmp_path).is_file()


def test_read_modbus_config_returns_dict_not_struct(tmp_path: Path) -> None:
    """The loader returns the L1 patch dict, never a struct."""
    patch = read_modbus_config(tmp_path)

    assert type(patch) is dict
    assert not isinstance(patch, ModbusServiceSettings)


def test_read_modbus_config_partial_file_returns_only_present_keys(tmp_path: Path) -> None:
    """A partial file yields a partial patch — absent keys inherit the layer below."""
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("port: 5020\n")

    result = read_modbus_config(tmp_path)

    assert result == {"port": 5020}


def test_read_modbus_config_partial_devices_keeps_int_keys(tmp_path: Path) -> None:
    """Device ids survive the ``type=dict`` decode as ``int`` so the merge can coerce them."""
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("devices:\n  1:\n    framer: ASCII\n")

    result = read_modbus_config(tmp_path)

    assert result["devices"] == {1: {"framer": "ASCII"}}
    assert all(isinstance(key, int) for key in result["devices"])


def test_read_modbus_config_malformed_raises_and_leaves_file(tmp_path: Path) -> None:
    """An unparseable file raises RuntimeError and is left untouched."""
    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("unterminated: [flow\n")

    with pytest.raises(RuntimeError):
        read_modbus_config(tmp_path)

    assert path.read_text() == "unterminated: [flow\n"


def test_read_modbus_config_none_dir_raises() -> None:
    """A None conf_dir is rejected with RuntimeError."""
    with pytest.raises(RuntimeError):
        read_modbus_config(None)


def test_read_modbus_config_missing_without_create_raises(tmp_path: Path) -> None:
    """A missing file with create_default=False raises and writes nothing."""
    with pytest.raises(RuntimeError):
        read_modbus_config(tmp_path, create_default=False)

    assert not _config_path(tmp_path).exists()


def test_to_gateway_config_device_id_from_dict_key() -> None:
    """The device id is derived from the dict key, not a field."""
    config = to_gateway_config(ModbusServiceSettings(devices={7: ModbusDeviceSettings()}))

    assert config.devices[7].device_id == 7


def test_to_gateway_config_invalid_device_id_raises() -> None:
    """An out-of-range device id is delegated to GatewayConfig and raises."""
    settings = ModbusServiceSettings(devices={300: ModbusDeviceSettings()})

    with pytest.raises(GatewayConfigError):
        to_gateway_config(settings)


def test_to_gateway_config_bad_dotted_path_raises() -> None:
    """An unresolvable plugin path is delegated to GatewayConfig and raises."""
    settings = ModbusServiceSettings(devices={1: ModbusDeviceSettings(translator="no.such.module.Translator")})

    with pytest.raises(GatewayConfigError):
        to_gateway_config(settings)


def test_serial_settings_has_no_framer_field() -> None:
    """The serial framer is dead at the gateway, so it must not be settable."""
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert({"framer": "RTU"}, type=ModbusSerialSettings)
