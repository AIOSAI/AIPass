[← Back to AIPass](../../../README.md)

# DAEMON

**Purpose:** Decentralized task scheduler fired by a systemd user timer. Discovers every citizen's `.daemon/schedule.json`, wakes due owners, and reports fleet activity. The plugin system it was born with is retired — see **Plugins** below.
**Module:** `aipass.daemon`
**Created:** 2026-03-07
**Citizen Class:** aipass_framework
**Last Updated:** 2026-09-08

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
│   │   │   └── json_handler.py       # The fleet's one json shim — binds prax's service (DPLAN-0325)
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
└── tests/                      # Test suite — 531 test functions in 19 files (pytest expands to 594)
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
| `run` | Decentralized scheduler tick: discover .daemon/ jobs, fire due ones | Operational |
| `inbox_sweep` | Fleet unread-mail backstop — wakes owners of mail unread past 24h | Operational |
| `rotation` | Nightly steward rotation — roster, pointer, turn history | Operational *(job ships disabled)* |

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

**Three tiers are swept (measured 2026-09-05: 28 citizens).** Core citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`) — 18 tonight. Resident citizens under `projects/<name>/` (listed in that project's own sealed `<NAME>_REGISTRY.json`) — 4 tonight: AIPASS_SITE, BAUD, EARMARK, FINCH. And **federated externals** — citizens in separate repos entirely, reached through their own registries — 6 tonight: VERA, RESEARCH, VERIFY and WRITER under `external/VERA-STUDIO`, plus `external/WREN` and `external/DEMO`. `drone @daemon rotation` prints the tier label; nothing routes on it.

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

### Schedule types

| Type | Fields | Due when |
|------|--------|----------|
| `interval` | `interval_minutes: N` | Elapsed >= N since last_run. With no `slot`, a job that has never run fires **immediately** — see below. |
| `daily` | `time: "HH:MM"` | Within +/-15 min of target time, once per day. |
| `hourly` | `time: "M"` (minute) | Within +/-15 min of target minute, once per hour. |
| `once` | `due_date: "YYYY-MM-DD"` | Date <= today, then marks completed. |
| `rotation` | `time: "HH:MM"` | Daily window — but wakes the next citizen on the fleet roster, not the owner. See below. |

### Optional schedule fields (2026-09-07, FPLAN-0492 ruling 6)

Both live inside the job's `schedule` block, next to `type` and `time`. Both are
opt-in: absent means today's behaviour, which is what every existing job gets.

| Field | Applies to | Effect |
|-------|-----------|--------|
| `slot` | `interval` | An ISO instant naming **one occurrence** of the rhythm you want (`"2026-09-06T03:00:00"`). A job that has never run is seeded from it, so its first fire lands on the next slot instead of the next tick. |
| `catch_up` | `daily`, `rotation` | When the window closed with no run, the first tick after it fires the job once and stamps `caught_up` on the runstate row. |

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

Scheduled daily at 09:00 from daemon's own `.daemon/schedule.json` (job id `inbox-sweep`). Run `drone @daemon inbox-sweep --dry-run` any time to see who is sitting on stale mail without waking anyone.

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
- The fleet — the unread-mail backstop (`inbox-sweep`) and the steward rotation
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
| `community_rotation` | @rotating | Archived — superseded by `rotation` module + `fleet-steward` job |
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

## Test Suite

All numbers below re-measured 2026-09-08 (FPLAN-0508 wave 7), not carried.

- **531 test functions** across 19 test files; parametrization expands these to **594 cases**
  (`.venv/bin/python -m pytest src/aipass/daemon -c pyproject.toml --rootdir=. -q` →
  `594 passed in 25.15s`, 0 failed, 0 skipped)
- Re-run with `activity_collector.get_branch_paths` forced to `[]` — the CI condition, where a
  checkout has no registry — also **594 passed**. Any test that exercises a name gate pins the
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

*Last Updated: 2026-09-08*

---
[← Back to AIPass](../../../README.md)
