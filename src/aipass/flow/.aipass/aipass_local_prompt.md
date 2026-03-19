# Flow -- Plan Lifecycle Management

Flow is AIPass's unified plan lifecycle system. It creates, tracks, closes, and archives numbered work plans across multiple plan types (FPLAN, DPLAN) via a data-driven plugin architecture.

## Commands

```bash
drone @flow create . "Subject"              # FPLAN (default)
drone @flow create . "Subject" master       # FPLAN master template
drone @flow create . "Design topic" dplan   # DPLAN
drone @flow close FPLAN-0042                # Close specific plan
drone @flow close --all                     # Close all open plans
drone @flow list                            # List open plans (all types)
drone @flow list all                        # List all plans
drone @flow restore FPLAN-0042              # Reopen a closed plan
```

## Architecture

- `apps/flow.py` -- Entry point. Auto-discovers modules in `apps/modules/` via `handle_command()` convention.
- `apps/modules/` -- Thin orchestrators. No business logic. Route to handlers and display results.
- `apps/handlers/` -- Implementation. Grouped by domain: `plan/`, `registry/`, `template/`, `dashboard/`, `mbank/`, `summary/`.
- `templates/` -- Data-only plugins. Each subdirectory has `plan_type.json` config + Markdown templates.
- `flow_json/` -- Per-type JSON registries (`fplan_registry.json`, `dplan_registry.json`).

## Plan Type Plugins

Plan types are DATA, not code. Each plugin directory under `templates/` contains:
- `plan_type.json` -- prefix, digits, registry_file, available_templates, default_template
- Markdown template files (e.g. default.md, master.md)

Discovered at runtime by `apps/handlers/template/plan_type_loader.py`. Add a new type by creating a new directory with these files.

| Type | Prefix | Registry File | Templates |
|------|--------|---------------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |

## Critical Files

- `apps/flow.py` -- CLI entry point, module discovery, command routing
- `apps/modules/create_plan.py` -- Plan creation orchestrator
- `apps/modules/close_plan.py` -- Plan closure orchestrator (async post-processing, archival)
- `apps/modules/list_plans.py` -- Multi-registry plan listing
- `apps/handlers/plan/list_ops.py` -- Merges plans from all registries for display
- `apps/handlers/plan/display.py` -- All formatting functions (prefix-aware)
- `apps/handlers/plan/close_ops.py` -- Close implementation (file ops, registry update, vector intake)
- `apps/handlers/template/plan_type_loader.py` -- Plugin discovery and config resolution
- `apps/handlers/registry/load_registry.py` -- Registry loader (supports per-type registry files)

## Integration Points

- **aipass.cli** -- Rich console output (`console`, `header`, `success`, `error`, `warning`)
- **aipass.prax** -- System logger
- **aipass.memory** -- Vector intake pipeline on plan close
- **aipass.trigger** -- Startup events and branch dashboard updates

## Conventions

- Modules return `True` from `handle_command()` when the command was recognized (even on failure), `False` only for "not my command".
- Plan IDs follow `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md`.
- All file I/O uses `pathlib.Path` and `encoding='utf-8'`.
- Handlers are stateless functions; modules inject dependencies.
