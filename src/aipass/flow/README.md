[← Back to AIPass](../../../README.md)

# Flow

**Purpose:** Unified plan lifecycle management for AIPass. Creates, tracks, closes, and archives numbered work plans across multiple plan types via a filesystem-driven template registry. Foreground archival with vector intake verification, cross-branch aggregation, and self-healing registries.
**Module:** `aipass.flow`
**Created:** 2025-11-15
**Last Updated:** 2026-04-07

---

## Overview

### What I Do
- Create numbered plans from type-specific templates via `templates/` plugins
- Unified create/close/list commands for all plan types (FPLAN, DPLAN, RPLAN, TDPLAN, ...)
- Close plans with foreground archival to `backup/processed_plans/`
- Vector intake on close via `drone @memory process-plans` with chroma verification
- List and filter plans across branches and plan types
- Restore plans from backups
- Template registry management: register, unregister, scan, auto-heal
- Aggregate plans across branches
- `--dry-run` for close preview

## Commands / Usage

```bash
# Create plans
drone @flow create . "Subject"                  # Create FPLAN (default)
drone @flow create . "Subject" master           # Create FPLAN master template
drone @flow create . "Design topic" dplan       # Create DPLAN

# Close plans
drone @flow close FPLAN-0042                    # Close specific plan
drone @flow close DPLAN-0005                    # Close a DPLAN
drone @flow close --all                         # Close all open plans
drone @flow close --all --dry-run               # Preview what would close

# List plans
drone @flow list open                           # List open plans (all types)
drone @flow list all                            # List all plans

# Template management
drone @flow templates                           # List registered types
drone @flow scan                                # Find unregistered directories
drone @flow register <dir> <PREFIX>             # Register new plan type
drone @flow unregister <dir>                    # Remove plan type

# Other
drone @flow restore FPLAN-0042                  # Reopen a closed plan
drone @flow aggregate                           # Cross-branch plan aggregation
drone @flow --help                              # Full help
```

---

## Architecture

```
flow/
├── apps/
│   ├── flow.py                  # Entry point (auto-discovers modules)
│   ├── modules/                 # Business logic (thin orchestrators)
│   │   ├── create_plan.py       # Plan creation with template support
│   │   ├── close_plan.py        # Closure with foreground archival + vector verify
│   │   ├── list_plans.py        # Plan listing and filtering
│   │   ├── restore_plan.py      # Plan recovery from backups
│   │   ├── registry_monitor.py  # Orphan detection, auto-healing
│   │   ├── aggregate_central.py # Cross-branch plan aggregation
│   │   ├── post_close_runner.py # Background post-processing *(partial — archival moved to foreground)*
│   │   └── template_manager.py  # Template registry management
│   └── handlers/                # Implementation details
│       ├── plan/                # Lifecycle, file ops, validation, close_ops
│       ├── registry/            # Load, save, auto-heal
│       ├── template/            # Plan type loader + template resolution + registry_ops
│       ├── dashboard/           # Status aggregation
│       ├── mbank/               # Memory archival
│       └── json/                # Auto-creating JSON handler
├── templates/                   # Plan type plugins (DATA, not code)
│   ├── flow_plans/              # FPLAN templates (default, master)
│   ├── dev_plans/               # DPLAN templates (default)
│   ├── research_plans/          # RPLAN templates (default)
│   ├── team_dev_plans/          # TDPLAN templates (default)
│   └── audit_plans/             # Unregistered — needs `drone @flow register`
├── flow_json/                   # Per-type registries + template_registry.json
├── tests/                       # 452 tests, 90/90 functions covered
├── docs/                        # Documentation
└── .archive/                    # Archived legacy code
```

---

## Plan Types

Plan types are filesystem-driven. Drop a directory with `.md` templates into `templates/`, register it with a prefix. No per-directory JSON config needed.

| Type | Prefix | Registry | Templates |
|------|--------|----------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |
| research_plans | RPLAN | rplan_registry.json | default |
| team_dev_plans | TDPLAN | tdplan_registry.json | default |

Plans follow the convention `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md` where NNNN is auto-incrementing per type.

### Auto-heal
- Template registry auto-prunes orphaned types (directory deleted → entry + plan registry JSON removed on next command)
- Plan registries auto-close entries for missing files

---

## Close Pipeline

On `drone @flow close`:
1. Template check (fast-delete empty templates)
2. Mark as closed in registry
3. Archive to `backup/processed_plans/` (foreground, sets processed/cleanup flags atomically)
4. Vector intake: `drone @memory process-plans` + `is_plan_vectorized()` verification
5. Dashboard updates (local + central + branch)
6. Append to `CLOSED_PLANS.local.json`

---

## Integration Points

### Depends On
- `aipass.cli` -- Terminal formatting (console, header, success, error)
- `aipass.prax` -- Structured logging via `system_logger`
- `aipass.trigger` -- Error reporting (optional)
- `aipass.memory` -- Vector intake on plan close (`process-plans` + `verify`)
- Python stdlib (`pathlib`, `json`, `importlib`, `sys`, `signal`, `subprocess`, `shutil`)

### Provides To
- All branches -- Plan creation, tracking, closure, and archival
- `aipass.devpulse` -- Plan status aggregation for system dashboards
- Registry: Per-type registries in `flow_json/`

---

## Quality

- **Seedgo:** 100% (all 33 standards)
- **Tests:** 452 tests, 90/90 public functions covered
- **Last audit:** 2026-04-09

---

*Last Updated: 2026-04-07*

---
[← Back to AIPass](../../../README.md)
