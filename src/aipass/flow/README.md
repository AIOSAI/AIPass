[← Back to AIPass](../../../README.md)

# Flow

**Purpose:** Unified plan lifecycle management for AIPass. Creates, tracks, closes, and archives numbered work plans across multiple plan types via a filesystem-driven template registry.
**Module:** `aipass.flow`
**Version:** 2.2.2
**Created:** 2025-11-15
**Last Updated:** 2026-08-13

---

## Overview

Flow is AIPass's plan management system. Every branch uses flow to create, track, close, and archive work plans. Plans are numbered markdown files (`FPLAN-0042_subject_2026-04-22.md`) organized by type, with per-type registries tracking status and metadata.

### What I Do
- Create numbered plans from type-specific templates
- Close plans with foreground archival and vector intake verification
- List and filter plans across all registered types
- Restore closed plans from backups
- Manage plan types via filesystem-driven template registry
- Aggregate plans across branches for central reporting
- Self-heal registries (orphan detection, auto-close missing files, auto-register new template dirs)
- Preview close operations with `--dry-run`

---

## Quick Start

```bash
drone @flow create . "My task description"          # Create a plan in the current directory
drone @flow list open                                # See all open plans
drone @flow close FPLAN-0042                         # Close a completed plan
drone @flow create . "Design topic" dplan            # Create a design plan (DPLAN)
drone @flow templates                                # List available plan types
```

---

## Commands

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
drone @flow close --dry-run FPLAN-0042          # Preview single close

# List plans
drone @flow list open                           # List open plans (all types)
drone @flow list all                            # List all plans

# Template management
drone @flow templates                           # List registered types
drone @flow scan                                # Find unregistered directories
drone @flow register <dir> <PREFIX>             # Register new plan type
drone @flow unregister <dir>                    # Remove plan type

# Registry
drone @flow registry scan                       # Scan filesystem, detect mismatches
drone @flow registry status                     # Show registry health

# Other
drone @flow restore FPLAN-0042                  # Reopen a closed plan
drone @flow aggregate                           # Cross-branch plan aggregation
drone @flow post                                # Background post-close processing
drone @flow --help                              # Full help
drone @flow --version                           # Version string
```

---

## Architecture

```
flow/
├── apps/
│   ├── flow.py                  # Entry point (auto-discovers modules)
│   ├── modules/                 # Thin orchestrators (8 modules)
│   │   ├── create_plan.py       # Plan creation with template support
│   │   ├── close_plan.py        # Closure with foreground archival + vector verify
│   │   ├── list_plans.py        # Plan listing and filtering
│   │   ├── restore_plan.py      # Plan recovery from backups
│   │   ├── registry_monitor.py  # Registry scanning and auto-healing
│   │   ├── aggregate_central.py # Cross-branch plan aggregation
│   │   ├── post_close_runner.py # Background post-processing with lock management
│   │   └── template_manager.py  # Template registry management
│   └── handlers/                # Implementation details
│       ├── plan/                # Lifecycle: create, close, list, restore, display, validation
│       ├── registry/            # Load, save, auto-heal registries
│       ├── template/            # Plan type loader, template resolution, registry CRUD
│       ├── dashboard/           # Status push to local, central, branch dashboards
│       ├── mbank/               # Memory archival and plan processing
│       ├── runner/              # Lock file operations for background processes
│       ├── json/                # Auto-creating JSON handler
│       ├── summary/             # Plan summarization (vestigial)
│       ├── config/              # Configuration loading
│       └── events/              # Event handling stubs
├── templates/                   # Plan type plugins (data, not code)
│   ├── flow_plans/              # FPLAN templates (default, master)
│   ├── dev_plans/               # DPLAN templates (default)
│   ├── research_plans/          # RPLAN templates (default)
│   ├── team_dev_plans/          # TDPLAN templates (default)
│   ├── audit_plans/             # APLAN templates (default)
│   └── playbook_plans/          # PPLAN templates (SOPs: merge, weekly_update, …)
├── flow_json/                   # Per-type registries + template_registry.json
├── tests/                       # 787 tests, 22 test files
└── .archive/                    # Archived legacy code
```

### Design Principles
- **Modules are thin orchestrators** — no business logic, route to handlers and display results
- **Handlers are stateless** — modules inject dependencies (registry loader, paths, config)
- **Plan types are filesystem-driven** — drop a template dir, register a prefix, done
- **Auto-discovery** — `flow.py` finds modules via `handle_command()` convention; `plan_type_loader.py` discovers types from `template_registry.json`

---

## Plan Types

| Type | Prefix | Registry | Templates |
|------|--------|----------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |
| research_plans | RPLAN | rplan_registry.json | default |
| team_dev_plans | TDPLAN | tdplan_registry.json | default |
| audit_plans | APLAN | aplan_registry.json | default |
| playbook_plans | PPLAN | pplan_registry.json | default, merge, prompt_change, weekly_update |

Plans follow the naming convention `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md` where NNNN auto-increments per type.

### Adding a New Plan Type
1. Create a directory in `templates/` with one or more `.md` template files
2. Run `drone @flow register <dirname> <PREFIX>` (or let auto-registration detect it on next command)
3. Use `drone @flow create . "Subject" <shorthand>` to create plans of the new type

### Auto-healing
- Template registry auto-prunes orphaned types (directory deleted → entry + plan registry JSON removed)
- Plan registries auto-close entries for missing files
- New template directories auto-register on next command

### Ignored Folders

`IGNORE_FOLDERS` (`apps/handlers/registry/monitor_ops.py`) is the set of directory
names the registry scan never descends into — dev/VCS tooling, backups, archives,
and system paths that legitimately contain files matching the PLAN filename
pattern but should never be registered as live plans.

**Exact-match only, never substring/pattern matching.** A folder name is skipped
only when it equals an entry in the set exactly. Substring matching was tried
historically and broke: a folder named `dev` would substring-match inside
`devpulse`, silently skipping the entire `devpulse/` tree from scanning (see
`key_learning #33`, `registry_monitor_runaway_log_fix`). Exact-match avoids that
trap entirely — adding `dropbox` only ever matches a folder literally named
`dropbox`, never `devpulse-dropbox-clone` or similar.

`dropbox` is in the set because every branch has one as its received-files
inbox — anything can land there, including old snapshot/backup copies of plan
files with real `PLAN-NNNN` filenames, so no live plan should ever be scanned
out of a `dropbox/` tree.

The current folder list lives in `monitor_ops.py` itself (`IGNORE_FOLDERS`) —
that file is the source of truth; this README doesn't duplicate the list to
avoid drift. Both `registry_monitor`'s scan pass and `heal_registry`'s doctrine
self-heal (collisions / unregistered files / wrong-prefix rows) import this
same set, so a folder added here is skipped by both in lockstep.

---

## Close Pipeline

On `drone @flow close`:
1. **Template check** — fast-delete empty/template-only plans
2. **Mark closed** — update plan registry with closure timestamp
3. **Archive** — move to `.backup/processed_plans/` (foreground, sets processed/cleanup flags atomically)
4. **Vector intake** — `drone @memory process-plans` + `is_plan_vectorized()` verification
5. **Dashboard updates** — local, central, and branch dashboards
6. **Append** — write to `CLOSED_PLANS.local.json`

Vector verification displays in console: "Vectorized: N chunks in chroma" or "NOT vectorized".

Closed plans are archived to `<repo-root>/.backup/processed_plans/`, a shared runtime namespace managed by `@backup` (see `src/aipass/backup/README.md`) and consumed by `@memory` for vectorization.

---

## Dashboard Writes — quick_status Is Shared Ground

`DASHBOARD.local.json` has one `quick_status` block and more than one writer.
`@prax`'s dashboard refresh contributes `todo_count` (read straight from
`.trinity/local.json`); Flow's plan push contributes `active_plans` and
`commons_mentions`. Whole-block replacement means last-writer-wins silently
deletes the other's fields — a plan close used to zero the todo count on every
branch card until the next prax refresh.

Flow's push therefore **merges** (`_calculate_quick_status` in
`apps/handlers/dashboard/push_branch_dashboard.py`):

| Keys | Behaviour |
|------|-----------|
| `active_plans`, `commons_mentions` | recomputed — Flow is the authority |
| `new_mail`, `opened_mail` | preserved if already set, seeded only when absent (@prax reads `inbox.json` first-hand; we only see the possibly-stale `ai_mail` section) |
| `action_required`, `summary` | recomputed over every counter present, foreign ones included |
| anything else | carried through untouched |

A foreign key named `*_count` holding an integer is additionally read as a
counter, so it still reaches `action_required` and the summary line
(`todo_count: 9` → `"9 todos"`). Every other foreign key is passed through
without interpretation.

---

## Integration Points

### Depends On
- `aipass.cli` — Rich terminal formatting (`console`, `header`, `success`, `error`, `warning`)
- `aipass.prax` — Structured logging via `system_logger`
- `aipass.memory` — Vector intake on plan close
- `aipass.trigger` — Error reporting (optional)

### Provides To
- All branches — plan creation, tracking, closure, and archival
- `aipass.devpulse` — plan status aggregation for system dashboards
- Central reporting — `PLANS.central.json` with per-branch plan sections (all branches, not just flow)

---

## Quality

- **Seedgo:** 100%
- **Tests:** 787 passed, 88/88 public functions tested (100%)
- **Source files:** 40 tracked by seedgo
- **Last audit:** 2026-08-13
- **Battle test:** 16/16 commands pass via drone CLI (2026-04-22)

### Known Issues
- Registry scan fires trigger events that are never handled (by design — foreground close handles everything)
- Dashboard push warns on some closes
- `mbank/process.py` at 669 lines (nearing 700 limit)
- `close_ops.py` split into `close_ops.py` (647 lines) + `close_helpers.py` (260 lines)
- `push_central.py` comprehensive rewrite (2026-06-02): now pushes all branches' plans, not just flow's — fixed dashboard refresh zeroing other branches' plan counts

---

*Last Updated: 2026-08-13*

---
[← Back to AIPass](../../../README.md)
