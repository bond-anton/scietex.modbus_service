"""Tests for the ModbusWorker gateway lifecycle and config apply hook."""

import logging

import msgspec
import pytest
from scietex.service import ValkeyWorker, ValkeyWorkerConfig

from scietex.modbus_service.config import (
    MODBUS_CONFIG_FILE,
    MODBUS_CONFIG_SUBDIR,
    ModbusSerialSettings,
    ModbusServiceSettings,
)
from scietex.modbus_service.modbus_worker import ModbusWorker


def _make_worker(tmp_path) -> ModbusWorker:
    """Build a worker with a real conf_dir and no remote-config handlers."""
    return ModbusWorker(
        ValkeyWorkerConfig(
            service_name="test",
            conf_dir=str(tmp_path),
            remote_config_enabled=False,
        )
    )


@pytest.mark.asyncio
async def test_cleanup_safe_when_never_started(tmp_path) -> None:
    """cleanup() is a no-op when the gateway was never constructed or started."""
    worker = _make_worker(tmp_path)

    await worker.cleanup()

    assert worker.gateway is None
    assert worker.tcp_server is None


@pytest.mark.asyncio
async def test_initialize_fails_when_serial_port_unopenable(tmp_path, monkeypatch) -> None:
    """A gateway bus that cannot open returns False and leaves refs cleaned up."""

    async def fake_initialize(self) -> bool:
        # Skip the live Valkey connect/config apply; only the gateway path is tested.
        return True

    monkeypatch.setattr(ValkeyWorker, "initialize", fake_initialize)

    config_path = tmp_path / MODBUS_CONFIG_SUBDIR / MODBUS_CONFIG_FILE
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(
        msgspec.yaml.encode(ModbusServiceSettings(serial=ModbusSerialSettings(port="/dev/nonexistent-port-xyz")))
    )
    worker = _make_worker(tmp_path)

    assert await worker.initialize() is False
    assert worker.gateway is None
    assert worker.tcp_server is None


def test_apply_hook_updates_settings_and_warns_on_running_gateway(tmp_path, caplog) -> None:
    """The apply hook stores settings and warns (no rebuild) when the gateway is up."""
    worker = _make_worker(tmp_path)
    worker._gateway = object()  # the hook only checks non-None; no methods are called
    settings = ModbusServiceSettings()

    worker._apply_modbus_settings(settings)

    assert worker.modbus_settings is settings
    assert any("restart required" in record.message for record in caplog.records)


def test_apply_hook_logs_info_when_gateway_not_started(tmp_path, caplog) -> None:
    """Before startup the apply hook stores settings and logs the startup path."""
    worker = _make_worker(tmp_path)
    settings = ModbusServiceSettings()

    with caplog.at_level(logging.INFO):
        worker._apply_modbus_settings(settings)

    assert worker.modbus_settings is settings
    assert any("Stored Modbus settings" in record.message for record in caplog.records)
