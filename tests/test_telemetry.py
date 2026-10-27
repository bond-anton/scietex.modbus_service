"""Tests for the telemetry payloads and the Telemetry manager loop."""

import socket

import msgspec
import pytest
from glide import ExpiryType
from scietex.service import ValkeyWorkerConfig

from scietex.modbus_service.config import ModbusDeviceSettings, ModbusSerialSettings, ModbusServiceSettings
from scietex.modbus_service.modbus_worker import ModbusWorker
from scietex.modbus_service.telemetry import ModbusBusStats, ModbusGatewayTelemetry, build_telemetry


def _make_worker(tmp_path) -> ModbusWorker:
    """Build a worker with a real conf_dir and no remote-config handlers."""
    return ModbusWorker(
        ValkeyWorkerConfig(
            service_name="test",
            conf_dir=str(tmp_path),
            remote_config_enabled=False,
        )
    )


def _free_port() -> int:
    """Pick a free unprivileged TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_build_telemetry_unconfigured_worker(tmp_path) -> None:
    """An unconfigured worker reports configured=False with zeroed fields."""
    worker = _make_worker(tmp_path)

    telemetry = build_telemetry(worker)

    assert telemetry.service == "test"
    assert telemetry.instance_id == worker.instance_id
    assert telemetry.configured is False
    assert telemetry.serial_connected is False
    assert telemetry.serial_port is None
    assert telemetry.tcp_listening is False
    assert telemetry.tcp_host is None
    assert telemetry.tcp_port is None
    assert telemetry.client_count == 0
    assert telemetry.devices == []
    assert telemetry.routed == []
    assert telemetry.bus == ModbusBusStats(0, 0, 0)
    assert telemetry.schema_version == 1


@pytest.mark.asyncio
async def test_build_telemetry_configured_worker(tmp_path) -> None:
    """A configured worker reads the gateway and TCP-server accessors."""
    worker = _make_worker(tmp_path)
    settings = ModbusServiceSettings(
        host="127.0.0.1",
        port=_free_port(),
        serial=ModbusSerialSettings(port="/dev/nonexistent-port-xyz"),
        devices={1: ModbusDeviceSettings(framer="RTU")},
    )
    assert await worker._build_and_start_gateway(settings) is True
    try:
        telemetry = build_telemetry(worker)

        assert telemetry.configured is True
        assert telemetry.serial_connected is False  # unopenable serial port
        assert telemetry.serial_port == "/dev/nonexistent-port-xyz"
        assert telemetry.tcp_listening is True
        assert telemetry.tcp_host == "127.0.0.1"
        assert telemetry.tcp_port == settings.port
        assert telemetry.client_count == 0
        assert telemetry.devices == []
        assert telemetry.routed == [1]
        assert telemetry.bus == ModbusBusStats(0, 0, 0)
    finally:
        await worker.cleanup()


@pytest.mark.asyncio
async def test_build_telemetry_reports_routing_table_not_observed_devices(tmp_path) -> None:
    """``routed`` is the gateway's routing table, not the addresses it served.

    An address can be observed (a client addressed it) while having no entry in
    the routing table — that is exactly what "unknown address" means, and the
    API relies on the two sets being reported separately.
    """
    worker = _make_worker(tmp_path)
    settings = ModbusServiceSettings(
        host="127.0.0.1",
        port=_free_port(),
        serial=ModbusSerialSettings(port="/dev/nonexistent-port-xyz"),
        devices={1: ModbusDeviceSettings(framer="RTU"), 3: ModbusDeviceSettings(framer="RTU")},
    )
    assert await worker._build_and_start_gateway(settings) is True
    try:
        gateway = worker.gateway
        assert gateway is not None
        gateway.metrics.record_request(9)
        gateway.metrics.touch(9)

        telemetry = build_telemetry(worker)

        assert telemetry.routed == [1, 3]
        assert [device.device_id for device in telemetry.devices] == [9]
    finally:
        await worker.cleanup()


@pytest.mark.asyncio
async def test_build_telemetry_reports_pending_restart_after_a_late_delivery(tmp_path) -> None:
    """A setting delivered after the gateway was built is inert until restart.

    The gateway is constructed once and never rebuilt, so the worker stores the
    new settings while the live gateway keeps the old ones. ``pending_restart``
    names the fields that differ, which is what the UI needs to tell an operator
    that a restart is required.
    """
    worker = _make_worker(tmp_path)
    settings = ModbusServiceSettings(
        host="127.0.0.1",
        port=_free_port(),
        serial=ModbusSerialSettings(port="/dev/nonexistent-port-xyz"),
        allow_unknown_devices=True,
    )
    assert await worker._build_and_start_gateway(settings) is True
    try:
        assert build_telemetry(worker).pending_restart == []

        # A later delivery is stored but does not rebuild the gateway.
        worker._apply_modbus_settings(
            ModbusServiceSettings(
                host="127.0.0.1",
                port=settings.port,
                serial=ModbusSerialSettings(port="/dev/nonexistent-port-xyz"),
                allow_unknown_devices=False,
            )
        )

        assert build_telemetry(worker).pending_restart == ["allow_unknown_devices"]
    finally:
        await worker.cleanup()


@pytest.mark.asyncio
async def test_telemetry_loop_writes_key_with_ttl(tmp_path, monkeypatch) -> None:
    """The Telemetry manager writes to scietex:{service}:{instance}:telemetry, TTL 6."""
    monkeypatch.setattr("scietex.modbus_service.modbus_worker.TELEMETRY_INTERVAL", 0)
    worker = _make_worker(tmp_path)

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def set(self, key, value=None, expiry=None):
            self.calls.append((key, value, expiry))

    fake = FakeClient()
    monkeypatch.setattr(worker, "_client", fake)

    await worker.telemetry_loop()

    assert len(fake.calls) == 1
    key, value, expiry = fake.calls[0]
    assert key == f"scietex:{worker.service_name}:{worker.instance_id}:telemetry"
    assert expiry.expiry_type == ExpiryType.SEC
    assert int(expiry.value) == 6

    decoded = msgspec.msgpack.decode(value, type=ModbusGatewayTelemetry)
    assert decoded.configured is False
    assert decoded.schema_version == 1
