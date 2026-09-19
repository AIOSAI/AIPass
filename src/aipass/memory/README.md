[← Back to AIPass](../../../README.md)

# MEMORY

**Purpose:** The central memory archive for AIPass. Archives a branch's `.trinity/` entries into searchable vectors when the files outgrow their keep counts, answers semantic queries across every branch's history, holds the entry shape and the character caps the whole fleet writes against, and keeps each branch's todo pad and its backlog.
**Module:** `aipass.memory`
**Version:** 1.2.0
**Created:** 2026-03-07

---

## Quick Start

```bash
drone @memory search "query"            # Semantic search across every branch's archived memory
drone @memory rollover check            # Dry run — what is over its keep count right now
drone @memory lint fields               # Every .trinity string field by chars, flagged against the shape
drone @memory push --dry-run            # The trinity push — report what would change, write nothing
```

---

## What It Does

- **Archives, never trims.** When a `.trinity/` file passes its keep count, rollover vectorizes the
  oldest entries, verifies the ingestion by reading it back, and only then removes them from the live
  file. Absent locally is not gone — `search` recalls it.
- **Answers across the whole fleet.** One semantic index over every citizen's sessions, learnings and
  observations, filterable by branch and by memory type.
- **Owns the entry shape and the caps.** `memory.config.json` publishes the closed field shape — every
  field an entry may carry, its type and its cap — plus the keep counts and the whole-file budgets.
  The write gate, the push, the state tabs and @seedgo's startup-budget pack all read those numbers
  from here rather than copying them.
- **Keeps the frame honest.** The trinity push rebuilds each branch's machine frame from the gold
  templates and moves every non-canonical entry to vectors, verbatim, verified before it is removed.
- **Holds the todo pad.** Ten live sticky notes per branch; the oldest roll by number to a backlog
  file, never to vectors, so open work can always be read back.
- **Refuses a limit it cannot honour.** A keep count whose worst-case file would bust its budget is
  refused at the verb and clamped on load, with the ceiling named.

Not a monitoring system (that is prax), not a planner (that is flow), and never a writer of another
branch's memory except through rollover and the push.

---

## Live Inventory

The list of modules and commands is **generated from the code that runs them**, so it is not written
down here and cannot go stale:

- `drone @memory` — the self-map: every discovered module with its one-line description.
- `drone @memory --help` — the full command surface: every verb, its arguments and its flags, plus
  the search options and the `--json` machine surface.

---

## How To Reach Me

- Mail: `drone @ai_mail email @memory "Subject" "Body"` — a cap you believe is wrong, an entry that
  should have been archived and was not, a search that cannot find something you know exists.
- **An entry that left a `.trinity` file by hand never reached a vector.** Rollover is the lane that
  archives *and then* trims, in that order; a hand trim skips the archive step. If you need room,
  run `drone @memory rollover run` rather than cutting a tail.
- I do not edit another branch's `.trinity/` files, including to put something back. That fence is
  the same one that protects yours.

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own help
output rots the next time a verb is added — this README carried four verbs that `--help` had never
heard of. The generated surface is the one above under **Live Inventory**, and it is always current.

---

## Architecture

Three layers. `apps/memory.py` is a thin entry point: it auto-discovers modules, dispatches to the
first one that claims a command, and turns a refusal into an exit code. `apps/modules/` holds one
business-logic module per verb — fleet, governance, health, limits, lint, pool, push, rollover,
roots, search, symbolic, templates, todo, verify and watch — alongside `rollover_config` and
`rollover_json`, which carry the `config` verb's implementation and the shared `--json` emitter for
a `rollover` module that outgrew one file. `apps/handlers/` holds the implementation,
grouped one directory per concern: `json/` (the fleet's json shim, the write gate, the caps and the
closed shape), `rollover/` (the extractor, the normalizer, the todo roll), `templates/` (the trinity
push and the gold templates), `tracking/` (line counts and the `*_meta` state tabs), `monitor/`
(branch discovery and the watcher), `vector/` and `storage/` (embedding and ChromaDB, each in its own
subprocess), plus `archive/`, `intake/`, `schema/`, `search/` and `governance/`.

The full directory tree lives in this branch's own prompt (`.aipass/aipass_local_prompt.md`) — one
place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/rollover_pipeline.md](docs/rollover_pipeline.md) | The rollover engine: the pipeline, normalization, the safety valve, the newest-first guardrail, and the one definition of the fleet |
| [docs/trinity_standard.md](docs/trinity_standard.md) | The entry shape and the write gate: the closed field shape, the two refusal reasons, authored-versus-carried, the char caps and the per-branch receipt |
| [docs/trinity_push.md](docs/trinity_push.md) | The push lane: vectorize → verify → prune, what counts as non-canonical, the scope and the two gates |
| [docs/todos_and_backlog.md](docs/todos_and_backlog.md) | The sticky-note pad, the backlog file, the roll and the restore |
| [docs/todos_v2_shape_contract.md](docs/todos_v2_shape_contract.md) | The todos v2 shape contract in full — the relay other branches build against |
| [docs/config_verbs.md](docs/config_verbs.md) | The rollover limit verbs, the keep-count ceiling, and the `--json` machine surface |
| [docs/templates_and_tabs.md](docs/templates_and_tabs.md) | The gold templates, the bump site, and the `*_meta` state tabs written into every memory file |
| [docs/vector_search.md](docs/vector_search.md) | The vector lane: subprocess isolation, `vectorize_and_store`, plan-ID matching |
| [docs/cli_surface.md](docs/cli_surface.md) | How this branch's CLI behaves: exit codes, help flags, and why a correct refusal must not become a runaway log |
| [docs/quality_and_proof.md](docs/quality_and_proof.md) | How this branch's suite is judged, and what a parked test costs |

---

## Integration Points

### Depends On
- `aipass.prax` — structured logging via `get_system_logger()`
- `aipass.cli` — Rich console and refusal formatting
- `AIPASS_REGISTRY.json` and external `*_REGISTRY.json` — branch discovery, the latter via
  `AIPASS_CALLER_CWD`
- Python stdlib: `pathlib`, `json`, `importlib`, `subprocess`

### Provides To
- Every branch — rollover archival when `.trinity/` files pass their keep counts, semantic search
  over what was archived, template distribution, and the todo pad and backlog
- `@hooks` — the entry caps, the closed field shape and its refusal reasons, read at the write gate
- `@seedgo` — the `.trinity` caps and whole-file budgets its startup-budget pack scores against
- `@daemon` — branch health via `apps/modules/health.py`'s `get_branch_health(branch_name)`, because
  a handler may not import another branch's handler directly

### ML Dependencies
Resolved in whichever venv `_get_memory_python()` finds: `fastembed` (ONNX embeddings,
`sentence-transformers/all-MiniLM-L6-v2`), `chromadb`, `numpy`. `search` fails honestly when they are
absent rather than returning nothing.

---

**Last Updated:** 2026-09-15

---
[← Back to AIPass](../../../README.md)
