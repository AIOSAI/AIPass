# Dashboard Handlers - Extracted from AIPass (legacy devpulse)

Extracted from AIPass devpulse on 2026-03-08. Adapted for `aipass.prax`.

## Files extracted

- `operations.py` - Dashboard load/save/update/write-through operations (core CRUD)
- `refresh.py` - Dashboard refresh from central files (reads .central.json, writes dashboards)
- `status.py` - Quick status calculation and branch path resolution
- `template_differ.py` - Diff dashboard template against branch dashboards (audit tool)
- `template_pusher.py` - Push template updates to all branches (schema migration)

## Pre-existing files (NOT overwritten)

- `agent_status_writer.py` - Already adapted for AIPass, pushes agent_status section
- `__init__.py` - Already wired for agent_status_writer

## Original location (historical)

`/home/aipass/AIPass/devpulse/apps/handlers/dashboard/`

## Key dependencies to resolve

- `refresh.py` imports `..central.reader` (cross-handler import) -- this handler does not exist in AIPass yet
- `operations.py` references template file via `_PRAX_ROOT / "templates"` -- resolved
- `template_pusher.py` and `template_differ.py` use `AIPASS_REGISTRY.json` -- resolved
- All hardcoded `Path.home()` references need conversion to AIPass-appropriate paths
