# Flow

**Purpose:** Unified plan lifecycle management for AIPass. Creates, tracks, closes, and archives numbered work plans across multiple plan types (FPLAN, DPLAN, etc.) via a plugin architecture. Registry-backed state, async post-processing, vector intake on close, and cross-branch aggregation.
**Module:** `aipass.flow`
**Created:** 2025-11-15
**Last Updated:** 2026-03-24

---

## Overview

### What I Do
- Create numbered plans from type-specific templates via `templates/` plugins
- Unified create/close/list commands for all plan types (FPLAN, DPLAN, ...)
- Close plans with async post-processing and archival to `backup/processed_plans/`
- Vector processing on close (via `aipass.memory` intake pipeline)
- List and filter plans across branches and plan types
- Restore plans from backups
- Monitor registry health with orphan detection and auto-healing
- Aggregate plans across branches

## Commands / Usage

```bash
drone @flow create . "Subject"                  # Create FPLAN (default)
drone @flow create . "Subject" master           # Create FPLAN master template
drone @flow create . "Design topic" dplan       # Create DPLAN
drone @flow close FPLAN-0042                    # Close an FPLAN
drone @flow close DPLAN-0005                    # Close a DPLAN
drone @flow close --all                         # Close all open plans
drone @flow list open                           # List open plans
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
│   │   ├── close_plan.py        # Closure with async archival
│   │   ├── list_plans.py        # Plan listing and filtering
│   │   ├── restore_plan.py      # Plan recovery from backups
│   │   ├── registry_monitor.py  # Orphan detection, auto-healing
│   │   ├── aggregate_central.py # Cross-branch plan aggregation
│   │   ├── post_close_runner.py # Background post-processing
│   │   └── template_manager.py  # Template registry management
│   └── handlers/                # Implementation details
│       ├── plan/                # Lifecycle, file ops, validation, close_ops
│       ├── registry/            # Load, save, auto-heal
│       ├── template/            # Plan type loader + template resolution
│       ├── dashboard/           # Status aggregation
│       ├── mbank/               # Memory bank archival
│       └── summary/             # AI-generated plan summaries
├── templates/                   # Plan type plugins (DATA, not code)
│   ├── flow_plans/              # FPLAN config + templates (default, master)
│   └── dev_plans/               # DPLAN config + templates (default)
├── flow_json/                   # Per-type registries (fplan_registry.json, dplan_registry.json)
├── docs/                        # Documentation
├── .archive/                    # Archived legacy code (DPLAN handlers, old templates, old registry)
└── tests/
```

---

## Plan Types (Plugins)

Plan types live in `templates/` as data-only plugins. Each subdirectory contains a `plan_type.json` config and Markdown template files. No per-type Python code is needed.

| Type | Prefix | Registry | Description |
|------|--------|----------|-------------|
| flow_plans | FPLAN | fplan_registry.json | Build/execution plans (default, master templates) |
| dev_plans | DPLAN | dplan_registry.json | Design/thinking plans |

Plans follow the convention `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md` where NNNN is auto-incrementing per type.

---

## Integration Points

### Depends On
- `aipass.cli` -- Terminal formatting (console, header, success, error)
- `aipass.prax` -- Structured logging via `system_logger`
- `aipass.trigger` -- Error reporting (optional)
- `aipass.memory` -- Vector intake on plan close (optional, best-effort)
- Python stdlib (`pathlib`, `json`, `importlib`, `sys`, `signal`)

### Provides To
- All modules -- Plan creation, tracking, closure, and archival
- `aipass.devpulse` -- Plan status aggregation for system dashboards
- Registry: Per-type registries in `flow_json/`

---

*Last Updated: 2026-03-24*
