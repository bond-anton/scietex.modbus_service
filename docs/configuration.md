# Configuration

The service reads its bootstrap settings from `modbus.yml`, a YAML file in a
`modbus/` subdirectory of the config directory. The file is the **L1 bootstrap
patch** of the framework's four-layer merge: a field-level map merged onto the
constructor defaults, then overlaid by the framework's `config.yml` snapshot and
the remote `modbus` section. The merged result is validated through
`ModbusServiceSettings`, a frozen struct with `forbid_unknown_fields=True`, so a
typo in a field name is a hard error, not a silently ignored key.

## Config directory resolution

The config directory is resolved once, at worker construction, by the framework's
`prepare_conf_dir`. The first **existing** directory wins:

1. The `--conf-dir` CLI argument
2. `SCIETEX_CONFIG_DIR`
3. `$XDG_CONFIG_HOME/scietex`
4. `~/.config/scietex`
5. `/etc/scietex`
6. `/usr/local/etc/scietex`
7. `./config` (current working directory)
8. `~/.config/scietex` — **created** if none of the above exist

Only step 8 creates a directory; steps 1–7 require the directory to already
exist. A set-but-nonexistent `SCIETEX_CONFIG_DIR` is silently skipped, so in a
container always create the directory before the worker starts.

## File layout

The service namespaces its files under a `modbus/` subdirectory so that multiple
`scietex.*` services sharing one config directory cannot collide:

```
<conf_dir>/
└── modbus/
    ├── modbus.yml     # service-owned bootstrap (this page)
    └── config.yml     # framework snapshot: core: + services.modbus (see remote-config.md)
```

`MODBUS_CONFIG_SUBDIR` in `config.py` is the single source of truth for the
subdirectory name. The service sets `config_file="modbus/config.yml"`, so the
framework's snapshot lands at `<conf_dir>/modbus/config.yml` and holds `core:`
plus `services.modbus`. The framework writes exactly this one snapshot per
service; there is no separate shared root `config.yml`.

`modbus.yml` is the **L1 bootstrap patch**: a field-level map that holds only the
modbus section. It can never carry a `core:` key — the framework converts the
merged section through `ModbusServiceSettings`, whose `forbid_unknown_fields=True`
rejects that as an unknown field. The framework never writes `modbus.yml`.

## `modbus.yml` schema

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

### Top-level fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `serial` | mapping | see below | Serial bus connection settings |
| `host` | string | `0.0.0.0` | TCP bind address |
| `port` | int | `502` | **TCP listen port** (not the serial port) |
| `default_framer` | string | `RTU` | Framer for devices without an explicit entry |
| `devices` | mapping | `{}` | Per-device routing table, keyed by device id |
| `allow_unknown_devices` | bool | `false` | Route unknown ids with the default framer |
| `bus_retries` | int | `0` | Retry count for bus transactions |

> **`port` vs `serial.port`.** The top-level `port` is the TCP listen port;
> `serial.port` is the serial device path. They are unrelated and must not be
> conflated.

### `serial` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `port` | string | `/dev/ttyUSB0` | Serial device path |
| `baudrate` | int | `9600` | Bus baud rate |
| `bytesize` | int | `8` | Data bits: `5`, `6`, `7`, or `8` |
| `parity` | string | `N` | Parity: `N` (none), `E` (even), or `O` (odd) |
| `stopbits` | int or float | `1` | Stop bits: `1`, `1.5`, or `2` |
| `timeout` | float or null | `null` | Read timeout in seconds |

There is deliberately **no `framer` field** on the serial connection. The
gateway selects framing per device from `default_framer` and each device's own
`framer`; a serial-level framer would be dead configuration.

### `devices` entries

Each key is a Modbus device id (1–247). The key becomes the device's `device_id`
when the settings are converted to the gateway's routing table, so the key and
the device id can never disagree.

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `framer` | string | `RTU` | `RTU`, `ASCII`, or a dotted path to a custom framer |
| `decoder` | string or null | `null` | Dotted path to a custom decoder |
| `pdus` | list of strings | `[]` | Dotted paths to custom PDU classes to register |
| `translator` | string or null | `null` | Dotted path to a `GatewayTranslator`, or null for pass-through |

All plugin references (framer, decoder, pdu, translator) are resolved at
construction time, so a bad dotted path fails fast at startup rather than at the
first request.

## Settings precedence

Effective settings resolve through four layers, later layers winning:

```
constructor default (L0)  <  modbus.yml (L1)  <  config.yml (L2)  <  remote modbus section (L3)
```

Each layer is a **field-level patch**, not a whole-object replacement. The merge
is RFC 7396, so a key has three states:

- **absent** — inherit the value from the layer below;
- **`null`** — clear the field, falling back to the L0 constructor default;
- **a value** — set the field.

The L0 base is `MODBUS_SETTINGS_DEFAULTS` (a concrete `ModbusServiceSettings`
instance). `config.yml` is the namespaced snapshot at
`<conf_dir>/modbus/config.yml`. A successful remote apply auto-writes it (see
[Remote configuration](remote-config.md)), so it mirrors the last-applied remote
config and is re-applied ahead of the remote read on the next start.

The gateway is built from the **effective** settings after the framework has
seeded L0+L1 and applied its local and remote config, so a remote `modbus`
section is reflected in the gateway that starts. See
[Remote configuration](remote-config.md) for the runtime behavior.

## Validation

Validation is split between the loader, the merge, and the gateway core:

- **Loader level** (`read_modbus_config`): YAML parse errors. The loader returns
  the raw `modbus.yml` mapping (`dict[str, object]`) as the L1 patch — it does not
  decode into a struct; struct conversion happens at the merge level. An
  unparseable `modbus.yml` raises `RuntimeError`; the framework's bootstrap seeder
  catches it, logs it, and leaves the section unresolved, so the worker fails to
  start.
- **Merge level** (`ModbusServiceSettings`): types and unknown fields. The merged
  section is converted through the struct, so a wrong type or an unrecognized key
  is rejected.
- **Gateway level** (`to_gateway_config`): device-id range, framer
  resolvability, and plugin dotted-path resolution. These are delegated to
  `GatewayConfig.__post_init__`, so `GatewayConfigError` and
  `SerialConnectionConfigError` propagate unchanged.

A configuration error at startup is logged and the worker fails to start — it
does not run with a partially applied config.

## Regenerating defaults

If `modbus.yml` is missing, the service writes a default file on first run. If
the file exists but is invalid, it is **left untouched**: the loader raises
`RuntimeError`, the framework's bootstrap seeder swallows it, the section stays
unresolved, and the worker fails to start — fix the file or remove it to
regenerate defaults.
