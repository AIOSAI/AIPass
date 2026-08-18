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
drone @memory rollover push                # ⚠ Reset ALL per_branch limits to defaults

drone @memory config                       # Introspection — the three config verbs
drone @memory config --help                # Full contract: types, bounds, semantics
drone @memory config get                   # Defaults + every branch that deviates
drone @memory config get @devpulse         # One branch's EFFECTIVE limits, marked
drone @memory config set @devpulse sessions 25   # Override one branch
drone @memory config set-default sessions 25     # Change the global default

drone @memory config get --json            # Machine surface — ONE JSON document, no Rich
drone @memory config get @devpulse --json  # `--json` rides in any slot on every config verb
drone @memory rollover push --json         # …and on push. `--help` still outranks it.

drone @memory search "query"               # Semantic search across all branch memories
drone @memory search "query" --branch X    # Filter by branch
drone @memory search "query" --n 10        # Limit results

drone @memory symbolic                     # PARKED 2026-08-14 — explains the ruling, then exits 1
                                           # Curated truth lives in Compass: drone @devpulse compass

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
│   ├── modules/                 # 10 modules
│   │   ├── governance.py        # Surfacing governance — re-exports from handlers
│   │   ├── health.py            # Branch health wrapper (entry-count + entry-size, read-only)
│   │   ├── lint.py              # Entry limit violation scanner (read-only)
│   │   ├── pool.py              # Pool vectorization + auto-process
│   │   ├── rollover.py          # Rollover orchestration, status, sync-lines
│   │   ├── search.py            # Semantic query routing
│   │   ├── symbolic.py          # PARKED 2026-08-14 — refusal stub (impl in .archive/)
│   │   ├── templates.py         # Template push, diff, status
│   │   ├── verify.py            # Plan vectorization check
│   │   └── watch.py             # Auto-rollover watcher (CLI routing only)
│   └── handlers/                # 14 handler groups
│       ├── archive/             # indexer.py
│       ├── cli/                 # help_flags.py — help-flag detection; json_flag.py — --json detection
│       ├── governance/          # engine.py — surfacing decision logic
│       ├── intake/              # plans_processor.py, pool_processor.py, auto_process.py
│       ├── json/                # json_handler.py, memory_files.py, entry_limits.py, lint_handler.py, config_loader.py
│       ├── monitor/             # detector.py, memory_watcher.py, watch_runner.py
│       ├── rollover/            # extractor.py, orchestrator.py
│       ├── schema/              # normalize.py
│       ├── search/              # query_executor.py
│       ├── storage/             # chroma_subprocess.py
│       ├── symbolic/            # PARKED 2026-08-14 — __init__ raises; impl in .archive/
│       ├── templates/           # pusher.py, differ.py, spawn_pusher.py
│       ├── tracking/            # line_counter.py, tab_renderer.py
│       ├── vector/              # embed_subprocess.py (embedder.py PARKED 2026-08-14)
│       └── central_writer.py
├── templates/                   # LOCAL.template.json, OBSERVATIONS.template.json
├── tests/                       # 1171 test functions — 1061 pass, 5 skip (parked symbolic tier)
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

### A correct refusal must not become a runaway log (2026-08-16)

@trigger raised `memory_extractor.log` CRITICAL at 634 lines/min. The safety valve was working
exactly as designed — it was refusing to archive entries an external branch had written at the
wrong end of its array — but it logged one `WARNING` **per refused entry**, each carrying the full
entry (~800 bytes). One pass over one file produced **97 warning lines in a single second**.

The valve's behaviour is unchanged; its volume is. One summary line per array per run names the
count and the reason; the per-entry detail moved to `DEBUG`, where it stays recoverable while
debugging without flooding a routine run.

The wall was also hiding the thing worth alarming on. When a file is over its limit and *nothing*
is archivable, the detector re-fires on it forever and refuses the same entries every run — a skip
loop. That case now says `NOTHING DRAINED` in words and names the two shapes that cause it: an
array that is not newest-first, or entries carrying no usable `number`. Same species as the
auto-compact skip loop behind DPLAN-0290 item 3: *a lane whose refusals are all correct can still
be a lane that never drains.*

### A help flag is never an instruction

Every module routes its help check through `handlers/cli/help_flags.wants_help()`, evaluated **before** any subcommand dispatch. Modules used to read `args[0]` only, so a flag in a later slot was discarded and the subcommand ran instead — `drone @memory rollover push --help` performed the fleet-wide `per_branch` reset it was being asked to describe.

A dashed flag (`--help`, `-h`) counts anywhere on the line. The bare word `help` counts anywhere only for modules whose subcommands take no free text (`rollover`, `templates`, `pool`, `lint`); for `search`, `symbolic` and `verify` it counts in the first slot only, so `drone @memory search rollover help` stays a three-word query.

`handlers/cli/json_flag.py` is the sibling handler for `--json`, and `wants_json()` is deliberately read *after* the help check for the same reason: `--help --json` is still a question, so it prints help and emits no payload. See [`--json` — the machine surface](#--json--the-machine-surface).

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

**Nothing hand-edits that file.** `drone @memory config` is the verb surface over rollover limits — see [Rollover limit config verbs](#rollover-limit-config-verbs).

**Source of truth:** `memory_json/custom_config/memory.config.json` — the operator-edited file *is* the runtime authority for rollover counts and entry char limits. `config_loader.DEFAULT_CONFIG` in code is the **regeneration seed**: when the file is genuinely *missing*, `load()` rebuilds it in full from those defaults so there is always a real file to edit. A file that *exists* but cannot be read — for **any** reason: bad syntax, bad bytes, bad permissions — is never written over (DPLAN-0206 red flag, `json_structure` v3.0.0) and never raises at the caller. `load()` logs an ERROR, serves defaults in memory, and leaves the bytes alone for the operator to fix; healing a stray comma must not cost them their per-branch tuning. `rollover push` refuses on the same condition rather than rebuilding from the seed. A file that parses is never rewritten either, so operator edits persist, and anything it omits is deep-merged from the defaults. Tab strings are *generated* from the effective config, never hand-written.

**Sections:** `todos_meta` (rollover OFF — operational, never trimmed), `key_learnings_meta`, `sessions_meta`, `observations_meta` (all rollover ON).

### One resolver, because the tab is an instruction

A tab is written **into** the agent's own memory file, where it reads as an instruction about that
agent's limits — so a tab naming a number the engine does not enforce is a lie in the one place an
agent trusts. `render_tab` therefore asks `config_loader.resolve_limits()` and never re-derives
anything; that is the same function behind `config get`, itself pinned against
`detector._should_rollover` with the engine as the test oracle.

Until 2026-08-16 it carried its own lookup and drifted two ways (found by @devpulse's wiring
research, both reproduced before fixing): it fell back per-branch-**dict** rather than
per-**file-key**, so a `per_branch` entry missing its `local` block ignored the defaults the engine
would have used; and it hard-defaulted a missing `count` to **15**, printing a limit that did not
exist. Where no limit is configured the tab now says `no entry limit configured` rather than naming
a number. `TestTabAgreesWithTheEngine` pins all of it, including a guard that fails if a `count`
fallback is ever reintroduced into this file.

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

## Rollover limit config verbs

`drone @memory config` is the verb surface over the rollover entry-count limits in
`memory.config.json`, so nothing hand-edits that file (DPLAN-0302). @api execs these verbs to serve
the BAUD settings panels, which makes **the CLI output and the refusal sentences the API contract** —
change them and something downstream breaks.

```bash
drone @memory config                             # Introspection — the three verbs
drone @memory config --help                      # Full usage
drone @memory config get                         # Defaults + every branch that deviates
drone @memory config get @devpulse               # One branch's EFFECTIVE limits, each marked
drone @memory config set @devpulse sessions 25   # Override one branch
drone @memory config set-default sessions 25     # Change the global default

drone @memory config get --json                  # Machine surface (see below)
drone @memory config get @devpulse --json
drone @memory config set @devpulse sessions 25 --json
drone @memory config set-default sessions 25 --json
drone @memory rollover push --json
```

**Settable types — exactly three:** `sessions`, `key_learnings`, `observations`. `auto_compact_cap`
is displayed read-only and preserved across writes, but is not settable in v1.

**Bounds:** `1 <= count <= 100`. Zero would roll over every entry immediately; past 100 rollover
stops being rollover. Unknown branches are refused against the registry — registry is truth.

**Effective limits resolve per FILE KEY, not per leaf key** — `config get` mirrors
`monitor/detector.py` `_should_rollover` exactly. If `per_branch[branch]["local"]` exists at all,
`defaults["local"]` is never consulted for that branch, so a per-branch entry carrying only
`sessions` leaves `key_learnings` with *no* limit rather than the default one. A deep merge here
would report a limit the engine does not enforce; `test_matches_the_detector_on_a_real_file` pins
the two together with the engine as the oracle.

**`[OVERRIDE]` is decided by VALUE**, not by provenance: all 17 branches carry a materialized
`per_branch` entry, so marking every one an override would be pure noise. A value is an override
when it differs from the corresponding default.

**`set-default` does not touch `per_branch`.** It changes `defaults` only — which means already
materialized branches keep their old numbers and start reporting as `[OVERRIDE]`. `rollover push`
remains the one explicit fleet-wide reset that brings every branch back to the defaults; its
semantics are unchanged. Writes go through `config_loader._write_config_file` (atomic tmp +
`os.replace`) and inherit the no-clobber contract: a config that exists but cannot be read is
refused, never rewritten.

**Apply timing:** limits take effect on the next rollover run (daemon tick) — there is no
immediate-kick verb in v1. The `*_meta` tab strings in `.trinity/` files are likewise refreshed by
the next rollover / sync-lines / push-templates run, so a freshly changed limit is live in the
engine before it is visible in the tab text.

### `--json` — the machine surface

`config get`, `config get @branch`, `config set`, `config set-default` and `rollover push` all take
`--json`. It exists because @api serves BAUD's memory-settings screens from these verbs and was
**reading the rendered human output** — every wording change was a silent breakage waiting to happen.

**`ok` is the machine success signal.** Refusals exit 0 branch-wide (that ruling is not this arc's to
change), so an exit code tells a caller nothing and the old alternative was inferring failure from
output *shape*. Every payload carries `ok` and `verb`; a refusal is `ok: false` plus `error` and
`suggestion` — **the exact sentences the human path prints**, because those are the published
contract. `suggestion` is always present, `null` where the refusal genuinely has no remedy line
(the unreadable-config refusal is the one such case).

**The flag rides in any slot** and is stripped before positional parsing, so
`config set @memory sessions 25 --json` parses identically to the same line without it.
**`--help` still outranks `--json`**: `config set @memory sessions 25 --help --json` prints help and
writes neither the config nor a payload — same rule that stopped `rollover push --help` from
performing the fleet-wide reset it was being asked to describe.

**Exactly one JSON document reaches stdout** — no panels, no banners, nothing else, and stderr stays
silent. The payload never travels through Rich: the shared console is width-80 with
`is_terminal=False`, so it hard-wraps a long document and a wrap landing inside a string value
inserts a newline *into* the value; it also parses markup, so a `[...]` token inside a string is
eaten as a style name. Both corruptions are invisible to a test that asserts on the string handed to
the printer, so `rollover._emit()` writes through `sys.stdout` and the tests assert on what reached
the pipe.

```jsonc
// config get --json
{"ok": true, "verb": "config get",
 "defaults": {"sessions": {"count": 15, "auto_compact_cap": 3},
              "key_learnings": {"count": 15}, "observations": {"count": 15}},
 "overrides": {"devpulse": {"sessions": {"count": 25, "default_count": 15,
                                         "is_override": true, "source": "per_branch"}}}}

// config get @memory --json
{"ok": true, "verb": "config get", "branch": "memory",
 "limits": {"sessions": {"count": 15, "default_count": 15, "is_override": false,
                         "source": "per_branch", "auto_compact_cap": 3},
            "key_learnings": {...}, "observations": {...}}}

// config set @memory sessions 25 --json
{"ok": true, "verb": "config set", "branch": "memory",
 "entry_type": "sessions", "count": 25, "pushed": false}

// config set-default sessions 25 --json
{"ok": true, "verb": "config set-default", "entry_type": "sessions", "count": 25, "pushed": false}

// rollover push --json
{"ok": true, "verb": "rollover push", "branches": 17}

// any refusal
{"ok": false, "verb": "config set", "error": "Unknown branch: @wizard",
 "suggestion": "Registry is truth — run 'drone systems' to list branches"}
```

`overrides` holds only the branches that deviate — `{}` when none do — and inside a branch only the
entry types that actually deviate, the same rule the rendered OVERRIDES block applies. `count` is
`null` when no limit is configured: the resolution is per FILE KEY, so a per-branch entry carrying
only `sessions` leaves `key_learnings` with *no* limit, and reporting `15` there would claim
enforcement that does not happen. `auto_compact_cap` appears only where one is set (`sessions`).

`pushed` is always `false` on both write verbs and states the delivery semantics in data:
`set-default` reaches **no** branch — `rollover push` is what delivers it. It is reported by
`config_loader`, not synthesized in the module, so the payload cannot drift from what the writer did.

---

## Integration Points

**Depends on:**
- `prax` — logging via `get_system_logger()`
- `api` — API key for symbolic extraction (`get_api_key()`) — dormant while the symbolic tier is parked
- `AIPASS_REGISTRY.json` — branch discovery for rollover scanning
- External `*_REGISTRY.json` — scanned via `AIPASS_CALLER_CWD`

**Provides to:**
- All branches — rollover archival when `.trinity/` files hit limits
- All branches — semantic search across archived memories
- All branches — `.trinity/` template distribution and sync
- `@daemon` — branch health check (entry-count rollover status + entry-size cap violations) via `apps/modules/health.py`'s `get_branch_health(branch_name)`, since seedgo blocks handler-to-other-branch-handler imports and daemon's own handlers cannot reach `handlers/monitor/detector.py` / `handlers/json/lint_handler.py` directly

**ML dependencies (memory `.venv/` only):**
- `fastembed` — ONNX embeddings (model: `sentence-transformers/all-MiniLM-L6-v2`)
- `chromadb` — vector storage and semantic search
- `numpy`

---

## Quality

- **Tests:** 1081 passed, 0 failures, 5 skipped (2026-08-17). The 5 skips are the parked symbolic-fragments tier and its embedder — see `.archive/parked_symbolic_20260814/`. A sixth skip appears on a fresh clone: the health test that reads this branch's real `.trinity/` files, which are gitignored (see below).
- **Seedgo:** 100%. The `--json` lane added exactly one rule (`json_flag.py` / `json_structure`), a verbatim mirror of the `help_flags.py` rule for its sibling predicate. The `cli` bypass it first appeared to need was **not** taken: `console.print(payload, markup=False, soft_wrap=True, highlight=False)` emits byte-exact JSON through the shared console, so no Rich bypass is required to serve a machine.
- **Bypass registry:** 113 rules, all pointing at files that exist. Verified 2026-08-13 by pulling rules and re-running the checklist lane per file.

### A suite that needs this machine is not a suite (2026-08-17)

PR #734 ran this branch's tests on a fresh ubuntu runner for the first time (an
unrelated `httpx` fix stopped killing whole suites at collection). 156 of the
repo's 165 CI failures were mine, identical on 3.11/3.12/3.13 — deterministic,
not flake. Every one of them was the suite depending on state that exists only
where AIPass has already run.

Four species, all fixed by making the fixtures mint their own state:

1. **The fixture copied the live operator config.** `memory.config.json` lives
   under `memory_json/custom_config/` and is gitignored — present on every dev
   machine, absent on a clone. 77 setup errors. The config is now built from
   `config_loader.DEFAULT_CONFIG` (the in-tree regeneration seed) and written by
   the real `_write_config_file`, so the fixture cannot drift from the shape the
   engine produces, and a hand-formatted copy cannot make the byte-identity
   tests assert against the test file's formatting instead of the writer's.
2. **The verbs resolve branches through `AIPASS_REGISTRY.json`**, also
   machine-managed and gitignored. Every branch-addressed test got
   `Unknown branch: @memory`. The registry is now minted in `tmp_path`, and
   **both** doors are shut: `detector._REPO_ROOT` *and*
   `_find_caller_registries`, which otherwise walks up from the caller's CWD and
   quietly finds the fleet's own registry whenever the suite runs inside a
   checkout. A test pins that the reachable registry holds exactly the three
   minted branches.
3. **Rich width is an environment variable.** Refusal sentences carry a tmp
   path; under an xdist worker that path is long enough that an 80-column
   console folds a newline *into* the sentence. Green on a wide terminal, red on
   a runner with none. `COLUMNS` was the old defence and it is still the
   environment deciding — both shared consoles are now pinned via `_width`
   (not the public `width` setter, which monkeypatch would restore by writing
   back the number it read, leaving the shared object pinned for the next
   suite). Long path assertions additionally compare whitespace-free, the only
   form that survives a fold landing mid-token. Removing both defences at
   `COLUMNS=40` turns 33 tests red — 29 more than CI had reached.
4. **A MagicMock standing in for a package has no `__path__`.**
   `test_rollover.py` mocks `handlers.cli` and registered only `help_flags`; a
   `json_flag` import added on 08-16 then resolved out of `sys.modules` **by
   accident**, because some earlier test in the same process had imported the
   real one. On a worker running that file first, all 18 tests died at import.
   Now both submodules are imported and registered, and a test reads
   `rollover.py`'s own import lines so the *next* submodule added to that
   package fails here instead of on a runner three days later.

Verified three ways: the branch suite as usual, the repo-root
`-n auto --dist loadscope` invocation, and a fresh-runner simulation — a pytest
plugin that makes `os.stat` and `open()` raise `FileNotFoundError` for exactly
the gitignored paths a clone does not carry, so nothing on this machine is moved
aside. Under the strongest combination (fresh-clone simulation, repo root, 8
workers, loadscope): 1080 passed, 6 skipped. The sixth skip is the health test
that deliberately reads real `.trinity/` files, and it says so out loud — a skip
that names its reason is honest; a pass that needed this machine is not.

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
