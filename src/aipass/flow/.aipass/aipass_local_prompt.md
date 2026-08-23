# Flow — Plan Lifecycle Management
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->

Flow is AIPass's unified plan lifecycle system. Creates, tracks, closes, archives numbered work plans across multiple plan types (FPLAN, DPLAN) via data-driven plugin architecture.
# Commands
`bash
drone @flow create . "Subject"              # FPLAN (default)
drone @flow create . "Subject" master       # FPLAN master template
drone @flow create . "Design topic" dplan   # DPLAN
drone @flow close FPLAN-0042                # Close specific plan
drone @flow close --all                     # Close all open plans
drone @flow list open                       # List open plans (all types)
drone @flow list all                        # List all plans
drone @flow restore FPLAN-0042              # Reopen closed plan
```
# Architecture
- `apps/flow.py` -- Entry point. Auto-discovers modules `apps/modules/` via `handle_command()` convention.
- `apps/modules/` -- Thin orchestrators. No business logic. Route handlers, display results.
- `apps/handlers/` -- Implementation. Grouped domain: `plan/`, `registry/`, `template/`, `dashboard/`, `mbank/`, `summary/`.
- `templates/` -- Plan type directories. Each subdirectory contains Markdown templates. Registered via `drone @flow register`.
- `flow_json/` -- Registries: per-type plan registries + `template_registry.json` (plan type definitions).]
# Plan Type System
Plan types filesystem-driven. Drop directory `.md` templates into `templates/`, register, done:
```bash
drone @flow register testing TPLAN          # Register new type
drone @flow unregister testing              # Remove type
drone @flow templates                       # List registered types
drone @flow scan                            # Find unregistered directories
```
Discovered runtime `plan_type_loader.py` + `registry_ops.py`. No per-directory JSON config needed.
| Type | Prefix | Registry File | Templates |
|------|--------|---------------|-----------|
| flow_plans | FPLAN | fplan_registry.json | default, master |
| dev_plans | DPLAN | dplan_registry.json | default |
# Critical Files
- `apps/modules/create/close/list_plan.py` -- Plan creation orchestrator 
- `apps/handlers/plan/list_ops.py` -- Merges plans all registries display
- `apps/handlers/plan/display.py` -- All formatting functions (prefix-aware)
- `apps/handlers/plan/close_ops.py` -- Close implementation (file ops, registry update, vector intake)
- `apps/handlers/template/plan_type_loader.py` -- Plugin discovery + config resolution
- `apps/handlers/registry/load_registry.py` -- Registry loader (supports per-type registry files)
#Integration Points
- **aipass.cli** -- Rich console output (`console`, `header`, `success`, `error`, `warning`)
- **aipass.prax** -- System logger
- **aipass.memory** -- Vector intake pipeline plan close
- **aipass.trigger** -- Startup events + branch dashboard updates
#Conventions
- Modules return `True` `handle_command()` when command recognized (even on failure), `False` only "not my command".
- Plan IDs follow `{PREFIX}-{NNNN}_topic_slug_YYYY-MM-DD.md`.
- All file I/O uses `pathlib.Path` + `encoding='utf-8'`.
- Handlers stateless functions; modules inject dependencies.
