[← Back to AIPass](../../../README.md)

# CLI

**Purpose:** Display and output formatting service for all AIPass branches. Provides consistent terminal output — headers, success/error/warning messages, section breaks, and operation templates — so every branch looks the same without duplicating Rich formatting code.
**Module:** `aipass.cli`
**Version:** 2.1.0
**Seedgo:** 100%
**Tests:** 192 tests across 10 files — 201 passing, 0 skipped (parametrized cases expand at runtime)
**Last Updated:** 2026-08-25

## Quick Start

```bash
drone @cli                     # Show discovered modules
drone @cli display demo        # Run display function showcase
drone @cli templates demo      # Run operation template showcase
drone @cli --help              # Full usage guide
```

## Usage

Import display functions from `aipass.cli` and call them to produce consistent Rich-formatted terminal output across all branches.

### Display Functions

```python
from aipass.cli import header, success, error, warning, section

header("Creating Branch", {"Name": "feature", "Type": "module"})
success("Files created", items=12, time="2.3s")
error("Path not found", suggestion="Check spelling")
warning("Config missing, using defaults")
section("Results")
```

### Operation Templates

```python
from aipass.cli.apps.modules import operation_start, operation_complete

operation_start("Processing", count=10)
# ... do work ...
operation_complete(created=5, skipped=3, failed=0, time="1.2s")
```

### Fatal (exit on error)

```python
from aipass.cli.apps.modules import fatal

fatal("Config file missing", suggestion="Run aipass init first")
# Prints error message + suggestion, then calls sys.exit(1)
```

### Direct Console Access

```python
from aipass.cli import console

console.print("[bold cyan]Custom Rich output[/bold cyan]")
```

## Public API

Exported from `apps/modules/__init__.py` (14 symbols):

| Function | Signature | Purpose |
|----------|-----------|---------|
| `console` | Rich Console instance | Standard output console |
| `err_console` | Rich Console instance | Stderr console |
| `header()` | `header(title, details=None)` | Bordered section header with optional key-value pairs |
| `success()` | `success(message, **kwargs)` | Green checkmark message with metadata |
| `error()` | `error(message, suggestion=None)` | Red error with optional suggestion |
| `warning()` | `warning(message, details=None)` | Yellow warning with optional details |
| `fatal()` | `fatal(message, suggestion=None)` | Error + `sys.exit(1)` for unrecoverable failures |
| `section()` | `section(title)` | Visual section separator with title |
| `operation_start()` | `operation_start(operation, **details)` | Standard operation begin header |
| `operation_complete()` | `operation_complete(**summary)` | Completion summary with optional timing |
| `mark_command_failed()` | `mark_command_failed()` | Set the process failure flag (`error()` calls it automatically) |
| `command_failed()` | `command_failed() -> bool` | Whether the failure flag is set since last reset |
| `reset_command_state()` | `reset_command_state()` | Clear the failure flag (tests, `main()` entry) |
| `resolve_exit()` | `resolve_exit(handled) -> int` | Exit code: not-handled→1, handled+failed→2, handled+ok→0 |

Import paths:
```python
from aipass.cli import console, header, success, error, warning, section  # Top-level (6 symbols)
from aipass.cli.apps.modules import header, fatal, operation_start        # Full set (14 symbols)
from aipass.cli.apps.modules.display import header                        # Direct module
```

## Commands

```bash
drone @cli --help              # Full help + architecture overview
drone @cli --version           # v2.1.0
drone @cli                     # Module discovery (introspection)
drone @cli display             # Display module info
drone @cli display demo        # Run display function showcase
drone @cli templates           # Templates module info
drone @cli templates demo      # Run templates function showcase
```

## Architecture

```
cli/
├── __init__.py                 # Top-level exports (6 symbols) + cli_entry()
├── apps/
│   ├── cli.py                  # Entry point (main, discover_modules, route_command)
│   ├── modules/                # PUBLIC — import from here
│   │   ├── __init__.py         # Re-exports all 14 display + template symbols
│   │   ├── display.py          # header, success, error, warning, fatal, section, exit-code API
│   │   └── templates.py        # operation_start, operation_complete
│   ├── handlers/               # PRIVATE — internal implementation
│   │   ├── cli/
│   │   │   └── help_flags.py   # wants_help() — whole-sequence help detection
│   │   ├── json/
│   │   │   └── json_handler.py # JSON lifecycle (CRUD, validation, rotation)
│   │   └── templates/          # Scaffold placeholder
│   ├── integrations/           # Scaffold placeholder
│   └── plugins/                # Required by spawn builder template
├── tests/                      # 192 tests across 10 files (201 pass, 0 skip)
│   ├── conftest.py             # make_capture_console() + strip_ansi() — the ONE capture helper
│   ├── test_display.py         # 60 tests — display functions + routing + exit codes + help flags
│   ├── test_json_handler.py    # 39 tests — CRUD, validation, rotation
│   ├── test_templates.py       # 31 tests — operation templates + routing + help flags
│   ├── test_help_flags.py      # 11 tests — whole-sequence help detection
│   ├── test_json_durability.py # 10 tests — atomic writes, torn-read race
│   ├── test_output_capture.py  # 8 tests — capture is environment-proof (ANSI strip, 4 shells)
│   ├── test_handler_guard.py   # 19 tests — cross-branch import guard contract
│   ├── test_integration.py     # 6 tests — main() flow, entry points
│   ├── test_init_provisioning.py # 4 tests — JSON provisioning on first run
│   ├── test_parked_is_not_collected.py # 4 tests — collection barrier over tests/parked/ holds
│   └── parked/                 # TRACKED, not run — collect_ignore_glob barrier (archive doctrine, 2026-08-18)
├── cli_json/                   # Auto-created JSON (config, data, log)
├── logs/                       # Branch-level logs
└── .archive/                   # Archived stubs (extensions/, json_templates/, drone_adapter, __main__, init_project leftovers)
```

Branch-standard scaffold dirs are omitted from the tree above: `artifacts/`, `docs/`,
`docs.local/`, `dropbox/`, `templates/`, `tools/`, and the dot-dirs (`.trinity/`,
`.aipass/`, `.ai_mail.local/`, `.seedgo/`, `.spawn/`, `.daemon/`, `.backup/`).
The scaffold `test_scaffold` moved out of `.archive/` to `tests/parked/scaffold(disabled).py`
on 2026-08-19 — tracked, not collected.

**Testing display output:** never assert on raw captured bytes. Build the console with
`make_capture_console()` from `tests/conftest.py` and assert through its `get_output()`,
which strips ANSI. Rich decides whether to emit escapes by probing the environment, so a
raw-bytes assert makes the suite a function of the shell — `FORCE_COLOR=3` renders
`created: 5` as `created: \x1b[1m5\x1b[0m` and a plain substring check fails on output a
human reads as correct. Assert what is VISIBLE.

**Two-tier design:**
- `apps/modules/` — Public API. Import from here.
- `apps/handlers/` — Internal implementation. Don't import directly.

## JSON Handler

Manages the three-file JSON pattern (config, data, log) for any module:

Every write goes through `_atomic_write_json()` — staged in the target directory, then
`os.replace()`d into place. A reader always sees the whole old document or the whole new
one, never a truncated file. This matters because `ensure_json_exists()` answers an
unreadable file by regenerating a template over it, so a torn read would have become
data loss.

```python
from aipass.cli.apps.handlers.json import json_handler

json_handler.log_operation("files_created", {"count": 12})
data = json_handler.load_json("cli", "config")
json_handler.save_json("cli", "data", {"key": "value"})
json_handler.ensure_module_jsons("cli")  # Create all 3 if missing
```

## Integration Points

### Depends On
- `rich` — Terminal formatting (Console, Panel, Table, Text, Columns, box)
- `aipass.prax` — Logging (one import, in `apps/cli.py` only — never in modules/ or handlers/)
- Python stdlib (`sys`, `os`, `json`, `time`, `tempfile`, `inspect`, `importlib`, `pathlib`, `datetime`, `typing`)

### Cannot Import (in modules/)
- `aipass.prax` — Circular dependency (prax depends on cli). Bypassed in `.seedgo/bypass.json`.

### Provides To
- **All branches** — Display formatting (header, success, error, warning, fatal, section)
- **All branches** — Operation templates (operation_start, operation_complete)
- **All branches** — Rich console access

## Entry Points

| Entry | Command | How |
|-------|---------|-----|
| drone | `drone @cli [command]` | Routes to `apps/cli.py:main()` |
| Import | `from aipass.cli import ...` | The real entry point — 356 import statements in 264 files across 17 branches (measured 2026-08-25; 33 of them in test files) |

`python -m aipass.cli` is **not** an entry point — `__main__.py` was archived 2026-05-02 (no branch in the fleet ships one). `cli_entry()` still exists in `__init__.py` but is no longer wired: `pyproject.toml` maps the `aipass` script to `aipass.aipass.apps.aipass:main`. See APLAN-0002 for the keep-or-retire decision.

---

*Last Updated: 2026-08-25*

---
[← Back to AIPass](../../../README.md)
