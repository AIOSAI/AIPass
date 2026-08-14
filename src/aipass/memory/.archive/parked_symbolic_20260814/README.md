# PARKED: symbolic fragments tier — 2026-08-14

**This is a park, not a demolition.** Patrick's ruling: *"comment out and disable the
fragments code, we may use it later, and comment where compass is and that it is active."*
Nothing here was deleted; every file is byte-identical to what ran in the tree.

## Why

The [Agent Memory Atlas](https://neoneye.github.io/agent-memory-atlas/systems/aipass/)
published a code-grounded review of AIPass memory at revision `0d27e5ef`. It was fair and
specific, and it praised the governance engine, the entry-limit/lint design and rollover.
Its top criticism landed on this tier:

> the AUDN deduplicator gives an LLM a `Delete` verdict with no record of what was removed
> or why — an unauditable deletion.

Correct, and it is the one criticism a memory system cannot shrug at. The tier was also
never wired into anything: no entry in `.aipass/hooks.json` (checked every `UserPromptSubmit`
and `PreCompact` lane), and no caller in rollover, the extractor, `auto_process`, search or
verify. The only import that reached it was `apps/handlers/__init__.py`, which pulled the
package in on *every* live call as a side effect of importing any sibling handler.

## Where the active piece is

**Compass** — @devpulse's curated-truth store. `src/aipass/devpulse`, SQLite + FTS5,
reached with `drone @devpulse compass`. It already carries the discipline this tier lacked:
a correcting entry archives and links the entry it replaces, so a change of mind leaves a
record instead of a hole.

**Not parked:** the surfacing governance engine (`apps/modules/governance.py` →
`apps/handlers/governance/engine.py`). It is a separate tier and it is LIVE on the prompt
lane — @hooks' `compass_recall` calls `should_surface` / `record_message` / `new_state` on
every `UserPromptSubmit` to decide which Compass decisions may be shown. Do not confuse the
two when reviving.

## What is in here

```
handlers/   chroma_client.py  deduplicator.py  extractor.py  hook.py  retriever.py
            storage.py  __init__.py          <- the original package init
modules/    symbolic.py                      <- the original 1602-line CLI module
```

Left in place in the live tree on purpose:

- `apps/handlers/symbolic/__init__.py` — a stub that **raises** `SymbolicTierParked` naming
  the ruling. A missing package raises `ModuleNotFoundError`, which explains nothing.
- `apps/modules/symbolic.py` — a stub whose subcommands all exit 1 with the ruling, and
  whose module `__getattr__` answers for the entire old public API.
- `memory_json/symbolic_config.json`, `symbolic_data.json`, `symbolic_log.json` and
  `logs/symbolic.log` — data, not code. Untouched, so revival keeps its history.

## How to revive

1. `mv .archive/parked_symbolic_20260814/handlers/*.py apps/handlers/symbolic/`
   (the original `__init__.py` is in there and replaces the raising stub)
2. `mv .archive/parked_symbolic_20260814/modules/symbolic.py apps/modules/symbolic.py`
3. Uncomment `from . import symbolic` in `apps/handlers/__init__.py` (~line 128)
4. Remove the module-level `pytest.skip(...)` at the top of `tests/test_symbolic.py`,
   `test_symbolic_cli.py`, `test_symbolic_extras.py`, `test_symbolic_module.py`
5. Delete `tests/test_symbolic_parked.py` — it pins the park, and the park would be over
6. Fix the Atlas finding before it goes live again: an AUDN `Delete` verdict must write what
   it removed, why, and when — or it must not delete.

Step 6 is not optional housekeeping. It is the reason this is parked rather than running.
