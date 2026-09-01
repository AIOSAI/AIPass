[<- Back to AIPass](../../../README.md)

# Seedgo

**Purpose:** Standards compliance platform for AIPass. Audits all 18 citizen branches against 45 code standards + diagnostics, manages bypass rules, runs proof certification, and provides per-file checklist validation consumed by the PostToolUse auto-fix gate.
**Module:** `aipass.seedgo`
**Version:** 2.0.0
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

### Via Drone (primary)

```bash
drone @seedgo                                          # Introspection (module list, version)
drone @seedgo --help                                   # Full command listing
drone @seedgo --version                                # Version string

# Audit
drone @seedgo audit aipass                             # Audit all 18 citizens (45 standards + diagnostics)
drone @seedgo audit aipass @flow                       # Audit single branch
drone @seedgo audit inbox-ids                          # Inbox message-ID validation

# Standards Query
drone @seedgo standard                                 # List all 45 standards
drone @seedgo standard cli                             # Show standard content (short form)
drone @seedgo standards_query aipass_standards         # List all 45 standards in pack
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

---

## Architecture

```
seedgo/
├── apps/
│   ├── seedgo.py                    # Entry point — thin router (326 lines)
│   │                                #   discover_modules() loads apps/modules/*.py
│   │                                #   route_command() dispatches to first handler returning True
│   ├── modules/                     # 10 business logic modules
│   │   ├── audit_tests.py           # Execution-tier test quality (runs the suite in a copy)
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
│   └── handlers/                    # 12 handler directories + 2 shared modules
│       ├── module_root.py           # Guarded module_file() — the one import-time __file__ resolve
│       ├── registry_scan.py         # Case-EXACT registry discovery — the one reader every lane uses
│       ├── aipass_standards/        # 45 checker standards (132 files: 45 check + 45 content
│       │   │                        #   + 38 md + applicability.py, skip_dirs.py,
│       │   │                        #   diagnostics.json, __init__.py)
│       │   ├── *_check.py           # Checker implementations (score 0-100)
│       │   ├── *_content.py         # Queryable standard content
│       │   └── *.md                 # Standard docs — 7 standards ship none (see triplet, below)
│       ├── aipass_proof/            # 5 proof validators (16 files: 5 validators + 5 _content.py
│       │   │                        #   + 5 md + __init__.py)
│       │   ├── triplet.py           # .trinity/ completeness
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
│       ├── json/                    # JSON tracking (json_handler)
│       ├── readme/                  # README generator + branch resolution
│       ├── audit_tests/             # audit-tests execution lane (write-gated suite run)
│       ├── tests_pytest_standards/  # pytest-standards adapter pack for the audit-tests lane
│       └── test_map/                # Function test coverage scanner
├── tests/                           # 59 test files, 2691 tests
├── .trinity/                        # Identity + memory
├── .aipass/                         # Branch prompt (aipass_local_prompt.md)
├── .seedgo/                         # Self-bypass rules + audit artifacts
└── .ai_mail.local/                  # Mailbox
```

### Key Patterns

**Module auto-discovery:** `discover_modules()` in seedgo.py loads all `.py` files from `apps/modules/`. Each module's `handle_command(command, args)` is called in discovery order; first returning `True` wins.

**Pack discovery:** Checker packs live in `handlers/*_standards/` directories. `standards_audit` strips the `_standards` suffix for command routing (`aipass_standards/` -> `audit aipass`). `standards_query` uses the full directory name (`standards_query aipass_standards`).

**CWD-first registry:** `_find_registry()` walks CWD parents first (for external project support), falls back to `__file__` parents, uses `*_REGISTRY.json` glob (not hardcoded name).

**Info channel (non-scored):** a checker may expose `check_branch_info(branch_path) -> list[str]`. `branch_audit` collects those lines into `info_lines` and `audit_display` renders them dim, always — including at 100%. They carry no score and no pass/fail by construction, so a checker can surface context it deliberately does not audit. First use: `json_structure` lists the operator files in `{branch}_json/custom_config/` (names only — the content is operator-owned and never judged).

**Bypass system:** `.seedgo/bypass.json` per branch. Each entry has file, standard, optional lines, and required reason. Checkers call `is_bypassed()` per violation. Bypass is intentional documented deviation, not ignoring.

**`.seedgoignore` (throwaway paths, no reason required):** Drop a `.seedgoignore` file into any directory to exclude matching files/dirs from scans, audits, and the per-file checklist — same gitignore-style patterns and per-directory nesting semantics as a real `.gitignore` (via `pathspec`). Scope is exactly that directory's subtree; a nested `.seedgoignore` adds further excludes on top of any ancestor's, it doesn't replace them. A global default (`tools/`) applies fleet-wide with zero setup, since every branch's `apps/tools/` is deliberate throwaway prototyping space — quick scripts for fast answers, not standards-compliant by design. Unlike bypass (documented exception to a specific standard on a specific file), `.seedgoignore` removes the file from consideration entirely and needs no reason. It does **not** touch diagnostics (ruff/pyright) — those keep running on ignored files so auto-fix still catches real errors while you write; only standards checks skip them. See `ignore_handler.load_ignore_entries()` / `is_seedgo_ignored()`.

---

## The 45 Standards

`Scope` is the checker's own `AUDIT_SCOPE` (where a result is REPORTED); `Applies to`
is its `APPLIES_TO` (which files are ELIGIBLE, default `everywhere`). These are two
different axes — see `applicability.py`. Both columns below are read from the checker
sources, not maintained by hand — regenerated against them 2026-08-25, when the table was
still 44 rows and the pack had been 45 since `gateway_boundary` landed on 08-18.

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
| json_handler | branch_level | everywhere | Canonical json_handler.py + bidirectional config/data/log triplet completeness |
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
| test_quality | branch_level | tests | JSON handler test coverage (51 items, 11 categories) |
| todo | all_files | everywhere | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | production | Trigger integration patterns |
| unused_function | branch_level | everywhere | No unreferenced public functions |
| windows_compat | all_files | everywhere | Cross-platform compatibility (no Unix-only APIs) |

> **Known naming split — `ruff` vs `ruff_check`.** The checker file is
> `ruff_check.py`, so stripping the `_check.py` suffix yields the standard name
> **`ruff`** — that is what the audit and checklist display. Its content and doc
> files are `ruff_check_content.py` / `ruff_check.md`, so the query surface lists
> and accepts **`ruff_check`**: `drone @seedgo standard ruff` returns
> "Unknown standard". The name the audit shows you is not the name the query
> takes. This also makes the triplet proof report two half-standards. Tracked in
> APLAN-0005.

---

## Hook Architecture

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure — engine, bridge, and
native handlers. Seedgo audits hooks via standards but does not own the hook system, and no
longer mirrors its roster here: the hand-maintained table this section used to carry listed 14
handlers when 29 existed, and named one — `prompt.global_loader` — that had already moved to
`.archive/`. A copy of someone else's registry rots quietly; the directory does not.

Counted from `src/aipass/hooks/apps/handlers/` on 2026-08-25:

| Category | Handlers | Directory |
|----------|----------|-----------|
| prompt | 9 | `apps/handlers/prompt/` |
| lifecycle | 9 | `apps/handlers/lifecycle/` |
| security | 6 | `apps/handlers/security/` |
| notification | 5 | `apps/handlers/notification/` |
| **Total** | **29** | |

Provider settings route every event through the bridge (`claude.py`), which dispatches to those
handlers. Event registrations live in `.claude/provider_manifest.json` (27 entries) and are keyed
by **hook alias, not filename** — `UserPromptSubmit:branch_prompt` fires `prompt/branch_loader.py`,
`identity_injector` fires `prompt/identity.py`. The two lists do not line up by name, which is the
second reason not to restate them here. Read the directory, or ask @hooks.

**The one that concerns this branch:** `lifecycle/auto_fix.py` (PostToolUse) runs
`drone @seedgo checklist <file>` against every edited file. That gate is what `checklist` feeds.


---

## Tests

- **57 test files, 2362 tests** — 2573 passed, 1 skipped (2574 collected with parametrised cases expanded; run 2026-08-30)
- **0 type errors** (pyright, via the audit pipeline)
- Key test areas: standards audit, checklist, bypass, JSON handler, hooks snapshot, permissions, proof, README, diagnostics, line coverage (plugin integrity, diagnostics, audit display, branch audit, architecture, checklist)

---

## Integration Points

### Depends On
- `aipass.cli` — Rich console, header formatting
- `aipass.prax` — Structured logging via `logger`
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

## Known Issues / Tech Debt

Full detail and status live in **APLAN-0005** (the standing branch health record).

- `seedgo proof aipass` reports **NOT CERTIFIED** — the auditor does not currently pass its own proof pack:
  - `readme_currency` fails on three counts, and only the first is a plain detector bug.
    (a) It recognises standard names only in a `pack checks:` prose format this README
    does not use, so 44 of the 45 standards in the table above read as "undocumented".
    (b) It scrapes any number near a pack reference as the claimed check count, so the
    "7 standards have no `.md`" line below is read as "README says 7, actual is 45".
    (c) It harvests **this bullet** into `stale_refs` — describing the detector's own bug
    in the README makes the detector fail harder. A checker cannot tell a document from
    a document *about* the document; see also `rich_markup` on `# BAD` examples.
  - `triplet` (live 2026-08-25: 37 complete | 1 check-only | 1 missing-check |
    7 other-incomplete | 2 orphaned | 46 total): **7** standards have no `.md` —
    cli_ux, gateway_boundary, hardcoded_path, json_structure, readme_quality,
    rich_markup, subcommand_help. `gateway_boundary` is the newest and shipped without
    one on 08-18. The `ruff`/`ruff_check` name split reports as 1 check-only +
    1 missing-check. The 2 **orphans** are `applicability.py` and `skip_dirs.py` —
    shared infrastructure that lives in the pack directory without being standards,
    which the triplet proof has no category for.
- `standard ruff` returns "Unknown standard" while the audit displays the standard as `Ruff` (see the naming-split note above).
- `--help` advertises `drone @seedgo diagnostics @flow`, but the module rejects a branch argument — standalone diagnostics runs only through the audit pipeline.
- ~~`permissions.py` introspection leak~~ — **fixed 2026-08-13 (S80).** The gate keyed on
  the arguments, never the command name, so the trust list printed above every bare
  subcommand while `drone @seedgo permissions` answered "Unknown command" *and then*
  printed the block. It now claims its own command and is silent for every other.
- This README has no auto-update markers, so `drone @seedgo readme check @seedgo` skips every section — the branch that ships README generation does not consume it.
- **No bypass-rot detection, and the obvious detector is wrong.** Nothing tells a branch
  that a bypass rule has stopped suppressing anything. The tempting measurement — re-run
  the audit with `bypass_rules=[]` and match each rule against the resulting violation
  records — was run against this branch's own 28 rules and called 6 of them dead. Five
  were live: four suppress real failures in the **checklist** lane (the audit walks
  `apps/`, the PostToolUse hook checks `tests/`), and one guards `dead_code`, a
  branch-level standard that reports through `checks[].message` prose rather than a
  `*_violations` list — removing it drops that standard 100 → 95. A rot detector must
  read both lanes and canary branch-level standards through `check_branch()`. See
  APLAN-0005.
- `audit_display.py`: **the DPLAN-0047 dynamic refactor has landed** — this line claimed
  16 hardcoded per-standard display blocks; the file now derives every standard from its
  `<name>_violations` key and renders it generically, with exactly **one** special case left
  (`architecture`, which needs its own renderer). Corrected 2026-08-25 by reading the file;
  the change is not attributed here because this branch's memory does not record who made it.
- `documentation_check.py` multi-line signature lookahead is **30 lines**, not the 5 this
  line claimed (`documentation_check.py:146`). Still a bounded window, still a limitation —
  just six times wider than documented.
- `dead_code_check.py` recognises `glob("*.py")` as a discovery pattern but **not**
  `iterdir()` — verified still true 2026-08-25.
- ~~Cross-branch file write detection recommended but not yet in standards (S73 finding)~~ —
  **shipped as the `gateway_boundary` standard, 2026-08-18.** It is the 45th checker and the
  one this README's own table had been missing.

---

## Latest Audit (2026-08-25)

- **Seedgo score:** 100% (45 standards + diagnostics, 129 files) — all standards green
- **Tests:** 2573 passed, 1 skipped (2362 test functions across 57 files)
- **Coverage:** 417 public functions, 341 tested (82%)
- **Type errors:** 0
- **Proof:** NOT CERTIFIED — 3 of 5 proofs pass (see Known Issues)
- **Bypass:** 28 rules. The removed-rules measurement — every rule live in the lane it names,
  and **98%** (94 suppressed violations) with all of them stripped — was taken on 08-13 at
  27 rules and is **not re-run here**. The 100% above is still a real score with 28 documented
  exceptions under it, not a clean sheet.

---

**Last Updated:** 2026-08-25

---
[<- Back to AIPass](../../../README.md)
