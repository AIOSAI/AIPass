[< Back to AIPass](../../../README.md)

# DevPulse

**Purpose:** Orchestration hub for the AIPass ecosystem
**Module:** `aipass.devpulse`
**Status:** Active
**Last Updated:** 2026-03-22

---

## Overview

DevPulse is the central coordination branch for AIPass. It plans, delegates, and tracks work across all 15 branches in the ecosystem. Think of it as the project manager — it doesn't build modules itself, but dispatches work to branch agents, monitors results, and maintains system-wide visibility.

### What DevPulse Does
- **Cross-branch orchestration** — Dispatch tasks to branches via AI Mail + wake
- **System-wide planning** — Create and manage DPLANs (design) and FPLANs (execution)
- **Diagnostic tooling** — 20 standalone scanners for code quality, security, and compliance
- **Status tracking** — Session history, branch audits, system health
- **Architecture discussions** — Work with the user on design decisions
- **Agent coordination** — Deploy sub-agents in parallel for research and builds

---

## Managed Directory — `src/aipass/`

DevPulse orchestrates all branches under `src/aipass/`:

```
src/aipass/
├── drone/          # Command routing — @ resolution, branch dispatch
├── seedgo/         # Standards & compliance — audits, checkers, packs
├── prax/           # Logging system — stack introspection, dual routing
├── cli/            # CLI framework — argument parsing, command registry
├── flow/           # Plan management — FPLANs, DPLANs, templates, tracking
├── ai_mail/        # Inter-branch comms — inbox, dispatch, wake
├── api/            # API layer — OpenRouter, Google, usage tracking
├── trigger/        # Event system — log watchers, event handlers
├── spawn/          # Branch lifecycle — create, update, delete, passport
├── devpulse/       # Orchestration hub (you are here)
├── daemon/         # Background scheduler — cron, plugins, monitoring
├── backup/         # Backup & archival utilities
├── memory/         # Memory bank — ChromaDB vectors, rollover, search
└── __init__.py

src/commons/        # Shared utilities — config, database, helpers
src/skills/         # Skill system — discovery, registry, lifecycle
```

**15 registered branches:** drone, seedgo, prax, cli, flow, ai_mail, api, trigger, spawn, devpulse, daemon, backup, memory, commons, skills

## DevPulse Architecture

```
devpulse/
├── .trinity/              # Identity + memory
│   ├── passport.json      # Branch identity
│   ├── local.json         # Session history + key learnings
│   └── observations.json  # Collaboration patterns
├── .aipass/               # AI context
│   └── aipass_local_prompt.md
├── .spawn/                # Spawn metadata
├── tools/                 # Diagnostic scanner suite (20 tools)
├── docs/                  # Tracked documentation
├── docs.local/            # Working files (gitignored)
├── tests/
├── STATUS.local.md        # Current work, issues, todos
└── README.md
```

DevPulse has no `apps/` directory — it's a **manager** branch, not a builder. It coordinates via dispatch and sub-agents rather than implementing code.

---

## Diagnostic Tools

DevPulse maintains a suite of 20 standalone diagnostic scanners in `tools/`. Each follows the `{concern}_scanner_v1.py` naming convention and supports `@branch`, `--all`, and `--summary` flags.

### Code Quality
| Tool | What it checks |
|------|---------------|
| `silent_catch_scanner_v1.py` | Except blocks with no logging or raise |
| `silent_catch_scanner_v2.py` | Same + tier-aware grouping (entry/module/handler) |
| `commented_logger_scanner_v1.py` | Commented-out `# logger.*()` calls |
| `debug_print_scanner_v1.py` | Raw `print()` that should use Rich console |
| `deep_nesting_scanner_v1.py` | Functions with nesting depth > 3 |
| `long_function_scanner_v1.py` | Top N longest functions (informational) |
| `unused_function_scanner_v1.py` | Functions defined but never called |
| `dead_code_scanner_v1.py` | Module/handler files with zero references |
| `todo_scanner_v1.py` | TODO/FIXME/HACK/XXX comments |
| `fallback_scanner_v1.py` | Intentional silent fallback patterns |

### Security
| Tool | What it checks |
|------|---------------|
| `hardcoded_key_scanner_v1.py` | API key patterns in source (0 findings = good) |
| `partial_key_scanner_v1.py` | `key[:N]` partial display patterns |
| `url_injection_scanner_v1.py` | Unencoded URL params in f-strings |

### Documentation & Consistency
| Tool | What it checks |
|------|---------------|
| `help_text_scanner_v1.py` | `python3` refs that should be `drone @branch` |
| `readme_freshness_scanner_v1.py` | README date vs newest code file |
| `prompt_scanner_v1.py` | Local prompt quality (RICH/BASIC/STUB/MISSING) |
| `test_scanner_v1.py` | Pytest coverage per branch + module |
| `command_scanner_v1.py` | Verifies drone commands are routable |
| `magic_number_scanner_v1.py` | Hardcoded numbers (cross-file consistency) |
| `stale_scanner_v1.py` | Outdated terminology (17 tracked keywords) |

### Utilities
| Tool | What it does |
|------|-------------|
| `dev_central_to_devpulse.py` | Rename stale terms across files |
| `verify_branch.py` | Verify branch structure compliance |

**Tool classification:** Hard checks (pass/fail) vs Advisory (flag for investigation). See DPLAN-0030 for full details.

---

## Commands

```bash
# System status
drone systems                    # List all registered branches
drone @seedgo audit aipass       # Run full standards audit

# Flow plans
drone @flow create . "Subject"              # Create FPLAN (execution plan)
drone @flow create . "Subject" dplan        # Create DPLAN (design/planning)
drone @flow create . "Subject" master       # Create master plan (multi-phase)
drone @flow list open                       # List active plans

# Dispatch work
drone @ai_mail dispatch @target "Subject" "Body"    # Send + wake (one command)
drone @ai_mail email @target "Subject" "Body"       # Just mail, no wake
drone @ai_mail dispatch wake @target                # Wake only
drone @ai_mail dispatch wake --fresh @target        # Fresh session wake

# Branch management
drone @spawn create <path>       # Create new branch from template
drone @spawn update @branch      # Update branch scaffold
drone @spawn delete @branch      # Archive + deregister branch
```

---

## Integration Points

### Depends On
- `aipass.prax` — Logging (all logging goes through prax)
- `aipass.ai_mail` — Inter-branch communication + dispatch
- `aipass.flow` — Plan creation and tracking (DPLANs + FPLANs)
- `aipass.drone` — Command routing to all branches
- `aipass.spawn` — Branch lifecycle management
- `aipass.seedgo` — Standards verification + audit

### Coordinates
- All 15 branches: drone, seedgo, prax, cli, flow, ai_mail, api, trigger, spawn, devpulse, daemon, backup, memory, commons, skills

---

## Role

DevPulse is a **manager** branch, not a builder. It delegates code tasks to sub-agents and branch agents. Its context window is reserved for coordination, planning, and architecture — not for reading and editing files across the codebase.

The `tools/` directory is DevPulse's "tool shed" — standalone diagnostic scripts for investigating code quality across all branches. These tools surface patterns and create conversations. They're built for AI consumption: run a scanner, get instant visibility, decide what matters.

---
[< Back to AIPass](../../../README.md)
