[← Back to AIPass](../../../README.md)

# CLI

**Purpose:** Display and output formatting service for all AIPass branches. Provides consistent terminal output — headers, success/error/warning messages, section breaks, and operation templates — so every branch looks the same without duplicating Rich formatting code.
**Module:** `aipass.cli`
**Version:** 2.1.0
**Seedgo:** 100%
**Tests:** 164 test functions across 9 files; pytest expands to 176 cases — 176 passing, 0 skipped (measured 2026-09-08)
**Last Updated:** 2026-09-08

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

## The exit seam — the idiom to copy

`mark_command_failed`, `command_failed`, `reset_command_state` and `resolve_exit`
live here, so this is the reference spelling for the whole fleet. **Three lines,
in this order**, in your branch's `main()`:

```python
def main() -> int:
    reset_command_state()                     # 1. clear the flag on entry
    ...
    handled = route_command(command, args, modules)
    if not handled:
        error(f"Unknown command: {command}")  # 2. refuse through error()
    return resolve_exit(handled)              # 3. let the seam pick the code
```

| code | meaning |
|------|---------|
| `0`  | routed, and nothing called `error()` |
| `2`  | routed, but a refusal went through `error()` |
| `1`  | not routed at all |

Why each line is load-bearing:

- **`reset_command_state()` first.** The flag is process-level state. Without
  the reset, one refused command makes every later command in the same process
  exit 2 — and under a test suite, one red test colours the next.
- **The refusal goes through `error()`, not `warning()`.** Only `error()` calls
  `mark_command_failed()`. `warning()` deliberately does not: it is for things
  that proceed. Swapping the colour without the flag changes nothing an exit
  code can see.
- **`return resolve_exit(handled)`, never a bare `0`.** A `main()` that returns
  0 on any truthy route discards the only thing the flag was recorded for. This
  is what made refusals exit 0 across the fleet (@canary's sweep, 2026-09-07):
  the machinery existed, three branches consulted it, and everywhere else
  `error()` printed red and the shell read success.
- **A caller's own `1` is never overwritten.** `resolve_exit()` checks
  `handled` *before* it looks at the flag, so a command that was never routed is
  a 1 whether or not `error()` also tripped the flag.

Cancellation is **130** (128 + SIGINT), not 0 — an interrupted run is not a
successful one. In this branch that lives in `run_cli()`, which exists as a
function rather than as bare code in the `__main__` block precisely so both it
and the crash path (`1`) can be pinned by test.

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
│   ├── cli.py                  # Entry point (main, run_cli, discover_modules, route_command)
│   ├── modules/                # PUBLIC — import from here
│   │   ├── __init__.py         # Re-exports all 14 display + template symbols
│   │   ├── display.py          # header, success, error, warning, fatal, section, exit-code API
│   │   └── templates.py        # operation_start, operation_complete
│   ├── handlers/               # PRIVATE — internal implementation
│   │   ├── cli/
│   │   │   └── help_flags.py   # wants_help() — whole-sequence help detection
│   │   ├── json/
│   │   │   └── json_handler.py # Shim — binds the ONE fleet json service in @prax
│   │   └── templates/          # Scaffold placeholder
│   ├── integrations/           # Scaffold placeholder
│   └── plugins/                # Required by spawn builder template
├── tests/                      # 164 test functions, 9 files — pytest expands to 176 cases, 0 skip
│   ├── conftest.py             # make_capture_console() + strip_ansi() — the ONE capture helper
│   ├── test_display.py         # 59 defs — display functions + routing + exit codes + help flags
│   ├── test_templates.py       # 31 defs — operation templates + routing + help flags
│   ├── test_handler_guard.py   # 19 defs — cross-branch import guard contract
│   ├── test_cli_routing.py     # 18 defs (21 cases) — entry point routing, help, version, refusals, the exit seam
│   ├── test_help_flags.py      # 10 defs (19 cases) — whole-sequence help detection
│   ├── test_import_dead_cwd.py # 9 defs — imports survive a deleted cwd + AST ban on inspect.stack()
│   ├── test_output_capture.py  # 8 defs — capture is environment-proof (ANSI strip, 4 shells)
│   ├── test_integration.py     # 6 defs — main() flow, entry points
│   ├── test_parked_is_not_collected.py # 4 defs — collection barrier over tests/parked/ holds
│   ├── .archive/               # NOT collected — the pre-service handler suites (DPLAN-0325), the
│   │                           #   shim wiring suite (2026-09-07), and two TYPE-ONLY units whose
│   │                           #   claims siblings already pinned by identity (2026-09-08)
│   └── parked/                 # TRACKED, not run — collect_ignore_glob barrier (archive doctrine, 2026-08-18)
├── cli_json/                   # Auto-created JSON (config, data, log)
├── logs/                       # Branch-level logs
└── .archive/                   # Archived stubs (extensions/, json_templates/, drone_adapter, __main__,
                                #   init_project leftovers) + four recovery_*_20260607 snapshots
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

`apps/handlers/json/json_handler.py` is a **shim**, not an implementation. It binds the
one fleet json service published by `@prax` (DPLAN-0325) — nine names plus
`InvalidDocument` and `WriteFailed` — and is byte-identical in every migrated branch.
Anything added to it is drift.

It BINDS (`log_operation = _h.log_operation`) and never wraps. The service names the
calling module from `sys._getframe(2)`, so a `def` wrapper would add exactly one frame and
send every log cli writes into `json_handler_log.json` instead of the caller's document.

The three-file pattern (config, data, log), atomic writes, validation, provisioning and
rotation all live in the service now, and are pinned once for the whole fleet by seedgo's
cross-branch contract rather than re-tested per branch. Under pytest the writes are
redirected by the `AIPASS_TEST_LOG_DIR` seam that `conftest.mock_infrastructure` sets;
the shim has no attribute to patch, and that is the point.

The call sites are unchanged:

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
- `aipass.prax` — Two live imports, both outside `modules/`: the logger in `apps/cli.py:32`, and the
  json service the shim binds in `apps/handlers/json/json_handler.py:26` (see JSON Handler above)
- Python stdlib (`sys`, `os`, `importlib`, `pathlib`, `linecache`, `typing`) — measured over the live
  tree 2026-09-06. `json`, `time`, `tempfile` and `datetime` left with the old json handler (DPLAN-0325);
  `inspect` left with the dead-cwd cure and is now AST-banned in these modules

### Cannot Import (in modules/)
- `aipass.prax` — Circular dependency (prax depends on cli). Bypassed in `.seedgo/bypass.json`.

`handlers/json/json_handler.py` is the exception, and it is not a loophole: prax's
`__init__` is lazy (PEP 562), so `from aipass.prax import json_handler` resolves the
service without importing `cli.display`. The cycle is real — archiving cli's old handler
mid-sweep took `drone` itself down through
`drone → cli.apps.modules.display → cli json_handler` — and laziness is what breaks it.
The two bypasses that read "json_handler cannot import prax (circular)" were retired on
2026-09-03 because the shim demonstrably does.

### Provides To
- **All branches** — Display formatting (header, success, error, warning, fatal, section)
- **All branches** — Operation templates (operation_start, operation_complete)
- **All branches** — Rich console access

## Entry Points

| Entry | Command | How |
|-------|---------|-----|
| drone | `drone @cli [command]` | Routes to `apps/cli.py:main()` |
| Import | `from aipass.cli import ...` | The real entry point — 368 import statements in 255 files across 18 branches (measured 2026-09-08 over live `.py` files only; `.archive/` and `tests/parked/` excluded). 42 of those statements are cli's own, in 16 files; 326 in 239 files come from the other 17 branches |

`run_cli()` in `apps/cli.py` is the process wrapper the `__main__` block calls: it runs
`main()` and maps a `KeyboardInterrupt` to 130 and an escaped exception to 1. It is a
function rather than bare code in the block so both codes can be pinned by test.

`python -m aipass.cli` is **not** an entry point — `__main__.py` was archived 2026-05-02 (no branch in the fleet ships one). `cli_entry()` still exists in `__init__.py` but is no longer wired: `pyproject.toml` maps the `aipass` script to `aipass.aipass.apps.aipass:main`. See APLAN-0002 for the keep-or-retire decision.

## Status / Known issues

**Status:** green. 176 cases pass, 0 skipped, from the repo root and from this directory;
`drone @seedgo audit aipass @cli` 100% on every scored category and
`drone @seedgo audit pytest_quality @cli` 100% on all ten v5 rules (all measured 2026-09-08).
No open defects in this branch's code.

**Known issues**

- `cli_entry()` in `__init__.py` is dead wiring. It is a valid console_scripts target, but
  `pyproject.toml` points the `aipass` script at `aipass.aipass.apps.aipass:main`, so nothing
  calls it. Keep-or-retire is still open under APLAN-0002.
- Nothing in the fleet currently exits **2**. The code is reachable — a routed command that
  calls `error()` and returns True gets it, measured from the shell 2026-09-08 — but no verb
  cli ships does that today, so the 2 is pinned by test rather than by a live command.
- Importer counts depend on the scope you measure. @hooks reports 21 cli imports in 21 of its
  files; this README counts 22 in 22, and both are right — the extra is @hooks' own dead-cwd
  test pin (`tests/test_import_dead_cwd.py:65`), a plain `import aipass.cli.apps.modules`.
  Production-only and all-files are different questions; say which one a number answers.

**Unverified in this pass**

- `tests/parked/` is described as TRACKED (not gitignored). This pass ran no git commands, so
  that word still carries from 2026-08-19. The collection barrier beside it *was* re-verified:
  `tests/parked/conftest.py` sets `collect_ignore_glob = ["*"]` and
  `test_parked_is_not_collected.py` pins it with real pytest collection.
- The @hooks importer figure quoted above (21 in 21 of its files) is carried from 2026-09-06.
  Only cli's own totals were re-measured tonight.

---

*Last Updated: 2026-09-08*

---
[← Back to AIPass](../../../README.md)
