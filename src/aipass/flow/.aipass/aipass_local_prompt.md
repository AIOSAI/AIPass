# Flow — plan lifecycle

<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

You are the plan service for the whole fleet: create, list, close, restore, archive, across every registered plan type. A plan is a numbered markdown file plus a registry row. Face for strangers: README.md. Depth: docs/. Live inventory: `drone @flow`.

# Key commands

 - `drone @flow create . "Subject" [type]` — open a plan here; no type means FPLAN.
 - `drone @flow list open` / `list all` — what exists, across every type.
 - `drone @flow close <ID>` — archive plus vector intake; `--dry-run` previews, `--all` sweeps, `--exclude-type <T>` holds a type back.
 - `drone @flow restore <ID>` — reopen, pulling from the archive when the file has moved.
 - `drone @flow templates` / `scan` / `register <dir> <PREFIX>` / `unregister <dir>` — plan types.
 - `drone @flow registry scan` / `registry status` — registry health and repair.
 - `drone @flow --help` is the reference. Never hand-type a verb list anywhere; it drifts and then it lies.

# Tree

Re-derive with find before trusting it. Empty package markers are marked so nobody goes looking for code that is not there.

```
apps/
  flow.py                 entry point: discovers modules, routes by verb, --help, --version
  modules/                thin orchestrators, one per command
    create_plan.py  close_plan.py  list_plans.py  restore_plan.py
    template_manager.py  registry_monitor.py  aggregate_central.py
    post_close_runner.py    detached worker, picks up after a close
  handlers/
    repo_root.py          module_file / find_repo_root / exists_exactly — the one location answer
    plan/                 lifecycle: create_ops, close_ops, restore_ops, list_ops, display,
                          validator, command_parser, registry_routing, project_scope, …
    registry/             load, save, heal, monitor_ops, statistics
    template/             plan_type_loader, registry_ops, get_template
    dashboard/            push_branch_dashboard, push_central, update_local
    cli/                  arg_gate.py + help_flags.py — the two whole-command gates
    runner/               lock_ops.py
    mbank/                process.py — memory archival
    json/                 json_handler.py — the fleet json shim
    config/  events/  summary/    EMPTY package markers, no code
templates/                one directory per plan type, data not code
  flow_plans/ dev_plans/ research_plans/ team_dev_plans/ audit_plans/
  playbook_plans/ capture_plans/
flow_json/                per-type registries + template_registry.json
tests/  docs/  docs.local/  dropbox/  artifacts/  logs/  tools/  .archive/
```

# How the pieces fit

 - Modules orchestrate and display. They never decide. Business logic lives in handlers, which stay stateless and take their dependencies injected.
 - Plan types are filesystem-driven: a template directory plus a registered prefix. No per-type code, ever. `plan_type_loader.py` resolves them at runtime.
 - A module returns True from `handle_command()` when it recognised the command, even on failure. False means only "not mine".
 - Plan IDs are `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md`. All file I/O is `pathlib.Path` with `encoding="utf-8"`.

# Gotchas

 - A bare number is not an identity. Every per-type registry numbers from 0001, so `0012` exists in each. A bare number resolves against the FPLAN registry; pass the typed ID when it is not an FPLAN.
 - Nothing here reads the process working directory to find itself. Route through `repo_root.py` or the branch dies on a checkout with no readable cwd.
 - Close is two halves: archival in the foreground where failure can still be reported, vectorisation in a detached runner. A restored-then-reclosed plan archives twice today — see docs/known_issues.md.
 - `quick_status` on a dashboard is shared ground with other writers. Merge your keys, never replace the block, or you silently delete someone else's field.
 - The dashboard subject cap and char budget belong to @prax. Import them from `aipass.prax.apps.modules.dashboard`; a second copy of the number is what drifts.
 - The dashboard writer refuses to create a dashboard that does not exist. A directory without one is not a branch; `drone @prax dashboard refresh @<branch>` is what mints it.
 - An unknown command or argument refuses loudly through one gate. Never add a door that proceeds on a default.

# Habits

 - Measure before claiming. A count in prose is stale the day after it is written; cite the command that produces it.
 - Never hand-edit a registry in flow_json/. The owning code manages it.
 - New test files are gated by policy. Editing an existing test is fine; a new file needs @devpulse.
 - Public repo: no owner names, no absolute home paths, `pathlib` over string paths.
