# Remote configuration

The service registers a `modbus` section with the framework's remote-config
system. An operator can push Modbus settings at runtime over the framework's
config channel (a Valkey key) instead of editing `modbus.yml` and restarting.

The section is **declarative and restart-required**: applying it validates and
stores the desired settings, but it never live-rebuilds the gateway. The serial
port and TCP listener are process-lifetime resources — reopening the bus and
rebinding the listener on a running worker is unsafe — so a running worker only
logs that a restart is needed.

## How it is registered

`ModbusWorker.__init__` registers the section:

```python
self.register_config_settings(
    MODBUS_SECTION,          # "modbus"
    ModbusServiceSettings,
    apply=self._apply_modbus_settings,
)
```

The framework validates the section against `ModbusServiceSettings`
(`forbid_unknown_fields=True`, so a typo is rejected), then calls the apply hook.
The hook runs `to_gateway_config(settings)` to validate declaratively — a bad
device id, framer, or plugin path raises, which the framework reports as a
failed apply — then stores the settings.

## Apply behavior

| Worker state | What happens on apply |
| --- | --- |
| **Before startup** (gateway not yet built) | Settings are stored; the gateway is built from them at startup. Logs `Stored Modbus settings for gateway startup`. |
| **Running** (gateway already built) | Settings are validated and stored, but the gateway is **not** rebuilt. Logs a warning that a restart is required. |

Because the gateway is built **after** the framework applies its local and
remote config, a remote `modbus` section pushed before startup is reflected in
the gateway that starts. A section pushed after startup takes effect only on the
next restart.

## Settings precedence

```
constructor default  <  modbus.yml  <  framework config.yml / remote modbus section
```

The remote section is authoritative when present. On every run the worker starts
from the constructor/default baseline and re-applies the local file and remote
source from scratch.

## `config:*` commands

The framework exposes three task types for remote config (available because the
service sets `remote_config_enabled=True`):

| Command | Purpose |
| --- | --- |
| `config:apply` | Apply an envelope (inline, or re-read the source of truth) |
| `config:store` | Persist the effective config to disk, remote, or both |
| `config:show` | Inspect the effective and declarative settings |

These are framework-level commands; their request/response schemas are
documented in the
[`scietex.service` remote-config guide](https://github.com/bond-anton/scietex.service/blob/main/docs/remote_config.md).

### `config:store` and `modbus.yml`

`config:store` with `target="disk"` writes the framework snapshot to
`<conf_dir>/modbus/config.yml` — **not** to `modbus.yml`. The service-owned
bootstrap file is never rewritten by the framework. To make a stored config
survive a restart, the operator either relies on the framework re-applying
`config.yml`, or copies the desired values into `modbus.yml` manually.

## Restart-required fields

Every field in `ModbusServiceSettings` is restart-required, because the whole
gateway is rebuilt from it:

- `serial.*` — the serial port is opened once at startup.
- `host` / `port` — the TCP listener is bound once at startup.
- `default_framer`, `devices`, `allow_unknown_devices`, `bus_retries` — baked
  into the `GatewayConfig` at construction.

A remote apply of any of these validates and stores the value, but the running
gateway keeps its original configuration until the process restarts.

## Security

The framework's remote-config security model applies unchanged:

- **Allowlist by type.** Only fields representable in `ModbusServiceSettings`
  can be set remotely; `forbid_unknown_fields=True` rejects anything else.
- **Validate-before-swap.** A candidate is constructed through the real struct
  and validated by `to_gateway_config` before it is stored; a bad value is
  rejected with no state change.
- **Broker ACLs are the primary defense.** Anyone able to write the config key
  can influence worker behavior. Restrict those writes to trusted operators at
  the broker.

See the
[`scietex.service` security model](https://github.com/bond-anton/scietex.service/blob/main/docs/remote_config.md#security-model)
for the full contract.
