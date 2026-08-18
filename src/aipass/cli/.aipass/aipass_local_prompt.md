# CLI — Branch Prompt
<!-- File: src/aipass/cli/.aipass/aipass_local_prompt.md — Injected every prompt when in cli directory. -->

Shared Rich display and formatting service for all AIPass branches. Provides consistent terminal output — headers, success/error/warning messages, section breaks, operation templates — so every branch renders the same without duplicating formatting code.

# Commands

```
drone @cli --help              # Full help + architecture overview
drone @cli                     # Module discovery (introspection)
drone @cli display demo        # Display function showcase
drone @cli templates demo      # Operation template showcase
```

# Public API

14 symbols exported from `apps/modules/__init__.py`:
 - `console`, `err_console` — Rich Console instances (stdout, stderr)
 - `header(title, details=None)` — Bordered section header with optional key-value pairs
 - `success(message, **kwargs)` — Green checkmark with metadata
 - `error(message, suggestion=None)` — Red error with optional suggestion
 - `warning(message, details=None)` — Yellow warning with optional details
 - `fatal(message, suggestion=None)` — Error then `sys.exit(1)`
 - `section(title)` — Visual section separator
 - `operation_start(operation, **details)` — Operation begin header
 - `operation_complete(**summary)` — Completion summary with timing
 - `mark_command_failed()`, `command_failed()`, `reset_command_state()`, `resolve_exit(handled)` — exit-code failure flag. `error()` trips it; `resolve_exit` maps not-handled→1, handled+failed→2, handled+ok→0.

Import: `from aipass.cli import console, header, success, error, warning, section` (top-level, 6 symbols) or `from aipass.cli.apps.modules import ...` (full set, 14 symbols).

# Architecture

```
cli/
├── __init__.py           # Top-level exports (6 symbols) + cli_entry()
├── apps/
│   ├── cli.py            # Entry point (main, route_command)
│   ├── modules/          # PUBLIC — import from here
│   │   ├── display.py    # header, success, error, warning, fatal, section, exit codes
│   │   └── templates.py  # operation_start, operation_complete
│   └── handlers/
│       ├── json/         # JSON lifecycle (CRUD, validation, atomic writes, rotation)
│       └── cli/          # help_flags.py — whole-sequence help detection
└── tests/                # 188 tests across 9 files (197 pass, 0 skip)
```

Two-tier design: `apps/modules/` is the public API. `apps/handlers/` is internal — don't import directly. See README for full tree.

# Critical Rules

 - `apps/modules/` must not import `aipass.prax` — circular dependency (prax depends on cli). Bypassed in `.seedgo/bypass.json`.
 - `json_handler.py` must not import prax either — same circular chain. Callers log via prax. Its failed writes RAISE rather than log.
 - Every json_handler write goes through `_atomic_write_json()` (mkstemp in the target dir + `os.replace`). Never `open(path, "w")` — that truncates first, and the regenerate path turns a torn read into data loss.
 - Help gates scan the WHOLE arg sequence via `wants_help(None, args)` — never `args[0]` alone.
 - Display tests assert VISIBLE characters, never raw bytes. Build captures with `make_capture_console()` from `tests/conftest.py`; its `get_output()` strips ANSI. A raw-bytes assert makes the suite a function of the shell (`FORCE_COLOR=3` bolds numbers, so `created: 5` is not literally present).
 - Import json_handler as module: `from aipass.cli.apps.handlers.json import json_handler` then `json_handler.log_operation(...)`. Seedgo AST checker matches this exact pattern.
 - `error()` suggestion param must not include "Try:" prefix — `display.py` adds it automatically.
 - `handle_command()` lives in `display.py` and `templates.py`, not `cli.py` — `route_command()` dispatches to them. Both are in `SERVICE_MODULES`, so bare `drone @cli` lists them under Services, not Discovered Modules (0 is correct, not a bug).
 - Project init is NOT ours — `aipass init` and `handlers/init/bootstrap.py` moved to the @aipass branch. Never re-add init routing here; send init questions to @aipass.

# Integration Points

 - Depends on: `rich` (formatting), `aipass.prax` (logging, in cli.py only), Python stdlib
 - Provides to: all branches — display functions, operation templates, Rich console access
 - Cannot import in modules/: `aipass.prax` — see bypass rules above

# Entry Points

 - `drone @cli [command]` — routes to `apps/cli.py:main()`
 - `from aipass.cli import ...` — the real entry point, 252 call sites fleet-wide
 - Not entry points: `python -m aipass.cli` (no `__main__.py`, archived 2026-05-02) and the `aipass` script (pyproject maps it to the @aipass branch, not `cli_entry()`)
