# Stderr Routing Standard
**Status:** Active
**Date:** 2026-03-13
**Origin:** FPLAN-0032 (CLI stderr standardization)

## What This Covers

Error and warning output must route to stderr via CLI display functions, not stay on stdout via raw `console.print()` with colored markup.

---

## The Problem

CLI `display.py` now has `err_console = Console(stderr=True)`. The functions `error()`, `warning()`, and `fatal()` route through it automatically. But branches still using `console.print('[red]Error...[/red]')` send errors to stdout — breaking piping, redirection, and machine-readable output.

## Correct Pattern

```python
from aipass.cli.apps.modules import error, warning, fatal

error('Branch not found', suggestion='Check spelling')   # stderr
warning('Template mismatch', details='Expected v2')       # stderr
fatal('Config missing')                                    # stderr + sys.exit(1)
```

## Wrong Pattern

```python
console.print('[red]Error: Branch not found[/red]')       # stdout!
console.print('[yellow]Warning: mismatch[/yellow]')       # stdout!
Console(stderr=True)                                       # Don't create your own
```

## What the Checker Catches

1. `console.print()` with `[red]`/`[bold red]` markup — use `error()` or `fatal()`
2. `console.print()` with `[yellow]`/`[bold yellow]` markup — use `warning()`
3. Custom `Console(stderr=True)` creation — import `err_console` from CLI

## CLI Display Exports

```python
from aipass.cli.apps.modules import (
    error,        # ❌ message + optional suggestion → stderr
    warning,      # ⚠ message + optional details → stderr
    fatal,        # ❌ message + sys.exit(1) → stderr
    err_console,  # Raw stderr Console (rare, prefer functions above)
)
```

## Scope

- All branches except CLI (which defines these functions)
- Handlers are exempt (CLI separation standard covers them separately)
- `if __name__ == '__main__':` blocks are excluded

## Reference

- `src/aipass/cli/apps/modules/display.py` — error(), warning(), fatal() definitions
- FPLAN-0032 — Phase 1+2: CLI stderr standardization (closed)
- FPLAN-0033 — Phase 3: branch migration (gates on this standard)
