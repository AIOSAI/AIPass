[<- Back to AIPass](../../../README.md)

# Seedgo

**Purpose:** Standards compliance platform for AIPass. Audits all 11 core agents against 35 code standards + diagnostics, manages bypass rules, runs proof certification, owns the hook system, and provides per-file checklist validation consumed by auto-fix hooks.
**Module:** `aipass.seedgo`
**Version:** 2.0.0
**Created:** 2026-03-05

---

## Overview

### What I Do
- Audit all 11 core agents against 35 code standards + diagnostics (architecture, CLI, imports, logging, naming, silent catch, deep nesting, etc.)
- Score files 0-100 per standard and report violations with actionable details
- Manage bypass rules (`.seedgo/bypass.json`) for deliberate exceptions
- Run pyright diagnostics across branches for type error detection
- Own the hook system: auto-fix diagnostics, edit gate, subagent stop gate, bridge installer
- Single-file checklist validation against all standards (consumed by PostToolUse auto-fix hook)
- Proof certification via proof/proof_query (triplet, plugin integrity, README currency)
- Custom function test coverage mapping via test_map
- README auto-generation and freshness checking
- Hook testing, listing, and probe infrastructure

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
drone @seedgo audit aipass                             # Audit all 11 agents (35 standards + diagnostics)
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

# Hooks
drone @seedgo hooks test                               # Run hook test suite (pytest per file)
drone @seedgo hooks list                               # Show all wired hooks from settings
drone @seedgo hooks probe                              # Hook event probe infrastructure

# Bridge
drone @seedgo bridge install                           # Install AIPass hooks to ~/.claude/settings.json
drone @seedgo bridge uninstall                         # Remove AIPass hooks
drone @seedgo bridge reinstall                         # Clean reinstall
drone @seedgo bridge status                            # Show hook installation status
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
│   ├── modules/                     # 13 business logic modules
│   │   ├── standards_audit.py       # Pack-aware compliance audit orchestrator
│   │   ├── standards_query.py       # Pack-aware content query
│   │   ├── diagnostics_audit.py     # Pyright diagnostics via audit pipeline
│   │   ├── checklist.py             # Per-file/dir standards check (hook consumer)
│   │   ├── seedgo_proof.py          # Proof certification orchestrator
│   │   ├── proof_query.py           # Proof content query
│   │   ├── hook_bridge.py           # Hook bridge installer (install/uninstall/reinstall/status)
│   │   ├── hooks.py                 # Hook probe display and testing
│   │   ├── hooks_ext.py             # Hook test + list subcommands (split from hooks.py)
│   │   ├── inbox_audit.py           # Inbox message-ID validation
│   │   ├── permissions.py           # TRUSTED_CROSS_WRITERS list for hook + drone auth
│   │   ├── readme_update.py         # README generation module
│   │   └── test_map.py              # Custom function test coverage mapping
│   └── handlers/                    # 11 handler directories
│       ├── aipass_standards/        # 34 checker standards (67 files)
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
│       ├── bypass/                  # Bypass system
│       │   ├── bypass_handler.py    # .seedgo/bypass.json loader
│       │   └── ignore_handler.py    # .seedgo/ignore patterns
│       ├── config/                  # Configuration handlers
│       ├── diagnostics/             # Pyright integration + branch discovery
│       ├── file/                    # File operations
│       ├── hooks/                   # Hook test runner
│       ├── json/                    # JSON tracking (json_handler)
│       ├── readme/                  # README generator + branch resolution
│       └── test_map/                # Function test coverage scanner
├── tests/                           # 39 test files, 1192 tests
├── drone_adapter.py                 # Drone routing bridge
├── .trinity/                        # Identity + memory
├── .seedgo/                         # Self-bypass rules
├── .ai_mail.local/                  # Mailbox
├── CLAUDE.md                        # Branch startup instructions
└── STATUS.local.md                  # Current state summary
```

### Key Patterns

**Module auto-discovery:** `discover_modules()` in seedgo.py loads all `.py` files from `apps/modules/`. Each module's `handle_command(command, args)` is called in discovery order; first returning `True` wins.

**Pack discovery:** Checker packs live in `handlers/*_standards/` directories. `standards_audit` strips the `_standards` suffix for command routing (`aipass_standards/` -> `audit aipass`). `standards_query` uses the full directory name (`standards_query aipass_standards`).

**CWD-first registry:** `_find_registry()` walks CWD parents first (for external project support), falls back to `__file__` parents, uses `*_REGISTRY.json` glob (not hardcoded name).

**Bypass system:** `.seedgo/bypass.json` per branch. Each entry has file, standard, optional lines, and required reason. Checkers call `is_bypassed()` per violation. Bypass is intentional documented deviation, not ignoring.

---

## The 34 Standards

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
| help_text | all_files | --help content quality |
| imports | all_files | Import ordering and grouping |
| introspection | entry_point | No-args introspection gate |
| json_structure | all_files | json_handler import + log_operation calls |
| log_handler | all_files | Prax logger usage (not stdlib logging) |
| log_level | all_files | Correct log level usage |
| log_structure | all_files | Structured log message format |
| log_visibility | all_files | Log output in key operations |
| meta | all_files | File header metadata block |
| modules | all_files | Module structure and naming |
| naming | all_files | snake_case, column-0 constants |
| permission_flags | all_files | No dangerous permission overrides |
| readme | branch_level | README.md exists and is current |
| ruff | branch_level + per-file | Ruff linter compliance |
| shebang | all_files | No shebang lines in library code |
| silent_catch | all_files | No bare except/pass patterns |
| stderr_routing | all_files | Proper stderr vs stdout usage |
| test_quality | branch_level | JSON handler test coverage (51 items, 11 categories) |
| todo | all_files | No unresolved TODO/FIXME/HACK comments |
| trigger | all_files | Trigger integration patterns |
| unused_function | branch_level | No unreferenced public functions |

---

## Hook Ownership

Seedgo owns the AIPass hook system. Canonical runtime location: `AIPass/.claude/hooks/`.

| Hook | Event | What It Does |
|------|-------|--------------|
| auto_fix_diagnostics.py v5.2.0 | PostToolUse (Edit/Write) | py_compile + ruff + pattern checks + `drone @seedgo checklist` + pyright. Saves state for edit gate |
| pre_edit_gate.py v1.3.0 | PreToolUse (Edit/Write) | Blocks edits to other files while type errors exist. Cross-branch inbox write protection |
| subagent_stop_gate.py v1.0 | SubagentStop | Runs checklist on modified .py files, blocks stop until clean |
| branch_prompt_loader.py | UserPromptSubmit | Injects `.aipass/aipass_local_prompt.md` when CWD is in a branch |
| identity_injector.py | UserPromptSubmit | Injects passport identity block |
| email_notification.py | UserPromptSubmit | Inbox banner |
| pre_compact.py | PreCompact | Memory archival prep |
| notification_sound.py | Notification | Sound effect |
| stop_sound.py | Stop | Sound effect |
| tool_use_sound.py | PreToolUse | Sound effect |

The `bridge` module (`drone @seedgo bridge install`) manages hook installation to `~/.claude/settings.json` using the AIPASS_HOOK_MANIFEST (13 entries across 7 events).

---

## Tests

- **39 test files**, **1192 tests**, all passing
- **200 public functions**, 200 tested (100% coverage)
- **0 type errors** (pyright)
- Key test areas: standards audit, checklist, bypass, JSON handler, hooks (probe, track A/B/E, utility, bridge), proof, README, diagnostics, line coverage (plugin integrity, diagnostics, audit display, branch audit, architecture, checklist)

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
- Hook location drift: `~/.claude/hooks/` vs `AIPass/.claude/hooks/` (DPLAN-0131)
- `proof`, `proof_query`, `test_map` not listed in `--help` output
- `documentation_check.py` 5-line lookahead limitation for multi-line function signatures
- `dead_code_check.py` doesn't recognize `iterdir()` as valid discovery pattern
- Cross-branch file write detection recommended but not yet in standards (S73 finding)
- Test coverage: 200/200 public functions (100%) but line coverage still has gaps in 6 handler files

---

## Latest Audit (2026-04-26)

- **Seedgo score:** 100% (34/34 + diagnostics) — all standards green
- **Tests:** 1131 passed, 0 failed, 0 skipped
- **Coverage:** 200 public functions, 200 tested (100%)
- **Type errors:** 0

---

**Last Updated:** 2026-05-16

---
[<- Back to AIPass](../../../README.md)
