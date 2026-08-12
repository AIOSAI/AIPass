[← Back to AIPass](../../../README.md)

# PRAX

**Purpose:** System-wide logging, real-time monitoring, and dashboard infrastructure for AIPass.
**Module:** `aipass.prax`
**Version:** 2.2.0
**Last Updated:** 2026-08-11

---

## Overview

Prax is the logging and monitoring backbone of the AIPass ecosystem. Any branch imports `logger` and gets automatic log routing — prax detects the caller via stack introspection and writes to the correct per-module log file. No configuration needed.

On top of logging, prax provides Mission Control (a real-time terminal console for file changes, log events, and agent activity), a log audit system, and a dashboard infrastructure.

## Quick Start

```python
from aipass.prax import logger

logger.info("Processing started")
logger.warning("Disk usage high")
logger.error("Connection failed")
```

Logs auto-route via two-tier placement:
- `system_logs/<branch>_<module>.log` — central aggregation at the repo root
- `<branch>/logs/<module>.log` — branch-local debugging

## Commands

```bash
drone @prax                              # Show discovered modules
drone @prax --help                       # Full command list
drone @prax --version                    # Version string
```

### Monitor — Mission Control

```bash
drone @prax monitor                      # Show monitor architecture
drone @prax monitor run                  # Launch Mission Control (all branches)
drone @prax monitor run seedgo,cli       # Monitor specific branches
drone @prax monitor run commons          # Live social feed of The Commons
drone @prax monitor run commons --logs   # Tail commons' technical logs instead
drone @prax monitor run --relay          # Mirror to Telegram (prax_monitor bot)
drone @prax monitor --help               # Monitor usage
```

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Branch scoping** — `monitor run seedgo,cli` shows only those branches (see below)
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[BRANCH/model]` (e.g., `[DEVPULSE/opus]`, `[DEVPULSE/gpt-5.4]`)
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL) session monitoring
- **Rate tracking** — 4th background thread scans `system_logs/` for runaway log growth every 10s
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`.

**Branch scoping.** A comma-separated list (`monitor run seedgo,cli`) restricts the
display to those branches; bare `run` and `run all` show everything, unchanged. A
scope covers each named branch's log lines, file changes and CLI sessions —
including session labels that carry a project prefix or model tag
(`AIPASS/SEEDGO/opus`) — plus commands the branch issued or was targeted by
(`devpulse → prax` appears in both scopes). Filtering happens at the queue, so
out-of-scope traffic never occupies a display slot and cannot push wanted events
out under load. The banner and `status` name the active scope, `status` also
reports how many events the scope is holding back, and a name that is in no
branch registry is called out at launch rather than showing a silently empty
screen. The monitor's own health warnings (file watcher unavailable, and similar)
bypass the scope — a filter must never hide the reason the screen is empty.
The scope is set at launch; there is no runtime `filter` command outside commons
feed mode.

**Commons feed mode** (`monitor run commons`) is a different watcher, not a branch
filter — it renders live social activity in The Commons (posts, comments, votes,
reactions) read-only, instead of file/log events. `--logs` opts back out to tailing
the commons branch's technical logs. Feed mode adds two interactive commands of its
own: `filter <room>` (comma-separated) and `filter clear`. `--relay` works in both
modes, and is also enabled by `AIPASS_PRAX_MONITOR_RELAY=1`.

### Log Health

```bash
drone @prax log-health                   # Show module info
drone @prax log-health scan              # Scan all log files, show current growth rates
drone @prax log-health snapshot          # Show last known rates (no new scan)
drone @prax log-health --help            # Log health usage
```

Quick overview of log file growth rates across `system_logs/`. Powered by the rate tracker handler — `scan` runs a fresh measurement, `snapshot` reads the last persisted state without scanning.

### Status

```bash
drone @prax status                       # System health (modules, loggers, watcher state)
drone @prax status sync                  # DORMANT — STATUS.md sync decommissioned (TDPLAN-0007)
drone @prax status --help                # Status usage
```

### Log Audit

```bash
drone @prax log-audit                    # Show audit module info
drone @prax log-audit audit              # Scan system_logs/ for health + oversized files
drone @prax log-audit enforce            # Truncate oversized logs to 1000 lines
drone @prax log-audit --help             # Audit usage
```

### Dashboard

```bash
drone @prax dashboard                    # Show dashboard sections
drone @prax dashboard refresh --all      # Refresh all branch dashboards from centrals
drone @prax dashboard refresh @flow      # Refresh a specific branch
drone @prax dashboard status             # Show dashboard status
drone @prax dashboard push-template      # Push template to all branches
drone @prax dashboard diff-template      # Diff template vs branch dashboards
drone @prax dashboard --help             # Dashboard usage
```

## Logging API

### Pattern A — Canonical (use this)

```python
from aipass.prax import logger

logger.info("Processing started")
```

This works from any branch. Prax detects the caller via stack introspection and routes to the correct log file. If prax fails to import, a NullLogger fallback prevents crashes.

Four levels are available — `debug()`, `info()`, `warning()`, `error()`.

### Log levels

`debug()` is silent by default. Nothing it logs reaches a file until the level is
lowered, which is the point: use it for the verbose trail you want available on
demand but absent from normal operation.

```bash
AIPASS_LOG_LEVEL=DEBUG drone @yourbranch yourcommand   # verbose run
```

The level can also be set per tier in `prax_json/prax_logger_config.json`, so a
branch can keep a verbose local log while the central aggregation stays quiet:

```json
{"config": {"system_logs": {"log_level": "INFO"}, "local_logs": {"log_level": "DEBUG"}}}
```

Precedence is `AIPASS_LOG_LEVEL` → the tier's `log_level` → `INFO`. An
unrecognised value warns once and falls back to `INFO` rather than silently
picking a level nobody asked for.

**Levels bind when a logger is created, not per call.** A long-running process
(Mission Control, a daemon, a bot) picks up a level change on restart — setting
the env var mid-flight does nothing for loggers that already exist.

### Pattern B — Direct Logger (for prax internals)

```python
from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()
logger.info("Direct log entry")
```

Use this in prax handler files that run in watchdog threads or sit in the import chain. Resolves module/branch at creation time, bypassing the runtime event pipeline.

### Programmatic Dashboard API

```python
from aipass.prax.apps.modules.dashboard import write_section

write_section(branch_path, "ai_mail", {"new": 3, "total": 5})
```

## Architecture

```
prax/
├── __init__.py                        # Public API: exports `logger` (NullLogger fallback)
├── apps/
│   ├── prax.py                        # Entry point — auto-discovers modules, routes commands
│   ├── modules/                       # Business logic (6 command modules)
│   │   ├── logger.py                  # SystemLogger — auto-routing, two-tier logging
│   │   ├── monitor.py                 # Mission Control — 4-thread real-time monitoring
│   │   ├── dashboard.py               # Dashboard — template management, refresh, write-through
│   │   ├── status.py                  # System status — health display (STATUS.md sync dormant)
│   │   ├── log_audit.py              # Log audit — scan, health summary, enforce limits
│   │   └── log_health.py             # Log health — rate overview (scan/snapshot)
│   └── handlers/                      # Implementation details (11 handler directories)
│       ├── central/                   # Central file reader (.ai_central/*.central.json)
│       ├── config/                    # Path resolution, log config, ignore patterns
│       ├── dashboard/                 # Refresh, operations, template push/diff, agent status
│       ├── discovery/                 # Module scanning, filtering, file watcher for new .py
│       ├── json/                      # Auto-creating JSON handler (config/data/log per module)
│       ├── json_templates/            # Default JSON templates for auto-creation
│       ├── logging/                   # Setup, rotation, introspection, override, direct logger
│       ├── monitoring/                # Event queue, branch detector, branch scope, stream output, log watcher, rate tracker
│       ├── registry/                  # Module registry load/save
│       ├── status/                    # STATUS.md sync handler (dormant — TDPLAN-0007)
│       └── watcher/                   # Background system watchers
├── prax_json/                         # Auto-created per-module config/data/log files
├── templates/                         # Dashboard template schema (DASHBOARD.template.json)
└── tests/                             # 1197 tests across 29 files
```

### Design Pattern

The entry point (`prax.py`) has zero business logic — it auto-discovers modules in `apps/modules/` and routes commands. Each module is a thin orchestrator over its handlers. Handlers are never imported by external branches.

### Command Routing

```
drone @prax monitor run
  → prax.py discovers modules (glob apps/modules/*.py)
  → calls monitor.handle_command("monitor", ["run"])
  → monitor.py delegates to handlers/monitoring/*
```

## How It Works

1. **Auto-routing** — `logger.info()` inspects the call stack to identify the caller's module, branch, and file path, then routes the log entry to the correct per-module log file.
2. **Two-tier logging** — Each log entry goes to both `system_logs/` (central, all branches) and `<branch>/logs/` (branch-local), both with size-based rotation.
3. **Self-healing** — Auto-creates missing log directories, falls back to `system_logs/external/` for unknown modules, provides NullLogger if prax itself fails to import.
4. **Mission Control** — Four threads: display worker (pulls from event queue), file watcher (watchdog on branch `apps/` dirs), log watcher (tails `system_logs/*.log`), rate tracker (scans `system_logs/` for runaway growth every 10s). Falls back to polling when inotify is exhausted.
5. **Multi-CLI monitoring** — Watches Claude Code JSONL and Codex JSONL session files. Extracts agent activity (thinking, tool use, responses) with model detection and branch resolution.
6. **Runaway-log detection** — Rate tracker measures byte growth per log file, estimates lines/min from byte deltas. Sustained thresholds: WARNING (>100 lines/min for 2 min), CRITICAL (>10 lines/sec for 1 min). Fires `runaway_log_detected` on the trigger event bus. State persists to disk across process restarts. Per-file suppression available.
7. **Dashboard** — Template-based per-branch dashboard files. Refreshes from central files (`*.central.json`). Write-through API for services to update sections directly.
8. **STATUS sync** — *(Dormant — TDPLAN-0007)* Previously scanned all branch `STATUS.local.md` files and built aggregated `STATUS.md`. Engine code intact but no longer triggered.

## Tests

1197 tests across 29 files, covering all major components:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_filesystem_handler.py | 142 | Multi-CLI adapters, Codex branch detection |
| test_monitoring_handlers.py | 139 | Branch detector, stream output, event handling |
| test_operations.py | 99 | Dashboard operations, write-through |
| test_log_watcher.py | 90 | Log file tailing, agent activity parsing |
| test_monitor_module.py | 82 | Monitor commands, thread lifecycle (4-thread), branch scoping |
| test_telegram_relay.py | 62 | Telegram relay, buffering, pause control |
| test_config.py | 61 | Config loading, path resolution, log levels |
| test_logging_handlers.py | 49 | Setup, rotation, introspection, direct logger |
| test_logging.py | 47 | Core logging system, debug level gating |
| test_logger_module.py | 46 | Logger init, routing, lifecycle, NullLogger fallback |
| test_event_queue.py | 49 | Thread-safe event buffering, scope suppression |
| test_monitoring_filters.py | 39 | Event filtering rules |
| test_commons_feed.py | 28 | Commons live feed, cursors, room filtering |
| test_instance_lock.py | 28 | Single-instance locking, stale reclaim |
| test_rate_tracker.py | 27 | Rate tracking, thresholds, persistence, suppression |
| test_discovery.py | 25 | Module scanning |
| test_registry.py | 24 | Module registry |
| test_watcher.py | 23 | File watcher behavior |
| test_json_handler.py | 18 | JSON auto-creation |
| test_central.py | 14 | Central reader |
| test_log_audit.py | 13 | Log audit |
| test_pid_cache.py | 12 | PID resolution cache |
| test_devpulse_dashboard_plugin.py | 9 | Dashboard plugin (git, session, dispatch) |
| test_jsonl_writer.py | 9 | JSONL append writer |
| test_branch_scope.py | 37 | Branch scope parsing, label matching, attribution |
| test_help_markup.py | 10 | Rendered console output (real Rich console) |
| test_status.py | 8 | Status commands |
| test_sweep.py | 6 | Log sweep |
| test_scaffold.py | 1 | Scaffold placeholder (skipped — branch conftest) |

## Integration Points

### Depends On
- `aipass.cli` — Console output, headers, success/error formatting
- `aipass.drone` — Caller attribution via `[CALLER:BRANCH]` log markers
- `aipass.trigger` — Optional event firing (module_discovered, error_detected)
- `watchdog` — File system monitoring (inotify + polling fallback)
- Python stdlib (`pathlib`, `logging`, `threading`, `argparse`, `importlib`)

### Provides To
- All branches — Unified logging via `from aipass.prax import logger`
- All branches — Real-time monitoring via Mission Control
- All branches — Per-branch dashboard files
- System — Log audit enforcement

## Known Issues
- **inotify exhaustion** — System often near `max_user_watches` limit. Monitor uses polling fallback (functional but slower).
- **No runtime filtering in Mission Control** — `_handle_interactive_cmd` dispatches
  only `help` and `status`; `watch` and `filter` fall through to "Unknown command". Branch
  selection is launch-time only (`monitor run seedgo,cli`) and cannot be changed without a
  restart. Commons feed mode is the exception: it implements `filter <room>` / `filter clear`
  live. `watch` exists in neither mode.

---

*Last Updated: 2026-08-11*

---
[← Back to AIPass](../../../README.md)
