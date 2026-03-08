# Dashboard Handlers - Extracted from Dev-Pass

Extracted from Dev-Pass devpulse on 2026-03-08.

These files need adaptation for AIPass before use.

Original imports use `aipass_os.dev_central.devpulse` -- must be converted to `aipass.prax`.

## Files extracted

- `operations.py` - Dashboard load/save/update/write-through operations (core CRUD)
- `refresh.py` - Dashboard refresh from central files (reads .central.json, writes dashboards)
- `status.py` - Quick status calculation and branch path resolution
- `template_differ.py` - Diff dashboard template against branch dashboards (audit tool)
- `template_pusher.py` - Push template updates to all branches (schema migration)

## Pre-existing files (NOT overwritten)

- `agent_status_writer.py` - Already adapted for AIPass, pushes agent_status section
- `__init__.py` - Already wired for agent_status_writer

## Original location

`/home/aipass/aipass_os/dev_central/devpulse/apps/handlers/dashboard/`

## Key dependencies to resolve

- `refresh.py` imports `..central.reader` (cross-handler import) -- this handler does not exist in AIPass yet
- `operations.py` references template file at `Path.home() / "aipass_os" / "dev_central" / "devpulse" / "templates"` -- needs path update
- `template_pusher.py` and `template_differ.py` use `BRANCH_REGISTRY.json` at `Path.home()` -- needs AIPass registry path
- All hardcoded `Path.home()` references need conversion to AIPass-appropriate paths
