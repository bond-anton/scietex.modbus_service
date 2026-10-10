"""Modbus gateway worker: a Valkey-backed service that owns a Modbus gateway.

`ModbusWorker` extends `ValkeyWorker` and fronts a serial Modbus bus with a TCP
listener. Because the TCP ``port`` is unset by default, a worker that has not
yet received a configuration starts with no gateway and keeps its heartbeat
alive (discoverable, ``configured=false``); the first remote-config ``modbus``
delivery with a configured port then live-builds the gateway. Subsequent
reconfigures are restart-required. A ``Telemetry`` manager publishes a gateway
snapshot every 2 s so the UI can observe the configured/live state.
"""

import asyncio
import logging
from typing import cast

import msgspec
from glide import (
    ConnectionError as GlideConnectionError,
)
from glide import (
    ExpirySet,
    ExpiryType,
    RequestError,
)
from glide import (
    TimeoutError as GlideTimeoutError,
)
from scietex.hal.serial import GatewayConfigError, GatewayTcpServer, ModbusGateway
from scietex.hal.serial.config import SerialConnectionConfigError
from scietex.service import Manager, ValkeyWorker, ValkeyWorkerConfig

from .config import (
    MODBUS_SECTION,
    MODBUS_SETTINGS_DEFAULTS,
    ModbusServiceSettings,
    read_modbus_config,
    to_gateway_config,
)
from .telemetry import TELEMETRY_INTERVAL, TELEMETRY_TTL, build_telemetry


class ModbusWorker(ValkeyWorker):
    """A `ValkeyWorker` that runs a serial<->TCP Modbus gateway.

    Settings resolve through the framework's four-layer merge: constructor
    default (L0) < ``modbus.yml`` bootstrap patch (L1) < framework ``config.yml``
    snapshot (L2) < remote ``modbus`` section (L3). Each layer is a field-level
    patch — a key absent from a layer inherits the layer below, ``null`` clears
    it back to the L0 default, and a value sets it.

    Because ``port`` defaults to ``None``, the gateway is built lazily: if the
    merged settings leave the port unset, the worker starts without a gateway
    and waits for a remote delivery. The first delivery with a configured port
    (whether at startup through L2/L3, or at runtime through the ``config:*``
    channel) builds and starts the gateway; once built it is restart-required
    for any later change.
    """

    def __init__(self, config: ValkeyWorkerConfig | None = None, *, client_factory=None, theme=None) -> None:
        super().__init__(config, client_factory=client_factory, theme=theme)
        self._settings: ModbusServiceSettings | None = None
        self._gateway: ModbusGateway | None = None
        self._tcp_server: GatewayTcpServer | None = None
        # Startup guard: the config apply hook runs both during
        # ``super().initialize()`` (L2/L3 delivery, where ``initialize`` itself
        # builds the gateway) and at runtime (where the hook must live-build).
        # False until ``initialize`` returns, so the hook knows which phase it
        # is in.
        self._startup_complete: bool = False
        # Runtime live-build task scheduled by the sync apply hook, awaited by
        # tests and reused on a restart to avoid a double build.
        self._pending_build: asyncio.Task[bool] | None = None
        # Telemetry encoding is done with an encoder owned here (the framework's
        # ``__encoder`` is private), and the key is resolved once at
        # construction.
        self._telemetry_encoder = msgspec.msgpack.Encoder()
        self._telemetry_key = f"scietex:{self.service_name}:{self.instance_id}:telemetry"
        self.register_config_settings(
            MODBUS_SECTION,
            ModbusServiceSettings,
            apply=self._apply_modbus_settings,
            defaults=MODBUS_SETTINGS_DEFAULTS,
            bootstrap=lambda: read_modbus_config(self.conf_dir),
        )

    @property
    def gateway(self) -> ModbusGateway | None:
        """The running `ModbusGateway`, or `None` before startup."""
        return self._gateway

    @property
    def tcp_server(self) -> GatewayTcpServer | None:
        """The running `GatewayTcpServer`, or `None` before startup."""
        return self._tcp_server

    @property
    def modbus_settings(self) -> ModbusServiceSettings | None:
        """The effective Modbus settings, or `None` before startup."""
        return self._settings

    async def initialize(self) -> bool:
        """Initialize the framework, then build the gateway when configured.

        `super().initialize()` seeds the L0+L1 layers (running the ``modbus.yml``
        bootstrap provider) and applies the L2/L3 layers, so the merged settings
        are read back via `current_config_settings` afterwards. A bootstrap
        failure is swallowed by the framework's seeder and surfaces only as an
        unresolved section, so the ``None`` guard below is the failure path. When
        the merged settings leave ``port`` unset, the worker returns `True` with
        no gateway — it stays up and waits for a remote configuration delivery.

        Returns:
            `True` if the framework initialized and the gateway is either built
            or deliberately deferred; `False` on any configuration or startup
            failure.
        """
        self._startup_complete = False
        if not await super().initialize():
            return False

        resolved = self.current_config_settings(MODBUS_SECTION)
        if resolved is None:
            self.logger.error("Modbus settings were not resolved before gateway startup")
            return False
        settings = cast(ModbusServiceSettings, resolved)
        self._settings = settings

        self._startup_complete = True
        if settings.port is None:
            self.logger.info("No Modbus configuration delivered; waiting for remote configuration")
            return True

        return await self._build_and_start_gateway(settings)

    async def cleanup(self) -> None:
        """Tear down the gateway, then the framework resources."""
        await self._stop_gateway()
        await super().cleanup()

    async def _build_and_start_gateway(self, settings: ModbusServiceSettings) -> bool:
        """Build and start the gateway + TCP server from merged settings.

        Shared by `initialize` and the runtime live-build path. Both the gateway
        and TCP server references are assigned before either is started, so a
        mid-start failure still leaves them reachable by `_stop_gateway`. A
        config-conversion failure is logged and reported as `False`; a start
        failure tears the gateway back down via `_stop_gateway` and reports
        `False`.
        """
        try:
            gw_config = to_gateway_config(settings)
        except (GatewayConfigError, SerialConnectionConfigError) as exc:
            self.logger.error("Invalid Modbus gateway configuration: %s", exc)
            return False

        self._gateway = ModbusGateway(gw_config, logger=self.logger)
        self._tcp_server = GatewayTcpServer(gw_config, self._gateway, logger=self.logger)
        try:
            await self._gateway.start()
            await self._tcp_server.start()
        except Exception as exc:
            self.logger.error("Failed to start the Modbus gateway: %s", exc)
            await self._stop_gateway()
            return False
        return True

    async def _stop_gateway(self) -> None:
        """Stop the TCP server and gateway, nulling refs before awaiting.

        Nulling each reference before awaiting its ``stop()`` makes this
        idempotent even when ``start()`` failed midway, and guards against a
        concurrent second cleanup. ``stop()`` errors are logged and swallowed so
        a teardown failure never aborts shutdown.
        """
        tcp_server, self._tcp_server = self._tcp_server, None
        gateway, self._gateway = self._gateway, None
        if tcp_server is not None:
            try:
                await tcp_server.stop()
            except Exception as exc:
                self.logger.warning("Failed to stop the Modbus TCP server: %s", exc)
        if gateway is not None:
            try:
                await gateway.stop()
            except Exception as exc:
                self.logger.warning("Failed to stop the Modbus gateway: %s", exc)

    def _apply_modbus_settings(self, settings: ModbusServiceSettings) -> None:
        """Validate and apply remote Modbus settings, live-building on first delivery.

        An unconfigured delivery (``port`` unset) is stored and logged as waiting.
        A configured delivery is validated through the conversion seam first — a
        bad device id, framer, or plugin path raises, which the framework reports
        as a failed apply. On a running gateway the change is only stored and
        logged as restart-required; on a waiting worker it triggers the
        "waiting → configured" transition by building the gateway live.

        The hook is synchronous (the framework invokes it inline, not awaited),
        so the live build is scheduled as a background task on the running loop
        rather than awaited here. During startup the hook runs before
        `initialize` builds the gateway, so it only stores — `initialize` builds
        from the final merged settings to avoid a double build.
        """
        if settings.port is None:
            self._settings = settings
            self.logger.info("No Modbus configuration delivered; waiting for remote configuration")
            return

        to_gateway_config(settings)  # validates; raises on bad config
        self._settings = settings

        if self._gateway is not None:
            self.logger.warning(
                "Modbus settings applied; restart required to rebuild the gateway "
                "(serial port and TCP listener are not live-reloaded)"
            )
            return

        if not self._startup_complete:
            self.logger.info("Stored Modbus settings for gateway startup")
            return

        self.logger.info("Modbus configuration delivered; starting the gateway")
        self._pending_build = asyncio.get_running_loop().create_task(self._build_and_start_gateway(settings))

    @Manager(name="Telemetry")
    async def telemetry_loop(self) -> None:
        """Publish gateway telemetry to Valkey once per iteration.

        The manager runtime repeats this body forever with auto-restart on error.
        The write is guarded on `self.client` and runs even when the worker is
        unconfigured, so the UI observes ``configured=false``. Glide errors are
        logged at WARNING and reported to the transport health, which drives the
        reconnect — matching the heartbeat's error handling.
        """
        client = self.client
        if client is not None:
            payload = build_telemetry(self)
            try:
                await client.set(
                    self._telemetry_key,
                    value=self._telemetry_encoder.encode(payload),
                    expiry=ExpirySet(ExpiryType.SEC, TELEMETRY_TTL),
                )
            except (GlideConnectionError, RequestError, GlideTimeoutError) as exc:
                self.logger.log(logging.WARNING, "Failed to publish Modbus telemetry: %s", exc)
                self._health.report_failure(exc)
        await asyncio.sleep(TELEMETRY_INTERVAL)
