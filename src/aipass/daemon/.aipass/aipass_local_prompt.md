# DAEMON — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/daemon/.aipass/aipass_local_prompt.md — Injected on every prompt when in daemon directory. -->

Background scheduler and monitoring branch. Cron-triggered tasks, activity reports, action registry, scheduled follow-ups.

## Commands

```
drone @daemon                          # Introspection — list discovered modules
drone @daemon --help                   # Full help with all commands
drone @daemon update                   # Status digest of daemon activity
drone @daemon schedule list            # List pending scheduled tasks
drone @daemon schedule create "task" --due 7d --to @branch
drone @daemon schedule run-due         # Fire all due tasks (sends emails)
drone @daemon activity                 # Quick 24h activity summary
drone @daemon activity-report          # Full detailed report (--json for raw)
drone @daemon branch-health BRANCH     # Single branch deep dive
drone @daemon actions list             # Action registry
drone @daemon actions set reminder 7d "msg" --to @branch
drone @daemon actions set schedule @branch "prompt" daily 04:00
```

Note: The `activity_report` module handles three commands: `activity`, `activity-report`, `branch-health`.

## Apps Layout

```
apps/
├── daemon.py              # Entry point — module discovery + command routing
├── daemon_wakeup.py       # Wakeup / cron trigger
├── scheduler_cron.py      # Cron scheduler
├── modules/               # update, schedule, activity_report, actions, scheduler_ops, wakeup_ops
├── handlers/
│   ├── actions/           # actions_registry.py
│   ├── json/              # json_handler.py
│   ├── monitoring/        # activity_collector, memory_health, red_flag_detector, report_generator
│   ├── schedule/          # task_registry, assistant_notifier, telegram_notifier
│   ├── telegram/          # assistant_chat
│   └── update/            # data_loader
├── extensions/            # Extension point (empty)
└── plugins/               # botfather_reminder, community_rotation, daily_audit, dev_central_monitor, heartbeat
```

## Known Issues

- `activity_report` module shows as `activity_report` in `--help` but its actual commands are `activity`, `activity-report`, `branch-health` — calling `drone @daemon activity_report` fails
- `branch-health` expects uppercase branch names from registry; lowercase fails
- Secrets path: `~/.secrets/aipass/` (Path.home() / '.secrets' / 'aipass')

## Memory & Tracking

- `.trinity/passport.json` — identity
- `.trinity/local.json` — session history
- `.trinity/observations.json` — collaboration patterns
- `dev.local.md` — scratchpad for issues, todos, notes
- `DASHBOARD.local.json` — dashboard state
