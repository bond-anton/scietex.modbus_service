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

The `Containerfile` is a two-stage build on `python:3.14-slim-trixie`:

- **Builder stage** installs the released `scietex.modbus_service` wheel from
  PyPI (selected by the `VERSION` build arg) and its dependencies into
  `/opt/venv`, then slims the venv (drops pip/setuptools/wheel, bytecode caches,
  and the unused per-interpreter `glide_shared` extensions).
- **Runtime stage** copies the venv, creates a non-root `appuser` (uid 1000) in
  the `dialout` group, prepares `/config`, and runs `start-modbus-service`.

The image installs the published package rather than building from the local
checkout, so the image and the PyPI artifact for a given version are the same
code. The `VERSION` build arg must name a version that exists on PyPI.

The image sets these defaults:

```dockerfile
ENV SCIETEX_CONFIG_DIR=/config \
    SCIETEX_SERVICE_NAME=ModbusService \
    SCIETEX_LOGGING_LEVEL=INFO
VOLUME ["/config"]
```

### Build

```bash
podman build --build-arg VERSION=2.1.0 -t scietex-modbus-service .
```

`build_image.sh` builds a multi-arch manifest (`linux/amd64,linux/arm64`) and
pushes it to `registry.buro-nts.ru/scietex-modbus-service`, tagged with the
version from `version.py`. It passes that version as the `VERSION` build arg, so
the image always installs the matching PyPI release. Pass `--latest` to also
push the `latest` tag.

### Run

```bash
podman run --rm \
  --device /dev/ttyUSB0 \
  --cap-add NET_BIND_SERVICE \
  -v ./config:/config \
  scietex-modbus-service
```

### Quadlet (systemd)

For a persistent deployment, run the container as a rootless systemd user
service via a Quadlet. `~/.config/containers/systemd/modbus-service.container`:

```ini
[Unit]
Description=Modbus Service Container
Requires=valkey.service
After=valkey.service

[Container]
ContainerName=modbus-service
Image=registry.buro-nts.ru/scietex-modbus-service:latest
UserNS=keep-id
# Preserve the host's supplementary groups (notably dialout, which owns the
# USB-serial device nodes) so the container user can open them.
GroupAdd=keep-groups
Volume=%h/.config/scietex:/config:z
Volume=%h/.config/scietex-modbus-container/valkey.yml:/config/valkey.yml:Z
PublishPort=15020:15020
# The gateway binds the Modbus/TCP port from the applied config, which defaults
# to 502 (privileged). Without this capability the worker fails to start with
# EACCES on bind. Drop it only if the configured port is >= 1024.
AddCapability=NET_BIND_SERVICE
# AddDevice= lines are generated into modbus-service.container.d/10-devices.conf
# by scietex-modbus-devices-sync.
AutoUpdate=registry

[Install]
WantedBy=multi-user.target default.target
```

Reload and start it:

```bash
systemctl --user daemon-reload
systemctl --user start modbus-service.service
```

`UserNS=keep-id` maps the host user to the container user; `GroupAdd=keep-groups`
preserves the host's supplementary groups so the container can open the
`dialout`-owned serial device. `AutoUpdate=registry` pulls a newer image on
restart. The `AddDevice=` lines are not written by hand — a hotplug helper
regenerates them from the present `/dev/scietex-serial/` symlinks. See
[Serial device access](serial-devices.md) for the device sync script, the path
unit, and the SELinux and group requirements.

#### Shared config dir: `:z`, not `:Z`

The `~/.config/scietex` mount uses `:z` (shared), while the per-container
`valkey.yml` overlay uses `:Z` (private). This distinction matters on
SELinux-enforcing hosts when more than one container mounts the same tree.

`:Z` assigns the source a **private** MCS category — a unique `s0:cN,cM` pair
per container. When two quadlets both mount `~/.config/scietex` with `:Z`, each
start relabels the directory to its own category and the other container loses
access to its own config. The failure is silent at the unit level: the service
starts, then dies inside with

```
PermissionError: [Errno 13] Permission denied: '/config/valkey.yml'
ERR - Failed to seed bootstrap for section 'modbus': Failed to create configuration directory /config/modbus!
```

Whichever container started last wins; the other is locked out until the next
restart flips it back. `:z` assigns `container_file_t` with **no** MCS category,
so every container mounting the tree can read it regardless of its own category.

Use `:Z` only for a path mounted by exactly one container — the `valkey.yml`
overlay qualifies, the shared config tree does not. If you add another service
that mounts `~/.config/scietex`, give it `:z` too.

Verify the labels after a restart:

```bash
ls -Zd ~/.config/scietex                      # expect container_file_t:s0 (no cN,cM)
podman exec modbus-service ls /config/valkey.yml
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

For static UARTs, USB adapters with unstable `ttyUSB*` numbering, hotplug, and
the SELinux and group requirements of rootless containers, see
[Serial device access](serial-devices.md).

## Port 502

Port 502 is privileged (below 1024). Binding it inside the container requires
one of:

- `--cap-add NET_BIND_SERVICE` — grant the capability to the container, or
- Override the port in `modbus.yml` (e.g. `port: 5020`) and map it on the host
  with `-p 502:5020`.

The `Containerfile` does **not** grant the capability by default; the operator
chooses at run time. The Quadlet example above grants it, because the default
applied config binds 502.

## Config volume

`/config` is declared as a volume and owned by `appuser`. Mount a host directory
there so configuration survives container replacement:

```bash
-v ./config:/config
```

The service writes its files under `/config/modbus/`:

```
/config/modbus/modbus.yml    # L1 bootstrap patch (service-owned)
/config/modbus/config.yml    # L2 snapshot (framework-owned)
```

On first run, `modbus.yml` is created with defaults. Edit it on the host and
restart the container to apply changes. The framework's `config.yml` snapshot is
written automatically after a successful remote apply and overlays the bootstrap
on the next start; the remote `modbus` section (L3) overlays both. See
[Configuration](configuration.md).

The worker's heartbeat reports which layer last applied the effective config
(`config_source`, `config_revision`, `config_hash`), so the API can show whether
a running gateway is on its local `config.yml` snapshot rather than the remote
delivery. This requires `scietex.service >= 6.2.0`; an older framework omits the
fields and the API reports the provenance as unavailable.

## Health and shutdown

There is **no HTTP server and no `/health` endpoint**. A container healthcheck
must observe the framework's broker-side heartbeat (a Valkey key) or the process
itself, not an HTTP probe.

`SIGTERM` triggers graceful shutdown: the worker stops the TCP server, then the
gateway, then the framework resources. See
[Remote configuration](remote-config.md) for the restart-required behavior of
runtime config changes.
