[← Back to AIPass](../../../README.md)

# CLI

**Purpose:** Display and output formatting service for all AIPass branches.
Provides consistent terminal output — headers, success/error/warning messages,
section breaks, and operation templates — so every branch looks the same without
duplicating Rich formatting code.
**Module:** `aipass.cli`
**Version:** 2.3.0
**Last Updated:** 2026-09-17

## Quick Start

```python
from aipass.cli import header, success, error, warning, section

header("Creating Branch", {"Name": "feature", "Type": "module"})
success("Files created", items=12, time="2.3s")
error("Path not found", suggestion="Check spelling")
warning("Config missing, using defaults")
section("Results")
```

That is the whole idea: import the function, call it, and the output matches
every other branch in the system. The full symbol table, signatures and import
paths are in [the display API](docs/display_api.md).

## How to reach me

`drone @cli` — bare, no arguments — prints the live self-map: which modules are
discovered, which services are registered, and what to run next. It is generated
from the code at the moment you run it, so it cannot go stale.

`drone @cli --help` is the reference: the full command list, the public service
table, import examples and an architecture panel.

Between those two, the live answer always wins over anything written here.

## Commands

This page deliberately does not carry a command list. The entry point publishes
its own, and a list typed here is a claim that rots the first time a verb is
added. Ask the branch instead — the self-map above lists what is registered, and
the help flag prints the reference with every verb, alias and flag it accepts.

## Architecture

Two tiers, and the boundary is the whole design. `apps/modules/` is the public
API: `display.py` owns the message functions and the exit-code seam,
`templates.py` owns the operation templates. Anything in `apps/handlers/` is
internal — `help_flags.py` detects a help flag anywhere in an argument sequence,
and the json handler is a thin shim over the one fleet json service. Callers
import from `apps/modules/`; nothing outside this branch should reach into
`apps/handlers/`.

The entry point (`apps/cli.py`) discovers modules at run time rather than from a
table, which is why the self-map and the code cannot disagree. The directory
tree and the gotchas that go with it live in this branch's own prompt, where the
people editing the code will actually see them.

## Documentation

The same index, in the docs directory itself: [docs/README.md](docs/README.md).

| Page | What it covers |
|------|----------------|
| [display_api.md](docs/display_api.md) | The render surface other branches import: every symbol, signature and import path |
| [exit_seam.md](docs/exit_seam.md) | The exit-code idiom to copy into your own `main()`, and why each line is load-bearing |
| [rich_markup.md](docs/rich_markup.md) | Printing literal square brackets, what eats placeholders, and the rule for the fleet |
| [testing_output.md](docs/testing_output.md) | Asserting on what is visible, not on raw bytes |
| [json_handler.md](docs/json_handler.md) | The json shim, and why it may import prax when `apps/modules/` may not |

## Integration Points

### Depends On

- `rich` — the formatting engine (Console, Panel, Table, Text, Columns, box)
- `aipass.prax` — logging in the entry point, and the json service the shim
  binds; both live outside `apps/modules/`
- Python standard library only otherwise

### Cannot Import (in `apps/modules/`)

- `aipass.prax` — circular dependency, since prax depends on this branch. The
  exception and the reason it is safe are in [the json
  handler](docs/json_handler.md).

### Provides To

- **All branches** — display formatting (header, success, error, warning,
  fatal, section), and `escape` for values carrying literal square brackets
- **All branches** — operation templates (operation_start, operation_complete)
- **All branches** — Rich console access, and the exit-code seam every `main()`
  is meant to copy

The import is the real entry point; the command line is a demo of it. To count
the live importers, grep the tree rather than trusting a number written here.

---
[← Back to AIPass](../../../README.md)
