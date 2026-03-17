# Seedgo

**Purpose:** Standards compliance platform for AIPass modules. Audits Python code against checker packs, scores each file, and reports violations. Ships with the `aipass_standards` pack (24 checkers covering imports, architecture, naming, logging, documentation, and more).
**Module:** `aipass.seedgo`
**Created:** 2026-03-05

---

## Overview

### What I Do
- Audit Python modules against checker packs via auto-discovered modules
- Score files and report violations with actionable details
- Query standard content by pack and name
- Support bypass rules for deliberate exceptions

## Commands / Usage

Seedgo provides standards auditing, content queries, per-file checklists, diagnostics, and README generation.

### CLI

```bash
seedgo --help                                          # Show usage
seedgo --version                                       # Show version

# Audit
seedgo audit                                           # Show available checker packs
seedgo audit aipass                                    # Audit all branches
seedgo audit aipass flow                               # Audit single branch

# Query Standards
seedgo standards_query                                 # List available packs
seedgo standards_query aipass_standards                 # List standards in pack
seedgo standards_query aipass_standards architecture    # Show standard content
```

### Via Drone

```bash
drone @seedgo                                          # Introspection
drone @seedgo --help                                   # Full help
drone @seedgo audit aipass                             # Audit all branches
drone @seedgo audit aipass @spawn                      # Audit specific branch
drone @seedgo standards_query aipass_standards cli      # Show standard content
```

---

## Architecture

```
seedgo/
├── apps/
│   ├── seedgo.py                    # Entry point — module discovery + routing
│   ├── modules/
│   │   ├── standards_audit.py       # Pack-aware compliance audit
│   │   ├── standards_query.py       # Pack-aware content query
│   │   ├── diagnostics_audit.py     # Pyright diagnostics
│   │   ├── checklist.py             # Per-file standards checklist (hook consumption)
│   │   └── readme_update.py         # README generation
│   └── handlers/
│       ├── aipass_standards/        # Built-in checker pack (17 standards)
│       │   ├── *_check.py           # Checker implementations (score 0-100)
│       │   ├── *_content.py         # Queryable standard content
│       │   └── *.md                 # Standard documentation
│       ├── audit/                   # Audit implementation
│       │   ├── branch_audit.py      # Per-branch scoring
│       │   ├── discovery.py         # Branch discovery
│       │   └── audit_display.py     # Result formatting
│       ├── bypass/                  # Bypass system
│       │   ├── bypass_handler.py    # .seedgo/bypass.json loader
│       │   └── ignore_handler.py    # .seedgo/ignore patterns
│       ├── config/                  # Configuration handlers
│       ├── diagnostics/             # Pyright integration
│       ├── file/                    # File operations
│       └── json/                    # JSON tracking
├── drone_adapter.py                 # Drone routing bridge
├── .trinity/                        # Memory files
└── README.md
```

### Pack Discovery Convention

Checker packs live in `handlers/*_standards/` directories. A valid pack must contain at least one `*_check.py` file. The `standards_audit` module strips the `_standards` suffix for the pack name used in commands (e.g., `aipass_standards/` → `audit aipass`). The `standards_query` module uses the full directory name (e.g., `standards_query aipass_standards`).

---

## Checker Packs

The `aipass_standards` pack checks: architecture, CLI, CLI flags, documentation, encapsulation, error handling, handlers, imports, introspection, JSON structure, log handler, log level, log structure, log visibility, meta, modules, naming, permission flags, readme, shebang, stderr routing, testing, trigger, and diagnostics patterns.

New packs go in `handlers/<name>_standards/` — add `*_check.py` files that implement scoring functions, and optionally `*_content.py` files that provide `get_<name>_standards()` for content queries.

---

## Integration Points

### Depends On
- `aipass.cli` — Rich-based display formatting (`console`, `header`)
- `aipass.prax` — Structured logging via `logger`
- `aipass.drone` — Branch resolution via `normalize_branch_arg`
- Python stdlib (`pathlib`, `sys`, `importlib`)

### Provides To
- All modules — standards auditing via `seedgo audit <pack>`
- All modules — content queries via `seedgo standards_query <pack> <standard>`
- `aipass.drone` — routed via `drone @seedgo` (registered as internal module)

---

**Last Updated:** 2026-03-17
