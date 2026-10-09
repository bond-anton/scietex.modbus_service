# AGENTS.md

`scietex.modbus_service` — a `scietex.service` v6 Valkey worker that runs the
serial<->TCP Modbus gateway from `scietex.hal.serial`. Python, `src/` layout,
namespace package. The `0.1` branch is a frozen snapshot of the pre-v1 code.

## Commands

Dependencies are managed with **uv**; checks and tests run through **tox**:

```bash
uv sync --all-extras          # create/refresh .venv (uv-managed; no pip inside)
uv run tox                    # full env_list: format, lint, type, py314
uv run tox -e py314           # tests only (coverage run -m pytest tests)
uv run tox -e lint            # ruff check --fix src tests
uv run tox -e type            # ty check src
uv run tox -e format          # ruff format .
```

Single test / focused run — pass args through tox:

```bash
uv run tox -e py314 -- tests/test_config.py
uv run tox -e py314 -- tests/test_config.py::test_to_gateway_config_device_id_from_dict_key
```

To run pytest directly, install the test extra first: `uv sync --extra test`
then `uv run pytest`. Order matters: **lint -> type -> test**.

## Test setup (non-obvious)

- `pytest.ini` sets `pythonpath = .` and `addopts = --capture=no`; it
  **overrides** the `[tool.pytest.ini_options] pythonpath = ["src"]` in
  `pyproject.toml`. Do not "fix" one without the other.
- Tests use a dual-import shim because of the namespace layout:
  `try: from src.scietex... except ModuleNotFoundError: from scietex...`.
  Follow this pattern in new test files.
- Tests are **hermetic** — no live Valkey/Redis required. `test_modbus_worker.py`
  monkeypatches `ValkeyWorker.initialize` to skip the live connect; the gateway
  failure path is exercised with a nonexistent serial port. CI still starts a
  `redis` service container, but the suite does not depend on it.
- `pytest-asyncio` is enabled; async tests are marked `@pytest.mark.asyncio`.

## Architecture

- `src/scietex/modbus_service/` is the package root; `scietex/` is an
  **implicit namespace package** (no `__init__.py`). Do not add one.
- Five modules: `config` (msgspec settings + `MODBUS_SETTINGS_DEFAULTS` L0 base +
  `read_modbus_config` L1 patch loader + the `to_gateway_config` conversion seam),
  `modbus_worker` (`ModbusWorker`), `run_worker` (CLI entry point), `version`,
  `__init__` (public exports).
- `ModbusWorker(ValkeyWorker)` owns a `ModbusGateway` + `GatewayTcpServer`.
  `initialize()` order is `super().initialize()` (framework seeds L0+L1 and
  applies L2/L3) -> read merged via `current_config_settings` -> convert -> build
  -> start. The gateway is built **after** `super().initialize()` so the remote
  `modbus` section hook has already updated `self._settings`. A bootstrap failure
  is swallowed by the framework's seeder and surfaces only as an unresolved
  section, so the `None` guard is the failure path.
- The remote-config `modbus` section is **declarative / restart-required**:
  applying it validates and stores settings but never live-rebuilds the gateway
  (serial port + TCP listener are process-lifetime resources). `config:store`
  persists to the framework snapshot, not to `modbus.yml`.
- Settings precedence: constructor default (L0) < `modbus.yml` (L1) < framework
  `config.yml` (L2) < remote `modbus` section (L3). Each layer is a field-level
  patch (RFC 7396): absent = inherit, `null` = clear to L0, value = set.
- `scietex.hal.serial` does **no** file I/O or config-dir resolution — config
  provisioning is this service's job. The gateway's serial-level `framer` is
  dead (the gateway uses `GatewayConfig.default_framer`), so the service schema
  deliberately omits it.
- Version is dynamic: `pyproject.toml` reads
  `scietex.modbus_service.version.__version__`. Bump it in `version.py`, not in
  `pyproject.toml`.

## Configuration & deployment

- Config is namespaced under `<conf_dir>/modbus/` so services sharing the
  framework's single config dir cannot collide: `modbus.yml` (service-owned L1
  bootstrap patch) and `config.yml` (framework L2 snapshot, via
  `config_file="modbus/config.yml"`). `MODBUS_CONFIG_SUBDIR` in `config.py` is
  the single source of truth for the subdir name.
- `conf_dir` resolution is the framework's `prepare_conf_dir` (arg ->
  `SCIETEX_CONFIG_DIR` -> XDG -> `~/.config/scietex` -> `/etc/scietex` ->
  `/usr/local/etc/scietex` -> `./config`).
- Entry point `start-modbus-service` (`run_worker:main`). CLI flags
  `--conf-dir` / `--service-name` / `--logging-level`; the latter two fall back
  to `SCIETEX_SERVICE_NAME` / `SCIETEX_LOGGING_LEVEL`. CLI flag > env > default.
- `Containerfile` runs as non-root `appuser` (in `dialout` for serial access),
  mounts `/config`, and sets `SCIETEX_CONFIG_DIR=/config`. Port 502 is
  privileged — binding it needs `--cap-add NET_BIND_SERVICE` or a `modbus.yml`
  port override. Serial devices need `--device /dev/ttyUSB0`.
- `build_image.sh` builds a multi-arch manifest and extracts the version from
  `src/scietex/modbus_service/version.py`.

## Conventions

- `ruff` formatting and linting (`E`, `F`, `I`, `UP`; line length 127) on
  `src tests`; `ty` type checking on `src` only.
- `py.typed` is shipped — keep type annotations accurate.
- `cspell.json` maintains the project word list; add new domain terms there.
- `uv.lock` is git-ignored (matching the sibling `scietex.*` repos); regenerate
  with `uv lock` after changing dependencies.

## Known inconsistencies (verify before trusting)

- `tox.ini` env_list targets `py{314}` only, while the CI matrix
  (`.github/workflows/python-package.yml`) runs 3.10/3.12/3.14 and
  `requires-python = ">=3.10"`. The local venv is Python 3.14.
- `build/lib/` is a **stale** build artifact containing an old package layout
  (`schemas/`, `handlers/`) that no longer exists in `src/`. Ignore it; never
  edit it. It is git-ignored.
- `README.md` is the user-facing entry point; `docs/` holds the detailed pages;
  this `AGENTS.md` holds repo conventions.
