# Architecture

Directory layout, per-file responsibilities, and the module status table for the daemon branch.

[<- daemon README](../README.md)

---

## Layout

The directory tree itself now lives only in the branch prompt. What follows are the per-file and
per-directory notes that used to sit inline in that tree, kept here so none of that information is
lost.

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
| `daemon_wakeup.py` | Wakeup / cron trigger |
| `.archive/` | scheduler_cron (archived — superseded by run.py) |
| `extensions/` | Extension point for additional capabilities |
| `integrations/` | Private branch-local wrappers — gitignored except its README |
| `.archive/` | json_templates (no readers, archived 2026-09-07) |

### apps/modules/

| Path | What it does |
|---|---|
| `update.py` | Status digest module — summarizes DAEMON activity |
| `run.py` | Scheduler tick — discover .daemon/ jobs, fire due ones (570 lines) |
| `queue.py` | Unified job queue view (Rich table / --json) |
| `activity_report.py` | Branch activity report generator |
| `inbox_sweep.py` | Fleet unread-mail backstop — wakes stale-mail owners |
| `rotation.py` | Rounds — wake policy + status surface |
| `timer_install.py` | systemd user timer install/uninstall |
| `schedule.py` | (retired) prints migration notice only |
| `actions.py` | (retired) prints migration notice only |
| `wakeup_ops.py` | ORPHANED — imported by nothing, unroutable (see [known_issues.md](known_issues.md)) |
| `.archive/` | scheduler_ops (archived) |

### apps/handlers/actions/

| Path | What it does |
|---|---|
| `.archive/` | actions_registry, action_processor (archived) |

### apps/handlers/json/

| Path | What it does |
|---|---|
| `json_handler.py` | The fleet's one json shim — binds prax's service (DPLAN-0325) |

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
| `telegram_notifier.py` | Fail-soft lifecycle pings via @skills |
| `tick_lock.py` | Single-instance advisory lock for the tick |
| `.archive/` | assistant_notifier, task_registry, plugin_processor, telegram_notifier (superseded copy) |

### apps/handlers/telegram/

| Path | What it does |
|---|---|
| *(this directory)* | ARCHIVED — moving to skills system |
| `.archive/` | assistant_chat (archived) |

### apps/handlers/update/

| Path | What it does |
|---|---|
| `data_loader.py` | Data loading for status digests |

### apps/plugins/

| Path | What it does |
|---|---|
| `__init__.py` | discover_plugins() — ORPHANED, no live caller |
| `.archive/` | ALL plugins archived: heartbeat, daily_audit, community_rotation, botfather_reminder, dev_central_monitor |

---

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| `update` | Status digest of DAEMON activity | *(partial)* — reads inbox/sessions but data_loader paths return empty |
| `queue` | Unified job queue view — Rich table or `--json` (frozen schema for @skills bot) | Operational |
| `schedule` | *(retired)* Fire-and-forget follow-ups — superseded by `.daemon/schedule.json` | Retired |
| `activity_report` | Branch activity reports: `activity`, `activity-report`, `branch-health` (the last also renders entry health via @memory) | Operational |
| `actions` | *(retired)* Action registry — superseded by `.daemon/schedule.json` | Retired |
| `scheduler_ops` | *(archived)* Scheduler cron facade — went to `.archive/` with scheduler_cron.py | Archived |
| `wakeup_ops` | *(orphaned)* Facade for daemon_wakeup.py that daemon_wakeup.py never imports — not registered in the router either, so `drone @daemon wakeup-ops` returns Unknown command | Dead code |
| `timer_install` | Idempotent systemd user timer installer for daemon scheduler | Operational |
| `run` | Decentralized scheduler tick: discover .daemon/ jobs, fire due ones — a wake, or a drone subprocess for a command job | Operational |
| `inbox_sweep` | Fleet unread-mail backstop — wakes owners of mail unread past 24h | Operational *(hand tool — no scheduled job since 2026-09-10)* |
| `rotation` | Nightly rounds — alphabetical roster, pointer, turn history | Operational *(job `rounds` ON since 2026-09-10: 05:00, opus, one citizen a night)* |
