# Output Routing Standard

**Status:** Active
**Date:** 2026-07-09

---

## What This Standard Is

User-facing error, success, and warning output must route through `@cli`'s semantic helpers (`error()`, `success()`, `warning()`) instead of raw `console.print()` with status markup or emojis.

## Why It Matters

1. **Consistent formatting** — all agents display errors, successes, and warnings the same way.
2. **Exit-code correctness** — `error()` carries the GitHub #661 failure-flag fix. Raw `console.print("[red]...")` bypasses it, causing error paths to exit 0.
3. **Stderr routing** — `error()` and `warning()` write to stderr; raw `console.print()` writes to stdout.

## What the Checker Scans For

Detects `console.print()` or `err_console.print()` calls containing status indicators:

- `[red]` or `[bold red]` markup (error-style output)
- Status emojis: `❌ ✅ ✓ ✗ ✘ ⚠ ✔`
- `[green]` paired with check emojis (`✓ ✔ ✅`)
- `[yellow]` paired with warning indicators (`⚠`, "warning", "WARN", "FAIL")

### Exclusions

- Docstring lines (the string first statement of a module, class or function), read from the parse tree
- The body lines of a multi-line string literal: data, never a call
- Comment lines (`# ...`)
- `__init__.py` files
- Test files (`test_*.py`, `*_test.py`, `conftest.py`)
- `console.print()` with no status markup (tables, panels, informational text)
- Non-status color like `[cyan]`, `[dim]`, `[blue]`

## Code Examples

### Violation

```python
console.print(f"[red]Error: {msg}[/red]")
console.print("[bold red]Failed to process[/bold red]")
console.print(f"[green]✓[/green] Task complete")
console.print(f"❌ Something went wrong")
```

### Fix

```python
from aipass.cli.apps.modules import error, success, warning

error(f"Error: {msg}")
error("Failed to process")
success("Task complete")
error("Something went wrong")
```

## Scoring

- Single check per file: pass (0 violations) or fail (any violations)
- Score: 100 if passed, 0 if failed
- Threshold: score >= 75 to pass overall
- Line-level bypass filtering is supported

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{"standard": "output_routing", "file": "path/to/file.py"}
```

Or bypass specific lines:

```json
{"standard": "output_routing", "file": "file.py", "lines": [42, 78]}
```

## Audit Scope

`AUDIT_SCOPE = all_files` — runs against every `.py` file in the branch. Skips `__init__.py` and test files.

## Reference

- Checker: `output_routing_check.py`
- Standards pack: seedgo standards (output_routing)
- Related: GitHub #661 (error paths exit 0)
