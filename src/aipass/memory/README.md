[← Back to AIPass](../../../README.md)

# MEMORY

**Central memory archive — vector search, rollover, and memory management for all AIPass branches.**

`drone @memory <command>` | Module: `aipass.memory` | Created: 2026-03-07

---

## Quick Start

```bash
drone @memory search "query"            # Search archived memories across all branches
drone @memory rollover status           # Show what needs archiving per branch
drone @memory rollover check            # Dry run — preview pending rollovers
drone @memory lint                      # Audit .trinity entries for limit violations
drone @memory watch                     # Auto-rollover watcher (Ctrl+C to stop)
```

---

## Commands

```bash
drone @memory rollover run                 # Execute rollover for files over limits
drone @memory rollover status              # Show per-branch rollover statistics
drone @memory rollover check               # Dry run — what needs rollover
drone @memory rollover sync-lines          # Update line count metadata

drone @memory search "query"               # Semantic search across all branch memories
drone @memory search "query" --branch X    # Filter by branch
drone @memory search "query" --n 10        # Limit results

drone @memory symbolic demo                # Mock analysis demonstration
drone @memory symbolic fragments "query"   # Search stored symbolic fragments
drone @memory symbolic extract <file>      # Extract fragments via LLM (requires API key)
drone @memory symbolic bootstrap           # Populate fragments from session JSONLs
drone @memory symbolic hook-test           # Test hook with sample conversation text

drone @memory templates push-templates     # Push template updates to all branches
drone @memory templates diff-templates     # Show template differences per branch
drone @memory templates template-status    # Show template version and push status

drone @memory pool status                  # Pool file count, config, vector stats
drone @memory pool process                 # Vectorize pool files + check rollover

drone @memory lint                         # Audit .trinity entries for over-limit violations (read-only)
drone @memory lint @devpulse               # Lint a specific branch

drone @memory verify FPLAN-XXXX            # Check if plan is vectorized in ChromaDB
drone @memory watch                        # Auto-rollover watcher daemon (Ctrl+C to stop)
```

---

## Architecture

```
memory/
├── apps/
│   ├── memory.py                # Entry point — auto-discovers modules
│   ├── modules/                 # 9 modules
│   │   ├── governance.py        # Surfacing governance — re-exports from handlers
│   │   ├── lint.py              # Entry limit violation scanner (read-only)
│   │   ├── pool.py              # Pool vectorization + auto-process
│   │   ├── rollover.py          # Rollover orchestration, status, sync-lines
│   │   ├── search.py            # Semantic query routing
│   │   ├── symbolic.py          # Fragmented memory extraction and search
│   │   ├── templates.py         # Template push, diff, status
│   │   ├── verify.py            # Plan vectorization check
│   │   └── watch.py             # Auto-rollover watcher (CLI routing only)
│   └── handlers/                # 14 handler groups
│       ├── archive/             # indexer.py
│       ├── cli/                 # help_flags.py — help-flag detection
│       ├── governance/          # engine.py — surfacing decision logic
│       ├── intake/              # plans_processor.py, pool_processor.py, auto_process.py
│       ├── json/                # json_handler.py, memory_files.py, entry_limits.py, lint_handler.py, config_loader.py
│       ├── monitor/             # detector.py, memory_watcher.py, watch_runner.py
│       ├── rollover/            # extractor.py, orchestrator.py
│       ├── schema/              # normalize.py
│       ├── search/              # query_executor.py
│       ├── storage/             # chroma_subprocess.py
│       ├── symbolic/            # chroma_client, deduplicator, extractor, hook, retriever, storage
│       ├── templates/           # pusher.py, differ.py, spawn_pusher.py
│       ├── tracking/            # line_counter.py, tab_renderer.py
│       ├── vector/              # embedder.py, embed_subprocess.py
│       └── central_writer.py
├── templates/                   # LOCAL.template.json, OBSERVATIONS.template.json
├── tests/                       # 997 tests
├── .chroma/                     # ChromaDB vector store
└── memory_json/                 # Operation logs + custom_config/memory.config.json
```

### Rollover Pipeline

```
detector.check_all_branches()        # scan AIPASS_REGISTRY.json + external registries
→ _should_rollover(file)             # v1: line_count >= max_lines (600)
                                     # v2: len(sessions) >= max_sessions (20)
→ orchestrator.execute_rollover()
  → create_rollover_backup()         # safety copy to branch/.backup/
  → extract_items()                  # v2: max(excess, 1) oldest entries
  → embed via subprocess             # fastembed (ONNX) in memory .venv
  → upsert in ChromaDB               # content-hash IDs (sha256[:16]), no duplicates
  → trim source file                 # write back with oldest removed
```

Rollover writes safety copies (`rollover_backup_*.json`) into `<branch>/.backup/` — a shared runtime namespace (see `@backup`'s README for all writers).

### Safety valve and the two session lanes

`sessions` holds two lanes with separate budgets: regular entries against `count`, and AUTO-COMPACT SNAPSHOT entries (`status == "auto-compact"`) against `auto_compact_cap`. Snapshots never push regular sessions out early, and vice versa.

Before archiving a tail entry as "oldest", `_is_misplaced_entry()` holds back anything that looks like a fresh write landed at the wrong end — numbered above the array head, or dated today (DPLAN-0278).

The **date** half is off for the snapshot lane (`date_guard=False`). Snapshots are machine-written several times a day, so at cap the oldest one is nearly always dated today: the valve refused every candidate, the lane could never drain, and the detector re-fired on the same file forever — a skip loop. Ordering says which snapshot is oldest there, not the date. Numbering still guards both lanes, and when an entry carries no usable `number` the date rule stays on regardless of the caller (DPLAN-0290 item 3).

### Newest-first guardrail (normalize)

`sessions`, `key_learnings`, `todos` and `observations` are newest-first by contract — rollover archives the **tail** as "oldest", so a misordered array is silent memory loss. `normalize_memory_file()` re-sorts them by `number`, and **never fails open silently** (GH #728):

- **Per-entry tolerance.** An entry whose `number` cannot be read as an int keeps its exact index; the readable entries beside it are still ordered among the slots they occupy. One bad row no longer forfeits protection for the whole container.
- **Loud skip.** Every unreadable row is reported — `result["warnings"]` names the container and the offending indices, a prax `WARNING` is logged, and `normalize_all_memory_files()` returns `files_with_warnings` (also printed by the CLI). Warnings are *not* mutations, so a file with nothing to change is left byte-identical.
- **Type repair.** A `number` stored as a numeric string (`"171"`) or integral float is coerced to `int`, recorded in `changes`, and persisted — the half-repaired container that used to raise `TypeError` inside `sorted()` now heals itself.
- A container with **no** numbers at all (the normal `todos` shape) is skipped silently — that is a legitimate shape, not corruption.

### A help flag is never an instruction

Every module routes its help check through `handlers/cli/help_flags.wants_help()`, evaluated **before** any subcommand dispatch. Modules used to read `args[0]` only, so a flag in a later slot was discarded and the subcommand ran instead — `drone @memory rollover push --help` performed the fleet-wide `per_branch` reset it was being asked to describe.

A dashed flag (`--help`, `-h`) counts anywhere on the line. The bare word `help` counts anywhere only for modules whose subcommands take no free text (`rollover`, `templates`, `pool`, `lint`); for `search`, `symbolic` and `verify` it counts in the first slot only, so `drone @memory search rollover help` stays a three-word query.

### `watch` is a module, and the entry point imports no handlers

`drone @memory watch` was a built-in on `apps/memory.py`, which therefore imported
two `monitor/` handlers directly — the one `encapsulation` violation on the branch.
It is now `modules/watch.py` (CLI routing) over `handlers/monitor/watch_runner.py`
(the session: start, report, block, shut down on Ctrl+C). A contract test fails the
suite if any handler import reappears in the entry point.

No-args still starts the watcher — that is the live contract — with the Level 2
introspection block printed as the watcher's banner, so the operator sees which
handlers it is wired to before it takes over the terminal.

**Every `apps/modules/*.py` ships a `__main__` block, so all of them must survive
direct execution.** Six relative imports in `rollover.py` and `pool.py` meant they
did not: `python3 apps/modules/rollover.py --help` died with *"attempted relative
import with no known parent package"* — the same defect class that left `watch`
dead, invisible because routing through the entry point imports them as a package.
All six are absolute now, and a contract test scans the whole directory.

### Subprocess Isolation

All ML operations (fastembed, chromadb) run via subprocess. The main process never imports these libraries. Python interpreter resolved via `_get_memory_python()` (env var `AIPASS_MEMORY_PYTHON` → `memory/.venv/bin/python` → `sys.executable`).

---

## State-Tabs (`*_meta` keys)

Every `.trinity/local.json` and `.trinity/observations.json` carries inline `*_meta` banner strings that tell the editing agent what rollover rules apply to each section. Example:

```
"sessions_meta": "⟦ rollover ON → oldest archived to @memory · keep 15 · summary ≤300 chars ⟧"
```

**Source of truth:** `memory_json/custom_config/memory.config.json` — the operator-edited file *is* the runtime authority for rollover counts and entry char limits. `config_loader.DEFAULT_CONFIG` in code is the **regeneration seed**: when the file is genuinely *missing*, `load()` rebuilds it in full from those defaults so there is always a real file to edit. A file that *exists* but cannot be read — for **any** reason: bad syntax, bad bytes, bad permissions — is never written over (DPLAN-0206 red flag, `json_structure` v3.0.0) and never raises at the caller. `load()` logs an ERROR, serves defaults in memory, and leaves the bytes alone for the operator to fix; healing a stray comma must not cost them their per-branch tuning. `rollover push` refuses on the same condition rather than rebuilding from the seed. A file that parses is never rewritten either, so operator edits persist, and anything it omits is deep-merged from the defaults. Tab strings are *generated* from the effective config, never hand-written.

**Sections:** `todos_meta` (rollover OFF — operational, never trimmed), `key_learnings_meta`, `sessions_meta`, `observations_meta` (all rollover ON).

### Two value flows

| Scenario | How tabs arrive |
|---|---|
| **Live branches** | `refresh_all_tabs()` walks the registry, renders tabs from config with per-branch overrides, writes them into `.trinity/` files. Wired after rollover, sync-lines, and push-templates. |
| **New branches** | Templates carry `{{TODOS_META}}`, `{{KEY_LEARNINGS_META}}`, `{{SESSIONS_META}}`, `{{OBSERVATIONS_META}}` placeholders. `spawn_pusher` propagates these (unresolved) from memory templates → spawn template sets. At branch creation, @spawn calls `render_all_meta_tabs()` to get rendered defaults and resolves the placeholders. |

### Public API

```python
from aipass.memory.apps.handlers.tracking.tab_renderer import render_all_meta_tabs

tabs = render_all_meta_tabs()
# → {"TODOS_META": "⟦ rollover OFF ...", "KEY_LEARNINGS_META": "⟦ rollover ON ...", ...}
```

Returns defaults (not per-branch overrides) — appropriate for template resolution at branch creation.

---

## Integration Points

**Depends on:**
- `prax` — logging via `get_system_logger()`
- `api` — API key for symbolic extraction (`get_api_key()`)
- `AIPASS_REGISTRY.json` — branch discovery for rollover scanning
- External `*_REGISTRY.json` — scanned via `AIPASS_CALLER_CWD`

**Provides to:**
- All branches — rollover archival when `.trinity/` files hit limits
- All branches — semantic search across archived memories
- All branches — `.trinity/` template distribution and sync

**ML dependencies (memory `.venv/` only):**
- `fastembed` — ONNX embeddings (model: `sentence-transformers/all-MiniLM-L6-v2`)
- `chromadb` — vector storage and semantic search
- `numpy`

---

## Quality

- **Tests:** 997 passed, 0 failures, 0 skips
- **Seedgo:** 100%. No new bypass rules were added to reach it.
- **Bypass registry:** 111 rules, all pointing at files that exist. Verified 2026-08-13 by pulling rules and re-running the checklist lane per file.

### Dead code, archived not deleted (2026-08-13)

Three handler files had no caller: `learnings/manager.py` (superseded by the
rollover extractor), `search/vector_search.py` and `storage/chroma.py` (both
in-process ChromaDB paths, superseded by `chroma_subprocess.py`). All three moved
to `.archive/unwired_handlers_20260813/` together with the 105 tests that covered
them — tests over unreachable code report coverage that does not exist.

`chroma.py` was **not** in the original finding; it surfaced only after
`vector_search.py`, its sole referencer, was archived. Two sibling files look
equally unreferenced and are load-bearing: `chroma_subprocess.py` and
`embed_subprocess.py` are executed as *scripts* by path in memory's `.venv`, never
imported. Disposition here is per-file and measured — repo-wide grep, dynamic
`importlib` check, and a path-invocation check — never "the checker said
unreferenced". See that directory's README for the full method.

---

## Known Issues

- `search` requires fastembed in memory `.venv/` — fails without it
- `drone @memory push` (and `rollover push`) overwrites every branch's `per_branch` limits with defaults, fleet-wide, with **no confirmation prompt**. Now that BAUD writes this config, an accidental `push` silently discards operator tuning. Open item — see APLAN-0010.
- Entry point imports two `monitor/` handlers directly for the built-in `watch` command, which the `encapsulation` standard flags (66% on `apps/memory.py`). Deliberately unshielded — the fix is to move `watch` into a module. Open item — see APLAN-0010.
- `pool.py` and `lint.py` score 85% on `introspection`: the checker only recognises a help guard whose `if` test contains a literal `"--help"`, so the shared `wants_help()` predicate is invisible to it. Both intercept help correctly (live-verified). Reported to @seedgo; not bypassed.

**Cleared 2026-08-13:** `rollover status` showing 0 branches did not reproduce (17 branches from two working directories). `memory_threshold_exceeded` appears nowhere in this branch's code — the previous note described @trigger's registry, not memory's.

---

*Last Updated: 2026-08-13 (full branch audit, APLAN-0010)*

---
[← Back to AIPass](../../../README.md)
