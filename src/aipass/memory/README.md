[← Back to AIPass](../../../README.md)

# MEMORY

**Central memory archive — vector search, rollover, and memory management for all AIPass branches.**

`drone @memory <command>` | Module: `aipass.memory` | Created: 2026-03-07

---

## Quick Start

```bash
drone @memory push --dry-run            # THE TRINITY PUSH — report what would change, write nothing
drone @memory search "query"            # Search archived memories across all branches
drone @memory rollover status           # Show what needs archiving per branch
drone @memory rollover check            # Dry run — preview pending rollovers
drone @memory lint run                  # Audit .trinity entries for limit violations
drone @memory watch                     # Auto-rollover watcher (Ctrl+C to stop)
```

---

## Commands

```bash
drone @memory rollover run                 # Execute rollover for files over limits
drone @memory rollover status              # Show per-branch rollover statistics
drone @memory rollover check               # Dry run — what needs rollover
drone @memory rollover sync-lines          # Report line counts + refresh state-tabs (counts are
                                           #   not persisted — see Line counts are reported, not stored)
drone @memory rollover push                # ⚠ Reset ALL per_branch limits to defaults (config only)

drone @memory push --dry-run               # Trinity push, FLEET dry-run — the report Patrick reads
drone @memory push --branch @canary        # Trinity push, one branch
drone @memory push --branch @canary --dry-run
drone @memory push --confirm               # FLEET push — refused without the flag

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
drone @memory search "query" --type local  # Filter by memory type (local, observations)
drone @memory search "query" --n 10        # Limit results shown

drone @memory symbolic                     # PARKED 2026-08-14 — bare prints the ruling, exits 0
drone @memory symbolic <subcommand>        # …a named subcommand is refused, exits 1
                                           # Curated truth lives in Compass: drone @devpulse compass

drone @memory templates push-templates     # ⚠ Writes against a dead pre-.trinity layout — see below
drone @memory templates diff-templates     # ⚠ Same lane — reports phantom diffs, not real drift
drone @memory templates template-status    # Reads .template_version.json (last push: 2026-06-25)

drone @memory pool status                  # Pool file count, config, vector stats
drone @memory pool process                 # Vectorize pool files + check rollover

drone @memory lint run                     # Audit .trinity entries for over-limit violations (read-only)
drone @memory lint @devpulse               # Lint a specific branch
drone @memory lint                         # Bare = introspection banner, NOT a scan

drone @memory verify FPLAN-XXXX            # Check if plan is vectorized in ChromaDB
drone @memory watch                        # Auto-rollover watcher daemon (Ctrl+C to stop)
```

---

## Architecture

```
memory/
├── apps/
│   ├── memory.py                # Entry point — auto-discovers modules
│   ├── modules/                 # 11 modules
│   │   ├── governance.py        # Surfacing governance — re-exports from handlers
│   │   ├── health.py            # Branch health wrapper (entry-count + entry-size, read-only)
│   │   ├── lint.py              # Entry limit violation scanner (read-only)
│   │   ├── pool.py              # Pool vectorization + auto-process
│   │   ├── push.py              # The trinity push lane (dry-run + gated execute)
│   │   ├── rollover.py          # Rollover orchestration, status, sync-lines
│   │   ├── search.py            # Semantic query routing
│   │   ├── symbolic.py          # PARKED 2026-08-14 — refusal stub (impl in tests/parked/)
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
│       ├── symbolic/            # PARKED 2026-08-14 — __init__ raises; impl in tests/parked/
│       ├── templates/           # trinity_push.py, push_store.py, push_report.py,
│       │                        #   receipt.py, pusher.py, differ.py, spawn_pusher.py
│       ├── tracking/            # line_counter.py, tab_renderer.py
│       ├── vector/              # embed_subprocess.py (embedder.py PARKED 2026-08-14)
│       └── central_writer.py
├── templates/                   # LOCAL.template.json, OBSERVATIONS.template.json
├── tests/                       # 1302 test functions on disk — 1201 collected, 1201 pass, 5 skip
├── .chroma/                     # ChromaDB vector store
└── memory_json/                 # Operation logs + custom_config/memory.config.json
```

### Rollover Pipeline

```
detector.check_all_branches()        # scan AIPASS_REGISTRY.json + external registries
→ _should_rollover(file)             # ENTRY COUNTS ONLY — no line-count trigger, no 600 fallback
                                     # len(sessions) >= count (default 15), auto-compact lane
                                     # against auto_compact_cap (3), key_learnings, observations
                                     # per_branch[branch][file_type] → defaults[file_type]
                                     # no limit either place = CONFIG GAP, logged, skipped
                                     # unparseable file = logged, skipped — never a fallback
→ orchestrator.execute_rollover()
  → create_rollover_backup()         # safety copy to branch/.backup/
  → extract_items()                  # v2: max(excess, 1) oldest entries
  → embed via subprocess             # fastembed (ONNX) — see Subprocess Isolation re: venv
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

### `vectorize_and_store` — text in, this branch owns the model (1.4.0, 2026-08-23)

`chroma_subprocess.py` gained a **text-in** operation so another branch can archive its own content
without ever choosing an embedding model:

```
vectorize_and_store(branch, memory_type, texts, metadatas, db_path=None)
    → embeds via embed_subprocess.py, stores through the existing _store_vectors path
    → content-hash IDs, upsert, dedup — same guarantees as rollover
    → validates: branch and memory_type required, len(metadatas) == len(texts)
    → timeout max(30, len(texts) * 3)s; always returns an explicit success flag
```

Caller today: `@ai_mail`'s `handlers/email/purge.py` — it sends sent/deleted mail as text before
deleting the originals (`ai_mail_email_sent`, `ai_mail_email_deleted`). The model choice stays here
because consistency across a collection is this branch's job, not the caller's.

**Why it exists.** For four months `purge.py` called an operation that did not exist. The handler
answered `success: false` on stdout and **exited 0**; the caller checked only the return code, so
purge reported mail vectorized and deleted it. 55 purges across 11 branches into a collection that
had never been created. An unknown operation that exits 0 is a lie — the operation now exists, and
the caller reads the payload.

### Anchored plan-ID matching (1.3.0)

`_source_matches()` backs `drone @memory verify`. A plain `label in source_file` had no boundary
check, so `DPLAN-0012` matched inside `TDPLAN-0012` — `verify DPLAN-0012` reported 27 chunks live
that all belonged to a different plan. A hit now counts only at the string start or after a
non-alphanumeric boundary, and scanning continues past a rejected hit so a real match later in the
same string (`TDPLAN-0012_supersedes_DPLAN-0012`) is still found. The same predicate is shared by
`_delete_by_source`, which **deletes** — that call site was the reason to fix it at the source.

### The templates lane targets a layout no branch uses (2026-08-25)

`push-templates`, `diff-templates` and `template-status` operate against a **pre-`.trinity`**
naming convention. `pusher._find_memory_files()` (`handlers/templates/pusher.py:309-322`) and
`differ` (`differ.py:236,275`) scan the **branch root** and match
`f.name.endswith(".local.json")` / `.observations.json`. The live layout is
`<branch>/.trinity/local.json` and `<branch>/.trinity/observations.json` — a file named
`local.json` does not end with `.local.json`, and it is not in the directory being scanned.
**Zero real matches are possible.**

Measured live: `diff-templates` reports "16 branches have template differences" and not one of them
is a `.trinity/` file — the only thing it ever matches is `CLOSED_PLANS.local.json`, an unrelated
archive file that ends in the right suffix by coincidence. It has never seen an
`observations.json`. `template-status` reads `.template_version.json`, whose `last_push` is
2026-06-25 — a date only a push down this same dead lane could move.

**The one part that is current:** `spawn_pusher.py` propagates memory's canonical templates into
@spawn's template sets at `spawn/templates/*/.trinity/{local,observations}.json` — the real layout,
verified live. It runs as a side effect of `push-templates` (`modules/templates.py:127-135`), so
that half works while the branch-facing half does not.

A rebuild against the current layout is DPLAN-0318 (@devpulse). **Not fixed here** — this section
documents the defect, it does not repair it.

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

## The trinity standard (DPLAN-0318, built 2026-08-25)

The standard has one rule: **numbers come from `memory.config.json`, prose comes from
`memory/templates/*.template.json`, entry content comes from the agent** — and nothing holds a fact
it can derive. The contract lives in `@devpulse dropbox/trinity_pattern.md`; this section is what
the code now does.

### An unmeasurable field is a violation, not a zero

`entry_limits._extract_text()` returned `""` for anything that was not a string. A `note` holding a
list of dicts therefore measured **0 chars** and cleared a 300-char cap — and `lint_handler` ran
`len()` on that same list, counting **elements**. Two independent gates agreeing is exactly what made
the drift look verified. Both now refuse what they cannot measure:

```
observations[0]: UNMEASURABLE — list, expected str (cap 300 chars cannot be applied)
```

The refusal payload keeps `length`/`cap`/`over_by` as ints (the @hooks `edit_gate` formats them with
`%d`) and adds `reason: "unmeasurable"` and `found_type`. **Unchanged legacy entries still pass** —
`enforce: true` is live and 9 branches carry list-shaped notes; only a *new or edited* unmeasurable
entry is refused, so the fix does not brick a fleet it was meant to protect.

#### …and a field it cannot FIND is the same species (fixed 2026-08-26)

The first pass fixed the wrong-type case and left the **missing-field** case still answering `""`.
A `key_learning` carrying its text under `learning` where the config says `value` therefore measured
as zero characters and cleared a 200-char cap — @hooks proved it live against their own `local.json`
the night 1.3.0 shipped: a 500-char entry, cap 200, **zero violations**. A renamed field is not an
absent text; it is a text the reader cannot find. `_extract_text` now returns `None` for it, and the
violation carries its own reason because the repair differs:

| `reason` | Means | What the agent does |
|---|---|---|
| `missing_field` | the canonical key is absent (`field` names it) | rename the key |
| `unmeasurable` | the key is there holding a non-string (`found_type` names it) | fix the shape |

`""` stays a legitimate answer for a field that is present and empty. Measured across the live fleet
the day of the fix: **42 missing-field entries on 3 branches** (@hooks, @ai_mail, @api — all
`key_learnings`, all the `learning` shape), previously reported as compliant by both gates.

**Lint's boundary moved with it.** `lint` used to skip an entry whose canonical field was absent, on
the reading that shape belongs to the trinity checker rather than to a char-cap scanner. That cost
more than it bought: the write gate refuses those entries, so a branch could be told it was compliant
and then be blocked on its next write for a shape lint had already seen. `run_lint` now names them.

### keep 15 now keeps 15

`extractor._extract_tail_excess` floored the drain at `max(len - limit, 1)`, so a file sitting at
exactly the limit lost one entry every run and every branch settled permanently at **14**. Fixing the
extractor alone would have stranded `detector._should_rollover`, which fired at `>=` — a fleet-wide
`NOTHING DRAINED` skip loop. Both thresholds moved together, and
`test_detector_and_extractor_never_disagree` sweeps the boundary so they cannot drift apart again.

### One resolver for char caps, too

`render_tab` read `entry_types` straight off the config and never consulted
`entry_limits.per_branch`, while the write gate (`load_entry_limits`) always did.
The first branch to take a per-branch char-cap override would have been *told* one number in its
`*_meta` line and *measured* against another — and would have failed @seedgo's Meta-lines rule
permanently, because the renderer keeps rewriting the line the checker keeps rejecting. Found by
@seedgo's trinity checker from the other side of the same contract, latent only because that map is
empty today. `entry_limits.resolve_entry_types()` is now the single implementation both call, and
`rollover.per_branch` (which `render_tab` already honoured) is no longer the odd one out.

### The renderer reads the template

`tab_renderer` used to carry the `_usage` text as `_CORRECTED_USAGE_*` string constants — a second
copy of prose the templates own. The constants are retired: `template_usage()` and
`template_semantics()` read the gold-source templates, and a missing or malformed template **raises**
rather than falling back to a stale string. `refresh_all_tabs()` now replaces only the `⟦ … ⟧` tab
portion of a `*_meta` value and preserves the template-owned sentence beside it.

### `status.health` is deleted, not computed

Patrick's ruling: the field had no consumer, read `healthy` hardcoded since 2025-11, and stored a
fact that is derivable — a second source of truth waiting to go stale. Every writer is gone
(`memory_files.update_metadata()` removed, the extractor's post-drain stamper removed,
`normalize.py` no longer relocates a root `status` or adds `last_health_check`), and the
template-conformance pass strips the orphan block from files that still carry it. Health is a
checker-computed report value now, never a stamp in the file. Source-scan tests pin that the writers
stay gone.

### Line counts are reported, not stored

`line_counter.update_line_count()` is now **read-only**: its only write was the health stamp, and the
line count itself was never persisted. `rollover sync-lines` therefore reports counts rather than
syncing them — the verb still writes, but only through the state-tab refresh it triggers. The name is
now wrong for what it does; flagged, not silently retired.

### `.template_version.json` — the per-branch receipt

```json
{
  "template_versions": {"local": "3.0.0", "observations": "3.0.0"},
  "stamped": "2026-08-25T23:37:05",
  "stamped_by": "memory push",
  "config_rendered": "2026-08-25T23:37:05"
}
```

`template_versions` reports each template's **`document_metadata.schema_version`**, not its
`version` — the two templates disagree on `version` (LOCAL 2.0.0, OBSERVATIONS 1.0.0) and agree on
`schema_version` (3.0.0), and the receipt reports the *structure* a branch was stamped with. Pinned
by a test, and confirmed to @seedgo whose checker compares against the same field.

Written by `handlers/templates/receipt.py`. Only three lanes may stamp it — `memory push`,
`spawn birth`, `reset` — and any other value is refused. The push lane stamps **only branches it
actually changed**; a tab refresh calls `bump_config_rendered()`, which **refuses to create** a
receipt that does not exist, because the renderer has no authority to claim a template version it
never wrote. @spawn's birth lane adopts the writer separately — this build ships the callable and
does not touch spawn.

---

## The trinity push (DPLAN-0318, built 2026-08-27)

`drone @memory push` is the one lane that brings a branch's `.trinity/` files to the trinity
standard. Per branch it does exactly three things:

1. **Re-renders the machine frame.** `document_metadata` is rebuilt as a **CLOSED set** — any key
   the standard does not name is pruned, `status` with it; `managed_by` takes the exact branch
   **directory** name (what @seedgo's checker compares against — the registry's own `name` field
   disagrees in casing for six citizens); `_usage` and the `guidelines` block come **verbatim** from
   the gold-source templates; all four `*_meta` lines are re-composed from config + template prose.
2. **Prunes every non-canonical entry — except a todo.** See the law below, and *Todos are never
   archived* under it.
3. **Writes one canonical session note** in the pruned branch's own `sessions[]` saying where its
   entries went, how to get them back, and which todos were left behind for it to reshape. Skipped
   entirely when nothing was pruned.

Then it stamps `.template_version.json` via `receipt.py` with `stamped_by: "memory push"` — the
push-lane wiring the receipt build left pending.

### The law: vectorize → VERIFY → prune

Pruning is a safety feature, not a deletion. Each entry is serialized **verbatim** (the stored
document *is* the entry as JSON, never a summary), embedded into both the branch's local `.chroma`
and the global store, and then **read back by ID and compared byte-for-byte** to what was sent. Only
then is it removed from the live file.

**If verification fails for any entry, NOTHING is pruned from that branch** and the file is left
exactly as found. A store call's own `success` flag is the writer's opinion; the read-back is the
evidence. This is the same law `vectorize_and_store` was built for after @ai_mail deleted four
months of mail on the strength of an unread success flag — `get_by_ids` (chroma_subprocess 1.5.0)
exists to make the second half of it possible, because `get_by_source` matches a metadata substring
and caps at `n_results`, so a partial hit reads like a full one.

`tests/test_trinity_push.py::TestNothingIsPrunedWithoutProof` pins all six failure shapes: the store
refuses, the vector never lands, it lands corrupted, one of several goes missing, the read-back call
itself fails, and a second destination fails after the first succeeded. Absent and corrupted get
**different** refusal sentences, because the repair differs — the lesson from `missing_field` vs
`unmeasurable`.

### What counts as non-canonical

Shape **and** size, because they are two different scan groups in the standard and an entry can pass
one while failing the other. A perfectly-shaped 315-char session summary under a 300 cap is
canonical to look at and still leaves its branch short of 100 — and it is exactly the entry @hooks'
`edit_gate` grandfathers today. Caps come from `entry_limits.resolve_entry_types`, the same resolver
the write gate and the tab renderer use, so the push cannot prune on a number the gate does not
enforce.

The note the push writes is itself measured against that same gate before it is written. A push that
left behind a note the standard would refuse would have re-introduced, in its own hand, the exact
violation it came to remove.

### Todos are never archived (1.1.0, 2026-08-27)

`todos` are **exempt from the prune lane**, and the exemption is not a softening of the standard — it
*is* the standard, which says in its own words that todos never roll.

Sessions, key_learnings and observations are **records**, and a record in a vector is still a record:
`drone @memory search` returns it the moment anyone wants it. A todo is a **debt**, and a debt only
works if it resurfaces **unbidden** on the next load. Vectorized, it never does — the agent opens a
clean file, sees nothing owed, and silently forgets what it promised. For this one container,
archiving *is* losing.

Found by @spawn after the fleet push: its three open todos were `{task, added}` shaped, so the shape
rule archived them like everything else. The archive half worked perfectly — @spawn verified verbatim
recall before restoring them by hand — which is exactly what made it dangerous: an agent that had not
gone looking would never have known.

So a non-canonical todo is **REPORTED for reshape-in-place**:

- kept in the file **byte-identical**, never vectorized, never removed;
- named **per entry, uncapped** in the push report (`~ todos[0] #? : missing 'priority'; …`) — unlike
  prune samples, which are capped at 6 because the vector store holds the full entry; this is the only
  place the left-behind work is named;
- **counted in the in-file note**, with the entry numbers enumerated when they fit the note's own cap
  and stepped down to a bare count when they do not;
- rolled up in the report totals as `TODOS LEFT TO RESHAPE: N across M branch(es)`.

**Reshaping it mechanically was considered and refused.** The canonical shape needs `priority` and
`status`, and a machine that invents someone else's priority has not preserved their open work — it has
rewritten it. That is the same rule this module already applies to everything it archives.

**The note is minted only when something was actually archived.** A branch whose only finding is a
drifted todo lost nothing and had nothing moved — and since that todo stays non-canonical until its
agent reshapes it, noting it on every run would stack a fresh session entry on every push and break the
idempotency the canary proved. The report says it every time; the file says it once, alongside the
entries that did move.

**The cost is stated, not hidden:** a branch carrying a drifted todo does not reach trinity 100 until
its own agent reshapes it. That is the correct trade — a debt visible and non-canonical beats a debt
canonical and gone.

### Scope

`--branch` pushes one branch. Fleet mode covers the DPLAN scope: the **18** active citizens in
`AIPASS_REGISTRY.json` plus the **4** named resident projects (`baud`, `earmark`, `finch`,
`aipass_site`) — **22** branches.

The resident list is a **named constant, never a glob** over `projects/`. A glob would sweep in
`marketstand`, which is marked `active` inside a directory literally named `(on _hold)`. Verified
live: `detector._read_registry()` reaches only 19 of the 22 (the core 18 plus `baud`, the one
resident registry that happens to sit in `known_registries.json`), so the push resolves its own
scope rather than inheriting that gap.

A branch whose files cannot be read is **refused by name**, never skipped — and refused *whole*, so
a branch never ends up with one canonical file and one drifted one.

### The two gates

- **`--dry-run` writes nothing anywhere** — not the memory files, not the vector store, not the
  receipts. Its report is the artifact, written to `artifacts/push_reports/` and echoed to the
  terminal.
- **A fleet write requires `--confirm`.** Encoding the gate as a flag rather than as an operator's
  memory is the difference between a rule and a hope; this branch has already demonstrated the
  alternative (see the `push` alias note under Known Issues, now cleared).

### Measured, 2026-08-27

Live end-to-end on @canary, the sanctioned guinea pig: **15 entries archived and pruned, 25 carried
over, trinity 77 → 100**, receipt stamped, note written. The promise in that note was then tested
rather than assumed — `drone @memory search "…" --branch canary` returns pruned key_learning **#30
verbatim**. Re-running the push prunes 0 and holds 100: the lane is idempotent.

Fleet dry-run: **366 entries to archive, 560 carry over, 22 branches, 0 refused, 0 errors.**
Projected by applying the push into a temp copy of each branch's real `.trinity/` and scoring it with
@seedgo's own checker: **fleet average 70.1 → 97.2**.

### Measured again, 2026-08-27 (the todo exemption)

The exemption was proven by replaying @spawn's real incident: its three archived todos recovered
**verbatim from the vectors they were pruned into**, re-inserted into a temp copy of @spawn's live
`.trinity/`, plus one drifted session so the archive lane fired in the same run. Through the real
handler and the real `push_store` against a throwaway `.chroma`: **1 session pruned, 3 todos left in
place byte-identical, note written at 266/300 chars naming all three, report roll-call correct.**
Nothing under `src/aipass/spawn/` was touched.

Fleet dry-run after the change: **0 entries to archive, 582 carry over, 22 branches, 0 todos to
reshape** — the fleet is already canonical, so the fix protects future pushes; the sweep is what
healed today's.

The one remaining blocker is the **File set** group, and it is **not push scope**: 16 branches carry
stray files in `.trinity/` (mostly `*.pre_v3_backup` migration leftovers, plus `daemon/.recovery`,
`seedgo/STATUS.local.md` and devpulse's `watchdog_active.json` pair) and 6 have no
`.trinity/README.md`. Deleting another citizen's files and authoring README prose are both outside
the three-part mandate, so the push **reports** them and leaves them alone. They need a ruling; with
it executed the fleet reaches 100 across the board.

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

**`[OVERRIDE]` is decided by VALUE**, not by provenance. `rollover push` materializes a
`per_branch` entry for every active branch in the registry, so once it has run, provenance marks
every branch an override — pure noise. A value is an override when it differs from the
corresponding default.

*Live state, measured 2026-08-25:* `per_branch` is **empty** in both `rollover` and `entry_limits`,
so every branch resolves from `defaults` and `config get @branch` reports
`source: "defaults"`. The registry carries **18** active branches, which is the number
`rollover push` materializes and reports.

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
{"ok": true, "verb": "rollover push", "branches": 18}   // = active branches in AIPASS_REGISTRY.json

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
- ~~`api`~~ — **no longer a dependency.** `get_api_key()` was the symbolic tier's, and it left the
  tree with it on 2026-08-14. Verified 2026-08-25: zero references anywhere under `apps/`; the only
  survivors are in `tests/parked/` and in the skipped `test_symbolic_extras.py`
- `AIPASS_REGISTRY.json` — branch discovery for rollover scanning
- External `*_REGISTRY.json` — scanned via `AIPASS_CALLER_CWD`

**Provides to:**
- All branches — rollover archival when `.trinity/` files hit limits
- All branches — semantic search across archived memories
- All branches — `.trinity/` template distribution and sync
- `@daemon` — branch health check (entry-count rollover status + entry-size cap violations) via `apps/modules/health.py`'s `get_branch_health(branch_name)`, since seedgo blocks handler-to-other-branch-handler imports and daemon's own handlers cannot reach `handlers/monitor/detector.py` / `handlers/json/lint_handler.py` directly

**ML dependencies (in whichever venv `_get_memory_python()` resolves to — repo root today):**
- `fastembed` — ONNX embeddings (model: `sentence-transformers/all-MiniLM-L6-v2`)
- `chromadb` — vector storage and semantic search
- `numpy`

---

## Quality

- **Tests:** 1201 passed, 0 failures, 5 skipped, 16.0s (re-run 2026-08-27 after the trinity push build, from the branch dir AND the repo root). The push added 69 of those in `tests/test_trinity_push.py`, and 10 mutations were run against the lane — all 10 bite, each on its own tests. The first pass had one survivor (`_verify_ingestion` ignoring absent vectors, caught anyway by the content comparison that follows); rather than accept a provably-equivalent survivor, two tests were added pinning that an ABSENT vector and a CORRUPTED one produce different refusal sentences, and the mutation now bites. The 5 skips are the parked symbolic-fragments tier and its embedder — see `tests/parked/symbolic_20260814/` — and each names its reason in the skip message. A sixth skip appears on a fresh clone: the health test that reads this branch's real `.trinity/` files, which are gitignored (`tests/test_health.py:404`, "no live .trinity files in this checkout").
  *Two different numbers, deliberately:* `grep def test_` over `tests/*.py` finds **1302 test functions** on disk. 237 of those live in 5 modules that call `pytest.skip(allow_module_level=True)` at import, so pytest never collects them individually (they surface as the 5 skips). The rest expand through `@pytest.mark.parametrize` into **1201** collected cases, and all 1201 pass. Both numbers are true and neither substitutes for the other — seedgo's `readme` rule counts the 1302 on disk, a green board counts the 1201 that execute.
- **Seedgo:** 100% across every rule including the new `trinity` standard, 0 type errors (re-run 2026-08-27 after the push build). The four findings the first audit raised on the new files were fixed rather than bypassed: report rendering moved out of the module into `handlers/templates/push_report.py` (modules do no direct file I/O), `json_handler` logging added to both new handlers, and the `unused_function` hit on `is_canonical()` was cleared by giving it a real caller — the guard that measures the push's own session note against the same gate everything else was pruned against. The `--json` lane added exactly one rule (`json_flag.py` / `json_structure`), a verbatim mirror of the `help_flags.py` rule for its sibling predicate. The `cli` bypass it first appeared to need was **not** taken: `console.print(payload, markup=False, soft_wrap=True, highlight=False)` emits byte-exact JSON through the shared console, so no Rich bypass is required to serve a machine.
- **Bypass registry:** **114** rules in `.seedgo/bypass.json` (`last_updated: 2026-08-16`). The old claim here — "113 rules, all pointing at files that exist", verified 2026-08-13 — is **stale on both counts**: re-measured 2026-08-25, **37 of the 114 point at 10 files that are no longer in the tree**, all of them parked on 08-14 / 08-18 (`symbolic/*.py`, `vector/embedder.py`, `storage/chroma.py`, `search/vector_search.py`, `learnings/manager.py`). One duplicate `(file, standard)` pair as well. The rules are inert — a bypass for an absent file suppresses nothing — but the registry is now a record of a tree that stopped existing. Cleanup is an open item, not fixed tonight.

### A park in the disposal zone is not a park (2026-08-18)

Patrick's ruling that night, fleet-wide: `.archive/` is always ignored, no
exceptions, and it is his disposal zone — cleaned without warning. Both of this
branch's parks lived there. `test_symbolic_parked.py` had nine pins asserting the
parked implementation was still on disk, and they had been green on every dev
machine and red on every fresh clone since the doctrine landed: 11 failures per
CI run, `missing from the park: handlers/chroma_client.py`.

The pins were not wrong about preservation. They were asking a question that
cannot detect the failure: **asserting a file exists cannot tell a tracked home
from a local one.** Both parks moved to `tests/parked/`, byte-identical (verified
by sha256 before and after), and a new pin asserts the *home* instead — no
component of the park's path may be `.archive`.

Two things the move surfaced that the ruling did not mention:

- **`(disabled)` does not stop pytest.** The suffix is the house convention for
  code that is present but must not run, and it does disable dotted-path import
  — `test_storage(disabled)` is not a valid identifier. But
  `test_storage(disabled).py` still matches pytest's default `test_*.py` glob,
  and four of the archived files in `unwired_handlers_20260813/` are the tests
  that covered handlers which left the tree. First landing: **66 failed, 39
  errors**, all of them parked tests running against absent code. The barrier is
  a `conftest.py` in `tests/parked/` — deliberately *not* a `norecursedirs` line
  in this branch's `pytest.ini`, because CI runs the whole repo from its root
  where the root config is in force and this branch's ini is never read. A
  conftest is loaded from its own directory whatever the rootdir, which is the
  only property that holds on the lane that broke. Pinned by a real collection
  run in a subprocess; emptying the conftest turns it red.
- **"Archived not deleted" was quietly false for the second park.** Nothing
  pinned `unwired_handlers_20260813/`, so CI never complained — but the README
  claim that 105 tests were preserved alongside their code was true only of this
  machine. It moved too.

The `recovery_*` snapshots stay in `.archive/`. They are not parks and are meant
to be disposable, which is what that directory is now for.

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
to `tests/parked/unwired_handlers_20260813/` together with the 105 tests that covered
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

- `search` requires `fastembed` in the venv `_get_memory_python()` resolves to — fails without it
- **The templates push/diff lane targets a dead pre-`.trinity` layout** and cannot match any live memory file — see [the section above](#the-templates-lane-targets-a-layout-no-branch-uses-2026-08-25). Rebuild tracked in DPLAN-0318 (@devpulse).
- **`.seedgo/bypass.json` holds 37 rules for 10 files that no longer exist** (parked 08-14 / 08-18) plus one duplicate `(file, standard)` pair. Inert, but the registry no longer describes the tree.
- **`rollover sync-lines` no longer syncs anything by that name** — `line_counter.update_line_count()` is read-only since the health stamp was removed (2026-08-25), and the line count itself was never persisted. The verb still writes, but only via the state-tab refresh it triggers. Renaming or retiring it is an open call, flagged rather than taken.
- **The receipt writer's `spawn birth` lane is still unwired.** `handlers/templates/receipt.py` now stamps for real from the trinity push (`stamped_by: "memory push"`, verified live on @canary), and a tab refresh bumps `config_rendered`. `spawn birth` adopts the writer separately — not built here.
- **16 branches carry stray files in `.trinity/` and 6 have no `.trinity/README.md`** — the only thing keeping the post-push fleet off 100 (File set group). Both are outside the push's mandate: it reports them per branch in the dry-run and never touches them. Needs a ruling.
- **`rollover sync-lines` still refreshes tabs fleet-wide, deliberately.** The scoping added on 2026-08-27 covers `rollover run`, the lane a PreCompact hook fires unattended. `sync-lines` is an explicit operator verb whose whole job is every branch, so it keeps the unscoped call — named here so the asymmetry is a decision on the record rather than an oversight.
- **`_read_registry()` reaches 19 of the fleet's 22 branches** — the core 18 plus `baud`, because `baud`'s registry is the one resident entry in `known_registries.json`. `earmark`, `finch` and `aipass_site` are invisible to rollover, lint and health for the same reason. The trinity push resolves its own scope and is unaffected; every other lane that walks the registry is not. Not fixed here.
- Bare `drone @memory lint` prints the introspection banner rather than scanning — `lint run` or `lint @branch` is the scan. Consistent with every other module's no-args convention; noted because the Quick Start used to read as if bare `lint` audited.

**Cleared 2026-08-27 (the trinity push build):** (1) `drone @memory push` no longer aliases `rollover push` — the bare word that fired an unprompted fleet-wide `per_branch` CONFIG reset on 18 branches now runs the trinity push, whose fleet lane refuses without `--confirm`; the config reset keeps its explicit `rollover push` verb, and a source-scan test fails if the alias returns. (2) A rollover's tab refresh is scoped to the branches it actually rolled (`refresh_all_tabs(branches=…)`), so no citizen's PreCompact hook can propagate renderer changes fleet-wide again — the 23:37 write of 38 files that opened this arc.

**Cleared 2026-08-25:** the entry-point `encapsulation` finding (66% on `apps/memory.py` for importing two `monitor/` handlers) — `watch` is a module now and a contract test fails the suite if any handler import returns to the entry point. Also cleared: `pool.py` / `lint.py` at 85% on `introspection`. Seedgo re-run 2026-08-25 reports **100% on all 45 rules**, both findings gone.

**Cleared 2026-08-13:** `rollover status` showing 0 branches did not reproduce (19 branches across two working directories at the 08-25 re-run). `memory_threshold_exceeded` appears nowhere in this branch's code — the previous note described @trigger's registry, not memory's.

---

*Last Updated: 2026-08-27 (the trinity push — every number here re-measured after the build; fleet figures are from the dry-run and a checker-scored simulation, not estimates)*

---
[← Back to AIPass](../../../README.md)
