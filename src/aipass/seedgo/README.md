# Seedgo

**Purpose:** Standards compliance platform for AIPass modules. Audits Python code against checker packs, scores each file, and reports violations. Ships with the `aipass_standards` pack (32 checkers covering imports, architecture, naming, logging, documentation, and more).
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
│   │   ├── seedgo_proof.py          # Proof orchestrator
│   │   ├── proof_query.py           # Proof content query
│   │   ├── readme_update.py         # README generation
│   │   └── test_map.py              # Custom function test coverage mapping
│   └── handlers/
│       ├── aipass_standards/        # Built-in checker pack (32 standards)
│       │   ├── *_check.py           # Checker implementations (score 0-100)
│       │   ├── *_content.py         # Queryable standard content
│       │   └── *.md                 # Standard documentation
│       ├── audit/                   # Audit implementation
│       │   ├── branch_audit.py      # Per-branch scoring
│       │   ├── discovery.py         # Branch discovery
│       │   └── audit_display.py     # Result formatting
│       ├── aipass_proof/             # Proof pack (README currency, etc.)
│       ├── bypass/                  # Bypass system
│       │   ├── bypass_handler.py    # .seedgo/bypass.json loader
│       │   └── ignore_handler.py    # .seedgo/ignore patterns
│       ├── config/                  # Configuration handlers
│       ├── diagnostics/             # Pyright integration
│       ├── file/                    # File operations
│       ├── json/                    # JSON tracking
│       └── test_map/                # Function test coverage scanner
├── drone_adapter.py                 # Drone routing bridge
├── .trinity/                        # Memory files
└── README.md
```

### Pack Discovery Convention

Checker packs live in `handlers/*_standards/` directories. A valid pack must contain at least one `*_check.py` file. The `standards_audit` module strips the `_standards` suffix for the pack name used in commands (e.g., `aipass_standards/` → `audit aipass`). The `standards_query` module uses the full directory name (e.g., `standards_query aipass_standards`).

---

## Checker Packs

The `aipass_standards` pack checks: architecture, CLI, CLI flags, commented logger, dead code, debug print, deep nesting, documentation, encapsulation, error handling, handlers, hardcoded key, help text, imports, introspection, JSON structure, log handler, log level, log structure, log visibility, meta, modules, naming, permission flags, readme, shebang, silent catch, stderr routing, test quality, todo, trigger, and unused function.

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

## Proof System

The `seedgo_proof` module orchestrates proof checks and `proof_query` provides content queries against the `aipass_proof/` handler pack. Proof checks verify triplet completeness (passport + local + observations), interface compliance, plugin integrity, content naming conventions, and README currency. Results are scored per-branch like standard audits.

---

## Diagnostics

The `diagnostics_audit` module runs pyright type checking across branches via handlers in the `diagnostics/` directory. Reports type errors, missing imports, and signature mismatches. Integrated into the audit pipeline as a separate diagnostic pass.

---

## Bypass System

The `bypass/` handler directory contains `bypass_handler.py` and `ignore_handler.py`. These manage `.seedgo/bypass.json` files per branch, allowing specific files, standards, or lines to be exempted from audit scoring. Each bypass requires a documented reason and is tracked in audit output.

---

## Checklist

The `checklist` module provides quick per-file or per-directory standards checks. Designed for consumption by auto-fix hooks and pre-commit validation, returning pass/fail results without full audit overhead.

---

## Test Map

The `test_map` module and `test_map/` handler directory provide custom function-level test coverage mapping. Scans public functions in source files and cross-references them against test files to identify untested functions and coverage gaps.

---

**Last Updated:** 2026-03-29
