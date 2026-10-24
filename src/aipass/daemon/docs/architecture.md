[<- Back to the README](../README.md)

# Architecture

Directory layout, per-file responsibilities, and the module status table for the daemon branch.

---

## Layout

The directory tree lives only in the branch prompt. What follows are the per-file and
per-directory notes that the tree points at.

### daemon/ (branch root)

| Path | What it does |
|---|---|
| `daemon-tick.service` | systemd user unit — one oneshot tick |
| `daemon-tick.timer` | systemd user timer — ~2 min cadence |
| `daemon_json/` | JSON tracking data |
| `docs/` | Documentation |
| `dropbox/` | Incoming file drops |
| `logs/` | Prax log output |
| `tools/` | Branch verification utilities |
| `tests/` | Test suite for the branch — see [testing.md](testing.md) for how it runs and current coverage |

`__init__.py`, `README.md` and `DASHBOARD.local.json` sit at the root with no inline annotation.

### apps/ (direct children)

| Path | What it does |
|---|---|
| `daemon.py` | Entry point (CLI) — module discovery + command routing |
| `.archive/` | scheduler_cron (superseded by run.py), daemon_wakeup and wakeup_ops (no caller), the plugin loader and its plugins, telegram_notifier |
| `extensions/` | Extension point for additional capabilities |
| `integrations/` | Private branch-local wrappers — gitignored except its README |

### apps/modules/

| Path | What it does |
|---|---|
| `update.py` | Status digest module — summarizes DAEMON activity |
| `run.py` | Scheduler tick — discover .daemon/ jobs, fire due ones |
| `queue.py` | Unified job queue view (Rich table / --json) |
| `activity_report.py` | Branch activity report generator |
| `inbox_sweep.py` | Fleet unread-mail backstop — wakes stale-mail owners |
| `rotation.py` | Rounds — wake policy + status surface |
| `timer_install.py` | systemd user timer install/uninstall |
| `schedule.py` | (retired) prints migration notice only |
| `actions.py` | (retired) prints migration notice only |
| `.archive/` | scheduler_ops (archived) |

### apps/handlers/actions/

| Path | What it does |
|---|---|
| `.archive/` | actions_registry, action_processor (archived) |

### apps/handlers/json/

| Path | What it does |
|---|---|
| `json_handler.py` | The fleet's one json shim — binds prax's service |

### apps/handlers/monitoring/

| Path | What it does |
|---|---|
| `activity_collector.py` | Collects branch activity data |
| `inbox_scanner.py` | Cross-branch stale unread-mail detection |
| `memory_health.py` | Memory health: files, structure, freshness |
| `red_flag_detector.py` | Detects anomalies / red flags |
| `report_generator.py` | Renders activity + branch reports |

### apps/handlers/schedule/

| Path | What it does |
|---|---|
| `catch_up_lane.py` | Tick-side glue: detect+queue the gap, drain one |
| `command_job.py` | Command jobs: validate, run a drone subprocess, notify mail |
| `job_reference.py` | The authoring reference run --help prints (data only) |
| `discovery.py` | Citizen + .daemon/ job discovery (both trees) |
| `recovery.py` | Gap detection, missed windows, queue, wake headers |
| `rotation.py` | Rounds roster, pointer state, prompt rendering |
| `runstate.py` | last_run/next_run tracking + due-logic |
| `tick_lock.py` | Single-instance advisory lock for the tick |
| `.archive/` | assistant_notifier, task_registry, plugin_processor, telegram_notifier (superseded copy) |

### apps/handlers/telegram(disabled)/

| Path | What it does |
|---|---|
| *(this directory)* | Disabled with Telegram: an empty package, not importable, out of the audit and of test collection |
| `.archive/` | assistant_chat (archived) |

### apps/handlers/update/

| Path | What it does |
|---|---|
| `data_loader.py` | Data loading for status digests |

---

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| `update` | Status digest of DAEMON's inbox: counts, actionable items, escalations; an unreadable inbox exits 1 | Operational |
| `queue` | Unified job queue view — Rich table or `--json` (frozen schema for @skills bot) | Operational |
| `schedule` | *(retired)* Fire-and-forget follow-ups — superseded by `.daemon/schedule.json` | Retired |
| `activity_report` | Branch activity reports: `activity`, `activity-report`, `branch-health` (the last also renders entry health via @memory) | Operational |
| `actions` | *(retired)* Action registry — superseded by `.daemon/schedule.json` | Retired |
| `scheduler_ops` | *(archived)* Scheduler cron facade — went to `.archive/` with scheduler_cron.py | Archived |
| `timer_install` | Idempotent systemd user timer installer for daemon scheduler | Operational |
| `run` | Decentralized scheduler tick: discover .daemon/ jobs, fire due ones — a wake, or a drone subprocess for a command job | Operational |
| `inbox_sweep` | Fleet unread-mail backstop — wakes owners of mail unread past 24h | Operational *(hand tool — no scheduled job)* |
| `rotation` | Nightly rounds — alphabetical roster, pointer, turn history | Operational *(job `rounds` enabled: 05:00, opus, one citizen a night)* |
