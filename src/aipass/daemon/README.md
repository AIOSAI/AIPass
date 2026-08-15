[← Back to AIPass](../../../README.md)

# DAEMON

**Purpose:** Cron-triggered task scheduler with plugin system. Routes commands to modules for scheduled tasks, activity reports, action management, and status digests.
**Module:** `aipass.daemon`
**Created:** 2026-03-07
**Citizen Class:** aipass_framework
**Last Updated:** 2026-08-13

---

## Quick Start

```bash
drone @daemon                           # Show discovered modules
drone @daemon update                    # Status digest
drone @daemon activity                  # Quick 24h activity summary
drone @daemon queue                     # View pending scheduled jobs
drone @daemon run                       # Fire all due jobs now
drone @daemon rotation                  # Whose steward night is next
drone @daemon inbox-sweep --dry-run     # Who is sitting on stale unread mail
drone @daemon branch-health DAEMON      # Deep dive on a branch
drone @daemon install-timer             # Enable systemd 2-min timer
```

---

## Overview

Framework citizen -- full 3-layer architecture with identity and memory. DAEMON serves as the background orchestration branch: it discovers modules at startup, routes CLI commands to them, and provides introspection and help output via Rich console.

### What I Do
- Route CLI commands to discovered modules (update, run, queue, activity_report, rotation, inbox_sweep)
- Fire the decentralized scheduler: discover every citizen's `.daemon/schedule.json`, wake due owners
- Generate activity reports across all branches (24h summary, detailed, per-branch)
- Run the fleet inbox sweep — wake branches sitting on mail unread past 24h
- Run the nightly steward rotation — one citizen a night gets a maintenance turn
- Detect red flags (code changes without memory updates, stale branches)
- Produce status digests (inbox, actionable items, escalations)

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
│   ├── .archive/              # scheduler_cron (archived — superseded by run.py)
│   ├── modules/
│   │   ├── update.py          # Status digest module — summarizes DAEMON activity
│   │   ├── run.py             # Scheduler tick — discover .daemon/ jobs, fire due ones
│   │   ├── queue.py           # Unified job queue view (Rich table / --json)
│   │   ├── activity_report.py # Branch activity report generator
│   │   ├── inbox_sweep.py     # Fleet unread-mail backstop — wakes stale-mail owners
│   │   ├── rotation.py        # Steward rotation — wake policy + status surface
│   │   ├── timer_install.py   # systemd user timer install/uninstall
│   │   ├── schedule.py        # (retired) prints migration notice only
│   │   ├── actions.py         # (retired) prints migration notice only
│   │   ├── wakeup_ops.py      # ORPHANED — imported by nothing, unroutable (see Known Issues)
│   │   └── .archive/          # scheduler_ops (archived)
│   ├── handlers/
│   │   ├── actions/
│   │   │   └── .archive/             # actions_registry, action_processor (archived)
│   │   ├── json/
│   │   │   └── json_handler.py       # JSON data operations
│   │   ├── monitoring/
│   │   │   ├── activity_collector.py  # Collects branch activity data
│   │   │   ├── inbox_scanner.py       # Cross-branch stale unread-mail detection
│   │   │   ├── memory_health.py       # Memory health: files, structure, freshness
│   │   │   ├── red_flag_detector.py   # Detects anomalies / red flags
│   │   │   └── report_generator.py    # Renders activity + branch reports
│   │   ├── schedule/
│   │   │   ├── discovery.py           # Citizen + .daemon/ job discovery (both trees)
│   │   │   ├── rotation.py            # Steward roster, pointer state, prompt rendering
│   │   │   ├── runstate.py            # last_run/next_run tracking + due-logic
│   │   │   ├── telegram_notifier.py   # Fail-soft lifecycle pings via @skills
│   │   │   └── .archive/             # assistant_notifier, task_registry, plugin_processor
│   │   ├── telegram/                  # ARCHIVED — moving to skills system
│   │   │   └── .archive/             # assistant_chat (archived)
│   │   └── update/
│   │       └── data_loader.py         # Data loading for status digests
│   ├── extensions/             # Extension point for additional capabilities
│   ├── json_templates/         # JSON template definitions
│   └── plugins/
│       ├── __init__.py                # discover_plugins() — ORPHANED, no live caller
│       └── .archive/                  # ALL plugins archived: heartbeat, daily_audit,
│                                      # community_rotation, botfather_reminder, dev_central_monitor
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

drone @daemon update                # Status digest — inbox, session info, escalations (partial — reads stale data paths)
drone @daemon schedule list         # List pending scheduled tasks
drone @daemon schedule create "task" --due 7d --to @branch
drone @daemon schedule run-due      # Fire all due tasks (sends emails)
drone @daemon activity              # Quick 24h activity summary
drone @daemon activity-report       # Full detailed report (--json for raw)
drone @daemon branch-health BRANCH  # Single branch deep dive
drone @daemon actions list          # Action registry
drone @daemon actions <id> on/off   # Toggle action
drone @daemon actions set reminder 7d "msg" --to @branch
drone @daemon actions set schedule @branch "prompt" daily 04:00
drone @daemon install-timer           # Install + enable systemd user timer
drone @daemon uninstall-timer         # Stop + remove systemd user timer

drone @daemon inbox-sweep             # Wake owners of mail unread past 24h
drone @daemon inbox-sweep --dry-run   # Show who WOULD wake, wake nobody
drone @daemon inbox-sweep --hours 48  # Custom staleness threshold
drone @daemon inbox-sweep --limit 3   # Cap wakes for this pass

drone @daemon rotation                # Roster, whose turn is next, recent turns
drone @daemon rotation --json         # Same state, machine-readable
```

Each module accepts `--help` for module-specific usage:
```bash
drone @daemon <command> --help
```

---

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| `update` | Status digest of DAEMON activity | *(partial)* — reads inbox/sessions but data_loader paths return empty |
| `queue` | Unified job queue view — Rich table or `--json` (frozen schema for @skills bot) | Operational |
| `schedule` | *(retired)* Fire-and-forget follow-ups — superseded by `.daemon/schedule.json` | Retired |
| `activity_report` | Branch activity reports: `activity`, `activity-report`, `branch-health` | Operational |
| `actions` | *(retired)* Action registry — superseded by `.daemon/schedule.json` | Retired |
| `scheduler_ops` | *(archived)* Scheduler cron facade — went to `.archive/` with scheduler_cron.py | Archived |
| `wakeup_ops` | *(orphaned)* Facade for daemon_wakeup.py that daemon_wakeup.py never imports — not registered in the router either, so `drone @daemon wakeup-ops` returns Unknown command | Dead code |
| `timer_install` | Idempotent systemd user timer installer for daemon scheduler | Operational |
| `run` | Decentralized scheduler tick: discover .daemon/ jobs, fire due ones | Operational |
| `inbox_sweep` | Fleet unread-mail backstop — wakes owners of mail unread past 24h | Operational |
| `rotation` | Nightly steward rotation — roster, pointer, turn history | Operational *(job ships disabled)* |

---

## Scheduling Jobs

Each citizen owns its schedule at `<branch>/.daemon/schedule.json`. The daemon discovers and fires — citizens define their own jobs.

Two trees are swept: framework citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`) and project citizens under `projects/<name>/*` (listed in that project's own sealed `<NAME>_REGISTRY.json`). A project registry's paths resolve against its own project root, never the repo root — `src/baud/baud` exists in both trees, and resolving repo-first picks the wrong directory. Vera-Studio is a separate repo and is out of scope until multi-root discovery exists.

### Job file schema

```json
{
  "version": 1,
  "branch": "@<branch>",
  "jobs": [
    {
      "id": "my-job",
      "enabled": true,
      "schedule": { "type": "interval", "interval_minutes": 30 },
      "wake": { "fresh": true, "model": "haiku" },
      "prompt": "Do something, then STOP."
    }
  ]
}
```

### Schedule types

| Type | Fields | Due when |
|------|--------|----------|
| `interval` | `interval_minutes: N` | Elapsed >= N since last_run. Fires immediately if never run. |
| `daily` | `time: "HH:MM"` | Within +/-15 min of target time, once per day. |
| `hourly` | `time: "M"` (minute) | Within +/-15 min of target minute, once per hour. |
| `once` | `due_date: "YYYY-MM-DD"` | Date <= today, then marks completed. |
| `rotation` | `time: "HH:MM"` | Daily window — but wakes the next citizen on the fleet roster, not the owner. See below. |

### Wake options

- `fresh` (bool) — start a fresh Claude session (true) or resume (false)
- `model` (string, optional) — `"haiku"` or `"sonnet"` recommended for light wakes

### Staggering

No native offset field. To stagger jobs, seed different `last_run` values in `daemon_json/daemon_runstate.json`.

---

## Fleet Inbox Sweep

Replies never wake their recipient, so a reply landing in a sleeping branch's inbox stays invisible until something looks. `inbox-sweep` is that something.

It reads every active branch's `.ai_mail.local/inbox.json`, finds mailboxes holding `new` (unread) mail older than the threshold, and wakes each owner via `wake_branch()` so the mail finally gets read.

| Rule | Behaviour |
|------|-----------|
| Threshold | 24h by default (`--hours N` to override) |
| Once per branch | One wake per branch per sweep, never more |
| Managers | Never woken — reported as skipped, their mail lands live |
| Blocklist | `@devpulse` and anything in ai_mail's `WAKE_BLOCKLIST` is skipped |
| Cap | 5 wakes per pass (`--limit N`); entries are oldest-first, and deferred branches are named in the output, not silently dropped |
| Wake model | `sonnet`, staggered 2s apart |

Scheduled daily at 09:00 from daemon's own `.daemon/schedule.json` (job id `inbox-sweep`). Run `drone @daemon inbox-sweep --dry-run` any time to see who is sitting on stale mail without waking anyone.

---

## Integration Points

### Depends On
- `rich` -- Console output and formatted display
- Python stdlib (`sys`, `typing`, `logging`)

### Provides To
- All modules — background task scheduling, activity monitoring, action tracking
- Plugins — extensible plugin system for recurring tasks (community_rotation, daily_audit, heartbeat)
- Note: Telegram handlers archived — moving to skills system. See `apps/handlers/telegram/.archive/`

---

## Plugins

**The plugin system is retired.** All three plugins are in `apps/plugins/.archive/`, and the
`discover_plugins()` entry point in `apps/plugins/__init__.py` has no live caller — its only
remaining import is from an archived file. Scheduling is now decentralized: each citizen owns
`<branch>/.daemon/schedule.json` and the daemon discovers and fires. See **Scheduling Jobs** above.

| Plugin | Target | Status |
|--------|--------|--------|
| `community_rotation` | @rotating | Archived — superseded by `rotation` module + `fleet-steward` job |
| `daily_audit` | @seed | Archived — targeted @seed, renamed to @seedgo years prior |
| `heartbeat` | @vera | Archived — @vera was never in the branch registry |

---

## Known Issues

*Verified live 2026-08-13 (APLAN-0015). Items are listed only if reproduced this session.*

- **`update` digest reads empty** (0 messages, 0 sessions, no focus) even with live mail and 30+
  recorded sessions — `data_loader` reads different paths than `.trinity/local.json`. Long-standing.
- **`apps/modules/wakeup_ops.py` is orphaned.** Not in the router's module list, so
  `drone @daemon wakeup-ops` returns "Unknown command"; `daemon_wakeup.py` names it only inside a
  print string. Its 9 tests are the only thing importing it.
- **`apps/plugins/discover_plugins()` is orphaned** — its sole caller is an archived file.

### Resolved

- ~~Memory health is fleet-wide noise~~ (2026-08-15) — `validate_memory_structure()` demanded a
  `limits` field that schema 3.0.0 dropped, so **0 of 17** branches passed and every one read
  WARNING forever. Per @memory's schema call the check now asks whether the file is *usable*:
  a metadata section, a readable `schema_version`, and the entry containers for its filename
  (`sessions`/`key_learnings`/`todos` in `local.json`, `observations` in `observations.json`).
  Caps stay @memory's — they live in `memory.config.json` as defaults deep-merged with per-branch
  overrides, and a copy here would drift. Measured after: **17 of 17 clean**, while a real
  pre-3.0.0 file (`projects/speakeasy`) is still flagged with three concrete reasons. Tests now
  pin the live `.trinity` files, not just a fixture — that pin immediately caught this branch's
  own `local.json` carrying a `todos_meta` line with no `todos` container.
- ~~`drone @daemon activity_report` (underscore) fails~~ — works; an explicit alias branch handles it.
- ~~A trailing `--help` could execute the verb~~ — the router now scans every remaining arg, not
  just the first. `inbox-sweep --hours 48 --help` used to run a real sweep and wake branches.

---

## Identity

- **Passport:** `.trinity/passport.json`
- **Session History:** `.trinity/local.json`
- **Observations:** `.trinity/observations.json`
- **Branch Prompt:** `.aipass/branch_system_prompt.md`

---

## Test Suite

- **420 tests** across 18 test files
- 10/10 modules covered, 44/50 public functions tested
- Seedgo audit: **100%** with bypasses, **99%** with the bypass list emptied (22 entries)

*Last Updated: 2026-08-15*

---
[← Back to AIPass](../../../README.md)
