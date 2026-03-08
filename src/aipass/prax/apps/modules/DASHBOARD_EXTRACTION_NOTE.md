# Dashboard Module - Extracted from Dev-Pass

Extracted from Dev-Pass devpulse on 2026-03-08.

These files need adaptation for AIPass before use.

Original imports use `aipass_os.dev_central.devpulse` -- must be converted to `aipass.prax`.

## Files extracted

- `dashboard.py` - Dashboard Section Utilities (module-level orchestration, CLI interface, schema definition)

## Original location

`/home/aipass/aipass_os/dev_central/devpulse/apps/modules/dashboard.py`

## Key imports to convert

- `from prax.apps.modules.logger import system_logger` - needs AIPass logger path
- `from cli.apps.modules import console` - needs AIPass CLI console
- `from aipass_os.dev_central.devpulse.apps.handlers.dashboard import ...` - convert to `from aipass.prax.apps.handlers.dashboard import ...`
- `from aipass_os.dev_central.devpulse.apps.handlers.dashboard.refresh import ...` - convert similarly
- `from aipass_os.dev_central.devpulse.apps.handlers.dashboard.template_pusher import ...` - convert similarly
- `from aipass_os.dev_central.devpulse.apps.handlers.dashboard.template_differ import ...` - convert similarly
