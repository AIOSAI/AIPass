[← Back to the cli README](../README.md)

# The display API — the render surface other branches import

Import display functions from `aipass.cli` and call them to produce consistent
Rich-formatted terminal output across all branches.

## Display functions

```python
from aipass.cli import header, success, error, warning, section

header("Creating Branch", {"Name": "feature", "Type": "module"})
success("Files created", items=12, time="2.3s")
error("Path not found", suggestion="Check spelling")
warning("Config missing, using defaults")
section("Results")
```

## Operation templates

```python
from aipass.cli import operation_start, operation_complete

operation_start("Processing", count=10)
# ... do work ...
operation_complete(created=5, skipped=3, failed=0, time="1.2s")
```

## Fatal (exit on error)

```python
from aipass.cli import fatal

fatal("Config file missing", suggestion="Run aipass init first")
# Prints error message + suggestion, then calls sys.exit(1)
```

## Direct console access

```python
from aipass.cli import console

console.print("[bold cyan]Custom Rich output[/bold cyan]")
```

## The version line

An agent has one version: the `# Version: X.Y.Z` line of its entry point's file
header. `--version` prints it; no `VERSION` constant holds a second copy.

```python
from aipass.cli import console, header_version

console.print(f"name v{header_version(__file__)}", highlight=False)
```

`header_version` reads the file as UTF-8 text (no import) and takes the first
`# Version:` line in the leading run of `#` lines. A missing line, or a value
that is not three integers, raises `ValueError` naming the file — there is no
`0.0.0` fallback.

## The public API

Handed out by the package door, `aipass.cli` (`__init__.py`), read from its home on each access:

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
| `escape()` | `escape(value) -> str` | Rich's own escape, for a value with literal square brackets |
| `operation_start()` | `operation_start(operation, **details)` | Standard operation begin header |
| `operation_complete()` | `operation_complete(**summary)` | Completion summary with optional timing |
| `header_version()` | `header_version(path) -> str` | `X.Y.Z` from the file header's `# Version:` line; `ValueError` if absent or malformed |
| `mark_command_failed()` | `mark_command_failed()` | Set the process failure flag (`error()` calls it automatically) |
| `command_failed()` | `command_failed() -> bool` | Whether the failure flag is set since last reset |
| `reset_command_state()` | `reset_command_state()` | Clear the failure flag (tests, `main()` entry) |
| `resolve_exit()` | `resolve_exit(handled) -> int` | Exit code: not-handled→1, handled+failed→2, handled+ok→0 |

The last four are the exit seam; see [the exit seam](exit_seam.md) for the idiom
to copy into your own `main()`.

Every name above, and the `display` module itself, come through the one door:

```python
from aipass.cli import console, err_console, fatal, operation_start, resolve_exit
from aipass.cli import display  # the module, for monkeypatching its consoles in tests
```

A cross-branch import that reaches under `aipass.cli.apps` fails sentry's `front_door` standard.

`error()`'s `suggestion` must not include a "Try:" prefix — `display.py` adds it.

## Two-tier design

- `aipass.cli` — the door. Other branches import from here.
- `apps/modules/` — where the door's names live. Inside this branch only.
- `apps/handlers/` — internal implementation; the fence refuses a foreign importer.

Passing a value that may contain square brackets? `header`, `success`, `section`
and the templates parse markup and eat it silently — wrap the value in
`escape()`. `error`, `warning` and `fatal` print values literally — do not
escape for them, or the backslash shows. The measured table is in
[Rich markup](rich_markup.md).

---
[← Back to the cli README](../README.md)
