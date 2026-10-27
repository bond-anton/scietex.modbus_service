"""Telemetry payloads the Modbus worker publishes to Valkey.

The structs mirror the API read side field-for-field so the monitoring endpoint
can decode the payload unchanged, with one addition: this producer carries a
``configured`` flag the API struct omits (the API decoder tolerates unknown
fields, so it is ignored there). The key shape, push interval, and TTL are the
frozen §5.2 contract: key ``scietex:{service}:{instance_id}:telemetry`` (the
``telemetry`` suffix never matches the heartbeat discovery glob
``scietex:*:*:status``), pushed every 2 s with a 6 s TTL.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import msgspec

from .config import to_gateway_config

if TYPE_CHECKING:
    from scietex.hal.serial import ModbusGateway

    from .modbus_worker import ModbusWorker

#: Push cadence and key TTL (§5.2): 2 s interval, 6 s TTL so a single missed
#: beat does not expire the key.
TELEMETRY_INTERVAL: float = 2.0
TELEMETRY_TTL: int = 6


class ModbusDeviceTelemetry(msgspec.Struct, frozen=True):
    """Per bus-address status."""

    device_id: int
    last_seen: datetime | None
    request_count: int
    error_count: int


class ModbusBusStats(msgspec.Struct, frozen=True):
    """Aggregate bus counters since worker start."""

    requests: int
    errors: int
    retries: int


class ModbusGatewayTelemetry(msgspec.Struct, frozen=True):
    """Gateway telemetry snapshot pushed by the worker.

    Mirrors the API read struct field-for-field and adds ``configured`` (whether
    a gateway is built). ``forbid_unknown_fields`` is deliberately left off so
    the API side can decode this payload with its own (slightly smaller) struct.
    """

    service: str
    instance_id: str
    configured: bool
    serial_connected: bool
    serial_port: str | None
    tcp_listening: bool
    tcp_host: str | None
    tcp_port: int | None
    client_count: int
    devices: list[ModbusDeviceTelemetry]
    #: Bus addresses the gateway actually routes: the keys of
    #: ``gateway.config.devices``. This is the routing table, not the set of
    #: observed addresses — an id may be observed (a client addressed it) while
    #: having no entry here, which is what "unknown address" means.
    routed: list[int]
    #: Settings the worker has accepted but the running gateway has not picked
    #: up. The gateway is built once and never rebuilt, so a delivered change
    #: only takes effect on restart; this lists the fields that differ between
    #: the desired settings and the live gateway config. Empty when the gateway
    #: matches what was delivered.
    pending_restart: list[str]
    bus: ModbusBusStats
    timestamp: datetime = msgspec.field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1


def _last_seen_datetime(last_seen: float | None) -> datetime | None:
    """Convert a monotonic `last_seen` stamp to a wall-clock UTC datetime.

    `DeviceCounters.last_seen` is `time.monotonic()` at the moment of the last
    request, so the elapsed delta since then is subtracted from the current UTC
    time to recover the wall-clock instant. ``None`` (never addressed) stays
    ``None``.
    """
    if last_seen is None:
        return None
    return datetime.now(timezone.utc) - timedelta(seconds=time.monotonic() - last_seen)


def _pending_restart(worker: ModbusWorker, gateway: ModbusGateway) -> list[str]:
    """Return the settings the running gateway has not picked up.

    The gateway is built once from the settings delivered at that moment and is
    never rebuilt, so a later delivery is stored but inert until restart. The
    desired settings live on the worker; the live ones on ``gateway.config``.
    Comparing the two names the fields an operator must restart to apply.
    """
    settings = worker.modbus_settings
    if settings is None:
        return []
    desired = to_gateway_config(settings)
    live = gateway.config
    pending = [
        name
        for name in ("host", "port", "default_framer", "allow_unknown_devices", "bus_retries")
        if getattr(desired, name) != getattr(live, name)
    ]
    if desired.devices != live.devices:
        pending.append("devices")
    if _serial_differs(desired.serial, live.serial):
        pending.append("serial")
    if desired.circuit_breaker != live.circuit_breaker:
        pending.append("circuit_breaker")
    return pending


def _serial_differs(desired: object, live: object) -> bool:
    """Compare two serial configs field by field.

    ``ModbusSerialConnectionConfig`` does not implement value equality: two
    structurally identical instances compare unequal, so ``==`` would report a
    pending restart on every snapshot. The fields below are the ones the gateway
    actually opens the port with.
    """
    fields = ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout")
    return any(getattr(desired, name, None) != getattr(live, name, None) for name in fields)


def build_telemetry(worker: ModbusWorker) -> ModbusGatewayTelemetry:
    """Snapshot the worker's gateway/TCP state into a telemetry payload.

    An unconfigured worker (no gateway) reports ``configured=False`` with zeroed
    fields, so the UI can observe the waiting state. A configured worker reads
    the live counters and accessors from the gateway and TCP server.
    """
    gateway = worker.gateway
    if gateway is None:
        return ModbusGatewayTelemetry(
            service=worker.service_name,
            instance_id=worker.instance_id,
            configured=False,
            serial_connected=False,
            serial_port=None,
            tcp_listening=False,
            tcp_host=None,
            tcp_port=None,
            client_count=0,
            devices=[],
            routed=[],
            pending_restart=[],
            bus=ModbusBusStats(0, 0, 0),
        )

    metrics = gateway.metrics
    devices = [
        ModbusDeviceTelemetry(
            device_id=device_id,
            last_seen=_last_seen_datetime(counters.last_seen),
            request_count=counters.requests,
            error_count=counters.errors,
        )
        for device_id, counters in sorted(metrics.devices.items())
    ]
    tcp_server = worker.tcp_server
    return ModbusGatewayTelemetry(
        service=worker.service_name,
        instance_id=worker.instance_id,
        configured=True,
        serial_connected=gateway.serial_connected,
        serial_port=gateway.serial_port,
        tcp_listening=tcp_server.tcp_listening if tcp_server is not None else False,
        tcp_host=tcp_server.tcp_host if tcp_server is not None else None,
        tcp_port=tcp_server.tcp_port if tcp_server is not None else None,
        client_count=tcp_server.client_count if tcp_server is not None else 0,
        devices=devices,
        routed=sorted(gateway.config.devices),
        pending_restart=_pending_restart(worker, gateway),
        bus=ModbusBusStats(metrics.requests, metrics.errors, metrics.retries),
    )
