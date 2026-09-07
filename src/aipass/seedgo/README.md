[<- Back to AIPass](../../../README.md)

# Seedgo

**Purpose:** Standards compliance platform for AIPass. Audits all 18 citizen branches against 45 code standards + diagnostics, manages bypass rules, runs proof certification, and provides per-file checklist validation consumed by the PostToolUse auto-fix gate.
**Module:** `aipass.seedgo`
**Version:** 2.0.1
**Created:** 2026-03-05

---

## Quick Start

```bash
drone @seedgo audit aipass              # Audit all branches against all standards
drone @seedgo checklist <file>          # Check a single file
drone @seedgo standard cli              # Look up what a standard checks
```

---

## Overview

### What I Do
- Audit all 18 citizen branches against 45 code standards + diagnostics (architecture, CLI, imports, logging, naming, silent catch, deep nesting, gateway boundary, etc.)
- Score files 0-100 per standard and report violations with actionable details
- Manage bypass rules (`.seedgo/bypass.json`) for deliberate exceptions
- Run pyright diagnostics across branches for type error detection
- Single-file checklist validation against all standards (consumed by PostToolUse auto-fix hook)
- Proof certification via proof/proof_query (triplet, plugin integrity, README currency)
- Custom function test coverage mapping via test_map
- Execution-tier test quality via audit-tests: runs a target's suite inside a copy under a `sys.addaudithook` write gate, refuses to publish unless a planted canary proves the gate can fire, and states what the gate cannot see beside every score
- README auto-generation and freshness checking

### What I Don't Do
- Runtime monitoring (that's prax)
- Code execution or deployment

---

## Commands

All commands available via `drone @seedgo <command>` or `python3 -m aipass.seedgo.apps.seedgo <command>`.
Every command below was run against this branch on **2026-09-07** and produced the output described.

### Via Drone (primary)

```bash
drone @seedgo                                          # Introspection (13 modules, 3 packs, version)
drone @seedgo --help                                   # Usage guide (see the gap note below)
drone @seedgo --version                                # Version string — "seedgo v2.0.1"

# Audit
drone @seedgo audit aipass                             # Audit all 18 citizens (45 standards + diagnostics)
drone @seedgo audit aipass @flow                       # Audit single branch
drone @seedgo audit inbox-ids                          # Inbox message-ID validation

# Standards Query
drone @seedgo standard                                 # List every standard name across ALL THREE packs (57)
drone @seedgo standard cli                             # Show standard content (short form)
drone @seedgo standards_query aipass_standards         # List the 45 standards in the aipass pack
drone @seedgo standards_query aipass_standards cli     # Show specific standard content

# Per-file Check
drone @seedgo checklist <file>                         # Single-file standards check (hook consumer)
drone @seedgo checklist <directory>                    # Directory-wide check (globs *.py)

# Diagnostics
drone @seedgo diagnostics                              # Pyright type checking via audit pipeline

# Proof
drone @seedgo proof aipass                             # Proof certification (CERTIFIED / NOT CERTIFIED)
drone @seedgo proof_query aipass_proof triplet          # Query proof standard content

# Test Coverage
drone @seedgo test_map @seedgo                         # Function-level test coverage mapping
drone @seedgo audit-tests @branch                      # Execution-tier test quality (hygiene gate)
drone @seedgo audit-tests <directory>                  # Any directory with pytest targets
drone @seedgo audit-tests aipass                       # Every citizen

# Test quality v5 (generic pack — weekly cadence + on demand, scores, gates nothing)
drone @seedgo audit pytest_quality @branch             # 11 AST rules over a project's tests
drone @seedgo audit pytest_quality                     # Every citizen

# Static test inventory + the weekly cadence
drone @seedgo test-inventory <path>                    # Every test function in a tree, ranked for reading
drone @seedgo shadow-cycle                             # The three weekly passes, one command

# README
drone @seedgo readme update @flow                      # README auto-generation for a branch
drone @seedgo readme check @seedgo                     # Marker-driven freshness check

# Introspection-only commands
drone @seedgo permissions                              # TRUSTED_CROSS_WRITERS trust list
drone @seedgo inbox_audit                              # Points at `audit inbox-ids`
```

### Via Python Module

```bash
python3 -m aipass.seedgo.apps.seedgo audit aipass      # Same commands, direct execution
python3 -m aipass.seedgo.apps.seedgo standards_query aipass_standards cli
```

> **Note:** the module path is the full entry point, `aipass.seedgo.apps.seedgo`. There is no
> `__main__.py`, so the shorter `python3 -m aipass.seedgo` fails with *"'aipass.seedgo' is a
> package and cannot be directly executed"* — this README advertised the short form until
> 2026-08-25, and it never worked.

> **Note:** `diagnostics` takes no branch argument despite what `--help` shows — standalone
> diagnostics is disabled and runs through the audit pipeline (`audit aipass [@branch]`).
> Re-checked 2026-09-07: `drone @seedgo diagnostics @flow` answers *"Unknown argument: '@flow'"*.

> **`--help` names the whole command surface as of 2026-09-06.** Until then its closing
> `Commands:` line stopped at 13 and left six live verbs unnamed (`audit-tests`, `test-inventory`,
> `shadow-cycle`, `permissions`, `inbox_audit`, and the `audit pytest_quality` pack — all of them
> ran, measured 2026-09-05). The help text now carries a Tests section, a Housekeeping section
> and the pack under Audit, and the `Commands:` line lists all 18.

> **Note — `standard` and `standards_query` count differently.** `drone @seedgo standard` is
> pack-agnostic and lists the union of all three checker packs (**57** names on 2026-09-07).
> `drone @seedgo standards_query aipass_standards` lists that one pack (**45**). Both read names
> from `*_content.py`, which is why `ruff` appears as `ruff_check` — see the naming-split note
> under the standards table.

---

## Architecture

```
seedgo/
├── apps/
│   ├── seedgo.py                    # Entry point — thin router (326 lines)
│   │                                #   discover_modules() loads apps/modules/*.py
│   │                                #   route_command() dispatches to first handler returning True
│   ├── modules/                     # 13 business logic modules
│   │   ├── audit_tests.py           # Execution-tier test quality (runs the suite in a copy)
│   │   ├── inventory.py             # test-inventory verb — every test ranked for READING
│   │   ├── shadow_cycle.py          # shadow-cycle verb — the three weekly passes, one command
│   │   ├── standards_audit.py       # Pack-aware compliance audit orchestrator
│   │   ├── standards_query.py       # Pack-aware content query
│   │   ├── diagnostics_audit.py     # Pyright diagnostics via audit pipeline
│   │   ├── checklist.py             # Per-file/dir standards check (hook consumer)
│   │   ├── seedgo_proof.py          # Proof certification orchestrator
│   │   ├── proof_query.py           # Proof content query
│   │   ├── inbox_audit.py           # Inbox message-ID validation
│   │   ├── permissions.py           # TRUSTED_CROSS_WRITERS list for hook + drone auth
│   │   ├── readme_update.py         # README generation module
│   │   └── test_map.py              # Custom function test coverage mapping
│   └── handlers/                    # 15 handler directories + 2 shared modules
│       ├── module_root.py           # Guarded module_file() — the one import-time __file__ resolve
│       ├── registry_scan.py         # Case-EXACT registry discovery — the one reader every lane uses
│       ├── aipass_standards/        # 45 checker standards (134 files: 45 check + 45 content
│       │   │                        #   + 38 md + applicability.py, exception_handling.py,
│       │   │                        #   skip_dirs.py, trinity_groups.py, diagnostics.json,
│       │   │                        #   __init__.py)
│       │   ├── *_check.py           # Checker implementations (score 0-100)
│       │   ├── *_content.py         # Queryable standard content
│       │   └── *.md                 # Standard docs — 8 checkers ship none (see triplet, below)
│       ├── aipass_proof/            # 5 proof validators (16 files: 5 validators + 5 _content.py
│       │   │                        #   + 5 md + __init__.py)
│       │   ├── triplet.py           # Pack triplet completeness (check + content + md)
│       │   ├── interface.py         # AUDIT_SCOPE + function signatures
│       │   ├── plugin_integrity.py  # No hardcoded standard names
│       │   ├── content_naming.py    # Function naming conventions
│       │   └── readme_currency.py   # README freshness
│       ├── audit/                   # Audit implementation
│       │   ├── branch_audit.py      # Per-branch scoring engine
│       │   ├── discovery.py         # Branch discovery (CWD-first registry)
│       │   ├── audit_display.py     # Rich result formatting
│       │   ├── incremental_cache.py # Content-hash cache — unchanged branch replays its score
│       │   └── artifact.py          # Untruncated violation set -> .seedgo/last_audit_<branch>.json
│       ├── bypass/                  # Bypass + ignore systems
│       │   ├── bypass_handler.py    # .seedgo/bypass.json loader
│       │   ├── ignore_handler.py    # Audit ignore patterns + .seedgoignore engine
│       │   ├── utils.py             # matching_rule() — the single scope-aware rule matcher
│       │   └── inert.py             # Derives inert (unreachable) bypass rules from checker ASTs
│       ├── cli/                     # help_flags.py — shared --help detection
│       ├── config/                  # Package marker only — __init__.py, no handlers today
│       ├── diagnostics/             # Pyright integration + branch discovery
│       ├── json/                    # json_handler — the canonical fleet shim (see below)
│       ├── readme/                  # README generator + branch resolution
│       ├── audit_tests/             # audit-tests execution lane (write-gated suite run)
│       ├── tests_pytest_standards/  # pytest-standards adapter pack for the audit-tests lane
│       ├── pytest_quality_standards/ # GENERIC test-quality scoring pack (v5) — 11 AST rules, weekly + on demand
│       ├── test_inventory/          # static fleet-wide test inventory (phase A, outside the lane)
│       ├── shadow_cycle/            # the weekly cadence — score + inventory + twins, then one mail
│       └── test_map/                # Function test coverage scanner
├── tests/                           # 62 test files, 3030 test functions (pytest expands to 3700 cases)
├── .trinity/                        # Identity + memory
├── .aipass/                         # Branch prompt (aipass_local_prompt.md)
├── .seedgo/                         # Self-bypass rules + audit artifacts
└── .ai_mail.local/                  # Mailbox
```

### Key Patterns

**Module auto-discovery:** `discover_modules()` in seedgo.py loads all `.py` files from `apps/modules/`. Each module's `handle_command(command, args)` is called in discovery order; first returning `True` wins.

**Pack discovery:** Checker packs live in `handlers/*_standards/` directories. `standards_audit` strips the `_standards` suffix for command routing (`aipass_standards/` -> `audit aipass`). `standards_query` uses the full directory name (`standards_query aipass_standards`).

**CWD-first registry:** `_find_registry()` walks CWD parents first (for external project support), falls back to `__file__` parents, uses `*_REGISTRY.json` glob (not hardcoded name).

**One json handler, fleet-wide.** As of DPLAN-0325 (2026-09-04) all 18 citizens ship a byte-identical
`apps/handlers/json/json_handler.py` — a 1724-byte shim that binds the prax-owned service and
resolves nothing of its own. Seedgo's `json_handler` standard now accepts a handler **only** if its
sha256 matches that pinned shim; there is no substring or marker path left. The shim *binds*, never
wraps: the service reads its caller at `sys._getframe(2)`, so an extra wrapper frame would misroute
every log line in the branch.

**Info channel (non-scored):** a checker may expose `check_branch_info(branch_path) -> list[str]`. `branch_audit` collects those lines into `info_lines` and `audit_display` renders them dim, always — including at 100%. They carry no score and no pass/fail by construction, so a checker can surface context it deliberately does not audit. First use: `json_structure` lists the operator files in `{branch}_json/custom_config/` (names only — the content is operator-owned and never judged).

**Bypass system:** `.seedgo/bypass.json` per branch. Each entry has file, standard, optional lines, and required reason. Checkers call `is_bypassed()` per violation. Bypass is intentional documented deviation, not ignoring.

**`.seedgoignore` (throwaway paths, no reason required):** Drop a `.seedgoignore` file into any directory to exclude matching files/dirs from scans, audits, and the per-file checklist — same gitignore-style patterns and per-directory nesting semantics as a real `.gitignore` (via `pathspec`). Scope is exactly that directory's subtree; a nested `.seedgoignore` adds further excludes on top of any ancestor's, it doesn't replace them. A global default (`tools/`) applies fleet-wide with zero setup, since every branch's `apps/tools/` is deliberate throwaway prototyping space — quick scripts for fast answers, not standards-compliant by design. Unlike bypass (documented exception to a specific standard on a specific file), `.seedgoignore` removes the file from consideration entirely and needs no reason. It does **not** touch diagnostics (ruff/pyright) — those keep running on ignored files so auto-fix still catches real errors while you write; only standards checks skip them. See `ignore_handler.load_ignore_entries()` / `is_seedgo_ignored()`.

---

## The 45 Standards

`Scope` is the checker's own `AUDIT_SCOPE` (where a result is REPORTED); `Applies to`
is its `APPLIES_TO` (which files are ELIGIBLE, default `everywhere`). These are two
different axes — see `applicability.py`. Both columns below are read from the checker
sources, not maintained by hand — regenerated against them **2026-09-07**, when the pack
was 45 checkers. It has been 45, 46 and 45 again inside a fortnight, which is why the row
count is verified against `discover_checkers()` on every pass rather than carried: the
2026-08-25 regeneration wrote 45 rows and silently omitted `trinity`, so the count matched
by accident while the table was wrong.

| Standard | Scope | Applies to | What It Checks |
|----------|-------|-----------|----------------|
| architecture | all_files | production | Module/handler separation, entry point structure |
| cli | all_files | production | Rich console usage, no bare print() |
| cli_flags | entry_point | everywhere | --help, --version flag handling |
| cli_ux | entry_point | everywhere | CLI navigation + output quality (Nav/Output scoring) |
| commented_logger | all_files | everywhere | No commented-out logger/logging calls |
| dead_code | branch_level | everywhere | Unreachable functions and dead imports |
| debug_print | all_files | everywhere | No debug print/pprint statements |
| deep_nesting | all_files | everywhere | Max nesting depth 4 (AST-measured) |
| documentation | all_files | production | Docstrings on public functions |
| encapsulation | all_files | production | No cross-branch imports, proper isolation |
| error_handling | all_files | everywhere | Try/except patterns, error propagation |
| gateway_boundary | all_files | production | A branch writes its OWN private storage; another branch's goes through that branch's door |
| handler_import | branch_level | everywhere | apps/__init__.py contains `from . import handlers` |
| handlers | all_files | production | Handler directory structure + handler independence |
| hardcoded_key | all_files | everywhere | No hardcoded API keys or secrets |
| hardcoded_path | all_files | everywhere | No hardcoded absolute paths |
| help_flag_safety | all_files | production | A help flag ANYWHERE means explain, never execute |
| help_text | all_files | everywhere | --help content quality |
| imports | all_files | everywhere | Import ordering and grouping |
| introspection | all_files | everywhere | No-args introspection gate |
| json_handler | branch_level | everywhere | The canonical json shim by sha256 + bidirectional config/data/log triplet completeness |
| json_structure | all_files | everywhere | json_handler import + log_operation calls |
| log_handler | all_files | everywhere | Prax logger usage (not stdlib logging) |
| log_level | all_files | everywhere | Correct log level usage |
| log_structure | all_files | everywhere | Structured log message format |
| log_visibility | all_files | everywhere | Log output in key operations |
| meta | all_files | production | File header metadata block |
| modules | all_files | production | Module structure and naming |
| naming | all_files | everywhere | snake_case, column-0 constants |
| output_routing | all_files | everywhere | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | everywhere | No dangerous permission overrides |
| readme | entry_point | everywhere | README.md exists and is current |
| readme_quality | entry_point | everywhere | README content depth and section quality |
| rich_markup | all_files | production | Literal `[placeholders]` Rich silently eats at render time |
| ruff *(advisory)* | branch_level | everywhere | Ruff linter compliance — surfaces violations, never gates the score |
| shebang | all_files | everywhere | No shebang lines in library code |
| silent_catch | all_files | everywhere | No bare except/pass patterns |
| stderr_routing | all_files | everywhere | Proper stderr vs stdout usage |
| subcommand_help | entry_point | everywhere | Subcommand --help interception before dispatch |
| template *(advisory)* | branch_level | everywhere | No unresolved spawn template markers |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| trinity | branch_level | everywhere | `.trinity/` document set — schema, caps, ordering, freshness |
| unused_function | branch_level | everywhere | No unreferenced public functions |
| windows_compat | all_files | everywhere | Cross-platform compatibility (no Unix-only APIs) |

The audit consults **46** entries for a branch — these 45 plus `diagnostics` (pyright), which has
no `_check.py` of its own. That 46 is what CI's `EXPECTED_STANDARDS` pins.

**`test_quality` (v4) left this table on 2026-09-07.** It was the pack's only
`APPLIES_TO = tests` checker: a per-branch TEXT scan that awarded an item for finding a
substring anywhere under `tests/`. Patrick sealed DPLAN-0323 that night — the scan
manufactured tests instead of measuring them, and the json sweep had to add four
`test_cli_routing.py` files purely to keep its items covered. The checker, its content
module and its `.md` are in `apps/handlers/aipass_standards/.archive/`; the table above
is 45 rows because of it, and no checker declares `APPLIES_TO = tests` any more. What
replaces it is not another gate: `pytest_quality` (v5, 11 AST rules) runs weekly and on
demand and scores without gating, and the json-handler claims v4 approximated are pinned
by execution over all 18 shims in `tests/test_json_handler_contract.py`.

> **Known naming split — `ruff` vs `ruff_check`.** The checker file is
> `ruff_check.py`, so stripping the `_check.py` suffix yields the standard name
> **`ruff`** — that is what the audit and checklist display. Its content and doc
> files are `ruff_check_content.py` / `ruff_check.md`, so the query surface lists
> and accepts **`ruff_check`**: `drone @seedgo standard ruff` returns
> "Unknown standard" (re-checked 2026-09-07). The name the audit shows you is not
> the name the query takes. This also makes the triplet proof report two
> half-standards. Tracked in APLAN-0005.

---

## Hook Architecture

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure — engine, bridge, and
native handlers. Seedgo audits hooks via standards but does not own the hook system, and no
longer mirrors its roster here: the hand-maintained table this section used to carry listed 14
handlers when 29 existed, and named one — `prompt.global_loader` — that had already moved to
`.archive/`. A copy of someone else's registry rots quietly; the directory does not.

Counted from `src/aipass/hooks/apps/handlers/` on 2026-09-07 (`*.py`, excluding `__init__.py`):

| Category | Handlers | Directory |
|----------|----------|-----------|
| prompt | 9 | `apps/handlers/prompt/` |
| lifecycle | 9 | `apps/handlers/lifecycle/` |
| security | 7 | `apps/handlers/security/` |
| notification | 5 | `apps/handlers/notification/` |
| **Total (event handlers)** | **30** | |

Four further directories under the same root are infrastructure rather than event handlers —
`bridges/` (2), `config/` (3), `json/` (2), `cli/` (1) — so the whole tree is 38 files. The
previous count here said 29 and was taken on 2026-08-25; `security/` has gained one since.

Provider settings route every event through the bridge (`claude.py`), which dispatches to those
handlers. Event registrations live in `.claude/provider_manifest.json` (27 entries under
`cli.claude.hooks`, verified 2026-09-07) and are keyed by **hook alias, not filename** —
`UserPromptSubmit:branch_prompt` fires `prompt/branch_loader.py`, `identity_injector` fires
`prompt/identity.py`. The two lists do not line up by name, which is the second reason not to
restate them here. Read the directory, or ask @hooks.

**The one that concerns this branch:** `lifecycle/auto_fix.py` (PostToolUse) runs
`drone @seedgo checklist <file>` against every edited file. That gate is what `checklist` feeds.

---

## Tests

Counted 2026-09-07, both ways, because the two numbers answer different questions:

- **62 test files, 3030 test functions** — the `def test_` count, the way seedgo's own
  `readme_check._count_test_functions()` counts it. **pytest expands to 3700 cases** once
  parametrisation is applied.
- **Run result:** 3695 passed, 5 skipped, 0 failed (334s, from the repo root in the CI shape:
  `python -m pytest src/aipass/seedgo -c pyproject.toml --rootdir=.`).
- **Down from 3087 functions on 2026-09-05, and every one of the 57 was retired on evidence**
  (FPLAN-0491): the v4 `test_quality` sections went with the standard; `tests/test_json_handler.py`
  moved whole to `.archive/` because all six of its tests are carried, parametrised over all 18
  shims, by `tests/test_json_handler_contract.py`; `test_content_functions.py` merged 37 twin pairs
  into 37 single tests, mutation-checked at the merge; and three rows judged DELETE in the
  2026-09-05 contested band came out after a mutation confirmed they pinned nothing.
- **The 5 skips are documented, not silent:** three in `test_import_dead_cwd.py` are instrument
  self-checks retired under the 2026-09-01 one-fix ruling (owner to rewrite as measurement); one in
  `test_checkers_batch7.py` needs canary's `paths.py`, which is not on this machine; one in
  `test_trinity_check.py` is a live-state guard with no drifted citizens to find.
- **0 type errors** (pyright, via the audit pipeline)
- Key test areas: standards audit, checklist, bypass, JSON handler contract, hooks snapshot,
  permissions, proof, README, diagnostics, trinity, encapsulation derivation, line coverage
  (plugin integrity, diagnostics, audit display, branch audit, architecture, checklist)

---

## Integration Points

### Depends On
- `aipass.cli` — Rich console, header formatting
- `aipass.prax` — Structured logging via `logger`, and the json service the local shim binds
- `aipass.drone` — Branch resolution via `normalize_branch_arg`
- Python stdlib (`pathlib`, `ast`, `importlib`, `json`, `re`)

### Provides To
- All branches — standards auditing via `drone @seedgo audit aipass [@branch]`
- All branches — content queries via `drone @seedgo standards_query`
- All branches — per-file checklist via hook (PostToolUse -> checklist)
- `aipass.drone` — routed by drone's `generic_adapter.py` from `routing_config.json`
  (`"seedgo": {"entry_point": "aipass.seedgo.apps.seedgo"}`). This branch ships no
  `drone_adapter.py`; the old one is archived as `.archive/drone_adapter(disabled).py`
  and no branch in the fleet has one.

---

## Status (2026-09-07)

| Signal | Value | How it was measured |
|--------|-------|---------------------|
| Self-audit | **100** on all 46 consulted entries | `drone @seedgo audit aipass --full` |
| Tests | 3695 passed, 5 skipped, 0 failed | `python -m pytest src/aipass/seedgo -c pyproject.toml --rootdir=.` |
| Type errors | 0 | pyright, via the audit pipeline |
| Proof certification | **NOT CERTIFIED** — 3 of 5 pass | `drone @seedgo proof aipass` |
| Function coverage | 449 / 584 tested (76%) | `drone @seedgo test_map @seedgo` |
| Bypass rules | **43** | `.seedgo/bypass.json` |
| Weekly v5 cadence | **enabled** 2026-09-07, next run Sun 2026-09-13 03:00 | `drone @daemon queue` |

---

## Known Issues / Tech Debt

Full detail and status live in **APLAN-0005** (the standing branch health record).
Everything below was re-checked on 2026-09-07 unless marked **UNVERIFIED**.

- `seedgo proof aipass` reports **NOT CERTIFIED** — the auditor does not currently pass its own proof pack.
  Tonight's line, verbatim: `content_naming` PASSED (45 correct / 45 total), `interface` PASSED
  (all 45 checkers comply), `plugin_integrity` PASSED (4/5 clean, 1 cosmetic), and:
  - `readme_currency` FAILED: *"README is stale: count mismatch, 1 stale reference(s),
    44 undocumented standard(s). (15 issues)"*. Three separate causes, and only the first is a
    plain detector bug.
    (a) It recognises standard names only in a `pack checks:` prose format this README
    does not use, so the standards in the table above read as "undocumented" no matter how
    accurate the table is.
    (b) It scrapes any number near a pack reference as the claimed check count, so the
    "8 checkers ship no `.md`" line below is read as a claim about the pack size.
    (c) It harvests **this bullet** into `stale_refs` — describing the detector's own bug
    in the README makes the detector fail harder. A checker cannot tell a document from
    a document *about* the document; see also `rich_markup` on `# BAD` examples.
  - `triplet` FAILED, live 2026-09-07: **37 complete | 1 check-only | 1 missing-check |
    7 other-incomplete | 4 orphaned | 46 total (9 issues)**. Read out:
    - **8 checkers have no `.md`** — the 7 "other-incomplete" (cli_ux, gateway_boundary,
      hardcoded_path, json_structure, readme_quality, rich_markup, subcommand_help) plus
      `ruff`, which is the "check-only" entry and is missing content *and* md.
      `gateway_boundary` shipped without one on 08-18 and still has none.
    - The `ruff`/`ruff_check` name split is what produces the 1 check-only (`ruff`) +
      1 missing-check (`ruff_check`) pair. 37 + 1 + 1 + 7 = the 46 total.
    - The **4 orphans** are `trinity_groups.py`, `applicability.py`, `skip_dirs.py` and
      `exception_handling.py` — shared infrastructure that lives in the pack directory without
      being standards, which the triplet proof has no category for. The 46 total is one lower
      than the 47 of 2026-09-05 for one reason: `test_quality` retired.
- ~~`test_quality_check.py` says 11 categories and holds 7~~ — **moot 2026-09-07: the file is
  archived.** The 09-05 README pass found its header and docstring claiming *"11 categories"*
  against a `STANDARD_CATEGORIES` of 7. It was never corrected because the standard itself
  retired first (FPLAN-0491), taking checker, content module and `.md` to
  `apps/handlers/aipass_standards/.archive/`. Recorded rather than deleted: the drift was real,
  and a docstring outliving the table it describes is the species, not the instance.
- ~~`--help` names 13 commands and the branch answers 19~~ — fixed 2026-09-06: `audit-tests`,
  `test-inventory`, `shadow-cycle`, `permissions`, `inbox_audit` and the `audit pytest_quality`
  pack are in the help text and its `Commands:` line.
- `standard ruff` returns "Unknown standard" while the audit displays the standard as `Ruff` (see the naming-split note above).
- `--help` advertises `drone @seedgo diagnostics @flow`, but the module rejects a branch argument — standalone diagnostics runs only through the audit pipeline.
- ~~`permissions.py` introspection leak~~ — **fixed 2026-08-13 (S80).** The gate keyed on
  the arguments, never the command name, so the trust list printed above every bare
  subcommand while `drone @seedgo permissions` answered "Unknown command" *and then*
  printed the block. It now claims its own command and is silent for every other.
- This README has no auto-update markers, so `drone @seedgo readme check @seedgo` skips every
  section — re-run 2026-09-07, five sections, all *"Skipped — no marker found"*. The branch that
  ships README generation does not consume it.
- **No bypass-rot detection, and the obvious detector is wrong.** Nothing tells a branch
  that a bypass rule has stopped suppressing anything. The tempting measurement — re-run
  the audit with `bypass_rules=[]` and match each rule against the resulting violation
  records — was run **on 2026-08-13, against 28 rules**, and called 6 of them dead. Five
  were live: four suppress real failures in the **checklist** lane (the audit walks
  `apps/`, the PostToolUse hook checks `tests/`), and one guards `dead_code`, a
  branch-level standard that reports through `checks[].message` prose rather than a
  `*_violations` list — removing it drops that standard 100 → 95. A rot detector must
  read both lanes and canary branch-level standards through `check_branch()`.
  **UNVERIFIED at today's 43 rules** — the removed-rules sweep has not been re-run since
  08-13, and the rule set has grown by 15 entries. Re-checked 2026-09-07 only that the count is
  still 43; the sweep itself is still not re-run. See APLAN-0005.
- `audit_display.py`: **the DPLAN-0047 dynamic refactor has landed** — this line once claimed
  16 hardcoded per-standard display blocks; the file derives every standard from its
  `<name>_violations` key and renders it generically, with exactly **one** special case left
  (`architecture`, `audit_display.py:282`, which routes to its own renderer because it reports
  through `results['checks']`). Re-verified 2026-09-05, unchanged 2026-09-07. The change is not attributed here
  because this branch's memory does not record who made it.
- `documentation_check.py` multi-line signature lookahead is **30 lines**, not the 5 an older
  edition of this line claimed. The site is `documentation_check.py:285`
  (`min(line_num + 30, len(lines) + 1)`) — the previous README cited line 146, which is stale.
  Still a bounded window, still a limitation — just six times wider than documented.
- `dead_code_check.py` recognises `glob("*.py")` / `glob('*.py')` as a discovery pattern
  (`dead_code_check.py:194`) but **not** `iterdir()` — no `iterdir` appears anywhere in the
  file. Re-verified 2026-09-05, unchanged 2026-09-07.
- ~~Cross-branch file write detection recommended but not yet in standards (S73 finding)~~ —
  **shipped as the `gateway_boundary` standard, 2026-08-18.** It was the 45th checker, `trinity`
  made 46, and `test_quality` leaving on 2026-09-07 puts the pack back at 45 — a different 45
  from the one that number named in August.
- **`standards_audit.print_help` has no test calling it.** Removing
  `test_handle_command_output_capture` (a DELETE verdict from the 2026-09-05 contested band, whose
  own comment said the `capsys` fixture was there "to satisfy the pattern requirement") left the
  function reached only through `handle_command`'s no-args path. The removed row asserted nothing
  about the output it captured, so this is a gap that was already there, now visible. Noted, not
  papered over.

---

## Latest Audit (2026-09-07)

- **Seedgo score:** 100% — **46** consulted entries (45 standards + diagnostics), every one at 100,
  nothing `not_applicable`. 47 until 2026-09-07; `test_quality` retiring is the whole difference,
  and CI's `EXPECTED_STANDARDS` tripwire moves with it.
- **Tests:** 3695 passed, 5 skipped (3030 test functions across 62 files; pytest expands them to
  3700 cases)
- **Coverage:** 449 public functions tested of 584 (76%)
- **Type errors:** 0
- **Proof:** NOT CERTIFIED — 3 of 5 proofs pass (see Known Issues)
- **Bypass:** 43 rules. The 100% above is a real score with 43 documented exceptions under it, not
  a clean sheet. The removed-rules measurement that once produced a "98% with every rule stripped"
  figure was taken on 2026-08-13 at 27 rules and is **not re-run here** — treat that percentage as
  historical, not current.

---

**Last Updated:** 2026-09-07

---
[<- Back to AIPass](../../../README.md)
