# PRAX

**Purpose:** System-wide logging, real-time monitoring, and dashboard for AIPass.
**Module:** `aipass.prax`
**Last Updated:** 2026-03-29

---

## Overview

Prax auto-routes log output from any module to per-module log files and provides a live monitoring console (Mission Control) that shows file changes, log events, and command execution across all branches.

## Commands / Usage

```bash
drone @prax status                              # System health status
drone @prax dashboard                           # Show dashboard
drone @prax monitor                             # Start log monitoring
drone @prax --help                              # Full help
```

## Usage

### Logging

**Canonical import (use this):**

```python
from aipass.prax import logger

logger.info("Processing started")
logger.warning("Disk usage high")
logger.error("Connection failed")
```

This is Pattern A — the recommended way for all branches. Logs auto-route via two-tier placement: `system_logs/<branch>_<module>.log` (central aggregation) and `<branch>/logs/` (branch-local). No configuration needed — prax detects the caller via stack introspection.

Pattern B (`from aipass.prax.apps.modules.logger import system_logger as logger`) also works but is verbose and exposes internals. Use Pattern A.

For prax handlers that need to bypass the event pipeline (watchdog threads, import-chain files):

```python
from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()
logger.info("Direct log entry")
```

### Mission Control

Real-time monitoring console for watching system activity across all branches.

```bash
drone @prax monitor
```

Interactive commands inside the monitor:

```
watch all           # Watch all branches
watch prax          # Watch specific branch
watch errors        # Only show errors
status              # Show current filters
quit                # Exit
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `drone @prax monitor` | Launch Mission Control |
| `drone @prax status` | Show system status |
| `drone @prax log-audit` | Audit log file sizes and health |
| `drone @prax dashboard` | Show system dashboard |
| `drone @prax dashboard refresh --all` | Refresh dashboard data from centrals |
| `drone @prax status sync` | Sync STATUS.md from all branch STATUS.local.md |

## Architecture

```
prax/
├── apps/
│   ├── prax.py                    # Entry point (CLI)
│   ├── modules/
│   │   ├── logger.py              # SystemLogger (public API)
│   │   ├── monitor.py             # Mission Control
│   │   ├── dashboard.py           # System dashboard
│   │   ├── status.py              # System status / STATUS sync
│   │   ├── log_audit.py           # Log file audit
│   │   └── agent_status.py        # Agent status overview
│   └── handlers/
│       ├── central/               # Central file reader
│       ├── config/                # Configuration loading
│       ├── dashboard/             # Dashboard refresh and operations
│       ├── discovery/             # Module scanning and filtering
│       ├── logging/               # Log setup, rotation, introspection
│       ├── monitoring/            # Event queue, branch detection, stream output
│       ├── registry/              # Module registry management
│       ├── status/                # STATUS sync handler
│       └── watcher/               # File and log watchers
├── docs/                          # Documentation
├── templates/                     # Dashboard templates
└── tests/                         # Test suite
```

## How It Works

1. **Auto-routing** — When any module calls `logger.info()`, prax inspects the call stack to identify the caller and routes the log entry to the appropriate file.
2. **Two-tier logging** — Each log entry goes to both `system_logs/` (central aggregation) and `<branch>/logs/` (branch-local), both with rotation. No nested hierarchical placement.
3. **Mission Control** — A multi-threaded monitoring console that watches file changes (via inotify), log events, and agent activity across all branches simultaneously.
4. **Dashboard** — Aggregates data from central files and branch status into per-branch dashboard views. Supports manual refresh from centrals.

---

## Integration Points

### Depends On
- `aipass.cli` — Console output, headers, success/error formatting
- Python stdlib (`pathlib`, `importlib`, `argparse`, `logging`)

### Provides To
- All modules — Unified logging via `system_logger` and `get_direct_logger`
- All modules — Real-time monitoring via Mission Control
- `aipass.spawn`, `aipass.drone`, `aipass.seedgo`, and others — Log infrastructure

---

*Last Updated: 2026-03-29*
