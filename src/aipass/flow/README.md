[← Back to AIPass](../../../README.md)

# Flow

**Purpose:** Unified plan lifecycle management for AIPass. Creates, tracks, closes, and archives numbered work plans across multiple plan types via a filesystem-driven template registry.
**Module:** `aipass.flow`
**Version:** 2.2.1
**Created:** 2025-11-15
**Last Updated:** 2026-08-13

---

## Overview

Flow is AIPass's plan management system. Every branch uses flow to create, track, close, and archive work plans. Plans are numbered markdown files (`FPLAN-0042_subject_2026-04-22.md`) organized by type, with per-type registries tracking status and metadata.

### What I Do
- Create numbered plans from type-specific templates
- Close plans with foreground archival and vector intake verification
- List and filter plans across all registered types
- Reopen closed plans whose file is still at its registered location
  (recovery from the `.backup/processed_plans/` archive exists but is only
  reached when the plan is absent from the registry entirely — see Known Issues)
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
drone @flow close --all                         # Close every open plan in YOUR project
drone @flow close --all --dry-run               # Preview what would close
drone @flow close --all --exclude-type APLAN    # Hold a whole plan type back (repeatable)
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

**Use the short verb.** Only the short form executes (`list`, `close`, `create`,
`restore`, `registry`, `aggregate`, `templates`). The module's full name
(`list_plans`, `close_plan`, …) resolves for `--help` but is rejected by the
dispatcher — `post`/`post_close_runner` is the sole module accepting both. The
`--help` screen currently claims otherwise; see Known Issues.

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
│   │   ├── restore_plan.py      # Reopen closed plans (+ backup recovery path)
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
│       ├── json_templates/      # Seed JSON payloads for the auto-creating handler
│       ├── summary/             # EMPTY — only generate.py(disabled) remains
│       ├── config/              # EMPTY — package marker only, no code
│       └── events/              # EMPTY — package marker only, no code
├── templates/                   # Plan type plugins (data, not code)
│   ├── flow_plans/              # FPLAN templates (default, master)
│   ├── dev_plans/               # DPLAN templates (default)
│   ├── research_plans/          # RPLAN templates (default)
│   ├── team_dev_plans/          # TDPLAN templates (default)
│   ├── audit_plans/             # APLAN templates (default)
│   └── playbook_plans/          # PPLAN templates (SOPs: merge, weekly_update, …)
├── flow_json/                   # Per-type registries + template_registry.json
├── tests/                       # 950 tests across 27 files
└── .archive/                    # Archived legacy code + orphaned registries
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

Auto-prune only fires while the type is **still registered** and its directory
has gone missing. `unregister <dir>` deliberately leaves the plan registry JSON
in place (see `remove_type()`), so unregistering *and then* deleting the
directory slips past the prune and strands a `<shorthand>_registry.json`
forever. `flow_json/pbplan_registry.json` is one such orphan.

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

### Orphaned Locations Heal Themselves

Branches get tested, moved and re-seated constantly, so plan rows pointing at
stale paths are **expected debris, not an anomaly** (ruling 2026-08-16). Hand-
editing the JSON is the wrong fix: it does not stick while code elsewhere still
writes the stale value. `drone @flow registry scan` re-attributes them instead,
as part of a normal scan.

A row is orphaned when its `location` is not where its citizen lives — either
the path is gone from disk, or it exists but merely *contains* the seat (a
project root holding records that belong to the branch inside it). Detection is
deliberately those two signals only: a plan filed at the repo root or inside a
citizen's own subdirectory is a normal filing, and treating every non-seat path
as debris buried the real orphans under ~30 false positives when first tried.

Attribution runs on evidence, in order: a directory containing exactly one live
seat *is* that citizen's ground; failing that, exactly one live citizen sharing
the directory name **within the same repository**. A bare name match across
repositories is a coincidence, not an identity, and is refused.

Anything unattributable is **quarantined, never guessed and never dropped** —
the row stays untouched and `drone @flow registry status` lists it with the
reason, for a human ruling. Re-running the healer changes nothing the second
time.

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

### The `flow` Section Shape

Every branch's `DASHBOARD.local.json` carries a `flow` section, `managed_by`
flow, written by `push_flow_to_branch_dashboard()`:

| Field | Shape | Meaning |
|-------|-------|---------|
| `active_plans` | **int** | count of *all* open plans for this branch |
| `open_recent` | list of `{plan_id, subject, created}` | the **5 newest open plans** by created date, newest first |
| `recently_closed` | list of `{id, subject, closed}` | last 5 closed within 7 days |
| `total_plans` | int | every plan ever filed for this branch |

`open_recent` is the bounded reading window: agents get their bearings from 5
named plans plus a total, never from a wall of rows. **The cap is enforced in
the renderer** (`_build_open_recent`, `OPEN_RECENT_LIMIT = 5`), not in the
consumer — a reader that has to remember to slice will eventually forget. The
full list lives behind `drone @flow list open`, on request.

**`active_plans` is a count, not a list** — ruling of 2026-08-16 (Patrick, via
`@devpulse`). Flow's push used to publish every open-plan row here; on a branch
with 23 open plans that was 6,096 of the section's 8,552 bytes, and it was the
unbounded context the ruling exists to kill. The list left the section
entirely, and `active_count` collapsed into this one name. The int also matches
what `@prax`'s refresh already writes, so the field means the same thing no
matter which writer built the section.

Card values are written per-branch on plan events, so a change to this contract
only reaches a branch that files a plan afterwards — a quiet branch keeps the
old shape indefinitely. `push_flow_to_all_branch_dashboards()` sweeps every
branch Flow holds plans for and is how a contract change lands fleet-wide.
Paths without a dashboard are skipped, never created.

> **Two writers, one section.** `@prax`'s dashboard refresh also builds this
> section, wholesale (`recently_closed` as `{plan_id, subject}`, and no
> `open_recent` / `total_plans`). Whichever writer ran last wins the whole
> section — the per-key merge above protects `quick_status` only, not section
> level. `active_plans` now agrees across both writers; `open_recent` should
> still be read as present-or-absent until `@prax`'s side is aligned.

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

In `PLANS.central.json`, `statistics.total_closed` is a **real count of every
plan a branch has ever closed**, not the size of the `recently_closed` window
beside it. The two are different numbers and only coincide on branches with
five or fewer closures. `recently_closed` is capped at 5; `total_closed` is
measured by `push_central` from the full registry and carried through
aggregation untouched, plus anything auto-closed during the run.

---

## Quality

- **Seedgo:** 100% (46 standards, 44 files, no type errors)
- **Tests:** 950 tests in 27 files — 969 cases collected after parametrisation, 968 pass / 1 skip. 98/98 public functions tested (100%, `drone @seedgo test_map @flow`)
- **Source files:** 44 tracked by seedgo
- **Bypass rules:** 59 (74 before the 2026-08-13 audit — 15 dead + 1 false-reason removed)
- **Last audit:** 2026-08-23 (every figure on this list re-measured, not carried forward)

### Known Issues
- **307 of 719 closed plans have no archived copy and cannot be restored.**
  Fixed 2026-08-22: `restore` now reads `.backup/processed_plans/` when the
  registered `file_path` is empty, which it always is after a close. Before
  that fix restore failed for **719 of 719** closed plans while 412 archives
  sat intact beside them. Coverage by close month: 2026-03 and 04 are 0%,
  05 is 89%, 06–08 are 98–100%. The 307 pre-May rows have no artifact to
  recover — that is a gap in the archive, not in restore, and it is not
  recoverable by code.
- **`--help` advertises full module names that the dispatcher rejects.** It
  prints "Commands can be called by short name or full name", but 7 of 8
  modules match only their short verb. It also lists `template`, which no
  module accepts — the working verb is `templates`, absent from that list.
- **`registry status` counts only FPLAN.** It reports the default registry's
  totals under a system-wide label (354/1 where the true figures across all
  types are 705/27), because `get_status_impl` calls a bare `load_registry()`.
- `flow_json/PLAN_REGISTRY.json` is legacy — zero readers anywhere in the tree
- `flow_json/pbplan_registry.json` is an orphaned type registry (see Auto-healing)
- Registry scan fires trigger events that are never handled (by design — foreground close handles everything)
- Dashboard push warns on some closes
- `mbank/process.py` at 718 lines (over the 700 limit)
- `close_ops.py` split into `close_ops.py` (614 lines) + `close_helpers.py` (257 lines)
- `push_central.py` comprehensive rewrite (2026-06-02): now pushes all branches' plans, not just flow's — fixed dashboard refresh zeroing other branches' plan counts

---

*Last Updated: 2026-08-23*

---
[← Back to AIPass](../../../README.md)
