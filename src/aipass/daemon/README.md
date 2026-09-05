[← Back to AIPass](../../../README.md)

# DAEMON

**Purpose:** Decentralized task scheduler fired by a systemd user timer. Discovers every citizen's `.daemon/schedule.json`, wakes due owners, and reports fleet activity. The plugin system it was born with is retired — see **Plugins** below.
**Module:** `aipass.daemon`
**Created:** 2026-03-07
**Citizen Class:** aipass_framework
**Last Updated:** 2026-08-30

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
│   │   │   └── .archive/             # assistant_notifier, task_registry, plugin_processor,
│   │   │                              # telegram_notifier (superseded copy)
│   │   ├── telegram/                  # ARCHIVED — moving to skills system
│   │   │   └── .archive/             # assistant_chat (archived)
│   │   └── update/
│   │       └── data_loader.py         # Data loading for status digests
│   ├── extensions/             # Extension point for additional capabilities
│   ├── integrations/           # Private branch-local wrappers — gitignored except its README
│   ├── json_templates/         # JSON template definitions (default/: config, data, log)
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

Two trees are swept: core citizens under `src/aipass/*` (listed in `AIPASS_REGISTRY.json`) and resident citizens under `projects/<name>/` (listed in that project's own sealed `<NAME>_REGISTRY.json`).

**Who counts as a citizen (2026-08-28, DPLAN-0319 wave 3).** Candidate discovery is registry-led and shallow — exactly `projects/<project>/<NAME>_REGISTRY.json`, one level down, every dot-prefixed path component refused by an explicit filter, because `pathlib` globs match hidden directories where a shell would not. It never walks passports: on this machine a passport walk under `projects/` finds eight passports for four residents, since `baud` carries real resident-declaring copies under `.backup/versioned/` and `.backup/snapshots/`. Classification then reads the branch's own `citizenship.residency`, and inside `projects/` **both keys are required** — the registry lists the branch `active` *and* the passport declares `resident`. Every other outcome is refused and named at error level: missing passport, unreadable passport, absent field, `core` claimed from inside `projects/`, an unknown value, or a registry path that is not on disk.

The trust model is asymmetric on purpose. A passport can never *add* scope (nothing walks passports, so a declared resident no registry lists is unreachable by construction), and a passport can never *remove* a core citizen (a core branch declaring nothing is kept and the disagreement is logged — otherwise an agent could stop its own jobs firing by deleting one line of its own file).

**This changed the parked-project policy.** The old walk made every branch a project registry marked `active` into a citizen, so a parked project kept its place in the scheduler, the steward rotation and the inbox sweep on the strength of a status field nobody had revisited — `marketstand` is parked and its registry still says `active`. The passport is now the second key and such a project is refused. The live roster is unchanged (22 citizens: 18 core + 4 residents, all four declaring `resident`), because both parked projects already sit under `projects/.archive/`; the change bites the day one is parked in place rather than moved. The same wave closed a real hole: `SKIP_DIRS` never listed `.archive`, so a registry planted directly at `projects/.archive/X_REGISTRY.json` *was* discovered — the parked projects escaped only by sitting one level deeper than the walk reached. A project registry's paths resolve against its own project root, never the repo root — BAUD's registry row reads `src/baud/baud`, which is a path that also *could* resolve under this repo, and resolving repo-first picks the wrong directory. That collision was live until the phantom `<aipass>/src/baud/` was removed (2026-08-24); the guard and its test stay, because the row is still relative and a repo-first join would recreate the phantom rather than fail. Vera-Studio is a separate repo and is out of scope until multi-root discovery exists.

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

No native offset field. To stagger jobs, seed different `last_run` values in `daemon_json/daemon_runstate.json`. Within a single tick, jobs that fire together are already separated by a fixed 1s sleep (`run.py`) — that is not configurable and is not a substitute for offsetting the schedules themselves.

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

## Memory Entry Health (via @memory)

`branch-health <BRANCH>` closes with an entry-health block sourced from @memory's public API,
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
`TERM=xterm-256color`. `TestSharedConsoleContract` separately pins the hazard behaviourally against
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

- ~~Torn writes in `json_handler`~~ (2026-08-16, fleet defect 90c9e40d axis 1) — every write opened
  the target with `"w"`, truncating it before the new bytes landed; worse, `ensure_json_exists`
  answers an unreadable document by writing a template over it, so a torn read became permanent
  data loss. Measured here first, unfixed, 2 writers + 2 readers over 13,103 reads: **74.6% empty,
  17.9% unparseable, 92.5% unusable**. Now every write site routes through `_atomic_write_json`
  (staged via `tempfile.mkstemp` in the *target's own* directory, then `os.replace`; the staged
  file is unlinked on failure and the helper raises rather than swallowing). Same probe after:
  **0 of 1,410 reads unusable**. `tests/test_json_durability.py` holds the guards, including a
  source check that no truncating `open()` returns — mutation-checked against `"w"`, `"a"` and
  `"w+"` reintroductions.
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

- **473 tests** across 19 test files (DPLAN-0325 pair 5, 2026-09-04: five DPLAN-0059 json-handler stamp files moved to `tests/.archive/`; the json handler is now the fleet's one shim over prax's service)
- 10/10 modules covered, 46/50 public functions tested
- Seedgo audit: **100%** with bypasses, **99%** with the bypass list emptied (22 entries)

*Last Updated: 2026-09-04*

---
[← Back to AIPass](../../../README.md)
