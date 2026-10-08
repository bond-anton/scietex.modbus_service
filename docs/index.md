# scietex.modbus_service

`scietex.modbus_service` is a [`scietex.service`](https://github.com/bond-anton/scietex.service)
worker that runs the serial-to-TCP Modbus gateway from
[`scietex.hal.serial`](https://github.com/bond-anton/scietex.hal.serial).

It bridges a serial RS485 bus to TCP/IP. TCP clients speak plain Modbus/TCP and
the gateway routes each request to the right device on the bus **by device id** —
no special protocol, no per-device client configuration.

## What it does

- **Owns one serial port** and **one TCP listener**, both built once at startup
  and torn down on shutdown.
- **Routes by device id.** Each Modbus/TCP request carries a unit id; the
  gateway forwards it to the matching device on the bus and returns the response.
- **Runs as a daemon** on the `scietex.service` framework, with signal handling,
  heartbeat, watchdog, and graceful shutdown inherited from `ValkeyWorker`.
- **Accepts remote configuration** through the framework's config channel, but
  the gateway is restart-required — see [Remote configuration](remote-config.md).
- **Tolerates a missing serial port at startup.** If the port cannot be opened,
  the worker still starts and logs a warning; it retries on each request and
  connects automatically once the device appears.

## How it fits together

```
Modbus/TCP client ──▶ GatewayTcpServer ──▶ ModbusGateway ──▶ serial RS485 bus ──▶ devices
                          (TCP)              (routing)          (one port)
```

`ModbusWorker` is a `ValkeyWorker` subclass. It owns a `ModbusGateway` and a
`GatewayTcpServer`, both from `scietex.hal.serial`. The worker's job is
lifecycle and configuration: it loads `modbus.yml`, lets the framework apply its
local and remote config, converts the effective settings into a `GatewayConfig`,
and starts the gateway.

The gateway core is documented in the
[`scietex.hal.serial` gateway guide](https://scietex-hal-serial.readthedocs.io/en/latest/guide/gateway/).

## Documentation

| Page | Contents |
| --- | --- |
| [Configuration](configuration.md) | The `modbus.yml` schema, defaults, and precedence |
| [Deployment](deployment.md) | Container, port 502, environment variables |
| [Serial device access](serial-devices.md) | Static UART, USB adapters, hotplug, SELinux, container access |
| [Remote configuration](remote-config.md) | The declarative `modbus` section and `config:*` commands |

## Quick start

```bash
pip install scietex.modbus_service
start-modbus-service --conf-dir /etc/scietex
```

On first run the service creates `<conf-dir>/modbus/modbus.yml` with defaults.
Edit it to point at your serial device and declare your devices, then restart.
See [Configuration](configuration.md) for the full schema.

## Requirements

- **Python** 3.10 or higher.
- **Linux** (the container image targets Debian Bookworm). Serial device access
  requires membership in the `dialout` group or equivalent.
- A **Valkey** (Redis-compatible) instance for the worker framework's task
  transport. The gateway itself does not use Valkey; the worker framework does.
