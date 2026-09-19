# MEMORY Branch-Local Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

# Identity

Memory — the central archive. Rollover moves a branch's oldest `.trinity/` entries into searchable vectors when the file passes its keep count; search answers across every branch. This branch also owns the entry shape, the char caps and the file budgets the whole fleet writes against, and each branch's todo pad and backlog.

# Finding the surface

Never hand-type a command list here — it rots. Three tiers:

 - `drone @memory` — the live self-map, every discovered module.
 - `drone @memory --help` — the full reference: verbs, arguments, flags, search options, the `--json` surface.
 - `README.md` is the face for strangers; depth is `docs/`, indexed from it. Not read at startup.

# Tree

```
memory/
├── apps/
│   ├── memory.py                # Entry point — auto-discovers modules, owns --help
│   ├── modules/                 # One per verb
│   │   ├── fleet.py             # The fleet definition — library, no CLI verb of its own
│   │   ├── governance.py        # Surfacing governance — re-exports from handlers
│   │   ├── health.py            # Branch health (entry-count + entry-size), read-only
│   │   ├── lint.py              # Entry scanner: the cap lane and the fields lane
│   │   ├── pool.py              # Pool vectorization + auto-process
│   │   ├── push.py              # The trinity push (dry-run + gated execute)
│   │   ├── rollover.py          # Rollover orchestration, status, report-lines, config verbs
│   │   ├── roots.py             # Declared repository roots — list/init/add/remove/heal
│   │   ├── search.py            # Semantic query routing
│   │   ├── symbolic.py          # PARKED — refusal stub, impl in tests/parked/
│   │   ├── templates.py         # Gold templates — spawn scaffolds, receipt status, bump
│   │   ├── todo.py              # The pad and its backlog — count, list, restore
│   │   ├── verify.py            # Plan vectorization check
│   │   └── watch.py             # Auto-rollover watcher
│   └── handlers/
│       ├── archive/             # indexer.py
│       ├── cli/                 # help_flags.py, json_flag.py, branch_flag.py
│       ├── governance/          # engine.py
│       ├── intake/              # plans_processor.py, pool_processor.py, auto_process.py
│       ├── json/                # json_handler.py (fleet shim), memory_files.py (the write gate),
│       │                        #   entry_limits.py (caps + closed shape), budget.py (worst-case
│       │                        #   arithmetic), config_loader.py, lint_handler.py
│       ├── monitor/             # detector.py, memory_watcher.py, watch_runner.py, registry_scope.py
│       ├── rollover/            # extractor.py, orchestrator.py, normalizer.py,
│       │                        #   todo_roll.py (pad → backlog file), todo_report.py
│       ├── schema/              # normalize.py
│       ├── search/              # query_executor.py
│       ├── storage/             # chroma_subprocess.py
│       ├── symbolic/            # PARKED — __init__ raises
│       ├── templates/           # trinity_push.py, push_store.py, push_report.py,
│       │                        #   receipt.py, template_bump.py, spawn_pusher.py
│       ├── tracking/            # line_counter.py, tab_renderer.py
│       ├── vector/              # embed_subprocess.py
│       └── central_writer.py
├── docs/                        # Tracked depth, one file per handler group, indexed from README
├── docs.local/                  # Untracked scratch and research
├── templates/                   # LOCAL.template.json, OBSERVATIONS.template.json — gold source
├── tests/  └── parked/          # parked/conftest.py is the collection barrier
├── .chroma/                     # ChromaDB vector store
└── memory_json/                 # Operation logs + custom_config/memory.config.json
```

# The config is the source of truth

`memory_json/custom_config/memory.config.json` is the runtime authority an operator edits. `config_loader.DEFAULT_CONFIG` is the regeneration seed, not a rival — keep them in lockstep. What lives there:

 - `entry_limits.entry_types.<type>` — the container, the canonical text field and its cap.
 - `entry_limits.entry_types.<type>.fields` — the closed shape: every field an entry may carry, its type, whether it is required, its `max_chars` / `max_items`. Anything not listed is `unknown_field`.
 - `entry_limits.file_budgets` — local.json 25,000, observations.json 15,000, passport.json 6,000 file and 600 per string. Read by the keep-count ceiling and by seedgo's startup-budget pack.
 - `rollover.defaults` / `rollover.per_branch` — keep counts, resolved per file key, never deep-merged.

Caps are read, never copied. A second copy of a number is a second source of truth.

# Gotchas

 - The write gate judges a write by what it AUTHORS, not what it carries. An entry byte-identical to disk is carried and reported, never refused — refusing it deadlocks rollover, whose whole job is handing back a smaller file.
 - Field violations use stricter identity than the cap check: the whole entry dict must be present verbatim in `before` to count as carried. A status-only edit is authorship.
 - `search` needs `fastembed` and `chromadb` in the resolved venv. It fails loudly; do not add a fallback.
 - Embedding and Chroma each run in a subprocess. The parent never imports them.
 - Newest-first is a guardrail, not a convention: entries go in at index 0. A tail insert reads as a misplaced write and is refused.
 - Never write a real `.backup/todo/<branch>/backlog.json` from a test. An autouse guard keeps backlogs in tmp; keep it that way.
 - `drone @memory push --confirm` is the fleet lane and is @devpulse's to run, not this seat's.
 - A hook gate refuses a shell write that names a memory file path, reads included, because an interpreter could write any path it holds. Read `.trinity` with the Read tool, `cat` or `jq`.
 - The PreCompact lane shells `drone @memory rollover check|run` from the repo root, and drone re-stamps `AIPASS_CALLER_CWD` — own-branch work there needs an explicit `--branch`.
 - `rollover.py` sits just under seedgo's 1,500-line module ceiling. Split it before adding to it.
 - A new test file is refused by policy. Editing an existing one is fine; a genuinely new file needs @devpulse's ruling first.

# Memory + tracking

 - `.trinity/` — passport.json, local.json, observations.json. Live caps are printed in each file's own `*_meta` line.
 - `DASHBOARD.local.json` — status glance, refreshed by `drone @prax dashboard refresh @memory`.
 - `docs.local/` — scratch, research, mutation logs. Survives a lost session; `/tmp` does not.
