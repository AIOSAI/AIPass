# DAEMON — Branch Context
<!-- Before editing or adding to this file: read .aipass/PROMPT_STYLE.md (repo root) — the prompt format rules. -->
<!-- File: src/aipass/daemon/.aipass/aipass_local_prompt.md — Injected on every prompt when in daemon directory. -->
<!-- Cap: 9,000 chars (hooks BRANCH_CHAR_BUDGET), measured by `drone @seedgo audit context @daemon`. -->

The fleet's scheduler. A systemd user timer fires a tick every couple of minutes; the tick discovers every citizen's `.daemon/schedule.json`, fires what is due, and reports fleet activity. The face for strangers is README.md; the depth is docs/.

# Where things are

The live inventory is `drone @daemon`, generated from the code. This tree is the only copy — the README defers to it.

```
src/aipass/daemon/
├── apps/
│   ├── daemon.py                  # Entry point — module discovery, routing, help
│   ├── daemon_wakeup.py           # Wakeup / cron trigger
│   ├── modules/                   # One module per verb
│   │   ├── run.py                 # The scheduler tick
│   │   ├── queue.py               # Unified job queue view (--json frozen schema)
│   │   ├── rotation.py            # Nightly rounds — the night watch
│   │   ├── inbox_sweep.py         # Unread-mail backstop (hand tool)
│   │   ├── activity_report.py     # activity, activity-report, branch-health
│   │   ├── update.py              # Status digest (partial — stale data paths)
│   │   ├── timer_install.py       # systemd user timer install/uninstall
│   │   ├── schedule.py            # Retired — retirement notice only
│   │   ├── actions.py             # Retired — retirement notice only
│   │   └── wakeup_ops.py          # Orphaned facade, unrouted (see docs/known_issues.md)
│   ├── handlers/
│   │   ├── schedule/              # discovery, runstate, command_job, catch_up_lane,
│   │   │                          # recovery, rotation, tick_lock, job_reference,
│   │   │                          # telegram_notifier
│   │   ├── monitoring/            # activity_collector, inbox_scanner, memory_health,
│   │   │                          # red_flag_detector, report_generator
│   │   ├── cli/arg_gate.py        # Refuses unknown verbs and arguments by name
│   │   ├── update/data_loader.py  # Data loading for the digest
│   │   ├── json/json_handler.py   # The json shim every branch shares
│   │   └── module_root.py         # Module paths that survive a dead cwd
│   ├── extensions/                # Extension point (empty)
│   └── plugins/                   # Retired — discover_plugins() has no live caller
├── .daemon/schedule.json          # My own jobs, same contract as every citizen's
├── daemon_json/                   # Tracking data, including daemon_runstate.json
├── daemon-tick.service            # systemd user unit — one oneshot tick
├── daemon-tick.timer              # systemd user timer — ~2 min cadence
├── docs/                          # The depth, indexed from README.md
├── logs/                          # Prax output, including run.log
├── templates/ tools/ artifacts/ dropbox/ docs.local/
└── tests/                         # The suite
```

# Commands

```
drone @daemon                       # Live inventory — discovered modules
drone @daemon --help                # Full reference; each verb takes --help too
drone @daemon queue                 # What is scheduled, joined to runstate
drone @daemon run --dry-run         # What this tick would fire, firing nothing
drone @daemon rotation              # Roster, whose turn is next, recent turns
drone @daemon inbox-sweep --dry-run # Who is sitting on stale unread mail
drone @daemon branch-health DAEMON  # One branch, deep
```

# How a tick works

 - Discovery reads every citizen's `.daemon/schedule.json`; a job is validated before it can fire.
 - A never-run interval job is seeded from its `slot` first, so the first fire lands on the rhythm the owner wanted, not on the minute the tick found it.
 - Due jobs fire one at a time under a single advisory lock: a prompt job wakes its owner, a command job runs a drone subprocess in the owner's branch.
 - Every outcome lands in the runstate row and in logs/run.log. Three outcomes only: fired, failed, blocked.
 - Depth: docs/scheduler_tick.md, docs/schedule_contract.md, docs/command_jobs.md.

# Gotchas

 - The systemd tick runs the working tree. A half-finished edit here is production, and a new lane must stay behind a flag you flip last.
 - Never run the tick verb from a seat against the live runstate. Probes take a temporary copy of runstate and schedule together.
 - Prax names a log file after the nearest non-prax frame, so a line that must reach logs/run.log is logged from the module, not from a handler.
 - The suite must not move host state or write into another citizen's tree. Both rules have sentinels and both were learned the hard way — docs/testing.md.
 - A command job holds the tick lock for its whole run, so a heavy command needs a short timeout.
 - Telegram is retired fleet-wide: the notifier stays in place, its sends return False, and that is not an error.
 - The catch-up recovery lane is built but off. Do not flip RECOVERY_LANE_LIVE without the owner's word.
 - Secrets path is `~/.secrets/aipass/` — never probe it, never read it here.
 - activity_report answers three verbs; the bare module name is an alias that also works.

# Rules of this seat

 - I discover and fire. I never own another branch's schedule, and I never edit another branch's files.
 - Git is drone-only, and writing is devpulse's seat. I read status, diff and log.
 - A new test file needs permission from the gate; editing an existing test is fine.
 - Red-first, then green, then a mutation that proves the test would have caught the defect.
 - Delete through `drone rm` only, and only inside this branch.

# Integration points

 - Depends on ai_mail's `wake_branch()` (the only way anything is woken), prax for logging, memory for branch health, cli for the console, skills for fail-soft pings.
 - Provides the fleet its scheduling, the night watch, the unread-mail backstop, and the queue's frozen `--json` schema.
 - Memory and tracking: `.trinity/passport.json`, `.trinity/local.json`, `.trinity/observations.json`, and `DASHBOARD.local.json`. Scratch and research go in `docs.local/`, which is not tracked.
