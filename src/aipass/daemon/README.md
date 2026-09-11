[← Back to AIPass](../../../README.md)

# DAEMON

**Purpose:** Decentralized task scheduler fired by a systemd user timer. Discovers every citizen's `.daemon/schedule.json`, wakes due owners, and reports fleet activity. The plugin system it was born with is retired — see **Plugins** below.
**Module:** `aipass.daemon`
**Created:** 2026-03-07
**Citizen Class:** aipass_framework
**Last Updated:** 2026-09-11

---

## Quick Start

```bash
drone @daemon                           # Show discovered modules
drone @daemon update                    # Status digest
drone @daemon activity                  # Quick 24h activity summary
drone @daemon queue                     # View pending scheduled jobs
drone @daemon run                       # Fire all due jobs now
drone @daemon rotation                  # Whose rounds night is next
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
- Run command jobs: a drone command on a schedule, as a subprocess, with no agent woken (DPLAN-0338)
- Generate activity reports across all branches (24h summary, detailed, per-branch)
- Keep the fleet inbox sweep as a hand tool — wake branches sitting on mail unread past 24h (no scheduled job)
- Run the nightly rounds — one citizen a night gets a maintenance turn (05:00, opus)
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
│   │   ├── run.py             # Scheduler tick — discover .daemon/ jobs, fire due ones (570 lines)
│   │   ├── queue.py           # Unified job queue view (Rich table / --json)
│   │   ├── activity_report.py # Branch activity report generator
│   │   ├── inbox_sweep.py     # Fleet unread-mail backstop — wakes stale-mail owners
│   │   ├── rotation.py        # Rounds — wake policy + status surface
│   │   ├── timer_install.py   # systemd user timer install/uninstall
│   │   ├── schedule.py        # (retired) prints migration notice only
│   │   ├── actions.py         # (retired) prints migration notice only
│   │   ├── wakeup_ops.py      # ORPHANED — imported by nothing, unroutable (see Known Issues)
│   │   └── .archive/          # scheduler_ops (archived)
│   ├── handlers/
│   │   ├── actions/
│   │   │   └── .archive/             # actions_registry, action_processor (archived)
│   │   ├── json/
│   │   │   └── json_handler.py       # The fleet's one json shim — binds prax's service (DPLAN-0325)
│   │   ├── monitoring/
│   │   │   ├── activity_collector.py  # Collects branch activity data
│   │   │   ├── inbox_scanner.py       # Cross-branch stale unread-mail detection
│   │   │   ├── memory_health.py       # Memory health: files, structure, freshness
│   │   │   ├── red_flag_detector.py   # Detects anomalies / red flags
│   │   │   └── report_generator.py    # Renders activity + branch reports
│   │   ├── schedule/
│   │   │   ├── catch_up_lane.py       # Tick-side glue: detect+queue the gap, drain one
│   │   │   ├── command_job.py         # Command jobs: validate, run a drone subprocess, notify mail
│   │   │   ├── job_reference.py       # The authoring reference run --help prints (data only)
│   │   │   ├── discovery.py           # Citizen + .daemon/ job discovery (both trees)
│   │   │   ├── recovery.py            # Gap detection, missed windows, queue, wake headers
│   │   │   ├── rotation.py            # Rounds roster, pointer state, prompt rendering
│   │   │   ├── runstate.py            # last_run/next_run tracking + due-logic
│   │   │   ├── telegram_notifier.py   # Fail-soft lifecycle pings via @skills
│   │   │   ├── tick_lock.py           # Single-instance advisory lock for the tick
│   │   │   └── .archive/             # assistant_notifier, task_registry, plugin_processor,
│   │   │                              # telegram_notifier (superseded copy)
│   │   ├── telegram/                  # ARCHIVED — moving to skills system
│   │   │   └── .archive/             # assistant_chat (archived)
│   │   └── update/
│   │       └── data_loader.py         # Data loading for status digests
│   ├── extensions/             # Extension point for additional capabilities
│   ├── integrations/           # Private branch-local wrappers — gitignored except its README
│   ├── .archive/                      # json_templates (no readers, archived 2026-09-07)
│   └── plugins/
│       ├── __init__.py                # discover_plugins() — ORPHANED, no live caller
│       └── .archive/                  # ALL plugins archived: heartbeat, daily_audit,
│                                      # community_rotation, botfather_reminder, dev_central_monitor
├── daemon-tick.service         # systemd user unit — one oneshot tick
├── daemon-tick.timer           # systemd user timer — ~2 min cadence
├── daemon_json/                # JSON tracking data
├── docs/                       # Documentation
├── dropbox/                    # Incoming file drops
├── logs/                       # Prax log output
├── tools/                      # Branch verification utilities
└── tests/                      # Test suite — 599 test functions in 19 files (pytest expands to 698)
```

---

## Unknown arguments are refused (2026-09-07, FPLAN-0492 wave 2b)

Patrick's standing ruling: **an unknown command or argument fails with a non-zero exit and a
message naming the token.** Never default, never silently ignore.

Every verb below routes its arguments through one shared gate,
`apps/handlers/cli/arg_gate.py`. An unexpected positional or an unrecognised flag is refused by
name on stderr, the usage line follows, exit is 1, and **nothing the verb was asked to do runs**.

```
$ drone @daemon queue not_a_real_subarg_xyz
❌ queue: unknown argument 'not_a_real_subarg_xyz'

Usage: drone @daemon queue [--json]
$ echo $?
1
```

The gate knows two kinds of flag, because they consume different amounts of argv: boolean flags
stand alone (`--json`), value flags swallow the token after them (`--hours 48`) — and that token
must not then be judged a stray positional. A help request outranks the gate and always exits 0.

Twelve surfaces are gated (`update`, `queue`, `rotation`, `activity`, `activity-report`,
`activity_report`, `inbox-sweep`, `install-timer`, `uninstall-timer`, `schedule`, `actions`,
`run`), plus `branch-health`, which gates a positional in its own module. Each has a pin in
`tests/test_cli_routing.py`, and each pin was mutation-checked: disable that verb's refusal and
its pin goes red.

The two retired verbs behave slightly differently and deliberately: bare `schedule` / `actions`
still print the migration notice and exit 0, because that notice is the right guidance. A retired
*subcommand* (`schedule create x`) prints the notice **and then refuses** — it did not create
anything, and exiting 0 told the caller's `&&` that it had.

The gate is a **handler**, so it decides and does not print: it raises `UnknownArgument`, and the
router in `apps/daemon.py` renders it once — one message shape for twelve verbs. The router may
not import a handler (seedgo *encapsulation*), so the exception is re-exported through
`apps/modules/__init__.py`; the router talks to the modules layer, the modules layer talks to the
handler. `gate()` is called **outside** each module's `try`, because a module that catches its own
refusal turns exit 1 back into exit 0 — `update` did exactly that before this was fixed.

**No test suite in this branch is parked.** Every `tests/test_*.py` file runs in CI; the only
disabled files under `apps/` are archived, carry a `(disabled)` marker, and are not tests. If a
suite ever has to be parked, the rule is: say so here, name the file, name the reason, and name
what has to be true to un-park it — a silently skipped suite reads as coverage that does not exist.

---

## Commands / Usage

```bash
drone @daemon                       # Show discovered modules (introspection)
drone @daemon --help                # Rich-formatted help with all commands
drone @daemon --version             # Print version

drone @daemon update                # Status digest — inbox, session info, escalations (partial — reads stale data paths)
drone @daemon activity              # Quick 24h activity summary
drone @daemon activity-report       # Full detailed report (--json for raw)
drone @daemon branch-health BRANCH  # Single branch deep dive

drone @daemon queue                   # Unified job queue view (--json for frozen schema)
drone @daemon run                     # One scheduler tick — fire every due job now
drone @daemon install-timer           # Install + enable systemd user timer
drone @daemon uninstall-timer         # Stop + remove systemd user timer

drone @daemon inbox-sweep             # Wake owners of mail unread past 24h
drone @daemon inbox-sweep --dry-run   # Show who WOULD wake, wake nobody
drone @daemon inbox-sweep --hours 48  # Custom staleness threshold
drone @daemon inbox-sweep --limit 3   # Cap wakes for this pass

drone @daemon rotation                # Roster, whose turn is next, recent turns
drone @daemon rotation --json         # Same state, machine-readable
```

`schedule` and `actions` are still routable, but only as retirement notices — they ignore every
argument and print the same migration text pointing at `.daemon/schedule.json`. There is no
`schedule list`, `schedule create`, `schedule run-due`, `actions list`, `actions set` or
`actions <id> on/off`; those subcommands were documented here long after the modules were retired.
Use `run`, `queue` and per-branch `.daemon/schedule.json` instead.

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
| `activity_report` | Branch activity reports: `activity`, `activity-report`, `branch-health` (the last also renders entry health via @memory) | Operational |
| `actions` | *(retired)* Action registry — superseded by `.daemon/schedule.json` | Retired |
| `scheduler_ops` | *(archived)* Scheduler cron facade — went to `.archive/` with scheduler_cron.py | Archived |
| `wakeup_ops` | *(orphaned)* Facade for daemon_wakeup.py that daemon_wakeup.py never imports — not registered in the router either, so `drone @daemon wakeup-ops` returns Unknown command | Dead code |
| `timer_install` | Idempotent systemd user timer installer for daemon scheduler | Operational |
| `run` | Decentralized scheduler tick: discover .daemon/ jobs, fire due ones — a wake, or a drone subprocess for a command job | Operational |
| `inbox_sweep` | Fleet unread-mail backstop — wakes owners of mail unread past 24h | Operational *(hand tool — no scheduled job since 2026-09-10)* |
| `rotation` | Nightly rounds — alphabetical roster, pointer, turn history | Operational *(job `rounds` ON since 2026-09-10: 05:00, opus, one citizen a night)* |

---

## Scheduling Jobs

Each citizen owns its schedule at `<branch>/.daemon/schedule.json`. The daemon discovers and fires — citizens define their own jobs.

**Nothing here is resident.** `install-timer` writes a systemd *user* timer, `daemon-tick.timer`
(`OnActiveSec=30s`, `OnUnitActiveSec=2min`, `Persistent=true`), which fires `daemon-tick.service` —
`Type=oneshot`, running `python3 -m aipass.daemon.apps.daemon run` once and exiting. Between ticks
there is no daemon process at all.

The 2 min is nominal, not exact: `OnUnitActiveSec` measures from the *last activation*, and systemd's
default `AccuracySec=1min` batches the wakeup, so observed gaps run **2–3 min**. A tick costs about
**0.6s of CPU** (`systemctl --user show daemon-tick.service -p CPUUsageNSec`, measured 2026-08-25:
`626320000` ns) and roughly 1s wall. `systemctl --user list-timers` shows the next fire; the tick's
own output appends to `~/.aipass/daemon-tick.log`.

**Three tiers are swept (measured 2026-09-05: 28 citizens).** Core citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`) — 18 tonight. Resident citizens under `projects/<name>/` (listed in that project's own sealed `<NAME>_REGISTRY.json`) — 4 tonight: AIPASS_SITE, BAUD, EARMARK, FINCH. And **federated externals** — citizens in separate repos entirely, reached through their own registries — 6 tonight: VERA, RESEARCH, VERIFY and WRITER under `external/VERA-STUDIO`, plus `external/WREN` and `external/DEMO`. `drone @daemon rotation` prints the tier label; nothing routes on it. The sweep covers all three tiers; the nightly rounds serve only the first — see *Nightly Rounds*.

**Who counts as a citizen is no longer decided here (FPLAN-0460).** The core-registry read, the `projects/*` glob, the dot-filter and the two-key resident rule all used to live in `discovery.py` as a second copy of the fleet definition. They are now one call to `fleet.fleet_branches()` in @memory — a fleet definition with two implementations agrees only by coincidence. `discovery.py:159` consumes that list rather than mirroring it, which is why the federated-external tier above arrived here without a line changing in this branch.

**What this branch still decides is an address.** @memory deliberately leaves that to each caller: their ruling is that a branch with no `email` is KEPT, because the path-based lanes (trinity push, rollover) still want it. Daemon cannot use it — a job's owner IS an email and the wake targets an email — so an addressless citizen is refused, and refused **loudly at error level**, because a citizen dropped without a line in the log is indistinguishable from one that was never discovered. A second row carrying an address already claimed is refused the same way: @memory deduplicates by resolved path, correct for its path-keyed lanes, but daemon is email-keyed and two rows sharing an address would double-fire the first citizen's schedule.

The trust model behind the fleet definition remains asymmetric on purpose: a passport can never *add* scope (nothing walks passports, so a declared resident no registry lists is unreachable by construction), and a passport can never *remove* a core citizen (a core branch declaring nothing is kept and the disagreement is logged — otherwise an agent could stop its own jobs firing by deleting one line of its own file). A project registry's paths resolve against its own project root, never the repo root — BAUD's registry row reads `src/baud/baud`, a path that *could* also resolve under this repo, and resolving repo-first picks the wrong directory.

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

A job carries **exactly one** of `prompt` (wake the owner with it) or `command` (run a drone
command, wake nobody; see *Command jobs* below). Both, or neither, is refused at discovery and
logged, the same way a missing `id` or `schedule` is.

### Schedule types

| Type | Fields | Due when |
|------|--------|----------|
| `interval` | `interval_minutes: N` | Elapsed >= N since last_run. With no `slot`, a job that has never run fires **immediately** — see below. |
| `daily` | `time: "HH:MM"` | Within +/-15 min of target time, once per day. |
| `hourly` | `time: "M"` (minute) | Within +/-15 min of target minute, once per hour. |
| `once` | `due_date: "YYYY-MM-DD"` | Date <= today, then marks completed. |
| `rotation` | `time: "HH:MM"` | Daily window — but wakes the next citizen on the fleet roster, not the owner. See below. |

### Optional schedule fields (2026-09-07, FPLAN-0492 ruling 6)

These live inside the job's `schedule` block, next to `type` and `time`. `slot` is
opt-in. `catch_up` **was** opt-in under ruling 6 and is now on by default — Patrick
reversed it on 2026-09-08 after every enabled job in the fleet left it unset and the
fleet therefore recovered from nothing.

| Field | Applies to | Effect |
|-------|-----------|--------|
| `slot` | `interval` | An ISO instant naming **one occurrence** of the rhythm you want (`"2026-09-06T03:00:00"`). A job that has never run is seeded from it, so its first fire lands on the next slot instead of the next tick. |
| `catch_up` | `daily`, `rotation`, `hourly` | When the window closed with no run, the first tick after it fires the job once and stamps `caught_up` on the runstate row. **ON by default since 2026-09-08** — see *Recovery after a gap*. |
| `catch_up_max_age_hours` | `daily`, `rotation`, `hourly` | Drop missed windows older than N hours. Absent = unlimited, which is the default Patrick asked for: ten days away still earns one wake. |

**Why `slot` exists.** An interval job with no `last_run` is due on the very next
tick, and that tick's minute becomes its rhythm forever. @seedgo enabled a weekly
cycle at 01:34 on 2026-09-07 before its slot was seeded; `run.log` shows two blocked
attempts (01:34:52, 01:40:20) and only @seedgo's own branch lock kept the week from
locking to 01:34 Monday instead of Sunday 03:00. With a slot the "seed first, then
enable" ordering trap disappears — the job can be enabled in any order.

Seeding is keyed on an **absent `last_run`, not an absent runstate row**, and the
difference is the whole cure: a blocked fire creates a row carrying `last_blocked_at`
and no `last_run`, so a row-keyed test would refuse to seed exactly the job that most
needs it. A past slot keeps its *phase* — it is rolled forward by whole intervals, not
used verbatim, so a stale anchor never makes a job instantly overdue. A job with no
slot keeps today's behaviour and says so in `run.log` at WARNING.

**`hourly` gained a catch-up arm on 2026-09-08.** Before that `is_job_due` routed
hourly to `_is_hourly_due` alone, so an hourly job had no catch-up at all whatever
its `catch_up` field said. Its window is refused rather than guessed when it crosses
the hour (a `time` past minute 44), the same shape as daily's midnight refusal.

**`catch_up` is bounded by `_already_ran_today`**, so a caught-up run can never
double-fire the day it lands in, and it never widens the window backwards — a job is
still not due *before* its window opens. A daily window whose tail crosses midnight
(`time` later than 23:44) never closes inside its own calendar day and is refused
rather than guessed at, in both directions.

**The `MISSED` line** is written to `run.log` for every daily job whose window closed
unrun — independent of `catch_up`, because a job nobody opted in still missed its
window and that is the fact you need in order to decide whether to opt it in. Stamped
once per job per day (`missed_logged_for`), since a ~2-minute tick would otherwise
repeat the same miss ~500 times before midnight.

### Wake options

- `fresh` (bool) — start a fresh Claude session (true) or resume (false)
- `model` (string, optional) — `"haiku"` or `"sonnet"` recommended for light wakes
- no wake-back, and not an option: every wake the daemon fires passes `wake_back=False`, so no job's finish wakes `@daemon` to read a reply nobody sends (DPLAN-0337 R2, 2026-09-10)

### Command jobs (2026-09-11, DPLAN-0338)

A job can run a drone command instead of waking an agent. It runs as a subprocess of the tick, so
it uses no seat, no session and no tokens. Patrick asked for this on 2026-09-11 because a
housekeeping sweep should not cost a Claude session: *"if it runs there's a log, if it passed or
failed there's a log, we can change the 10 days to 5 days by one character change."* The first
one is @prax's weekly sweep of stale staging temps (DPLAN-0338 wave 2a):

```json
{
  "id": "tmp-sweep-weekly",
  "enabled": true,
  "schedule": { "type": "interval", "interval_minutes": 10080, "slot": "2026-09-14T04:00:00" },
  "command": "drone rm --stale 10d ../..",
  "timeout_seconds": 600,
  "notify": { "email": "@devpulse" }
}
```

It lives in `src/aipass/prax/.daemon/schedule.json`, so it runs from `src/aipass/prax/`. A
relative path in the command resolves from there, which makes `../..` the `src/` directory.

| Field | Required | Meaning |
|-------|----------|---------|
| `command` | yes, instead of `prompt` | One drone command line. `drone` must be the first token. |
| `timeout_seconds` | no, default **600** | A positive whole number. When it runs out, the command's whole process tree is stopped and the fire is FAILED. 600 matches drone's own executor default. |
| `notify` | no | `false` silences the Telegram pings. `{"email": "@devpulse"}` also sends an ai_mail **email** (never a wake) on start and on finish. |
| `wake` | ignored | A command job wakes nobody. Discovery drops the block and logs a warning if one is present. |

**The rules, and why each one exists.**

- **`drone` is the first token, and nothing else can be.** A schedule file is per-branch and its
  owner can edit it, so whatever it names runs with the tick's authority. Holding command jobs to
  drone verbs means drone's own gates decide what a scheduled command may do: rm's fence, git's
  refusal, the argument gates. `bash -c ...`, `env drone ...`, `/usr/local/bin/drone` and
  `rm ...` are all refused at discovery.
- **No shell.** The command is split with `shlex.split`, which applies POSIX quoting on every
  platform, and runs as an argv list with `shell=False`. That means no globs, no pipes, no `;`
  and no variable expansion. `drone rm *.tmp ; echo x` reaches drone as the literal arguments
  `*.tmp`, `;`, `echo`, `x`. Nothing in a JSON string can turn into a second command.
- **It runs in the owner's branch directory.** Drone reads cwd as identity, so the work is logged
  as the citizen whose schedule asked for it. The directory comes from the same citizen record
  that vouched for the schedule file, looked up by email. It is not looked up again by directory
  name, because two citizens can share one across federated roots. A job with no branch directory
  is refused, never run from the tick's own cwd (the repo root, which would sign it as the project).
- **Never a rotation.** A rotation wakes tonight's citizen on the roster. A command wakes nobody,
  so the two cannot be combined, and the combination is refused.

**What a fire records.** Exit 0 is `fired`. A non-zero exit, a timeout, or a command that could
not start is `failed`, with the detail `exit 2, 0.4s — <last lines of output>`. A command job is
**never** `blocked`: no seat is in use, so no gate can refuse it, and it never takes the
active-agent lock. The runstate row is exactly a wake job's row (`last_run`, `last_status`,
`last_success_at` / `last_failure_at`, `last_error`, and `completed` for `once`). Catch-up,
interval, daily, slot and backoff logic is unchanged, because due-ness never reads what a job does.
`drone @daemon queue` shows `command: <the command>` in the preview column. The frozen `--json`
keys are unchanged.

**Two log lines every fire, pass or fail**, written to both the tick log
(`~/.aipass/daemon-tick.log`) and `logs/run.log`:

```
FIRE: @daemon/dplan-0338-proof -> command: drone @daemon --help
DONE: @daemon/dplan-0338-proof — exit 0, 1.5s —   Fleet mail: | ... |   drone @daemon <command> --help
```

**Notify.** The Telegram pings follow the rule every job follows (`_should_notify`: on unless
`notify` is false). A `notify` block counts as on. `notify.email` sends one mail as the command
starts (owner, id, command, timeout) and one as it finishes (exit code, duration, output tail).
The mail goes out as a `drone @ai_mail email` subprocess from daemon's own directory, so it is
signed `@daemon`. It is not sent through an in-process ai_mail import, for two reasons: ai_mail has
no public send function that takes an explicit sender, and the tick runs from the repo root, so an
in-process send would sign the mail as the project. A mail that fails is logged as a WARNING and
never changes the fire's answer. Each mail costs about 5 to 7 seconds of tick time (measured
on the proof). That is fine for a weekly job and a reason not to set `notify.email` on a job that
runs every few minutes.

**How the subprocess runs.** It uses `Popen`, not `subprocess.run(capture_output=True)`, for two
measured reasons:

- **Output goes to an anonymous temp file, not a pipe.** A pipe only reaches EOF when every
  holder of its write end has closed it. A drone verb that starts anything in the background hands
  that process the pipe, so a command that exited 0 in a second would be reported as a 600-second
  timeout. Mutation-proved: swapping in the pipe form turns
  `test_a_background_child_holding_the_output_is_not_a_timeout` red. `TemporaryFile` is unlinked
  the moment it is created, so it leaves no `.tmp` litter behind.
- **A timeout stops the whole process tree.** Drone runs every `@branch` verb in a child of its own
  (`drone/apps/handlers/executor.py`), so killing drone alone would orphan exactly the work that
  overran. On POSIX the command gets its own session, and the timeout sends SIGTERM to the group,
  waits 2 s, then sends SIGKILL. Windows has no process group to signal: the direct child is killed
  and a grandchild may outlive it. That is the known residual.

stdin is `/dev/null`: a scheduled command has no human to answer a prompt.

**While a command runs, it holds the tick.** Ticks are single-instance, so a command that takes
ten minutes makes the next four or five timer fires step aside (`Another scheduler instance is
running`). A windowed job still has its ±15 minutes, and the 600 s default stays well under the
30-minute gap threshold. It is still a reason to keep command jobs short.

**Proof on the real clock (2026-09-11).** A `once` job running `drone @daemon --help`, with
`notify.email` set to `@daemon`, went into daemon's own schedule. The live timer fired it at
13:03:45: FIRE, then DONE `exit 0, 1.5s`, a runstate row with `last_status: success` and
`completed` set, and both mails in the inbox (13:03:50 started, 13:03:59 passed). The job was then
removed.

### What a fire consumes (2026-08-30)

**Only a wake that actually STARTED consumes the job's period.** A fire ends in one
of three states, not two, and each writes a different record:

| Outcome | What happened | `last_run` | Next tick |
|---------|---------------|-----------|-----------|
| `fired` | An agent started | stamped | period consumed |
| `blocked` | The wake was refused before anything started — the target is busy (`lock`), holds an interactive session (`occupancy`), autonomous_pause is on, or the dispatch lock could not be taken | **untouched** | still due; retries inside the same window after a 5-min hold |
| `failed` | The wake ran and went wrong, or the target is a decided refusal (`resolve` — no such branch; `blocklist`) | stamped | measured from the last SUCCESS; 10-min backoff |

The middle row is the fix for a scheduler that planted the blocker for its own next
fire: an interactive room left open in a branch made `wake_branch` refuse, the refusal
was recorded as a run, and the next day's fire was swallowed by a room nobody was
sitting in. Blocked is not ran.

Both holds are **bounds, not suppressions**. Removing a suppression without adding a
bound is how you turn one swallowed fire into a spawn storm: a windowed schedule allows
±15 min at a ~2-minute tick, and an interval job measures from its last *attempt*, which
a block deliberately does not write. Blocked holds for less than a failure (5 min vs 10)
because nothing spawned and the target being busy usually clears itself.

`queue` renders the new `blocked` value in its existing `last_status` column — the
`--json` schema is unchanged.

### The scheduled lane

Every wake `run` makes was fired by a clock, so it passes `scheduled=True` to
`wake_branch` unconditionally. The flag describes **this caller's lane, never the
target** — deciding it per-target would mean reading the target's passport here, a
second copy of the manager gate `wake_branch` already owns.

What it changes: a **manager** target goes headless through `dispatch_monitor`
(self-terminating, context pin, bounce mail, lock cleanup, a register entry something
closes) instead of an interactive tmux session that nothing ever closes — which was the
room that blocked the next night's fire. A **`WAKE_BLOCKLIST`** target (`@devpulse`) is
refused outright in this lane; `@devpulse/cl-harvest-resume` is the one job that would
meet that fence, and it ships disabled. Every other target is unaffected.
`rotation.py` already took this lane for managers; `run.py` was the odd path out.

### Staggering

Interval jobs have `slot` (above) — declare the hour you want and the first fire lands on it. For the other types, seed different `last_run` values in `daemon_json/daemon_runstate.json`. Within a single tick, jobs that fire together are already separated by a fixed 1s sleep (`run.py`) — that is not configurable and is not a substitute for offsetting the schedules themselves.

---

## run.py's split (2026-09-08, PR #759 row 13)

`run.py` reached 690 lines against seedgo's module cap and held one direct file
operation — `LOCK_FILE.parent.mkdir` — which a module may not do. Both were the last
red row on PR #759. Two coherent pieces came out; the tick lane itself did not move.

| Module | Owns | Why it is not in run.py |
|--------|------|-------------------------|
| `handlers/schedule/catch_up_lane.py` | detect-and-queue, drain-one, and the `OUTCOME_*` vocabulary | The DPLAN-0332 glue is a whole subject, and it was the largest block a reader had to skip past to follow an ordinary tick |
| `handlers/schedule/tick_lock.py` | the lock directory, the lock file, `fcntl` | It is the only thing in the tick lane that touches the filesystem, and a handler may do that where a module may not |

**`catch_up_lane` fires nothing itself.** `fire` and `log` arrive as callables from
`run.py`. A handler may not import a module — that is seedgo's encapsulation rule and
the circular import it exists to prevent — so injection is what keeps the dependency
arrow pointing one way. It also means the lane is testable without a tick.

**`tick_lock` takes the lock path as an argument** rather than holding its own copy of
the constant. `run.py` still owns `LOCK_FILE`, so a test that seams the path on that
module still seams the file that actually gets opened; a second copy of the constant
would have quietly re-pointed the suite at the live lock.

`OUTCOME_FIRED` / `OUTCOME_FAILED` / `OUTCOME_BLOCKED` are re-exported from `run.py`,
not redefined there: the drain branches on the same three words the fire returns, and
one definition means they cannot drift.

Result: **run.py 690 → 585 lines**, zero direct file operations, `Modules` 100,
`drone @seedgo audit aipass @daemon` **100%**. No behaviour changed and
`RECOVERY_LANE_LIVE` stayed `False` throughout.

**The cap is 600 lines, not 650** (measured 2026-09-11 in seedgo's
`handlers/aipass_standards/modules_check.py`: 600 or more fails as "too large"). This section
said 650 until then. DPLAN-0338 wave 1a's command-job arm took run.py from 589 to 647 and cost
the audit a point. The 79 lines of static job-authoring reference that `run --help` prints moved
to `handlers/schedule/job_reference.py` as data, and run.py still does the printing. Result:
**run.py 570 lines**, with `run --help` output byte-identical before and after (diffed at
`COLUMNS=200`). The fire logic stayed in run.py on purpose. Prax names a log file after the
nearest calling frame, so the FIRE and DONE lines reach `logs/run.log` only when run.py
writes them.

## Recovery after a gap (2026-09-08, DPLAN-0332)

On 2026-09-07 the scheduler timer went away at 11:46 and nothing ticked for 23 hours.
@vera/release-watch and @daemon/inbox-sweep both missed their windows. The fleet came
back and **nothing noticed** — no gap was detected, no catch-up was owed, and the
agents that eventually woke were told nothing about the time they had lost. Patrick's
ruling that morning: the scheduler must recover on its own, and the agent must be
told the truth about time.

The principle the header follows: **the system informs, the agent reasons.** The
header states facts about time and stops. It never tells the agent what to conclude
and it never replays history at it.

**The path a gap takes through a tick**

| Step | Where | What it does |
|------|-------|--------------|
| stamp | `recovery.record_tick` | `last_tick` written in a `finally`, so the stamp survives every early return |
| detect | `recovery.detect_gap` | gap wider than 30 min (~15 missed ticks); cause read from the host |
| enumerate | `recovery.enumerate_missed` | every `daily`/`rotation`/`hourly` window that both **opened and closed** inside the gap |
| queue | `recovery.queue_catch_up` | **one** entry per `@owner/job_id` carrying every missed instant, merged idempotently on re-detection |
| supersede | `recovery.drop_from_queue` | a job whose regular window arrives first drops its entry — the on-time wake still carries the missed list |
| drain | `recovery.drain_ready` | at most **one** catch-up in flight fleet-wide; the next goes when the previous completed, 60 min is the ceiling not the rhythm |
| inform | `recovery.scheduled_header` / `catch_up_header` | prepended to the prompt, filed to the target's `.daemon/last_wake_prompt.txt` **and** `daemon_json/last_wake_prompt.txt`, and logged to `run.log` |

**Cause is read from the host, or refused by name.** `psutil` first (the fleet has a
Windows job), `/proc/stat btime` second, then `BootTimeUnavailable` — never a guess,
because a guessed boot time becomes a confident false sentence in a citizen's wake
header.

| Boot time | Cause | What the sentence says |
|-----------|-------|------------------------|
| before the gap opened | `scheduler_stopped` | ticking stopped at X while the machine was up — 09-07's shape |
| inside the gap | `scheduler_stopped_then_rebooted` | ticking stopped at X, **and** the host booted at Y, inside the gap, after it had already opened |
| not readable | `unknown` | the cause could not be read from this host — the gap is still reported |

Three values, not the DPLAN's original two. @devpulse ruled on 2026-09-08 after
measuring 09-07: the incident was **both** — the timer was removed at 11:46 while the
machine was up, and the machine then rebooted at 16:14 inside the same gap. A
two-valued cause reports only the reboot and hides the defect that actually mattered.
There is no `machine_off` value, because boot-inside-the-gap cannot be told apart
from "shut down for the night" without positive evidence the host was up during the
gap, and no cross-platform source provides it — so the cause names what is **known**
and the sentence states both instants rather than picking a story.

**One catch-up, never a replay.** Ten days off is one wake carrying ten dates, not
ten wakes — "imagine 10 missed events all firing at once" (Patrick). The header ends
with *do not replay each one*, because an agent handed ten dates may otherwise
reasonably try to do ten days of work. A refused fire retries after the cooldown;
three attempts and it is **parked at the tail of the queue, not dropped** — "we could
not reach this branch" and "this branch owed nothing" are not the same sentence.

**The queue is visible.** `drone @daemon queue` prints a Catch-up Queue under the job
table (owner, windows missed, oldest, cause, state, attempts) whenever anything is
owed, and `--json` gained an additive `catch_up_queue` key. The eleven job fields and
the three original top-level keys are untouched, so @skills' scheduler bot sees
exactly what it saw before.

**Where the wake transcript is filed.** Both places, per @devpulse's ruling of
2026-09-08: the target branch's `.daemon/last_wake_prompt.txt` **and** daemon's own
`daemon_json/last_wake_prompt.txt`. `.daemon/` is the scheduler's surface in every
branch — the owner writes `schedule.json` into it, the scheduler writes its outputs
beside it — so this is the daemon's own artifact in the daemon's own directory, not a
cross-branch edit of somebody's code. Written atomically (tmp then replace) so a
branch waking mid-write never reads half a header, and fail-soft **per destination**
so a read-only external tree costs neither the local copy nor the wake. The owner is
resolved by **email** through discovery's roster, never by directory name: two
citizens can share a directory name across federated roots, and filing a wake under
the wrong one hands a citizen somebody else's instructions. ai_mail's write at
`wake.py:802` stays for the tmux manager lane; the headless scheduled lane it never
covered now has this second writer.

**`RECOVERY_LANE_LIVE` (`runstate.py`) is `False`, and everything above is built but
NOT IN SERVICE.** The systemd tick runs this **working tree** every two minutes, not a
commit — an edit here is production the moment it is saved. That bit the fleet twice
in one morning: at 11:31:42 the half-flipped default fired @vera/release-watch out of
window with no header, and at 12:04:39, minutes after the flag went `True`, the very
next timer tick fired her a *second* time that day under a `Scheduled` header whose
"Last run 2026-09-07 09:46" was false — she had run at 11:31:42.

@devpulse's ruling, 2026-09-08: *"the tree is production while the timer is installed,
so nothing under the flag may be True at any moment you are not personally watching a
tick."* The flag stays `False` until the controlled live proof runs from @devpulse's
seat with Patrick. `False` is exactly the pre-DPLAN-0332 behaviour: `catch_up` is
opt-in again, no gap detection, no queue, no drain.

**Two refusals detect_gap owes the fleet**, both found by @devpulse reading run.log
against the journal after my own probes wrote false sentences into it:

- **No `last_tick` is not a gap.** A runstate full of older instants (`last_run`,
  `last_success_at`, `next_run`) is the temptation; reaching for one invents an
  absence the fleet never had and queues catch-ups for windows nobody missed.
- **A boot that precedes the last tick did not cause the gap**, and the sentence has
  to *say* so rather than merely mention the instant — a boot named next to a gap
  reads as cause to anyone skimming it.

**Probes run against copies.** The live runstate is host state under the rule that
landed at `0d14e8c1`: never run the `run` verb from a seat against it. Every
experiment takes a `tmp_path` copy of the runstate and the schedule file.

## Nightly Rounds (2026-09-10, DPLAN-0337 R2)

The night watch doing its rounds: one citizen a night, woken fresh on opus for a maintenance turn inside its own branch. Designed in August as DPLAN-0287, shipped disabled as `fleet-steward`, renamed `rounds` and switched on by Patrick's ruling of 2026-09-10.

| Knob | Value |
|------|-------|
| Job | `@daemon/rounds`, type `rotation`, in daemon's `.daemon/schedule.json` |
| When | 05:00 window (+/-15 min — the first tick inside it fires, so about 04:45); `catch_up` off, a missed night is not woken late |
| Who | **Framework fleet only** — citizens whose branch lives under this install's `src/aipass/` (17 on 2026-09-10). `projects/*` residents and every external root are out, whatever their class. Alphabetical by email. `@devpulse` never; managers excluded (`include_managers: false`) |
| Wake | `fresh: true`, `model: opus`, `sender: @daemon`, `wake_back: false` |
| Busy target | Logged as a miss, pointer advances, that citizen gets its next turn in the cycle |

**Scope, by ruling.** Patrick, 2026-09-10 21:47, marked very important: the rounds are AIPass maintaining its own agents. Vera keeps her own schedule, and the projects are nowhere near a trust stage. `ROSTER_SCOPE` in `apps/handlers/schedule/rotation.py` is a named rule applied inside `build_roster` before any passport is read. It is decided on the branch PATH, never on the tier label, which stays presentation-only. `drone @daemon rotation` prints it on its `Scope:` line. Pinned by `TestRoundsScope`: a temp install holding a framework branch, a projects resident and an external-root citizen, all declaring the same class, serves only the first.

**What a citizen does on its night:** inbox to zero; reconcile `.trinity` todos against reality; refresh and read its dashboard; review its logs; run its seedgo self-audit; do mailed-in work only if it sits in its own domain and fits one session; small fixes in its own branch, red-first.

**Budget, stated in the prompt:** never dispatch or wake another citizen; at most 2 sub-agents, sonnet or lower; never edit another branch; no fleet-wide investigations; anything out of lane is written down for @devpulse, not chased.

**The night's one artefact** is a single mail to @devpulse: health verdict, what it did, what it noticed, what it needs. There is no dispatch to reply to — a rounds wake is a session prompt, not a mail — and no APLAN step.

`drone @daemon rotation` shows the roster, whose night is next, and the last ten turns. Pinned by `TestShippedRoundsJob` (the stanza as shipped) and `TestRoundsNight` (a real tick at 05:01, wake caught at ai_mail's `wake_branch` seam).

## Fleet Inbox Sweep

Replies never wake their recipient, so a reply landing in a sleeping branch's inbox stays invisible until something looks. `inbox-sweep` is that something.

It reads every active branch's `.ai_mail.local/inbox.json`, finds mailboxes holding `new` (unread) mail older than the threshold, and wakes each owner via `wake_branch()` so the mail finally gets read.

**Scope: a citizen is a citizen.** The sweep looks wherever the fleet definition looks — `src/aipass/*` framework branches, `projects/*/` residents and the federated externals alike — because it walks discovery's active branch map and that map is @memory's `fleet.fleet_branches()`. Measured 2026-09-07: **28 citizens, 18 core + 4 under `projects/` + 6 external**; that morning's sweep listed @baud, @finch, @earmark, @aipass_site and @wren among its stale mailboxes. FPLAN-0460 widened this when it deleted daemon's private registry read; the module docstring and the introspection panel still said "AIPASS_REGISTRY.json" until 2026-09-07 and now say what the code does. Pinned by `TestSweepScopeIsTheWholeFleet`.

| Rule | Behaviour |
|------|-----------|
| Threshold | 24h by default (`--hours N` to override) |
| Once per branch | One wake per branch per sweep, never more |
| Managers | Never woken — reported as skipped, their mail lands live |
| Blocklist | `@devpulse` and anything in ai_mail's `WAKE_BLOCKLIST` is skipped |
| Cap | 5 wakes per pass (`--limit N`); entries are oldest-first, and deferred branches are named in the output, not silently dropped |
| Wake model | `sonnet`, staggered 2s apart |

**Not scheduled since 2026-09-10.** The daily 09:00 job is deleted (DPLAN-0337 R2): waking up to five agents every morning was, in Patrick's words, nuisance token waste, and the nightly rounds now take each citizen's inbox to zero, one citizen a night. The command stays as a hand tool; `drone @daemon inbox-sweep --dry-run` shows who is sitting on stale mail without waking anyone.

---

## Memory Entry Health (via @memory)

`branch-health <BRANCH>` resolves the branch name case-insensitively against the registry
**before** it generates anything, so `drone`, `DRONE` and `dRoNe` all reach the same report and
an unknown name is refused once — non-zero, with the token named — instead of rendering two
"not found" blocks and exiting 0 (@devpulse fleet sweep 2026-09-07, row 21). A missing branch
name is a refusal on the same terms. It closes with an entry-health block sourced from @memory's public API,
`get_branch_health(branch_name)` — entry-count (is a `.trinity` file over its rollover trigger)
and entry-size (is any entry over its character cap).

The call lives in `apps/modules/activity_report.py`, never in `apps/handlers/monitoring/memory_health.py`
— seedgo blocks handler-to-other-branch imports, so the module layer is the only legal caller.

Caps are **not** re-encoded on this side. They live in @memory's `memory.config.json`, where defaults
are deep-merged with per-branch overrides; a copy here would be a snapshot that drifts.

| Fact | Severity | Rendered |
|------|----------|----------|
| `should_rollover: True` | INFO — rollover being due is not a fault; it auto-fires at the next PreCompact | `[PENDING]` |
| `total_violations > 0` | WARNING — a write got past the character-cap gate | `[!] WARNING` |
| memory file absent | skipped, not an error | `[SKIP]` |
| unknown branch / @memory not importable | named reason, never an empty section | `[!]` |

Markers are uppercase deliberately: `console.print()` parses Rich markup, so a lowercase tag like
`[ok]` reads as a style name and is silently swallowed — the marker vanishes on screen while a test
asserting on the returned string still passes. `TestMarkersSurviveRichMarkup` renders through Rich
to pin this.

Those render-through-Rich tests name `force_terminal` **and** `color_system` explicitly, and strip
ANSI before asserting. Both are load-bearing, and each was paid for:

- Rich decides whether to emit escape codes from `is_terminal`, and `FORCE_COLOR` in the environment
  makes even a `StringIO` count as one. `ReprHighlighter` then wraps every bracket and number in
  **bold**, so a plain-substring assert fails while the marker is plainly visible. `no_color=True`
  does not help — it strips colour, not attributes. This suite was green in the morning and red the
  same evening on byte-identical code, and the reds blocked a fleet commit train.
- `force_terminal=True` alone is still not deterministic: under `TERM=dumb` Rich resolves no colour
  system and emits plain text regardless. An early draft of the fix passed under `FORCE_COLOR` and
  failed under `TERM=dumb` — the same defect, one layer along.

The suite is verified green under `FORCE_COLOR=3`, `TERM=dumb`, `NO_COLOR=1`, and
`TERM=xterm-256color` (re-measured 2026-09-05: 36 passed under each of the four).
Both classes live in `tests/test_activity_report.py`. `TestSharedConsoleContract` separately pins the hazard behaviourally against
the real `aipass.cli` console: it asserts a lowercase tag is still swallowed there, so a cli change
surfaces here rather than blanking this report.

---

## Integration Points

### Depends On
- `rich` — console output and formatted display (via `@cli`'s shared console)
- `@prax` — the logger every module writes through
- `@ai_mail` — `wake_branch()`, the only way a job or a sweep actually wakes a citizen; also its
  `WAKE_BLOCKLIST`, read by the sweep's wake policy
- `@memory` — `get_branch_health()`, rendered by `branch-health` (module layer only, see below)
- `@skills` — fail-soft Telegram lifecycle pings; imported lazily, absence is not an error
- Python stdlib, and a systemd *user* instance for the tick timer

### Provides To
- The fleet — job discovery and firing for any citizen that writes a `.daemon/schedule.json`
- The fleet — the nightly rounds, and the unread-mail backstop (`inbox-sweep`) as a hand tool
- `@skills` bot — `queue --json`, a frozen schema
- Note: Telegram handlers archived — moving to skills system. See `apps/handlers/telegram/.archive/`

---

## Plugins

**The plugin system is retired.** All five plugins are in `apps/plugins/.archive/`, and the
`discover_plugins()` entry point in `apps/plugins/__init__.py` has no live caller — its only
remaining import is from an archived file. Scheduling is now decentralized: each citizen owns
`<branch>/.daemon/schedule.json` and the daemon discovers and fires. See **Scheduling Jobs** above.

| Plugin | Target | Status |
|--------|--------|--------|
| `community_rotation` | @rotating | Archived — superseded by `rotation` module + `rounds` job |
| `daily_audit` | @seed | Archived — targeted @seed, renamed to @seedgo years prior |
| `heartbeat` | @vera | Archived — @vera was not in `AIPASS_REGISTRY.json` then and is not now. It *is* a live citizen tonight, via the federated-external tier (`external/VERA-STUDIO`), so the target exists again — the plugin does not |
| `botfather_reminder` | @dev_central | Archived — Telegram stripped |
| `dev_central_monitor` | @dev_central | Archived — @dev_central is in no registry tonight |

---

## Known Issues

*Re-verified live 2026-09-05 (FPLAN-0490 truth pass). Items are listed only if reproduced this session.*

- **`update` digest reads empty** — reproduced 2026-09-05: `drone @daemon update` printed 0 messages
  and 0 sessions while the mailbox held 2 opened emails and `.trinity/local.json` held 16 sessions.
  `data_loader` reads different paths than `.trinity/local.json`. Long-standing.
- **`apps/modules/wakeup_ops.py` is orphaned.** Not in the router's module list, so
  `drone @daemon wakeup-ops` returns "Unknown command"; `daemon_wakeup.py` names it only inside a
  print string. Its 9 tests are the only thing importing it.
- **`apps/plugins/discover_plugins()` is orphaned** — its sole caller is an archived file.

### Resolved

- ~~Torn writes in `json_handler`~~ (2026-08-16, fleet defect 90c9e40d axis 1) — every write opened
  the target with `"w"`, truncating it before the new bytes landed; worse, `ensure_json_exists`
  answers an unreadable document by writing a template over it, so a torn read became permanent
  data loss. Measured here first, unfixed, 2 writers + 2 readers over 13,103 reads: **74.6% empty,
  17.9% unparseable, 92.5% unusable**. Now every write site routes through `_atomic_write_json`
  (staged via `tempfile.mkstemp` in the *target's own* directory, then `os.replace`; the staged
  file is unlinked on failure and the helper raises rather than swallowing). Same probe after:
  **0 of 1,410 reads unusable**. The guards travelled with the subject: this branch's json handler is
  now the fleet shim over prax's service (DPLAN-0325 pair 5), so `tests/test_json_durability.py` moved
  to `tests/.archive/deleted_2026-09-04_json_durability.py` along with the handler it pinned. The
  durability contract is prax's to hold now, and it does: `aipass/prax/tests/test_json_durability.py`
  is live there (verified 2026-09-05). **Nothing in this branch tests it any more** — correctly, since
  nothing in this branch implements it.
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

## The suite may not write into another citizen's tree (2026-09-09)

Found by @devpulse, not by me: Vera-Studio's live
`.daemon/last_wake_prompt.txt` held exactly the 16 bytes `tend your branch` —
`test_run_blocked_contract.py`'s `_job()` default prompt, mtime 2026-09-08
20:45:18, the minute the daemon suite ran during the PR #759 landing. The path is
`_fire_job` → `recovery.record_wake_prompt` → `_branch_daemon_dir`, which resolves
`@vera` through `discovery.active_citizens()` to the **real** Vera-Studio tree and
writes. The `FakeStatus` seam stops a wake reaching a live tmux; nothing stopped the
transcript reaching a live branch.

**Sealed on the seam, session-wide** (`_seal_branch_wake_prompt`), not on the row that
bit. Nine real citizen emails appear as fixture owners in this suite — `@commons`,
`@backup`, `@vera`, `@devpulse`, `@daemon`, `@seedgo`, `@baud`, `@flow`, `@api` — so a
guard scoped to one test module would have left it open for the tenth. The fixture
returns a tmp directory rather than `None`, so a test can still assert the
branch-side write *happened*; only its destination changes.

**The sentinel tells a test from a real fire, precisely.** The live scheduler runs
while the suite runs — a ~2 minute timer against a ~30 second suite — and a genuine
fire legitimately rewrites a branch's transcript (@vera's did at 07:45:19 on 09-09).
But `record_wake_prompt` always writes **both** destinations with the same text, and
the suite's `daemon_json` copy is sealed to tmp. So a branch file that changed *and*
now matches `daemon_json` is a real tick from another process; one that changed and
does not match is this suite. That discriminator is what lets the sentinel be strict
without crying wolf.

Removing the seal reproduces the exact evidence — `tend your branch` back in Vera's
file — and the sentinel names it, plus a **second** escaped citizen the original
report had not found: `@commons`.

## The suite may not move host state (2026-09-08, FPLAN-0524)

**Patrick's ruling, his words:** *"tests can't disable processes, they should restore to exact
same state before the test. The test is fine and good that it can enter something."*

**What went wrong.** `tests/test_cli_routing.py` runs the real router over every verb in
`GATED_VERBS`, and two of those verbs are `install-timer` and `uninstall-timer`. With the argument
gate in place the refusal comes first and the verb never runs — so the committed suite was safe.
Without it (a red-first run, or any mutation run that disables the gate) `_install()` and
`_uninstall()` executed against the user's real systemd. `journalctl --user` recorded seven
Started/Stopped pairs across four such runs on 2026-09-07, ending on a **Stop at 11:46:40**.
Nothing ticked for twenty-three hours: `@vera/release-watch` and `@daemon/inbox-sweep` both missed
their windows, and no MISSED line could be written, because writing one takes a tick. The suite
reported `594 passed` every time.

**The seal.** `tests/conftest.py` holds `_seal_timer_host_state` — **autouse, unconditional**,
patching the three seams by which `timer_install` can change host state:

| seam | what it covers |
|---|---|
| `_run_systemctl` | every stop / disable / enable / start / daemon-reload |
| `_UNIT_DIR` | where unit files are copied to and unlinked from |
| `_STATE_DIR` | the `~/.aipass` mkdir |

Session-wide rather than on the two rows that bit, because the defect is not *"two rows reach
systemd"* — it is *"a test can reach systemd at all"*, and the next verb added to `GATED_VERBS`
would inherit the hole silently. `TestRunSystemctl` is unaffected: it binds `_run_systemctl` by
direct import at module load, so it still exercises the real function against a patched
`subprocess.run`.

**The sentinel.** `_host_state_sentinel` (session-scoped, autouse) snapshots the live timer at
session start and asserts it unchanged at session end. It is the backstop for a route nobody has
thought of yet — a test that shells `drone @daemon uninstall-timer`, a helper calling `systemctl`
directly. It does **not** restore: a sentinel that quietly put the timer back would hide the
defect it exists to report. Proven by mutation — with the end-of-session reading doctored to
`active: inactive`, the run reports `14 passed, 1 error`. A suite can no longer pass and take the
scheduler down in the same run.

**If a test must reach the real timer**, it takes the `timer_host_state` fixture and only that: it
records `is-enabled` / `is-active` / the unit-file list, restores exactly what it recorded in a
`finally`, and then asserts the restore matched. Idempotent by construction — it restores *to a
recorded state* rather than toggling. No test needs it today; it is the contract for the next one.

### Making a mutation run safe

A mutation run is the dangerous case, because the whole point of one is to disable a guard and see
what still passes — and the guard being disabled is often the one holding the verb back.

- **A harness that shells out to `pytest` is safe with nothing to remember.** The seal is autouse
  and session-scoped, so every subprocess run inherits it. This is the shape used for FPLAN-0524's
  own four mutations.
- **A harness that imports `timer_install` and calls a verb directly is not.** It bypasses the
  conftest entirely and must take `timer_host_state`, or patch the three seams itself.
- **Say plainly what changed:** the FPLAN-0492 wave 2b harness (2026-09-07) had neither. It
  replaced the gate call and ran the pins in-process, which is exactly how the scheduler ended up
  uninstalled. The rule above is the line that changes.

Every mutation in FPLAN-0524 was chosen so the assertion is exercised without the destructive path
ever running: the gate patch removed (proves the verb executes), `shutil.copy2` disabled (proves
the sealed-dir assertion is live), the test's `live_dir` redirected (proves the live comparison
bites), and the sentinel's end reading doctored (proves the session fails). The unsealed world was
**not** re-run to prove it dangerous — 2026-09-07's journal already measured that, and repeating
the damage to re-derive a known fact is not evidence, it is a second outage.

---

## Test Suite

**2026-09-11 (FPLAN-0543, DPLAN-0338 wave 1a):** 616 → **698 passed** from both rootdirs. The
82 new cases pin command jobs: validation in `test_discovery.py`, the subprocess and fire path and
the runstate row in `test_run_module.py`, and the queue preview in `test_scheduler_bot.py`. 20 of
20 mutants went red, and each harness restored the tree byte-identical. `tests/conftest.py` gained
`_seal_command_launcher`, an autouse seal on `command_job.LAUNCHER`, so no test can start the
real drone or send a real mail. That seal was not mutation-run: removing it would do exactly that.
The counts below are the 2026-09-08 baseline.

All numbers below re-measured 2026-09-08 (FPLAN-0527), not carried.

- **534 test functions** across 19 test files; parametrization expands these to **598 cases**
  (`.venv/bin/python -m pytest src/aipass/daemon -c pyproject.toml --rootdir=. -q` →
  `598 passed in 25.51s`, 0 failed, 0 skipped; **598 passed in 25.63s** from the branch directory)
- **DPLAN-0332's own 59 pins are NOT in that count.** They are written, green and
  mutation-proved (17/17 red) but parked at `docs.local/pending/test_recovery.py.pending`:
  the test-write gate (Patrick, 2026-09-01, DPLAN-0323) refuses new test files and daemon
  cannot flip it. They were not appended into an existing test file instead — the gate names
  that as its deliberate residual, and using it would be routing around a human ruling.
  The ask is with @devpulse.
- Re-run with `activity_collector.get_branch_paths` forced to `[]` — the CI condition, where a
  checkout has no registry — also **596 passed**. Any test that exercises a name gate pins the
  roster it resolves against; the dev machine's registry is not a fixture (learned from CI red
  on b681c085, cured in 5c132a5e)
- 10/10 modules covered — every module under `apps/modules/` is imported by at least one live test file
- **57 of 61 public functions tested** (seedgo's count; was 47/51 before ruling 6 added
  the catch-up, MISSED and slot surfaces, and 54/58 before wave 2b added the argument gate)
- Seedgo audit **100%**, every scored category at 100 including Trinity, with 22 bypass rows
- The bypass list holds **22 rows**. The `apps/daemon_wakeup.py` *encapsulation* row added by
  a6956b0f is **gone** — seedgo cured the derivation (251f2eb9) and Encapsulation now scores 100
  with no row for that file, so it is not needed. The row still present for `daemon_wakeup.py` is
  the long-standing *architecture* one (entry-point script outside the 3-layer structure).
- *Unverified:* the old "99% with the bypass list emptied" figure was not re-measured tonight —
  emptying the list is a seedgo-side change, out of scope for a docs pass.

*Last Updated: 2026-09-11*

---
[← Back to AIPass](../../../README.md)
