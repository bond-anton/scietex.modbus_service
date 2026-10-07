# Deployment

How to run `scietex.modbus_service` as a container (Docker or Podman) and how to
configure it. The service is a plain Python console script; the included
`Containerfile` packages it with a non-root user and a mounted config volume.

## Entry point

The package installs one console script:

```bash
start-modbus-service
```

It accepts three flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--conf-dir` | auto-resolved | Configuration directory |
| `--service-name` | `$SCIETEX_SERVICE_NAME` or `ModbusService` | Service name reported to the framework |
| `--logging-level` | `$SCIETEX_LOGGING_LEVEL` or `INFO` | Logging level |

Precedence is **CLI flag > environment variable > built-in default**. The
`--conf-dir` flag defaults to `None` so the framework resolves the directory
itself (it already honors `SCIETEX_CONFIG_DIR`).

The service runs in the foreground until it receives `SIGINT` or `SIGTERM`.
`docker stop` / `podman stop` send `SIGTERM`, which triggers graceful shutdown —
no extra wiring is needed.

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `SCIETEX_CONFIG_DIR` | Config-directory candidate (used if set and an existing dir) | unset |
| `SCIETEX_SERVICE_NAME` | Fallback for `--service-name` | `ModbusService` |
| `SCIETEX_LOGGING_LEVEL` | Fallback for `--logging-level` | `INFO` |
| `XDG_CONFIG_HOME` | XDG base dir; candidate becomes `$XDG_CONFIG_HOME/scietex` | unset → `~/.config/scietex` |

## Container image

The `Containerfile` is a two-stage build on `python:3.13-slim-bookworm`:

- **Builder stage** installs the package and its dependencies into `/opt/venv`.
- **Runtime stage** copies the venv, creates a non-root `appuser` (uid 1000) in
  the `dialout` group, prepares `/config`, and runs `start-modbus-service`.

The image sets these defaults:

```dockerfile
ENV SCIETEX_CONFIG_DIR=/config \
    SCIETEX_SERVICE_NAME=ModbusService \
    SCIETEX_LOGGING_LEVEL=INFO
VOLUME ["/config"]
```

### Build

```bash
podman build -t scietex-modbus-service .
```

`build_image.sh` builds a multi-arch manifest (`linux/amd64,linux/arm64`) and
pushes it to `registry.buro-nts.ru/scietex-modbus-service`, tagged with the
version from `version.py`. Pass `--latest` to also push the `latest` tag.

### Run

```bash
podman run --rm \
  --device /dev/ttyUSB0 \
  --cap-add NET_BIND_SERVICE \
  -v ./config:/config \
  scietex-modbus-service
```

## Serial device access

The container runs as `appuser`, which is a member of the `dialout` group
(GID 20 on Debian). To give the container access to a serial device:

1. Pass the device through with `--device /dev/ttyUSB0`.
2. Ensure the host device's group matches `dialout` (GID 20), or adjust the
   `groupadd`/`useradd` lines in the `Containerfile` to match your host.

Without `--device`, the serial port inside the container does not exist. The
gateway still starts — it logs a warning that the bus could not be opened and
retries on each request — but every request fails until the device is passed
through and the container is restarted.

## Port 502

Port 502 is privileged (below 1024). Binding it inside the container requires
one of:

- `--cap-add NET_BIND_SERVICE` — grant the capability to the container, or
- Override the port in `modbus.yml` (e.g. `port: 5020`) and map it on the host
  with `-p 502:5020`.

The `Containerfile` does **not** grant the capability by default; the operator
chooses at run time.

## Config volume

`/config` is declared as a volume and owned by `appuser`. Mount a host directory
there so configuration survives container replacement:

```bash
-v ./config:/config
```

The service writes its files under `/config/modbus/`:

```
/config/modbus/modbus.yml    # service bootstrap
/config/modbus/config.yml    # framework snapshot (remote config)
```

On first run, `modbus.yml` is created with defaults. Edit it on the host and
restart the container to apply changes. See [Configuration](configuration.md).

## Health and shutdown

There is **no HTTP server and no `/health` endpoint**. A container healthcheck
must observe the framework's broker-side heartbeat (a Valkey key) or the process
itself, not an HTTP probe.

`SIGTERM` triggers graceful shutdown: the worker stops the TCP server, then the
gateway, then the framework resources. See
[Remote configuration](remote-config.md) for the restart-required behavior of
runtime config changes.
