# Apps

Application layer for `DEVPULSE`.

- `devpulse.py` — Entry point. Auto-discovers and routes commands to modules.
- `modules/` — Business logic and orchestration. One module per command.
- `handlers/` — Implementation details. Called by modules, never by CLI directly.
- `plugins/` — Scheduled tasks and extensions.
