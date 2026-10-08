# Serial device access

The gateway owns exactly one serial port. This page covers how to make that port
available to the service, both when it runs directly on the host and when it runs
in a container, for two device classes:

- **Static UART** — an on-board or add-in UART that always appears at the same
  path (`/dev/ttyS0`, `/dev/ttyAMA0`, `/dev/ttyO0`, …).
- **USB serial adapter** — a hot-pluggable bridge (FTDI, Prolific, CH340, STM32
  VCP, …) whose kernel-assigned `ttyUSB*` / `ttyACM*` number can change between
  boots and replugs.

The service reads the port from `serial.port` in `modbus.yml`. See
[Configuration](configuration.md) for the full schema.

## Static UART

A static UART has a fixed device path, so `serial.port` can name it directly:

```yaml
serial:
  port: /dev/ttyS0
  baudrate: 9600
```

Two things to check on the host:

1. **The device exists and is the right one.** On many boards the UART is
   disabled by default (device-tree overlay, BIOS setting, or a kernel console
   occupying it). Confirm with `ls -l /dev/ttyS0` and `dmesg | grep ttyS`.
2. **Permissions.** The device is usually `root:dialout` mode `0660`. The service
   user must be in `dialout` (or the device must be group-readable by it).

Because the path never changes, no udev rule is needed. If the UART is a
`ttyAMA*`/`ttyO*` device, substitute the actual path.

## USB serial adapters

USB adapters are the harder case: the kernel assigns `ttyUSB0`, `ttyUSB1`, … in
enumeration order, so the number is **not stable** across reboots or replugs.
Pointing `serial.port` at `/dev/ttyUSB0` works until it doesn't.

The fix is a udev rule that creates a **stable symlink** keyed by the adapter's
USB vendor:product id (and, when several adapters share an id, an index). The
service then points at the symlink, not the raw node.

### Supported adapters

The reference rule below covers the adapters used in the field:

| Vendor | Product | Adapter |
| --- | --- | --- |
| `0403` | `6001` | FTDI FT232R |
| `0403` | `6010` | FTDI FT2232H |
| `0403` | `6011` | FTDI FT4232H |
| `0403` | `6012` | FTDI FT232H |
| `0403` | `6013` | FTDI FT2232D |
| `0403` | `6014` | FTDI FT232H (alt) |
| `0403` | `6015` | FTDI FT231X |
| `067b` | `2303` | Prolific PL2303 |
| `1a86` | `7523` | QinHeng CH340 |
| `0483` | `5740` | STMicroelectronics STM32 Virtual COM Port |

FTDI, Prolific, and CH340 adapters bind to the `ttyUSB` driver (char major 188);
the STM32 VCP binds to `ttyACM` (char major 166). The rule matches on
`SUBSYSTEM=="tty"` and the USB attributes, so it covers both.

### udev rule

Install `/etc/udev/rules.d/70-scietex-serial.rules`:

```udev
# Stable symlinks for the USB-serial adapters used by the Modbus gateway.
# Each adapter gets /dev/scietex-serial/<vid>-<pid>; when several share an id,
# udev appends an index (e.g. 0403-6001-1).
#
# Each rule also touches /run/scietex-serial/state. The user path unit watches
# that marker rather than /dev/scietex-serial itself: the container bind-mounts
# the device directory, so watching it would re-trigger on every container
# restart and loop. /run/scietex-serial is never mounted into the container.

# FTDI
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="scietex-serial/0403-6001", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6010", SYMLINK+="scietex-serial/0403-6010", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6011", SYMLINK+="scietex-serial/0403-6011", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6012", SYMLINK+="scietex-serial/0403-6012", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6013", SYMLINK+="scietex-serial/0403-6013", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6014", SYMLINK+="scietex-serial/0403-6014", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", SYMLINK+="scietex-serial/0403-6015", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"

# Prolific PL2303
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", SYMLINK+="scietex-serial/067b-2303", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"

# QinHeng CH340
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="scietex-serial/1a86-7523", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"

# STMicroelectronics STM32 Virtual COM Port (CDC-ACM)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", SYMLINK+="scietex-serial/0483-5740", GROUP="dialout", MODE="0660", RUN+="/bin/sh -c 'mkdir -p /run/scietex-serial && touch /run/scietex-serial/state'"
```

Reload and apply:

```bash
sudo cp 70-scietex-serial.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
```

Verify with the adapter plugged in:

```bash
ls -l /dev/scietex-serial/
# 1a86-7523 -> ../ttyUSB0
```

Then point `modbus.yml` at the stable path:

```yaml
serial:
  port: /dev/scietex-serial/1a86-7523
  baudrate: 9600
```

To find the vendor:product of an unknown adapter, plug it in and run
`lsusb`, or read the attributes directly:

```bash
udevadm info -q property -n /dev/ttyUSB0 | grep -E 'ID_VENDOR_ID|ID_MODEL_ID'
```

### Multiple adapters with the same id

When two adapters share a vendor:product id, udev appends an index to the second
symlink (`0403-6001`, `0403-6001-1`, …). The index follows enumeration order, so
it is stable only as long as the adapters are always plugged into the same
physical ports. For a guaranteed-stable path, match on the adapter's serial
number instead:

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A50285BI", SYMLINK+="scietex-serial/bus-a", GROUP="dialout", MODE="0660"
```

## Container access

Running the service in a container adds three requirements beyond the host
setup: the device must be passed through, the container user must be able to
open it, and SELinux (on Fedora/RHEL and derivatives) must allow it.

### Pass the device through

Rootless Podman cannot use `--device-cgroup-rule`, and `--device` requires the
path to exist at container start. Pass the device explicitly:

```bash
podman run --rm \
  --device /dev/scietex-serial/1a86-7523 \
  -v /dev/scietex-serial:/dev/scietex-serial:ro \
  -v ./config:/config \
  scietex-modbus-service
```

Podman resolves a symlinked `--device` to its target and mounts the **target**
node, so the stable `/dev/scietex-serial/<vid>-<pid>` path would not exist inside
the container. Bind-mounting the symlink directory read-only (second `-v`) makes
the stable path available, so `modbus.yml` can reference it unchanged.

### Group access

The container runs as `appuser` (uid 1000). With `--userns=keep-id`, the host
user maps to the container user, but the host's supplementary groups are **not**
preserved by default — the device appears owned by an unmapped gid and `open()`
fails with `EACCES`. Add:

```bash
--group-add keep-groups
```

This preserves the host's supplementary groups (notably `dialout`, which owns
the device node) inside the container. It is the portable fix — no hardcoded
gids, no `chgrp` on the device.

### SELinux

On SELinux-enforcing hosts the container runs as `container_t`, which is not
allowed to open `usbtty_device_t` device nodes by default. The symptom is
`Permission denied` on `open()` even though the device is present and the group
is correct. Enable the boolean:

```bash
sudo setsebool -P container_use_devices on
```

`-P` makes it persistent across reboots. Verify with `getsebool
container_use_devices`. If access still fails, check for denials:

```bash
sudo ausearch -m avc -ts recent | grep -i usbtty
```

## Hotplug with a user quadlet

A rootless quadlet cannot hot-add a device to a running container, so a
plug/unplug must restart the service. The pattern below regenerates the
quadlet's `AddDevice=` list from the present symlinks and restarts the container
only when the set actually changed.

### Device sync script

`~/.local/bin/scietex-modbus-devices-sync`:

```bash
#!/usr/bin/env bash
# Regenerate the modbus-service quadlet drop-in with AddDevice= lines for every
# USB-serial adapter currently present under /dev/scietex-serial/.
#
# Restarts modbus-service only when the device set actually changed. This is
# what breaks the feedback loop: the path unit fires on directory activity, and
# an unconditional restart would re-trigger it indefinitely.
set -euo pipefail

SYMLINK_DIR=/dev/scietex-serial
DROPIN_DIR="${HOME}/.config/containers/systemd/modbus-service.container.d"
DROPIN="${DROPIN_DIR}/10-devices.conf"

mkdir -p "${DROPIN_DIR}"

tmp="$(mktemp)"
{
    echo "# Generated by scietex-modbus-devices-sync. Do not edit by hand."
    echo "# Lists every supported USB-serial adapter currently present."
    echo "[Container]"
    if [[ -d "${SYMLINK_DIR}" ]]; then
        for link in $(find "${SYMLINK_DIR}" -maxdepth 1 -type l -printf '%f\n' 2>/dev/null | sort); do
            echo "AddDevice=${SYMLINK_DIR}/${link}"
        done
        echo "Volume=${SYMLINK_DIR}:${SYMLINK_DIR}:ro"
    fi
} > "${tmp}"

if [[ -f "${DROPIN}" ]] && cmp -s "${tmp}" "${DROPIN}"; then
    rm -f "${tmp}"
    exit 0
fi

mv "${tmp}" "${DROPIN}"
systemctl --user daemon-reload
systemctl --user restart --no-block modbus-service.service
```

The drop-in **must** start with a `[Container]` group header — quadlet's INI
parser rejects a file whose first non-comment line is not a group.

### Path unit

`~/.config/systemd/user/modbus-serial-hotplug.path`:

```ini
[Unit]
Description=Restart Modbus service when a scietex USB-serial adapter appears or disappears

[Path]
# Watch the marker the udev rules touch on every supported adapter add/remove.
# The device directory itself is NOT watched: the container bind-mounts it, so
# watching it would re-trigger on every container restart and loop.
PathChanged=/run/scietex-serial/state
Unit=modbus-serial-sync.service

[Install]
WantedBy=paths.target
```

### Sync service

`~/.config/systemd/user/modbus-serial-sync.service`:

```ini
[Unit]
Description=Sync modbus-service AddDevice list with present USB-serial adapters
Before=modbus-service.service
# The path unit may fire in quick succession during a multi-device plug event;
# do not let systemd's default rate limit turn that into a failed unit.
StartLimitIntervalSec=0

[Service]
Type=oneshot
# The script regenerates the drop-in and restarts modbus-service itself, but
# only when the device set actually changed.
ExecStart=%h/.local/bin/scietex-modbus-devices-sync
```

Enable it:

```bash
systemctl --user enable --now modbus-serial-hotplug.path
```

### Why the marker file

Watching `/dev/scietex-serial` directly creates a feedback loop: the container
bind-mounts that directory, so every container restart touches it, which
re-fires the path unit, which restarts the container again. The udev rules
therefore touch `/run/scietex-serial/state` — a path the container never mounts —
and the path unit watches that instead. Combined with the script's
change-detection (it exits early when the drop-in is unchanged), the loop is
broken.

## Quadlet reference

`~/.config/containers/systemd/modbus-service.container`:

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
Volume=%h/.config/scietex:/config:Z
Volume=%h/.config/scietex-modbus-container/valkey.yml:/config/valkey.yml:Z
PublishPort=15020:15020
# AddDevice= lines are generated into modbus-service.container.d/10-devices.conf
# by scietex-modbus-devices-sync.
AutoUpdate=registry

[Install]
WantedBy=multi-user.target default.target
```

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `could not open port ... No such file or directory` | Device not passed through, or symlink dir not mounted | Add `--device` and the `/dev/scietex-serial` bind-mount |
| `could not open port ... Permission denied` | Group not preserved, or SELinux denial | Add `--group-add keep-groups`; `setsebool -P container_use_devices on` |
| Device present but owned by `nobody:nogroup` | Host uid/gid not mapped into the container | Expected with `keep-id`; `keep-groups` grants access via the group |
| Symlink missing after replug | udev rule not reloaded | `sudo udevadm control --reload-rules && sudo udevadm trigger` |
| Container restarts in a loop | Path unit watching the mounted device dir | Watch `/run/scietex-serial/state` instead |
| `key file does not start with a group` | Drop-in missing `[Container]` header | Add the header as the first non-comment line |
