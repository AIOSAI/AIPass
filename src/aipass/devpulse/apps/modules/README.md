# Modules

Business logic for `DEVPULSE`. One module per command.

Modules orchestrate work by calling handlers. They are the public API of the branch — drone routes commands here.

## Modules

| Module | Purpose |
|---|---|
| `watchdog.py` | Always-on dispatch reporting — a session signs in via `baseline` and every completion report is delivered; plus directed wakes. Subcommands: `baseline`, `agent`, `timer`, `schedule`, `status`, `cancel`, `list`. |
| `feedback.py` | Cross-project feedback channel. `compose` / `inbox` handlers. Lets external projects report bugs/friction back to devpulse. |
