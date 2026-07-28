[<- Back to AIPass](../../../README.md)

# Seedgo

**Purpose:** Standards compliance platform for AIPass. Audits all 11 core agents against 42 code standards + diagnostics, manages bypass rules, runs proof certification, and provides per-file checklist validation consumed by the PostToolUse auto-fix gate.
**Module:** `aipass.seedgo`
**Version:** 2.0.0
**Created:** 2026-03-05

---

## Quick Start

```bash
drone @seedgo audit aipass              # Audit all branches against all standards
drone @seedgo checklist <file>          # Check a single file
drone @seedgo standards_query aipass_standards cli  # Look up what a standard checks
```

---

## Overview

### What I Do
- Audit all 11 core agents against 40 code standards + diagnostics (architecture, CLI, imports, logging, naming, silent catch, deep nesting, etc.)
- Score files 0-100 per standard and report violations with actionable details
- Manage bypass rules (`.seedgo/bypass.json`) for deliberate exceptions
- Run pyright diagnostics across branches for type error detection
- Single-file checklist validation against all standards (consumed by PostToolUse auto-fix hook)
- Proof certification via proof/proof_query (triplet, plugin integrity, README currency)
- Custom function test coverage mapping via test_map
- README auto-generation and freshness checking

### What I Don't Do
- Runtime monitoring (that's prax)
- Code execution or deployment

---

## Commands

All commands available via `drone @seedgo <command>` or `python3 -m aipass.seedgo <command>`.

### Via Drone (primary)

```bash
drone @seedgo                                          # Introspection (module list, version)
drone @seedgo --help                                   # Full command listing
drone @seedgo --version                                # Version string

# Audit
drone @seedgo audit aipass                             # Audit all 11 agents (40 standards + diagnostics)
drone @seedgo audit aipass @flow                       # Audit single branch
drone @seedgo audit inbox-ids                          # Inbox message-ID validation

# Standards Query
drone @seedgo standards_query aipass_standards         # List all 33 standards in pack
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

# README
drone @seedgo readme update @flow                      # README auto-generation for a branch
```

### Via Python Module

```bash
python3 -m aipass.seedgo audit aipass                  # Same commands, direct execution
python3 -m aipass.seedgo standards_query aipass_standards cli
```

> **Note:** `proof`, `proof_query`, and `test_map` commands work but are not listed in `--help` output (known TODO).

---

## Architecture

```
seedgo/
├── apps/
│   ├── seedgo.py                    # Entry point — thin router (~290 lines)
│   │                                #   discover_modules() loads apps/modules/*.py
│   │                                #   route_command() dispatches to first handler returning True
│   ├── modules/                     # 10 business logic modules
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
│   └── handlers/                    # 9 handler directories
│       ├── aipass_standards/        # 40 checker standards (120 files)
│       │   ├── *_check.py           # Checker implementations (score 0-100)
│       │   ├── *_content.py         # Queryable standard content
│       │   └── *.md                 # Standard documentation
│       ├── aipass_proof/            # 5 proof validators (11 files)
│       │   ├── triplet.py           # .trinity/ completeness
│       │   ├── interface.py         # AUDIT_SCOPE + function signatures
│       │   ├── plugin_integrity.py  # No hardcoded standard names
│       │   ├── content_naming.py    # Function naming conventions
│       │   └── readme_currency.py   # README freshness
│       ├── audit/                   # Audit implementation
│       │   ├── branch_audit.py      # Per-branch scoring engine
│       │   ├── discovery.py         # Branch discovery (CWD-first registry)
│       │   └── audit_display.py     # Rich result formatting
│       ├── bypass/                  # Bypass + ignore systems
│       │   ├── bypass_handler.py    # .seedgo/bypass.json loader
│       │   └── ignore_handler.py    # Audit ignore patterns + .seedgoignore engine
│       ├── config/                  # Configuration handlers
│       ├── diagnostics/             # Pyright integration + branch discovery
│       ├── json/                    # JSON tracking (json_handler)
│       ├── readme/                  # README generator + branch resolution
│       └── test_map/                # Function test coverage scanner
├── tests/                           # 38 test files, 1217 tests
├── drone_adapter.py                 # Drone routing bridge
├── .trinity/                        # Identity + memory
├── .seedgo/                         # Self-bypass rules
├── .ai_mail.local/                  # Mailbox
└── CLAUDE.md                        # Branch startup instructions
```

### Key Patterns

**Module auto-discovery:** `discover_modules()` in seedgo.py loads all `.py` files from `apps/modules/`. Each module's `handle_command(command, args)` is called in discovery order; first returning `True` wins.

**Pack discovery:** Checker packs live in `handlers/*_standards/` directories. `standards_audit` strips the `_standards` suffix for command routing (`aipass_standards/` -> `audit aipass`). `standards_query` uses the full directory name (`standards_query aipass_standards`).

**CWD-first registry:** `_find_registry()` walks CWD parents first (for external project support), falls back to `__file__` parents, uses `*_REGISTRY.json` glob (not hardcoded name).

**Bypass system:** `.seedgo/bypass.json` per branch. Each entry has file, standard, optional lines, and required reason. Checkers call `is_bypassed()` per violation. Bypass is intentional documented deviation, not ignoring.

**`.seedgoignore` (throwaway paths, no reason required):** Drop a `.seedgoignore` file into any directory to exclude matching files/dirs from scans, audits, and the per-file checklist — same gitignore-style patterns and per-directory nesting semantics as a real `.gitignore` (via `pathspec`). Scope is exactly that directory's subtree; a nested `.seedgoignore` adds further excludes on top of any ancestor's, it doesn't replace them. A global default (`tools/`) applies fleet-wide with zero setup, since every branch's `apps/tools/` is deliberate throwaway prototyping space — quick scripts for fast answers, not standards-compliant by design. Unlike bypass (documented exception to a specific standard on a specific file), `.seedgoignore` removes the file from consideration entirely and needs no reason. It does **not** touch diagnostics (ruff/pyright) — those keep running on ignored files so auto-fix still catches real errors while you write; only standards checks skip them. See `ignore_handler.load_ignore_entries()` / `is_seedgo_ignored()`.

---

## The 40 Standards

| Standard | Scope | What It Checks |
|----------|-------|----------------|
| architecture | entry_point | Module/handler separation, entry point structure |
| cli | all_files | Rich console usage, no bare print() |
| cli_flags | entry_point | --help, --version flag handling |
| commented_logger | all_files | No commented-out logger/logging calls |
| dead_code | branch_level | Unreachable functions and dead imports |
| debug_print | all_files | No debug print/pprint statements |
| deep_nesting | all_files | Max nesting depth 4 (AST-measured) |
| documentation | all_files | Docstrings on public functions |
| encapsulation | all_files | No cross-branch imports, proper isolation |
| error_handling | all_files | Try/except patterns, error propagation |
| handler_import | branch_level | apps/__init__.py contains `from . import handlers` |
| handlers | entry_point | Handler directory structure |
| hardcoded_key | all_files | No hardcoded API keys or secrets |
| hardcoded_path | all_files | No hardcoded absolute paths |
| help_text | all_files | --help content quality |
| imports | all_files | Import ordering and grouping |
| introspection | entry_point | No-args introspection gate |
| json_handler | branch_level | JSON handler test coverage validation |
| json_structure | all_files | json_handler import + log_operation calls |
| log_handler | all_files | Prax logger usage (not stdlib logging) |
| log_level | all_files | Correct log level usage |
| log_structure | all_files | Structured log message format |
| log_visibility | all_files | Log output in key operations |
| meta | all_files | File header metadata block |
| modules | all_files | Module structure and naming |
| naming | all_files | snake_case, column-0 constants |
| output_routing | all_files | Status output via @cli helpers, not raw console.print |
| permission_flags | all_files | No dangerous permission overrides |
| readme | branch_level | README.md exists and is current |
| ruff | branch_level + per-file | Ruff linter compliance |
| shebang | all_files | No shebang lines in library code |
| silent_catch | all_files | No bare except/pass patterns |
| stderr_routing | all_files | Proper stderr vs stdout usage |
| subcommand_help | entry_point | Subcommand --help interception before dispatch |
| template | branch_level | No unresolved spawn template markers |
| test_quality | branch_level | JSON handler test coverage (51 items, 11 categories) |
| todo | all_files | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | Trigger integration patterns |
| unused_function | branch_level | No unreferenced public functions |
| windows_compat | all_files | Cross-platform compatibility (no Unix-only APIs) |

---

## Hook Architecture

The **hooks branch** (`src/aipass/hooks/`) owns all hook infrastructure — engine, bridge, and 14 native handlers. Seedgo audits hooks via standards but does not own the hook system.

Provider settings route all events through the bridge (`claude.py`), which dispatches to native Python handlers:

| Handler | Event | Category |
|---------|-------|----------|
| `prompt.global_loader` | UserPromptSubmit | prompt |
| `prompt.branch_loader` | UserPromptSubmit | prompt |
| `prompt.identity` | UserPromptSubmit | prompt |
| `notification.email` | UserPromptSubmit | notification |
| `security.edit_gate` | PreToolUse | security |
| `security.git_gate` | PreToolUse | security |
| `lifecycle.auto_fix` | PostToolUse | lifecycle |
| `lifecycle.auto_watchdog` | PostToolUse | lifecycle |
| `security.subagent_gate` | SubagentStop | security |
| `notification.stop_sound` | Stop | notification |
| `notification.announce` | Notification | notification |
| `notification.tool_sound` | PreToolUse | notification |
| `lifecycle.compact` | PreCompact | lifecycle |
| `lifecycle.rollover` | PreCompact | lifecycle |

---

## Tests

- **38 test files**, all passing
- **0 type errors** (pyright)
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
- `aipass.drone` — in-process routing via `drone_adapter.py`

---

## Known Issues / Tech Debt

- `audit_display.py`: 16 hardcoded display blocks for specific standards (DPLAN-0047 tracks dynamic refactor)
- `proof`, `proof_query`, `test_map` not listed in `--help` output
- `documentation_check.py` 5-line lookahead limitation for multi-line function signatures
- `dead_code_check.py` doesn't recognize `iterdir()` as valid discovery pattern
- Cross-branch file write detection recommended but not yet in standards (S73 finding)

---

## Latest Audit (2026-07-11)

- **Seedgo score:** 100% (40/40 + diagnostics) — all standards green
- **Tests:** 1217 passed, 0 failed, 0 skipped
- **Coverage:** 208 public functions, 197 tested (95%)
- **Type errors:** 0

---

**Last Updated:** 2026-07-11

---
[<- Back to AIPass](../../../README.md)
