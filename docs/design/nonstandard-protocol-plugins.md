# Design — Non-Standard Protocol Plugin Support

Status: **proposed**
Last updated: 2026-10-02

How `scietex.modbus_service` exposes the `scietex.hal.serial` gateway's
non-standard (vendor) protocol plugin mechanism, and how the first plugin —
`scietex.hal.vacuum_gauge` — is wired in.

## Context

The gateway core already supports non-Modbus devices through a **translator
plugin**: a per-device `GatewayTranslator` maps standard Modbus PDUs to and from
a vendor protocol. The mechanism is fully implemented in `scietex.hal.serial`
2.0.0 (see its `docs/design/modbus-gateway-nonstandard.md`):

- `GatewayTranslator` protocol — `to_vendor(request)` / `to_standard(response)`,
  both pure (no I/O).
- `GatewayDeviceConfig` carries four plugin references: `framer`, `decoder`,
  `pdus`, `translator` (all dotted paths, except the `RTU`/`ASCII` framer
  shortcuts).
- `plugin_loader` resolves each reference by dotted path and validates it is a
  subclass of the expected base at construction time.
- `ModbusGateway` builds one `(framer, decoder, translator)` runtime per device
  and dispatches through the translator when present.

The first real plugin, `scietex.hal.vacuum_gauge`, ships the four artifacts for
the Thyracont RS485 protocol (V1 and V2):

| Artifact | V1 | V2 |
| --- | --- | --- |
| Vendor PDU | `...rs485.v1.request.ThyracontRequest` | `...rs485.v2.request.ThyracontRequest` |
| Vendor framer | `...rs485.v1.framer.ThyracontASCIIFramer` | `...rs485.v2.framer.ThyracontASCIIFramer` |
| Vendor decoder | `...rs485.v1.decoder.ThyracontDecodePDU` | `...rs485.v2.decoder.ThyracontDecodePDU` |
| Translator | `...rs485.v1.translator.ThyracontV1Translator` | `...rs485.v2.translator.ThyracontV2Translator` |

## What already works

The service's config schema **already exposes** the plugin surface. From
`config.py`:

```python
class ModbusDeviceSettings(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    framer: str = "RTU"
    decoder: str | None = None
    pdus: list[str] = msgspec.field(default_factory=list)
    translator: str | None = None
```

`to_gateway_config` passes all four through to `GatewayDeviceConfig`, so a
`modbus.yml` device entry can already name a translator by dotted path. No
schema change is required.

## The gap: plugin availability

The plugin mechanism resolves dotted paths by **importing the module at
startup**. If the plugin package is not installed in the service's environment,
resolution fails:

```
GatewayConfigError: Cannot import module
  'scietex.hal.vacuum_gauge.thyracont.rs485.v1.framer':
  No module named 'scietex.hal.vacuum_gauge'
```

This is the only real gap. The service declares `scietex.hal.serial` and
`scietex.service[valkey]` as dependencies but **not** any plugin package, so a
`modbus.yml` that references a vacuum-gauge translator cannot start.

The design question is therefore not "how do we add plugin support" (it exists)
but **"how does a plugin package get into the service's environment, and how do
we keep the core service free of vendor coupling?"**

## Decision: optional extras, one per plugin family

Plugin packages are declared as **optional extras** in `pyproject.toml`, not as
core dependencies. The core service stays vendor-agnostic; an operator installs
the extra for the hardware they have.

```toml
[project.optional-dependencies]
vacuum-gauge = ["scietex.hal.vacuum_gauge>=2.0.0,<3.0.0"]
```

Install:

```bash
pip install "scietex.modbus_service[vacuum-gauge]"
```

### Why extras, not core dependencies

- **No vendor coupling.** The core service must not depend on every gauge
  vendor. A new plugin family adds an extra, not a core dependency.
- **No import cost.** A plugin package is imported only when a device entry
  names one of its classes. An operator without that hardware never pays for it.
- **Explicit operator intent.** Installing the extra is a deliberate act that
  matches the hardware on the bus.
- **Version pinning.** The extra pins a compatible plugin range, so a plugin
  API change is caught at install time, not at startup.

### Why not dynamic install / entry-point discovery

- **Entry-point discovery** (a plugin registry via `importlib.metadata`) would
  let plugins self-register, but it adds a discovery layer the gateway core does
  not have and the dotted-path contract does not need. The dotted path *is* the
  registry. Rejected as over-engineering for the current plugin count.
- **Runtime pip install** is rejected: the service runs as a non-root user in a
  read-only-ish container; installing at runtime is a security and
  reproducibility anti-pattern.

## Configuration

A non-standard device is declared in `modbus.yml` with all four plugin
references. Example — a Thyracont V1 gauge on device id 1:

```yaml
serial:
  port: /dev/ttyUSB0
  baudrate: 9600
devices:
  1:
    framer: scietex.hal.vacuum_gauge.thyracont.rs485.v1.framer.ThyracontASCIIFramer
    decoder: scietex.hal.vacuum_gauge.thyracont.rs485.v1.decoder.ThyracontDecodePDU
    pdus:
      - scietex.hal.vacuum_gauge.thyracont.rs485.v1.request.ThyracontRequest
    translator: scietex.hal.vacuum_gauge.thyracont.rs485.v1.translator.ThyracontV1Translator
```

A V2 gauge uses the matching `...rs485.v2...` paths and
`ThyracontV2Translator`.

A standard Modbus device omits `translator` (and usually `decoder`/`pdus`),
keeping the frame-proxy behavior:

```yaml
devices:
  2:
    framer: RTU
```

### Validation

All four references are validated at **startup**, when `to_gateway_config` runs
`GatewayConfig.__post_init__`:

- A bad dotted path (typo, missing package) raises `GatewayConfigError`.
- A resolved class that is not a subclass of the expected base raises
  `GatewayConfigError`.
- The worker logs the error and **fails to start** — it does not run with a
  partially resolved device table.

This fail-fast behavior is deliberate: a misconfigured plugin is an operator
error that should surface immediately, not at the first client request.

## Runtime behavior

Once started, the gateway dispatches per device:

```
TCP client ──FC03 @ addr 0──▶ GatewayTcpServer
   decode with the device's framer/decoder
        │
        ▼
   ModbusGateway._forward(dev_id, std_request, runtime)
        │  vendor_req = translator.to_vendor(std_request)
        │  vendor_req.dev_id = dev_id
        ▼  async with lock: swap framer if needed
   bus.execute(False, vendor_req)
        │
        ▼  vendor response PDU
   std_response = translator.to_standard(vendor_response)
        │
        ▼
   encode with the device's framer ──▶ TCP client
```

The client speaks plain Modbus/TCP and never knows the device is non-Modbus.

### Error mapping

A translator raises `GatewayError` for an unsupported request, a malformed
vendor response, or a count mismatch. The gateway catches it (along with
`ModbusException` and `asyncio.TimeoutError`) and returns a standard Modbus
exception response (code `0x0B`, gateway target failed to respond). The TCP
connection stays open, so the client can retry.

## Remote configuration

The `modbus` remote-config section is **declarative / restart-required** (see
[Remote configuration](../remote-config.md)). This applies unchanged to plugin
devices: a remote apply validates the plugin references (via
`to_gateway_config`) and stores the settings, but the gateway is not rebuilt.
Changing a device's translator requires a restart.

A remote apply that names an unresolvable plugin path fails validation and is
rejected — the running gateway keeps its original configuration.

## Container

The container image installs the core service. To use a plugin, build an image
that installs the matching extra:

```dockerfile
RUN pip install --no-cache-dir ".[vacuum-gauge]"
```

Alternatively, install the plugin package into the image directly. The plugin
package must be importable by the same interpreter that runs
`start-modbus-service`.

## Adding a new plugin family

1. **Plugin repo** — implement the four artifacts (PDU, framer, decoder,
   translator) against `scietex.hal.serial`'s bases. The translator is the only
   genuinely new code; the other three are often reusable from an existing
   vendor package.
2. **Service repo** — add an optional extra pinning the plugin package:
   ```toml
   [project.optional-dependencies]
   my-vendor = ["scietex.hal.my_vendor>=1.0.0,<2.0.0"]
   ```
3. **Docs** — add a device example to
   [Configuration](../configuration.md) and, if the plugin has non-obvious
   register semantics, a short section here.
4. **No core code change.** The dotted-path contract means the service needs no
   new code to support a new plugin family.

## Open items

1. **Extra naming** — `vacuum-gauge` (hyphenated, PEP 685 normalized) vs
   `vacuum_gauge`. Lean: hyphenated, matching the normalized distribution name.
2. **Version range** — pin `<3.0.0` to match the plugin's own
   `scietex.hal.serial <3.0.0` bound, or track the plugin's minor releases.
   Lean: `>=2.0.0,<3.0.0` (the release that added the translators).
3. **Plugin readiness** — `scietex.hal.vacuum_gauge`'s translators exist
   (commit `31c4880`, released as 2.0.0) and satisfy the protocol. The package's
   emulator uses `ModbusDeviceContext`, which pymodbus 3.15 deprecates (the
   `.store`/`.setValues`/`.getValues` methods are gone; the class remains and
   the plugin's own tests pass). This is a plugin-repo concern, not a service
   concern, and does not affect production use against real hardware.
4. **Testing without hardware** — the service's tests are hermetic. A plugin
   integration test would need either the plugin's emulator (blocked on item 3)
   or a synthetic vendor stub like `hal.serial`'s `tests/gateway/vendor_stub/`.
   Lean: a synthetic stub in the service tests, resolved by dotted path, to
   exercise the full startup→dispatch path without a vendor dependency.
5. **`pdus` vs `translator`** — both are passed through; the gateway registers
   `pdus` on the decoder and instantiates `translator` separately. A plugin
   needs both when the vendor PDU must be decodable. Documented, not changed.

## Phasing

1. **Add the `vacuum-gauge` extra** to `pyproject.toml`. No code change.
2. **Document the plugin config** in `docs/configuration.md` with a Thyracont
   example.
3. **Add a synthetic-stub integration test** exercising startup with a
   translator device, resolved by dotted path.
4. **Container variant** (optional) — a build arg or documented Dockerfile
   snippet that installs the extra.

Phases 1–2 are the minimum to make the first plugin usable. Phase 3 hardens it.
