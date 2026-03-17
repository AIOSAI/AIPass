# DAEMON

**Purpose:** Cron-triggered task scheduler with plugin system. Routes commands to modules for scheduled tasks, activity reports, action management, and status digests.
**Module:** `aipass.daemon`
**Created:** 2026-03-07
**Citizen Class:** builder
**Last Updated:** 2026-03-17

---

## Overview

Builder citizen -- full 3-layer architecture with identity and memory. DAEMON serves as the background orchestration branch: it discovers modules at startup, routes CLI commands to them, and provides introspection and help output via Rich console.

### What I Do
- Route CLI commands to discovered modules (update, schedule, activity_report, actions)
- Provide scheduled task management and follow-ups
- Generate activity reports across branches
- Manage an action registry with toggle, info, reminders, and schedules
- Produce status digest updates

---

## Architecture

```
daemon/
├── __init__.py
├── README.md
├── DASHBOARD.local.json
├── apps/
│   ├── daemon.py              # Entry point (CLI) — module discovery + command routing
│   ├── daemon_wakeup.py       # Wakeup / cron trigger
│   ├── scheduler_cron.py      # Cron scheduler
│   ├── modules/
│   │   ├── update.py          # Status digest module — summarizes DAEMON activity
│   │   ├── schedule.py        # Scheduled follow-ups — fire-and-forget task management
│   │   ├── activity_report.py # Branch activity report generator
│   │   ├── actions.py         # Action registry CLI — list, toggle, info, reminders
│   │   ├── scheduler_ops.py   # Scheduler cron operations facade
│   │   └── wakeup_ops.py      # Wake-up cron operations facade
│   ├── handlers/
│   │   ├── actions/
│   │   │   └── actions_registry.py   # Action registry implementation
│   │   ├── json/
│   │   │   └── json_handler.py       # JSON data operations
│   │   ├── monitoring/
│   │   │   ├── activity_collector.py  # Collects branch activity data
│   │   │   ├── memory_health.py       # Memory health checks
│   │   │   └── red_flag_detector.py   # Detects anomalies / red flags
│   │   ├── schedule/
│   │   │   ├── task_registry.py       # Task registry for scheduled items
│   │   │   └── .archive/             # assistant_notifier, telegram_notifier (archived)
│   │   ├── telegram/                  # ARCHIVED — moving to skills system
│   │   │   └── .archive/             # assistant_chat (archived)
│   │   └── update/
│   │       └── data_loader.py         # Data loading for status digests
│   ├── extensions/             # Extension point for additional capabilities
│   ├── json_templates/         # JSON template definitions
│   └── plugins/
│       ├── community_rotation.py      # Community rotation plugin
│       ├── daily_audit.py             # Daily audit plugin
│       ├── heartbeat.py               # Heartbeat / liveness plugin
│       └── .archive/                  # botfather_reminder, dev_central_monitor (archived)
├── daemon_json/                # JSON tracking data
├── docs/                       # Documentation
├── dropbox/                    # Incoming file drops
├── logs/                       # Prax log output
├── tools/                      # Branch verification utilities
└── tests/                      # Test suite
```

---

## Commands / Usage

```bash
drone @daemon                       # Show discovered modules (introspection)
drone @daemon --help                # Rich-formatted help with all commands
drone @daemon --version             # Print version

drone @daemon update [args...]      # Status digest — summarize DAEMON activity
drone @daemon schedule [args...]    # Manage scheduled follow-ups and tasks
drone @daemon activity_report [args...]  # Generate branch activity reports
drone @daemon actions [args...]     # Action registry — list, toggle, info, set reminder/schedule
```

Each module accepts `--help` for module-specific usage:
```bash
drone @daemon <command> --help
```

---

## Modules

| Module | Description |
|--------|-------------|
| `update` | Status digest of DAEMON activity |
| `schedule` | Fire-and-forget scheduled follow-ups and task management |
| `activity_report` | Branch activity report generator (plain text output) |
| `actions` | Action registry CLI -- list, toggle, info, set reminder, set schedule, plugin migration |
| `scheduler_ops` | Scheduler cron operations facade for scheduler_cron.py |
| `wakeup_ops` | Wake-up cron operations facade for daemon_wakeup.py |

---

## Integration Points

### Depends On
- `rich` -- Console output and formatted display
- Python stdlib (`sys`, `typing`, `logging`)

### Provides To
- All modules -- background task scheduling, activity monitoring, action tracking
- Plugins -- extensible plugin system for recurring tasks (heartbeat, daily audit, community rotation)
- Note: Telegram handlers archived -- moving to skills system. See `apps/handlers/telegram/.archive/`

---

## Identity

- **Passport:** `.trinity/passport.json`
- **Session History:** `.trinity/local.json`
- **Observations:** `.trinity/observations.json`
- **Branch Prompt:** `.aipass/branch_system_prompt.md`

---

*Last Updated: 2026-03-17*
