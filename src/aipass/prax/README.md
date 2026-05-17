[← Back to AIPass](../../../README.md)

# PRAX

**Purpose:** System-wide logging, real-time monitoring, and dashboard infrastructure for AIPass.
**Module:** `aipass.prax`
**Version:** 2.0.0
**Last Updated:** 2026-05-16

---

## Overview

Prax is the logging and monitoring backbone of the AIPass ecosystem. Any branch imports `logger` and gets automatic log routing — prax detects the caller via stack introspection and writes to the correct per-module log file. No configuration needed.

On top of logging, prax provides Mission Control (a real-time terminal console for file changes, log events, and agent activity), a log audit system, a dashboard infrastructure, and cross-branch STATUS.md synchronization.

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
drone @prax monitor --help               # Monitor usage
```

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[BRANCH/model]` (e.g., `[DEVPULSE/opus]`, `[DEVPULSE/gpt-5.4]`)
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL), Gemini (JSON) session monitoring
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`.

### Status

```bash
drone @prax status                       # System health (modules, loggers, watcher state)
drone @prax status sync                  # Build STATUS.md from all branch STATUS.local.md
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
│   ├── modules/                       # Business logic (5 command modules)
│   │   ├── logger.py                  # SystemLogger — auto-routing, two-tier logging
│   │   ├── monitor.py                 # Mission Control — 3-thread real-time monitoring
│   │   ├── dashboard.py               # Dashboard — template management, refresh, write-through
│   │   ├── status.py                  # System status — health display, STATUS.md sync
│   │   └── log_audit.py              # Log audit — scan, health summary, enforce limits
│   └── handlers/                      # Implementation details (11 handler directories)
│       ├── central/                   # Central file reader (.ai_central/*.central.json)
│       ├── config/                    # Path resolution, log config, ignore patterns
│       ├── dashboard/                 # Refresh, operations, template push/diff, agent status
│       ├── discovery/                 # Module scanning, filtering, file watcher for new .py
│       ├── json/                      # Auto-creating JSON handler (config/data/log per module)
│       ├── json_templates/            # Default JSON templates for auto-creation
│       ├── logging/                   # Setup, rotation, introspection, override, direct logger
│       ├── monitoring/                # Event queue, branch detector, stream output, log watcher
│       ├── registry/                  # Module registry load/save
│       ├── status/                    # STATUS.md sync handler
│       └── watcher/                   # Background system watchers
├── prax_json/                         # Auto-created per-module config/data/log files
├── templates/                         # Dashboard template schema (DASHBOARD.template.json)
└── tests/                             # 912 tests across 18 files
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
4. **Mission Control** — Three threads: display worker (pulls from event queue), file watcher (watchdog on branch `apps/` dirs), log watcher (tails `system_logs/*.log`). Falls back to polling when inotify is exhausted.
5. **Multi-CLI monitoring** — Watches Claude Code JSONL, Codex JSONL, and Gemini JSON session files. Extracts agent activity (thinking, tool use, responses) with model detection and branch resolution.
6. **Dashboard** — Template-based per-branch dashboard files. Refreshes from central files (`*.central.json`). Write-through API for services to update sections directly.
7. **STATUS sync** — Scans all branch `STATUS.local.md` files, extracts State/Last update fields, builds aggregated `STATUS.md` at the repo root.

## Tests

912 tests across 18 files, covering all major components:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_filesystem_handler.py | 172 | Multi-CLI adapters, Codex/Gemini branch detection |
| test_monitoring_handlers.py | 139 | Branch detector, stream output, event handling |
| test_operations.py | 99 | Dashboard operations, write-through |
| test_log_watcher.py | 82 | Log file tailing, agent activity parsing |
| test_monitor_module.py | 74 | Monitor commands, thread lifecycle |
| test_logging_handlers.py | 41 | Setup, rotation, introspection, direct logger |
| test_logger_module.py | 40 | Logger init, routing, lifecycle |
| test_monitoring_filters.py | 39 | Event filtering rules |
| test_config.py | 38 | Config loading, path resolution |
| test_event_queue.py | 35 | Thread-safe event buffering |
| test_logging.py | 33 | Core logging system |
| test_discovery.py | 25 | Module scanning |
| test_watcher.py | 23 | File watcher behavior |
| test_registry.py | 22 | Module registry |
| test_json_handler.py | 18 | JSON auto-creation |
| test_central.py | 14 | Central reader |
| test_log_audit.py | 10 | Log audit |
| test_status.py | 8 | Status commands |

134/136 public functions tested (99%).

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
- System — `STATUS.md` sync, log audit enforcement

## Known Issues
- **inotify exhaustion** — System often near `max_user_watches` limit. Monitor uses polling fallback (functional but slower).
- **Interactive filtering deferred** — `watch`/`filter` commands in Mission Control are not operational.

---

*Last Updated: 2026-05-16*

---
[← Back to AIPass](../../../README.md)
