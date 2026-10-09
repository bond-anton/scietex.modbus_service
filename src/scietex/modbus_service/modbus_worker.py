"""Modbus gateway worker: a Valkey-backed service that owns a Modbus gateway.

`ModbusWorker` extends `ValkeyWorker` and fronts a serial Modbus bus with a TCP
listener. The gateway (serial bus + TCP listener) is built once at startup from
``modbus.yml`` and torn down at cleanup. The remote-config ``modbus`` section is
declarative / restart-required: applying it validates and stores the desired
settings but never live-rebuilds the gateway, because reopening the serial bus
and rebinding the TCP listener on a running worker is unsafe.
"""

from typing import cast

from scietex.hal.serial import GatewayConfigError, GatewayTcpServer, ModbusGateway
from scietex.hal.serial.config import SerialConnectionConfigError
from scietex.service import ValkeyWorker, ValkeyWorkerConfig

from .config import (
    MODBUS_SECTION,
    MODBUS_SETTINGS_DEFAULTS,
    ModbusServiceSettings,
    read_modbus_config,
    to_gateway_config,
)


class ModbusWorker(ValkeyWorker):
    """A `ValkeyWorker` that runs a serial<->TCP Modbus gateway.

    Settings resolve through the framework's four-layer merge: constructor
    default (L0) < ``modbus.yml`` bootstrap patch (L1) < framework ``config.yml``
    snapshot (L2) < remote ``modbus`` section (L3). Each layer is a field-level
    patch — a key absent from a layer inherits the layer below, ``null`` clears
    it back to the L0 default, and a value sets it. The gateway is built from the
    merged settings after the framework seeds L0+L1 and applies L2/L3, so the
    remote section's apply hook runs before gateway construction.
    """

    def __init__(self, config: ValkeyWorkerConfig | None = None, *, client_factory=None, theme=None) -> None:
        super().__init__(config, client_factory=client_factory, theme=theme)
        self._settings: ModbusServiceSettings | None = None
        self._gateway: ModbusGateway | None = None
        self._tcp_server: GatewayTcpServer | None = None
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
        """Initialize the framework, then build and start the gateway.

        `super().initialize()` seeds the L0+L1 layers (running the ``modbus.yml``
        bootstrap provider) and applies the L2/L3 layers, so the merged settings
        are read back via `current_config_settings` afterwards. A bootstrap
        failure is swallowed by the framework's seeder and surfaces only as an
        unresolved section, so the ``None`` guard below is the failure path. Both
        the gateway and TCP server references are assigned before either is
        started, so a mid-start failure still leaves them reachable by
        `_stop_gateway`.

        Returns:
            `True` if the framework initialized and the gateway started;
            `False` on any configuration or startup failure.
        """
        if not await super().initialize():
            return False

        resolved = self.current_config_settings(MODBUS_SECTION)
        if resolved is None:
            self.logger.error("Modbus settings were not resolved before gateway startup")
            return False
        settings = cast(ModbusServiceSettings, resolved)
        self._settings = settings

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

    async def cleanup(self) -> None:
        """Tear down the gateway, then the framework resources."""
        await self._stop_gateway()
        await super().cleanup()

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
        """Validate and store remote Modbus settings without rebuilding the gateway.

        The conversion seam validates declaratively: a bad device id, framer, or
        plugin path raises, which the framework reports as a failed apply. The
        gateway is not rebuilt here — the serial bus and TCP listener are
        restart-required — so a running worker only logs that a restart is needed.
        """
        to_gateway_config(settings)
        self._settings = settings
        if self._gateway is not None:
            self.logger.warning(
                "Modbus settings applied; restart required to rebuild the gateway "
                "(serial port and TCP listener are not live-reloaded)"
            )
        else:
            self.logger.info("Stored Modbus settings for gateway startup")
