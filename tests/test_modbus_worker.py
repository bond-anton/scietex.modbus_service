"""Tests for the ModbusWorker gateway lifecycle and config apply hook."""

import logging
import os
import socket
from pathlib import Path

import msgspec
import pytest
from pymodbus.datastore import ModbusDeviceContext
from pymodbus.pdu import ExceptionResponse
from pymodbus.pdu.register_message import (
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
)
from scietex.hal.serial.config import ModbusSerialConnectionConfig
from scietex.hal.serial.server.rs485_server import (
    ReactiveSequentialDataBlock,
    RS485Server,
)
from scietex.hal.serial.virtual import VirtualSerialPair
from scietex.service import ValkeyWorker, ValkeyWorkerConfig

from scietex.modbus_service.config import (
    MODBUS_CONFIG_FILE,
    MODBUS_CONFIG_SUBDIR,
    ModbusDeviceSettings,
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


def _free_port() -> int:
    """Pick a free unprivileged TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(tmp_path, *, serial_port: str, devices: dict) -> None:
    """Write a modbus.yml with an unprivileged TCP port and the given devices."""
    config_path = tmp_path / MODBUS_CONFIG_SUBDIR / MODBUS_CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(
        msgspec.yaml.encode(
            ModbusServiceSettings(
                host="127.0.0.1",
                port=_free_port(),
                serial=ModbusSerialSettings(port=serial_port),
                devices=devices,
            )
        )
    )


@pytest.fixture
def vsp():
    """A virtual serial pair, stopped on teardown."""
    pair = VirtualSerialPair()
    pair.start()
    yield pair
    pair.stop()


@pytest.fixture
def bus_server(vsp):
    """An RS485 server on one end of the virtual pair."""
    block = ReactiveSequentialDataBlock(0x01, list(range(1, 101)))
    store = ModbusDeviceContext(di=block, co=block, hr=block, ir=block)
    serial = ModbusSerialConnectionConfig(vsp.serial_ports[0], timeout=0.5)
    return RS485Server(serial, devices={1: store})


@pytest.mark.asyncio
async def test_cleanup_safe_when_never_started(tmp_path) -> None:
    """cleanup() is a no-op when the gateway was never constructed or started."""
    worker = _make_worker(tmp_path)

    await worker.cleanup()

    assert worker.gateway is None
    assert worker.tcp_server is None


@pytest.mark.asyncio
async def test_initialize_succeeds_when_serial_port_unopenable(tmp_path, monkeypatch, caplog) -> None:
    """A missing serial port does not fail startup; the gateway stays up.

    The gateway tolerates an unopenable bus (it reconnects on the next request),
    so initialization succeeds and both the gateway and TCP server are built.
    The TCP port is unprivileged so the serial port is the only failure.
    """

    async def fake_initialize(self) -> bool:
        # Skip the live Valkey connect/config apply; only the gateway path is tested.
        return True

    monkeypatch.setattr(ValkeyWorker, "initialize", fake_initialize)

    _write_config(
        tmp_path,
        serial_port="/dev/nonexistent-port-xyz",
        devices={1: ModbusDeviceSettings(framer="RTU")},
    )
    worker = _make_worker(tmp_path)

    with caplog.at_level(logging.WARNING):
        assert await worker.initialize() is True

    assert worker.gateway is not None
    assert worker.tcp_server is not None
    assert any("could not be opened" in record.message for record in caplog.records)
    await worker.cleanup()


@pytest.mark.asyncio
async def test_gateway_recovers_when_port_appears_after_start(tmp_path, monkeypatch, vsp, bus_server) -> None:
    """The worker's gateway recovers once a port missing at startup appears.

    The worker is pointed at a symlink that does not exist yet, so startup
    succeeds with the bus down. Creating the symlink to a live bus port must let
    the next request through the worker's gateway reconnect and succeed.
    """

    async def fake_initialize(self) -> bool:
        return True

    monkeypatch.setattr(ValkeyWorker, "initialize", fake_initialize)

    await bus_server.start()
    late_port = Path(tmp_path) / "late-port"
    _write_config(
        tmp_path,
        serial_port=str(late_port),
        devices={1: ModbusDeviceSettings(framer="RTU")},
    )
    worker = _make_worker(tmp_path)
    assert await worker.initialize() is True
    try:
        request = ReadHoldingRegistersRequest(address=0, count=2, dev_id=1)
        before = await worker.gateway.handle_request(1, request)
        assert isinstance(before, ExceptionResponse)
        assert before.exception_code == 0x0B

        os.symlink(vsp.serial_ports[1], late_port)
        after = await worker.gateway.handle_request(1, ReadHoldingRegistersRequest(address=0, count=2, dev_id=1))
        assert isinstance(after, ReadHoldingRegistersResponse)
        assert after.registers == [1, 2]
    finally:
        await worker.cleanup()
        await bus_server.stop()


@pytest.mark.asyncio
async def test_gateway_recovers_when_port_returns_after_loss(tmp_path, monkeypatch, vsp, bus_server) -> None:
    """The worker's gateway recovers once a port lost after startup returns."""

    async def fake_initialize(self) -> bool:
        return True

    monkeypatch.setattr(ValkeyWorker, "initialize", fake_initialize)

    await bus_server.start()
    _write_config(
        tmp_path,
        serial_port=vsp.serial_ports[1],
        devices={1: ModbusDeviceSettings(framer="RTU")},
    )
    worker = _make_worker(tmp_path)
    assert await worker.initialize() is True
    try:
        request = ReadHoldingRegistersRequest(address=0, count=2, dev_id=1)
        healthy = await worker.gateway.handle_request(1, request)
        assert isinstance(healthy, ReadHoldingRegistersResponse)

        await bus_server.stop()
        gone = await worker.gateway.handle_request(1, ReadHoldingRegistersRequest(address=0, count=2, dev_id=1))
        assert isinstance(gone, ExceptionResponse)
        assert gone.exception_code == 0x0B

        block = ReactiveSequentialDataBlock(0x01, list(range(1, 101)))
        store = ModbusDeviceContext(di=block, co=block, hr=block, ir=block)
        serial = ModbusSerialConnectionConfig(vsp.serial_ports[0], timeout=0.5)
        bus_server = RS485Server(serial, devices={1: store})
        await bus_server.start()
        back = await worker.gateway.handle_request(1, ReadHoldingRegistersRequest(address=0, count=2, dev_id=1))
        assert isinstance(back, ReadHoldingRegistersResponse)
        assert back.registers == [1, 2]
    finally:
        await worker.cleanup()
        await bus_server.stop()


@pytest.mark.asyncio
async def test_gateway_recovers_when_permissions_restored(tmp_path, monkeypatch, vsp, bus_server) -> None:
    """The worker's gateway recovers once port permissions are restored.

    The port is unreadable at startup (EACCES), so the initial connect fails and
    the request yields 0x0B. Restoring the permissions lets the next request
    reconnect and succeed.
    """

    async def fake_initialize(self) -> bool:
        return True

    monkeypatch.setattr(ValkeyWorker, "initialize", fake_initialize)

    await bus_server.start()
    gateway_port = vsp.serial_ports[1]
    os.chmod(gateway_port, 0o000)
    _write_config(
        tmp_path,
        serial_port=gateway_port,
        devices={1: ModbusDeviceSettings(framer="RTU")},
    )
    worker = _make_worker(tmp_path)
    try:
        assert await worker.initialize() is True
        denied = await worker.gateway.handle_request(1, ReadHoldingRegistersRequest(address=0, count=2, dev_id=1))
        assert isinstance(denied, ExceptionResponse)
        assert denied.exception_code == 0x0B

        os.chmod(gateway_port, 0o600)
        restored = await worker.gateway.handle_request(1, ReadHoldingRegistersRequest(address=0, count=2, dev_id=1))
        assert isinstance(restored, ReadHoldingRegistersResponse)
        assert restored.registers == [1, 2]
    finally:
        os.chmod(gateway_port, 0o600)
        await worker.cleanup()
        await bus_server.stop()


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
