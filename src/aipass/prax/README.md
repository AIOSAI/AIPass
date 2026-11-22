[← Back to AIPass](../../../README.md)

# PRAX

**Purpose:** The logging and monitoring backbone of AIPass. Every branch imports one logger and its lines route themselves; on top of that sit Mission Control, the branch dashboards, and the audits that catch a log growing out of control.
**Module:** `aipass.prax`
**Version:** 2.4.0

---

## Quick Start

```python
from aipass.prax import logger

logger.info("Processing started")
logger.warning("Disk usage high")
logger.error("Connection failed")
```

No configuration, no setup call, no per-branch logger to build. Prax reads the call stack to
find the caller's branch and module, then writes the line twice: to `system_logs/` at the repo
root, where every branch's output is aggregated, and to that branch's own `logs/` directory
for local debugging. Both rotate by size. An installed package (`uv tool install`, pip) has
no repo root to log under, so its `system_logs/` lives in `~/.aipass/system_logs`. A missing
directory is created rather than raised, and a log file that cannot be opened is reported as
`Log handler failed` on prax's trail. If prax itself cannot be imported, the import raises in
every spelling: a broken logger is a failure the caller hears, never a silent substitute.

---

## What It Does

- **Routes every branch's logs automatically** — one import, two-tier placement, self-healing
  directories, and a documented fallback when the caller cannot be identified.
- **Runs Mission Control** — a real-time terminal console over file changes, log events and
  live agent sessions, with a read-only feed of The Commons.
- **Watches for runaway logs** — growth rates per file, sustained-threshold alarms, and an
  event on the trigger bus when one goes off.
- **Audits log files** — health summaries and oversized-file reports (writers rotate their own
  files; nothing truncates a live one), and a weekly stale-temp sweep defined as a daemon job (shipped disabled).
- **Builds the branch dashboards** — the `DASHBOARD.local.json` every agent reads at its
  greeting, refreshed from the central files, plus the write-through API other services call
  to update their own section.
- **Keeps the module registry** — a scheduled scan of the ecosystem, so the inventory is
  produced by code rather than maintained by hand.

Not application logic: prax is infrastructure. It does not analyse or alert on log content
beyond growth rate, and it never edits another branch's files.

---

## Live Inventory

The module and command list is generated from the code that runs it, so it is not written
down here and cannot go stale:

- `drone @prax` — the self-map: every discovered module, with the version.
- `drone @prax --help` — the full command surface: every verb, its arguments and its flags.

Each module carries its own reference too, reached by adding `--help` to the verb.

---

## How To Reach Me

- Mail: `drone @ai_mail email @prax "Subject" "Body"` — a log that lands in the wrong file, a
  routing question, a dashboard section that looks wrong, a monitor that will not start.
- Logs are the first diagnostic in this ecosystem. If something misbehaved, say which branch
  and roughly when, and the line is usually already on disk.
- Caps other branches read from prax are named as constants, never as numbers to copy:
  `SUBJECT_CAP` and `DASHBOARD_CHAR_BUDGET`, `from aipass.prax import ...`. The
  contract for both is [docs/dashboard_caps.md](docs/dashboard_caps.md).

---

## Commands

There is no command list on this page, deliberately: a hand-typed copy of the branch's own
help output rots the next time a verb is added or renamed. The generated surface above under
**Live Inventory** is always current, and the depth behind each verb is in the documentation
index below.

---

## Architecture

Three layers. The entry point `apps/prax.py` holds no business logic: it discovers the
modules beside it and routes each command to the one that claims it. `apps/modules/` holds
one thin orchestrator per verb — `logger`, `monitor`, `dashboard`, `status`, `log_audit`,
`log_health` and `discover`. `apps/handlers/` holds the implementation, one directory per
concern: logging setup and rotation, monitoring threads, dashboard refresh and template,
discovery and the registry, the central-file reader, the CLI predicates, the
config resolution, the background watchers, and the json service every branch shares.

External branches import from one door, the package top file: `from aipass.prax import <name>`,
never a path under `apps/`. The door is lazy (PEP 562) and caches nothing: each name
(`__all__` in `__init__.py` is the list) is read from its home on every access, so importing
prax costs nothing until a name is used, and a patch on the home reaches every later read.

The directory tree lives in this branch's own prompt (`.aipass/aipass_local_prompt.md`) —
one place, so it cannot disagree with itself.

---

## Documentation

Depth lives in [docs/](docs/), one file per module or handler group:

| Doc | What it covers |
|---|---|
| [docs/logging_api.md](docs/logging_api.md) | Both import patterns, log levels, the mocking contract other branches' tests rely on |
| [docs/monitor.md](docs/monitor.md) | Mission Control: the threads, multi-CLI session reading, the commons feed |
| [docs/dashboard.md](docs/dashboard.md) | Refresh, template push and diff, and the write-through API services call |
| [docs/dashboard_caps.md](docs/dashboard_caps.md) | The subject cap and whole-file budget every dashboard writer reads, including writers outside prax |
| [docs/log_audit.md](docs/log_audit.md) | Health summaries, growth rates, the stale-log sweep, and the weekly sweep job the daemon can run |
| [docs/discovery.md](docs/discovery.md) | The scheduled scan behind the module registry, and the watcher's own events |
| [docs/json_service.md](docs/json_service.md) | The config/data/log triplet every branch writes through, and its test seam |
| [docs/architecture.md](docs/architecture.md) | How a command reaches a handler: router, unknown-argument gate, exit seam, help behaviour |
| [docs/tests.md](docs/tests.md) | How the suite is organised, what the fixtures guarantee, how to run it |

---

## Integration Points

### Depends On

- `aipass.cli` — console output, headers, success and error formatting.
- `watchdog` — filesystem events for Mission Control and the discovery watcher, with a
  polling fallback when inotify watches run out. It is not on the logging path.
- `aipass.trigger` — event firing. The logging path never touches it; the monitor and
  log-health modules import it at call time.
- Python stdlib: `pathlib`, `logging`, `threading`, `argparse`, `importlib`.
- **@drone is not an import.** Prax never imports drone; it parses the `[CALLER:<branch>]`
  marker drone writes into its own log lines (in either case), and reads `AIPASS_CALLER_CWD` from the
  environment. The coupling is a text format, not a dependency.
- The json service imports stdlib only, on purpose: a fresh interpreter can reach
  `json_handler` without loading a third-party package.

### Provides To

- Every branch — logging through `from aipass.prax import logger`, real-time monitoring, and
  its `DASHBOARD.local.json`.
- Every service — the dashboard write-through API, so each owns its own section and no
  writer deletes another's keys.
- The system — log rotation and audit, the module registry the fleet reads, and the published
  `log_backup_count()`, `LOGGING_ALLOWED` and `LOGGER_DOORS` (see [docs/logging_api.md](docs/logging_api.md)).

---

**Last Updated:** 2026-11-21

---
[← Back to AIPass](../../../README.md)
