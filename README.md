# scietex.modbus_service

**scietex.modbus_service** is a `scietex.service` worker that runs the
serial-to-TCP Modbus gateway from
[`scietex.hal.serial`](https://github.com/bond-anton/scietex.hal.serial). It
bridges a serial RS485 bus to TCP/IP: TCP clients speak plain Modbus/TCP, and
the gateway routes each request to the right device on the bus **by device id**.

The worker is a long-running daemon. It owns one serial port and one TCP
listener, both built once at startup from `modbus.yml` and torn down on
shutdown. Configuration can also be pushed at runtime through the framework's
remote-config channel, but the gateway itself is **restart-required** — see
[Remote configuration](docs/remote-config.md).

**Python ≥ 3.10** · **License: MIT**

## Documentation

- [Overview](docs/index.md) — what the service does and how it fits together
- [Configuration](docs/configuration.md) — the `modbus.yml` schema and precedence
- [Deployment](docs/deployment.md) — container, serial device access, port 502
- [Remote configuration](docs/remote-config.md) — the declarative `modbus` section

## Installation

```bash
pip install scietex.modbus_service
```

This pulls in `scietex.hal.serial` (the gateway core) and
`scietex.service[valkey]` (the worker framework and its Valkey transport).

## Quick start

### 1. Write a configuration file

The service reads `modbus.yml` from a `modbus/` subdirectory of its config
directory. Create it by hand, or let the service generate defaults on first run.
The file is the bootstrap layer of a four-layer merge: constructor defaults <
`modbus.yml` < the framework's `config.yml` snapshot < the remote `modbus`
section. Each layer is a field-level patch — a key absent from a layer inherits
the layer below, `null` clears it back to the constructor default, and a value
sets it:

```yaml
serial:
  port: /dev/ttyUSB0
  baudrate: 9600
  bytesize: 8
  parity: N
  stopbits: 1
  timeout: null
host: 0.0.0.0
port: 502
default_framer: RTU
devices:
  1:
    framer: RTU
  2:
    framer: ASCII
allow_unknown_devices: false
bus_retries: 0
```

`port` at the top level is the **TCP listen port**; `serial.port` is the
**serial device path**. They are unrelated — do not conflate them.

### 2. Run the service

```bash
start-modbus-service --conf-dir /etc/scietex
```

The service resolves its config directory automatically when `--conf-dir` is
omitted (see [Configuration](docs/configuration.md#config-directory-resolution)).
It runs in the foreground until it receives `SIGINT` or `SIGTERM`.

### 3. Point a Modbus/TCP client at it

Connect to `host:port` and issue normal Modbus/TCP requests, using the target
device id as the unit id. No special protocol is required.

## Configuration at a glance

The defaults below are the constructor (L0) values: a field absent from every
layer, or explicitly cleared with `null`, resolves to the value shown.

| Setting | Default | Meaning |
| --- | --- | --- |
| `serial.port` | `/dev/ttyUSB0` | Serial device path |
| `serial.baudrate` | `9600` | Bus baud rate |
| `host` / `port` | `0.0.0.0` / `502` | TCP bind address and port |
| `default_framer` | `RTU` | Framer for devices without an explicit entry |
| `devices` | `{}` | Per-device routing table, keyed by device id |
| `allow_unknown_devices` | `false` | Route unknown ids with the default framer |
| `bus_retries` | `0` | Retry count for bus transactions |

Full field reference: [Configuration](docs/configuration.md).

## Container

A `Containerfile` is included. It installs the released package from PyPI
(selected by the `VERSION` build arg), runs as a non-root `appuser` in the
`dialout` group, mounts `/config`, and sets `SCIETEX_CONFIG_DIR=/config`:

```bash
podman build --build-arg VERSION=2.1.0 -t scietex-modbus-service .
podman run --rm \
  --device /dev/ttyUSB0 \
  --cap-add NET_BIND_SERVICE \
  -v ./config:/config \
  scietex-modbus-service
```

Port 502 is privileged — binding it needs `--cap-add NET_BIND_SERVICE`, or
override the port in `modbus.yml`. See [Deployment](docs/deployment.md) for
details.

## Development

Dependencies are managed with **uv**; checks and tests run through **tox**:

```bash
uv sync --all-extras
uv run tox                    # format, lint, type, py314
uv run tox -e py314           # tests only
```

See [AGENTS.md](AGENTS.md) for the full toolchain and repo conventions.
