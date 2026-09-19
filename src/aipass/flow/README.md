[← Back to AIPass](../../../README.md)

# Flow

**Purpose:** Plan lifecycle management for AIPass — creates, tracks, closes and archives numbered work plans across every registered plan type.
**Module:** `aipass.flow`
**Version:** 2.7.0
**Created:** 2025-11-15

---

## What It Does

A plan is a numbered markdown file with a registry row behind it
(`FPLAN-0042_subject_2026-04-22.md`). Every branch in the fleet uses this one
service to open a plan, find it again, close it and have it archived, so work
that outlives a session has somewhere to live that is not a chat log.

Plan types are data, not code. A type is a directory of templates plus a
registered prefix, which is why `FPLAN`, `DPLAN`, `RPLAN` and the rest all run
through the same lifecycle without a line of per-type logic. Drop a template
directory in, register a prefix, and the new type is live.

Closing is the interesting half: archival happens in the foreground, where a
failure can still be reported honestly, and vectorisation is handed to a
detached background runner so a slow embedding never holds up the caller.

---

## Quick Start

```bash
drone @flow create . "My task description"   # open a plan here
drone @flow list open                        # what is still open
drone @flow close FPLAN-0042                 # close it when done
drone @flow create . "Design topic" dplan    # a design plan instead
```

---

## Live Inventory

This page is the face and goes stale the moment the code moves. The inventory
that cannot go stale is generated from the code itself:

- `drone @flow` — the live self-map: every command module discovered right now.
- `drone @flow --help` — the full reference: verbs, flags and worked examples.
- `drone @flow <command> --help` — the detail for one command.

Call a command by the verb the help table shows. A module's full filename is
not a command, with `post` the one module that answers to both.

---

## How To Reach Me

Mail `@flow`. Send a defect with what you measured, or a request for a plan
type, a template or a lifecycle change. Plans themselves need no permission —
create one from any branch, in any directory, whenever you need one.

---

## Commands

The verb list is not written down here on purpose: a hand-typed list drifts
from the dispatcher and then lies to whoever trusts it. `--help` is generated
from the modules that actually exist, so it is the reference, and the Live
Inventory section above is the one door worth remembering.

What the branch covers: opening plans from a template, closing one or sweeping
every open plan in a project, previewing either with a dry run, holding a whole
plan type back from a sweep, listing and filtering, reopening a closed plan,
registering and scanning plan types, checking registry health, and aggregating
plans across branches for central reporting.

---

## Architecture

The entry point `apps/flow.py` discovers its command modules at import and
routes by verb, so adding a module adds a command with no registration step.
The modules are thin orchestrators that route and display, never decide:
`create_plan`, `close_plan`, `list_plans`, `restore_plan`, `template_manager`,
`registry_monitor`, `aggregate_central`, and `post_close_runner`, which is the
detached worker that picks up where a close left off.

Below them, `apps/handlers/` holds the implementation in groups by domain —
plan lifecycle, registry load and repair, template and plan-type resolution,
dashboard writes, memory archival, runner locks, the shared CLI gates, and
`apps/handlers/repo_root.py`, the single answer to "where am I" that keeps the
branch alive on a checkout with no readable working directory.

Registries live in `flow_json/`, one per plan type plus the template registry
that defines the types. Templates live in `templates/`, one directory per type.

The directory tree is deliberately not drawn here — it rots the day someone
adds a file. It lives in the branch prompt, `.aipass/aipass_local_prompt.md`,
re-derived from the real tree, and `drone @flow` names the modules live.

**Design principles.** Modules orchestrate, handlers do the work and stay
stateless with their dependencies injected. Plan types are filesystem-driven.
An unknown command or argument refuses loudly rather than proceeding on a
default. Nothing reads the process working directory to find itself.

---

## Documentation

Depth lives in [`docs/`](docs/README.md), one page per module or handler group.
Read the one that broke.

| Page | What is in it |
|---|---|
| [Plan Lifecycle](docs/plan_lifecycle.md) | Verb forms that execute, how a bare number resolves against per-type registries, and what the close pipeline does in the foreground versus the background runner |
| [Plan Types](docs/plan_types.md) | Registering a type, and the three self-healing behaviours: auto-close of missing files, ignored folders, orphaned locations |
| [Location Discovery](docs/repo_root.md) | `repo_root.py`, the cross-platform test worlds, and the structural rules earned from reds a single-dimension test could not see |
| [Argument Gate](docs/argument_gate.md) | Why an unrecognised argument refuses, the one gate every door routes through, and what "absolute" means in a shared registry |
| [Dashboard Mirror](docs/dashboard_mirror.md) | The flow section contract, why `quick_status` is merged rather than replaced, and the caps mirrored from the dashboard owner |

Current state is never written down here; it is produced on demand.
`drone @flow templates` lists the registered types, `drone @flow registry
status` reports registry health, `drone @flow list all` counts the plans, and
`drone @seedgo audit aipass @flow` scores the code.

---

## Integration Points

### Depends On

- `aipass.cli` — Rich terminal formatting.
- `aipass.prax` — structured logging, and the dashboard caps this branch mirrors rather than copies.
- `aipass.memory` — vector intake when a plan closes.
- `aipass.trigger` — error reporting.

### Provides To

- Every branch — plan creation, tracking, closure and archival.
- `aipass.devpulse` — plan status for the system dashboards.
- Central reporting — `PLANS.central.json`, carrying a per-branch section for
  every branch that holds plans. Its `statistics.total_closed` is a real count
  of everything a branch has ever closed, not the size of the
  `recently_closed` window beside it; the two coincide only on branches with
  very few closures.

---

**Last Updated:** 2026-09-15

[← Back to AIPass](../../../README.md)
