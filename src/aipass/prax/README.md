[← Back to AIPass](../../../README.md)

# PRAX

**Purpose:** System-wide logging, real-time monitoring, and dashboard infrastructure for AIPass.
**Module:** `aipass.prax`
**Version:** 2.4.0 — the string `drone @prax --version` actually prints (`apps/prax.py:211`)
**Last Updated:** 2026-09-11

---

## Status

Every claim below was re-checked against the code on **2026-09-08** (FPLAN-0512;
the 09-07 gate wave and the 09-05 truth pass are its predecessors). Numbers in
this file are measurements taken on this machine, not estimates: where a number
is a single-machine reading rather than a property of the system, it says so.
Anything that could not be verified is marked **UNVERIFIED** in place rather
than left standing green.

- **Tests:** 1421 test functions across 36 files; pytest expands them to 1510
  cases, all passing from both rootdirs. Re-measured 2026-09-11: FPLAN-0548
  added 7 test functions (8 cases) to `test_operations.py`. Earlier the same
  day, FPLAN-0542 added 10 test functions (15 cases) to `test_json_handler.py`.
  The file count is unchanged.
- **Standards:** `drone @seedgo audit aipass @prax` — 100% on every CI-scored
  category. `drone @seedgo audit pytest_quality @prax` — 100% on all eleven v5
  rules.
- **Last behaviour change:** FPLAN-0556 (2026-09-12). `module_discovered` and
  `file_watcher_died` reach the trigger bus for the first time — the module-level
  import that gated them could never succeed. Before that, FPLAN-0555 (2026-09-12):
  the two explicit lifecycle doors, `initialize_logging_system()` and
  `shutdown_logging_system()`, fire `logging_system_initialized` and
  `logging_system_shutdown`, with the trigger import inside each function so the
  logging path stays clear of it. Both described under Lifecycle events. Before that, FPLAN-0553 (2026-09-12) made
  discovery a scheduled scan: `drone @prax discover run` daily, and the first log
  line of a process starts no filesystem watcher — 0 inotify watches instead of
  1,589, registry 250 modules to 1,442. Described under Discovery.
- **Last structural change:** FPLAN-0542 (2026-09-11) — the data leg of every
  module's json triplet is wired: each `log_operation` that lands bumps
  `operations_total` and stamps `last_operation`/`last_updated` in
  `<module>_data.json`, merged never replaced, and rate_tracker's save no longer
  rebuilds that document. Described under The fleet json service.

---

## Overview

Prax is the logging and monitoring backbone of the AIPass ecosystem. Any branch imports `logger` and gets automatic log routing — prax detects the caller via stack introspection and writes to the correct per-module log file. No configuration needed.

On top of logging, prax provides Mission Control (a real-time terminal console for file changes, log events, and agent activity), a log audit system, and a dashboard infrastructure.

## Quick Start

```python
from aipass.prax import logger

logger.info("Processing started")
logger.warning("Disk usage high")
logger.error("Connection failed")
```

Logs auto-route via two-tier placement:
- `system_logs/<branch>_<module>.log` — central aggregation at the repo root
- `<branch>/logs/<module>.log` — branch-local debugging

## Commands

```bash
drone @prax                              # Show discovered modules
drone @prax --help                       # Full command list
drone @prax --version                    # Version string
```

### Monitor — Mission Control

```bash
drone @prax monitor                      # Show monitor architecture
drone @prax monitor run                  # Launch Mission Control (all branches)
drone @prax monitor run seedgo,cli       # Monitor specific branches
drone @prax monitor run commons          # Live social feed of The Commons
drone @prax monitor run commons --logs   # Tail commons' technical logs instead
drone @prax monitor run --relay          # Mirror to Telegram (prax_monitor bot)
drone @prax monitor --help               # Monitor usage
```

**On request only — there is no monitor service.** Patrick's ruling, 2026-08-18:
*"monitor should only be running on request when i call it. not in background.
the logs are already running."* Mission Control is an operator console, and
logging does not depend on it: `system_logs/` and the branch-local logs are
written by the logging handlers whether or not a monitor is running. Start it
when you want to watch, quit it when you are done.

The `prax-monitor.service` systemd unit that used to run it always-on is
**retired and deleted from the repo**, which under Patrick's archive doctrine
(2026-08-18) is what retired means: *`.archive/` is always ignored, no
exceptions — and files there are not safe, they get cleaned without warning.*
So the retirement record lives here, in tracked prose, rather than in an archive
directory that neither ships nor survives. A convenience copy may sit in
`.archive/` on any given machine; nothing depends on it.

**Why it was retired.** Two rulings the same day landed on the one file. First,
the on-request ruling above. Second, Telegram was retired — and this unit's
entire stated purpose was `Description=AIPass Prax Monitor — Telegram relay`,
setting `AIPASS_PRAX_MONITOR_RELAY=1`; BAUD is the surface going forward. It was
also expensive: 3h23m of CPU consumed, 2.29GB RSS at the end, and it was one of
the six processes that lost their watchdog dispatcher at 02:19 that day and grew
unbounded (DPLAN-0305, fixed above).

**What the unit was**, for anyone reconstructing it: a `Type=simple` user unit
running `python3 -m aipass.prax.apps.modules.monitor run` with
`Restart=always`, `WorkingDirectory` at the repo root, `AIPASS_PRAX_MONITOR_RELAY=1`,
and both stdout and stderr appended to `~/.aipass/prax-monitor.service.log` —
deliberately *outside* `system_logs/`, because the monitor tails `system_logs/*.log`
and @trigger watches it too, so writing its own output there is a feedback loop.

**If an always-on monitor is ever wanted again**, two questions have to be
answered before reinstalling anything:

- **Log rotation.** `StandardOutput=append:` has no rotation. That log reached
  **117MB unrotated** before it was archived. A long-lived unit needs a rotation
  story first.
- **The ecosystem observer.** Any long-lived process that logs still lazy-starts
  a recursive observer over the ecosystem root (`start_file_watcher()` schedules
  one `WatchdogObserver` with `recursive=True`). Re-read 2026-09-05: the watch is
  unchanged and always-on processes still multiply it. What changed on 2026-09-04
  is *who waits for it* — the logger's first call now goes through
  `start_file_watcher_in_background()`, so the walk happens on a thread nobody
  joins (see "The watcher start does not block the first log line" below).
  DPLAN-0307, which tracked the design, was closed 2026-08-22 in a batch with
  three other prax plans — the plan is closed and the design is not.

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Branch scoping** — `monitor run seedgo,cli` shows only those branches (see below)
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[BRANCH/model]` (e.g., `[DEVPULSE/opus]`, `[DEVPULSE/gpt-5.4]`)
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL) session monitoring
- **Rate tracking** — 4th background thread scans `system_logs/` for runaway log growth every 10s
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`/`q`.

**Who counts as a branch.** Names and paths come from declarations, never from
path shape. Three sources, in precedence order: `AIPASS_REGISTRY.json` for
`src/aipass/*` branches; then a sweep of `projects/*/*_REGISTRY.json` for in-repo
project citizens; then, for any file still unresolved, the nearest
`.trinity/passport.json` walking up to the repo root. A relative registry path
is resolved against *its own registry's* directory, not the process CWD. First registration wins, so a project cannot
claim a name AIPass already uses.

The project sweep resolves whoever the registries *declare*, not whoever has a
directory. Measured 2026-09-05: **22 known branches** — the 18 in
`AIPASS_REGISTRY.json` (AIPASS, AI_MAIL, API, BACKUP, CANARY, CLI, COMMONS,
DAEMON, DEVPULSE, DRONE, FLOW, HOOKS, MEMORY, PRAX, SEEDGO, SKILLS, SPAWN,
TRIGGER) plus the four project citizens that ship a registry today: BAUD,
EARMARK, AIPASS_SITE and FINCH.

Two names this README used to list are no longer resolvable, and the tree
explains both without naming anyone: `projects/` now holds exactly four
directories (`aipass-site`, `baud`, `earmark`, `finch`), so **MARKETSTAND** has
no registry to declare it and `projects/speakeasy(on_hold)/` — previously cited
here as an empty-`branches[]` citizen — is not in the tree at all. The count
moved because the declarations moved; the rule did not change. Earlier revisions
also listed a `TESTING` citizen — no such project registry exists.

That third shape was missing until 2026-08-14: `monitor run baud` answered "BAUD
is not a known branch", and — worse — BAUD's files were labelled **AIPASS**,
because the old fallback matched path segments against known names and the repo
directory is called `AIPass`. Misattribution is worse than UNKNOWN: events land
on the wrong screen and are filtered off the right one. Same family as the
watchdog fix (c247fce8) and the statusline passport walk-up.

**Branch scoping.** A comma-separated list (`monitor run seedgo,cli`) restricts the
display to those branches; bare `run` and `run all` show everything, unchanged. A
scope covers each named branch's log lines, file changes and CLI sessions —
including session labels that carry a project prefix or model tag
(`AIPASS/SEEDGO/opus`) — plus commands the branch issued or was targeted by
(`devpulse → prax` appears in both scopes). Filtering happens at the queue, so
out-of-scope traffic never occupies a display slot and cannot push wanted events
out under load. The banner and `status` name the active scope, `status` also
reports how many events the scope is holding back, and a name that is in no
branch registry is called out at launch rather than showing a silently empty
screen. The monitor's own health warnings (file watcher unavailable, and similar)
bypass the scope — a filter must never hide the reason the screen is empty.
The scope is set at launch; there is no runtime `filter` command outside commons
feed mode.

**Display resilience.** Everything on screen is other branches' output, so every
dynamic value is escaped before it reaches Rich — a tailed line containing
`[/usr/bin]` is shown, not parsed. If a line still cannot be drawn, the failure
costs that one line: the display thread reports it (rate-limited, in plain
language) and keeps consuming. It is the queue's only consumer, and a consumer
that dies leaves the queue permanently full with nobody to empty it. The
Telegram relay is fed before the console for the same reason — one sink failing
must not take the other with it.

**Commons feed mode** (`monitor run commons`) is a different watcher, not a branch
filter — it renders live social activity in The Commons (posts, comments, votes,
reactions) read-only, instead of file/log events. `--logs` opts back out to tailing
the commons branch's technical logs. Feed mode adds two interactive commands of its
own: `filter <room>` (comma-separated) and `filter clear`. `--relay` works in both
modes, and is also enabled by `AIPASS_PRAX_MONITOR_RELAY=1`.

### Log Health

```bash
drone @prax log-health                   # Show module info
drone @prax log-health scan              # Scan all log files, show current growth rates
drone @prax log-health snapshot          # Show last known rates (no new scan)
drone @prax log-health --help            # Log health usage
```

Quick overview of log file growth rates across `system_logs/`. Powered by the rate tracker handler — `scan` runs a fresh measurement, `snapshot` reads the last persisted state without scanning.

`snapshot` reports what the last scan measured, including which process
measured it: the rate history is persisted, so a CLI invocation can read rates
collected by the long-running Mission Control service. Restored samples are
trimmed to the deque's own horizon (`_RATE_HISTORY_SIZE × SCAN_INTERVAL` =
5 min), so a tracker that was down for hours cannot feed stale history into the
runaway-threshold window. When nothing recent exists, `snapshot` says
**"No recent measurements"** rather than rendering every file as idle — an
all-zero screen would otherwise be indistinguishable from a genuinely quiet
fleet.

### Status

```bash
drone @prax status                       # System health (modules, loggers, last discovery scan)
drone @prax status sync                  # ⚠ STILL WIRED — recreates repo-root STATUS.md (see below)
drone @prax status --help                # Status usage
```

**`status sync` is not dormant, and that is a defect.** TDPLAN-0007
decommissioned the STATUS flow: `STATUS.local.md` and the aggregated
`STATUS.md` were deleted across every branch, and the engine was made inert by
unwiring its *trigger registration*. The CLI subcommand was never unwired —
`status sync` still routes to `sync_status()`, which walks every branch and
writes `STATUS.md` back to the repo root, resurrecting a file the fleet
decided to delete. This README described the command as dormant until the
2026-08-13 audit ran it and recreated the file. The engine is intentionally
revivable, so the fix (refuse and point at `DASHBOARD.local.json`, or finish
the decommission) is a ruling for @devpulse, not a unilateral prax change —
tracked in APLAN-0009. Until then, treat this command as one that writes.

### Log Audit

```bash
drone @prax log-audit                    # Show audit module info
drone @prax log-audit audit              # Scan system_logs/ for health + oversized files
drone @prax log-audit enforce            # Truncate oversized logs to 1000 lines
drone @prax log-audit sweep              # Delete log files older than 30 days
drone @prax log-audit --help             # Audit usage
```

`audit` reports problems but always exits 0 — it flags unbounded and critical
files in its output, so a health gate must read the text, not `$?`.

### Scheduled job — the weekly tmp sweep (DPLAN-0338, 2026-09-11)

prax owns one daemon job, in `.daemon/schedule.json`: **`tmp-sweep-weekly`**.
It is a *command* job, so the daemon tick runs it as a subprocess from this
directory. No agent is woken and no tokens are spent.

```
drone rm --stale 10d ..        # '..' from src/aipass/prax is src/aipass
```

- **What it sweeps.** Regular `*.tmp` files sitting directly inside any `*_json`
  folder under `src/aipass`, with an mtime more than 10 days old. Nothing else.
  The one call covers every branch's json folder: drone crosses its
  sibling-branch fence in stale mode only, by design, because a stale staging
  temp is nobody's work. A staged write is temp + fsync + rename, and a process
  killed between the two leaves the temp behind. The real document is intact
  whatever happens to it.
- **When.** Weekly, Sunday 04:00 local. That is the quiet hour, clear of
  @seedgo's Sunday 03:00 shadow cycle and @daemon's 09:00. The slot is
  `2026-09-13T04:00:00`. The tick seeded the runstate row from it at 13:31 on
  09-11 (`last_run` 09-06 04:00, first fire 09-13 04:00), so the job never fires
  at whatever minute a tick first discovers it. A Sunday missed while the
  machine was off fires on the first tick after it is back.
- **Where it shows.** The `FIRE` and `DONE` lines (exit code, duration, output
  tail) in daemon's `logs/run.log` and in `~/.aipass/daemon-tick.log`. The
  runstate row `@prax/tmp-sweep-weekly` in `daemon/daemon_json/daemon_runstate.json`.
  One row per deleted file in `.ai_central/deletions.jsonl` (`mode: stale`,
  `age: 10d`). A mail to @devpulse when the sweep starts and another when it
  finishes. `drone @daemon queue` lists it; `--json` carries
  `command: drone rm --stale 10d ..` as the preview.
- **Changing it.** To change the age, edit the command string (`10d` → `5d`;
  `m`/`h`/`d` are accepted, zero is refused). To turn it off, set
  `enabled: false`. `timeout_seconds` is 120 because a command job holds the
  tick lock for its whole run.

**The first sweep, run by hand 2026-09-11 13:32.** The dry run printed
`folders scanned 1539, files matched 706 (35602375 bytes)`. The real run deleted
all 706, freed 35.6 MB, refused 0 and added 706 ledger rows. `*.tmp` under
`src/aipass/*/*_json` went from 1170 to 466. Every file deleted was an old-era
`tmpXXXX.tmp` from the retired handler. The 466 left are younger than 10 days
and age in week by week. The run took **39 s wall**; a dry run with nothing to
delete takes 1.2 s. So the cost is about 54 ms per deleted file, because each one
writes a ledger row and a log line. At that rate 120 s covers about 2,100 files a
week. A timeout marks the row FAILED but keeps whatever it already deleted.

**Where the orphans come from (measured 2026-09-11, cured 2026-09-12).** Each
new-era `.<pid>_<n>.tmp` still holds the document it was staging, so its content
names the writer. Of the 442 in `prax_json/` (09-04 to 09-11), **384 (87%)**
were staging one record: `discovery_watcher_event` with `action: started`. That
is the last line of `start_file_watcher()` (`handlers/discovery/watcher.py:234`).
Since 2026-09-04 it runs on `prax-watcher-start`, the daemon thread nobody joins
(see "The watcher start does not block the first log line"). A short-lived
process such as a hook logs once and exits while that thread is still walking or
writing, and interpreter exit kills a daemon thread wherever it stands, between
temp and rename included. That dates the rise DPLAN-0338 calls "cause unknown"
to this move: about 5 a day in the old era, 18 to 73 a day since 09-04. The
files come from 439 distinct pids, so it is one death per process, not one bad
process. The rest: 28 empty or partial,
`jsonl_append` 16, `introspection_resolved` 9, `direct_log_created` 3,
`config_loaded` 2. On 09-11 the count jumped
to 174 in 13 hours. 57 of those 174 are the FPLAN-0542 data-leg bump staging the
same `started` record. That bump added a second staged write to every
`log_operation`, so each dying process now has two windows instead of one. The
strip DPLAN-0338 leaves open (the creation-time records) is aimed at
`introspection_resolved`, and by this count that is one of the smallest
writers. **The cure (DPLAN-0339 step 1, 2026-09-12).** The `started` record is gone from
`start_file_watcher()`. It had no reader — not in production, not in the tests,
nowhere in the fleet — so nothing was traded away for it. The numbers that
convicted it, re-measured on HEAD `d6deeb42`: the walk thread finishes at
**0.431-0.440 s** wall (CPU 0.133 s, so 70% of it is GIL waiting) and a
short-lived process exits at **0.394-0.433 s**, which means the record was
written inside its own destruction window on every process, every time. Removing
the one `log_operation` call removes both staged writes, because the data-leg
bump rides on it.

Proof, 240 throwaway processes each side under `AIPASS_TEST_LOG_DIR` with the
live tree untouched: **6 orphans before, 0 after** — and `watcher_log.json` came
through all 240 with its mtime unchanged, so the record is not merely unobserved,
it is never written. The after-run carried *higher* load than the before-run
(7.71 vs 3.71), so the race had more chance to fire, not less. First-log-line
cost is unchanged, as expected: this step is litter, not speed. The orphan rate
is load-dependent — the same 40-process run that gave 3 of 40 on 09-11 gave 0 of
40 on 09-12 before the change, because a slower first line pushes exit past the
0.43 s write. That is why the baseline here is 240 processes and not 40.

What is deliberately NOT in this step: the `died` record, `trigger.fire(
"startup")` on the first log line (94% of that line's cost), and the background
watcher start itself. Those are separate, separately ruled. The startup fire went
in step 3, immediately below; the other two are still open.

### Discovery is a scheduled scan

**DPLAN-0339 step 4, 2026-09-12.** `drone @prax discover run` walks the ecosystem
once and writes `prax_registry.json` as a **snapshot**: modules added, modules
whose file is gone removed, `discovered_time` carried over for anything already
on record. It runs daily as `module-scan-daily` in `.daemon/schedule.json`
(04:30, `timeout_seconds` 60, `notify: false`). The verb existed before and was
archived 2026-03-18 when discovery became a per-process watch; this brings it
back and retires the watch. Bare `drone @prax discover` shows introspection and
scans nothing — the fleet's module standard, and the right default for a verb
that rewrites a registry.

**What it replaced.** `SystemLogger._ensure_watcher` started
`start_file_watcher_in_background()` on the **first log line of every process**:
a daemon thread that walked 1,589 directories and installed one inotify watch per
directory, then died with the process. Short-lived processes never finished it.
Long-lived processes that merely logged carried a whole-tree watch by accident —
6,356 of this machine's 6,634 inotify watches were four such processes.

**It was also not working.** Measured 2026-09-11: the registry held **250 of the
1,442 modules a scan finds — 17%** — because a module was registered only if it
happened to be created while some process was both alive and still walking. It
never pruned either: the first real scan removed **55** entries, including probe
files deleted in August and flagged as unpruned back on 09-04.

| | before | after |
|---|---|---|
| modules in the registry | 250 | **1,442** |
| inotify watches held by a process that logs | ~1,589 | **0** |
| threads started by the first log line | 1 (`prax-watcher-start`) | **0** |
| first `.info()` | 0.420 s | **0.011 s** |
| steady state | 0.402 ms/line | **0.232 ms/line** |

The first scan reported **+1,245 / -55 / 197 unchanged**; a second run over the
unchanged tree reports **0 and 0**, which is what makes it safe to schedule. A
full scan is 5.5 s wall end to end (the walk alone is 0.18 s).

**Steady state improved, which was not the plan.** Step 3 measured 0.402 ms/line
with the background walk still running; the walk was contending with the caller
for the GIL for its whole life. With it gone the line costs 0.232 ms. The
contention DPLAN-0339 measured in both directions is simply not there any more.

**Logging never depended on discovery.** A module gets its log file when it logs,
not when it is registered; nothing outside prax reads the registry, and nothing
anywhere reads `discovered_time`. What the registry feeds is prax's own dedupe
and the module count in `drone @prax status`.

**What still starts a watcher.** `initialize_logging_system()` →
`run_initialize` → `start_file_watcher()`, synchronously, for the life of that
process. That door is deliberate and unchanged, and it is why the liveness check,
the `died` record and the `file_watcher_died` fire all stay: a process that opens
it can still lose its watchdog dispatcher (DPLAN-0305) and must still find out.
(Both the `died` record and the fire work as of FPLAN-0556 — until then the fire
was gated behind an import that always failed. See "The watcher's own events".)

### The first log line no longer fires a startup event

**DPLAN-0339 step 3, 2026-09-12.** `SystemLogger._ensure_watcher` used to end
with `trigger.fire("startup")`, so every process in the fleet fired a startup
event on its first log line. That fire *was* the first log line: **0.339 s of its
0.361 s, 94%**, nearly all of it importing the `aipass.trigger` graph so that one
event could reach one handler.

What it bought was an error catch-up scan in trigger's `handle_startup`. At 5.1
fires a minute, **100 of 100** of those runs found 0 errors — and because every
process shared one throttle, a hook or a drone command routinely consumed the
recovery window seconds before the scan that actually needed it. Recovery now has
a real owner: trigger's `log_watcher_service` calls `run_error_catchup()` itself
at service start, and `last_scan_timestamp` advances only after a scan that
covered every file (FPLAN-0551, live since 00:28). Medic's digest lane never rode
the fire — it calls `run_startup_catchup()` directly, deliberately.

Measured here, 12 throwaway processes each side, `AIPASS_TEST_LOG_DIR` redirect,
live tree untouched:

| | median | range |
|---|---|---|
| first `.info()` before | 0.420 s | 0.336-0.826 |
| first `.info()` after | **0.016 s** | 0.012-0.021 |
| steady state before | 0.390 ms/line | 0.240-0.488 |
| steady state after | 0.402 ms/line | 0.384-0.574 |

**The first log line got ~26x cheaper; the steady state did not move.** The event
still exists and still has exactly one listener, and `drone @trigger fire startup`
still works — nothing fires it per-process any more, by design. Proof that the
per-process fire is gone: trigger's `startup_log.json` ring gained **40 records
from a batch of 40 short processes before the change and 0 after** (counted by
timestamp, because the ring is capped at 100 rows and a raw count is saturated).

### The lifecycle doors fire, the log line does not

**FPLAN-0555, 2026-09-12.** Removing the hot-path `startup` fire in step 3 left
`logger.py` with no `trigger.fire` anywhere, and seedgo's Trigger standard reads
that file-level: its Pattern 9 checks `initialize_*_system` / `shutdown_*_system`
only when the file contains no fire at all, so the two doors had been passing on
a technicality the whole time. Once the technicality went, the audit dropped to
99% and the CI gate went red (Linux run 34682737344).

The cure is the one the standard actually asks for. `initialize_logging_system()`
fires `logging_system_initialized` (carrying `modules_count`) after
`run_initialize` returns; `shutdown_logging_system()` fires
`logging_system_shutdown` after `run_shutdown`, last, so the event says the
system *is* down rather than that it is going down. seedgo's event table names no
system-lifecycle event, so those two names are prax's, following the convention
it does state: lowercase, underscore-separated, past tense.

**Both imports are inside their function, and that is the design, not a style
choice.** `from aipass.prax import logger` and every log line the fleet writes
must stay clear of the `aipass.trigger` import graph — that graph was 0.339 s of
a 0.361 s first log line before step 3. A door called deliberately, once, can
afford what a hot path cannot. Each fire is guarded `(ImportError, OSError)`
exactly as the removed one was: these doors must still work on a host where
trigger cannot import or inotify is exhausted, so a failed fire is a warning and
never a failed initialize. Nothing listens to either event today, by design — the
point of the standard is that a handler can plug in later without prax changing.

Measured on a fresh interpreter that imports the logger and logs one line:
**no `aipass.trigger` module at all**, not even a package shell, and the first
`.info()` costs about 0.010 s. Pinned in
`test_logger_module.py::TestLoggingPathIsTriggerFree`.

### The watcher's own events were never reaching the bus

**FPLAN-0556, 2026-09-12.** Proving the section above turned up three
`aipass.trigger` *package shells* in a process that only logged, and pulling that
thread found a fire that had never fired.

`handlers/discovery/watcher.py` held a module-level
`from aipass.trigger.apps.modules.core import trigger`. It could not succeed, and
never had: this module is still executing its own import when it reaches that
line → trigger's `core.py:20` does `from aipass.prax.apps.modules.logger import
system_logger` → prax's logger does `from ...discovery.watcher import
is_file_watcher_active` → the watcher is partially initialised and those names do
not exist yet → `ImportError`. Python discarded `core` and kept the three parent
packages it had already created, which is where the shells came from.

The cost was not the shells. The fallback set a module-level
`_HAS_TRIGGER = False` that nothing could ever set back to True, and both fires
in the file sat behind it: **`module_discovered` and `file_watcher_died` had
never once reached the bus.** `file_watcher_died` is the one that matters — it is
the escalation path for DPLAN-0305, and the step-4 decision in DPLAN-0339 to keep
it was made about a fire that was already dead. Nobody knew, because a gate that
is always closed and a bus with no listener look identical from outside.

The cure is the same shape as the lifecycle doors above: `_get_trigger()` imports
at the fire site, guarded `(ImportError, OSError)` to a warning, and returns
`None` when the host cannot give us a bus. `_HAS_TRIGGER` is gone — a flag that
could only ever hold one value was not telling anyone anything. By the time a
fire site runs, this module is fully imported and the cycle is gone, so the same
import succeeds. Proven live: a throwaway that drives `on_created` and
`_report_watcher_death` under `AIPASS_TEST_LOG_DIR` sees
`[('module_discovered', 'fplan0556_probe_module'), ('file_watcher_died', 7)]` on
a listener double attached to the real bus.

What the 2026-08-31 Windows CI incident taught is kept in full — the guard is
still `(ImportError, OSError)`, because trigger's own import guard can raise
`FileNotFoundError` on a host with no readable working directory, and an optional
dependency's fallback must be at least as wide as the failures its import can
produce. Only the *placement* those pins encoded was dropped, and the placement
was the defect.

### Asking for help never does the thing

Every module screens the **whole argument sequence** for help, not just the
first token, inside `handle_command` — so the guarantee holds however the module
is reached: through drone, through `prax.py`, or by running the file directly.

- `--help` and `-h` count **anywhere** on the line, matched exactly (`--help-me`
  and `-hx` are not help flags).
- The bare word `help` counts **only in the first slot**, because branch names,
  log filenames and grep patterns are free text — `monitor run help` scopes to a
  branch called `help`.
- The gate sits *after* each module's ownership check, since `prax.py` routes by
  trying modules in turn; a scan at the top of the function would let one module
  answer another's `--help`.

This was not theoretical. Modules gated help at `args[0]` only, and the
standalone paths screened `--help` but not `-h` — which survives a `--`-prefix
filter because it carries a single dash. `log_audit.py enforce -h` truncated
every oversized log, and `monitor.py run -h` started a live Mission Control.
Found by @seedgo's `help_flag_safety` standard, 2026-08-13; `dashboard.py`
already scanned both spellings and was the reference implementation. The
predicate lives in `handlers/cli/help_flags.py` — pure argument inspection, no
I/O, matching the convention @memory, @trigger, @drone and @ai_mail settled the
same day. Its sibling `handlers/cli/arg_gate.py` answers the opposite question —
"is this token one we do not define?" — and is described under Command Routing.

### Dashboard

```bash
drone @prax dashboard                    # Show dashboard sections
drone @prax dashboard refresh --all      # Refresh all branch dashboards from centrals
drone @prax dashboard refresh @flow      # Refresh a specific branch (core, then the caller's project registry)
drone @prax dashboard refresh            # Refresh the branch the CALLER stands in
drone @prax dashboard status             # Show dashboard status
drone @prax dashboard template           # Show the template schema
drone @prax dashboard template-status    # Per-branch template sync state
drone @prax dashboard push-template      # Push template to all branches
drone @prax dashboard diff-template      # Diff template vs branch dashboards
drone @prax dashboard --help             # Dashboard usage
```

`refresh --all` writes every branch's `DASHBOARD.local.json`. It accepts and
silently ignores unknown flags, so `refresh --all --dry-run` is a real
fleet-wide write, not a preview — there is no dry-run mode.

**`refresh @branch` reaches external projects (2026-09-11, FPLAN-0548).** The
name is looked up in `AIPASS_REGISTRY.json` first, exactly as before. On a
miss, prax looks in the caller's own project registry: the nearest
`*_REGISTRY.json` at or above the directory the caller stands in. A relative
path there resolves against that registry's own directory. A name declared in
both registries goes to core, and a warning names both rows. Before this, a
Vera Studio branch running `drone @prax dashboard refresh @verify` got
`Branch 'VERIFY' not found in registry` (exit 2), which is step 2 of the
post-compact re-ground. So every external branch's dashboard stayed as it was:
verify's still said `last_updated` 2026-07-09 and `new_mail` 0, while its inbox
held 5 unread. `--all` is unchanged and still covers core only.

**The caller's directory is `AIPASS_CALLER_CWD`, not the process cwd.** drone
runs every branch with its cwd set to the *target* branch, so inside prax
`Path.cwd()` is always prax. Measured the same day: a bare
`drone @prax dashboard refresh` from `src/aipass/flow` refreshed **PRAX**. Both
the project walk and the bare `refresh` now start from `_caller_dir()` in
`apps/modules/dashboard.py`. That reads `AIPASS_CALLER_CWD` first (an empty
value counts as unset) and falls back to the process cwd only for a direct run.
With neither, the bare form refuses and tells you to name the branch. It is
prax's one sanctioned working-directory read, the single entry in
`tests/test_repo_root.py`'s allowlist, so it stays in the module. The handler
`resolve_branch_path(ref, caller=None)` takes the directory as an argument and
never reads a cwd. Called without one, it is core-only, as before.

**Mail counts come from the branch's own inbox, never from the ai_mail central.**
`calculate_quick_status` counts `<branch>/.ai_mail.local/inbox.json`. The
refresh also builds an `ai_mail` section from `AI_MAIL.central.json`, but
nothing reads it and it is popped before save. So a branch with no central row,
which is every external branch today, still gets its true count. Pinned in
`tests/test_operations.py`: a central listing only FLOW, a branch inbox with 3
new, and `new_mail` 3. The comment in `refresh.py` used to say the section fed
the counts, and it misled a measurement that same day. It has been corrected.

### The discovery watcher cannot kill its own thread

`PythonFileWatcher.on_created` guards its **whole body** with `except Exception`,
and that breadth is deliberate. watchdog's dispatcher loop
(`observers/api.py::EventDispatcher.run`) catches only `queue.Empty`, so any
exception escaping a handler kills the dispatcher thread permanently and
silently, while the emitter keeps filling an **unbounded** queue that nobody
drains again. The process then retains every filesystem event in the ecosystem
for as long as it lives.

That happened. On 2026-08-18 at 02:19 an archived probe file
(`api/apps/handlers/host/.archive/probe.py`) was created and deleted inside the
same second; `stat()` on the vanished path raised `FileNotFoundError` from
`on_created`; **six** long-running processes lost their dispatcher at the same
instant and grew to ~2.3GB RSS each — 13.7 of 15GB with swap full — over the
next 15 hours, with nothing logged. Diagnosed by @devpulse in DPLAN-0305.

The evidence is reproduced here rather than referenced, because the log it came
from lives in an archive directory and plans are not tracked either — under the
archive doctrine, a record that must survive belongs in tracked prose:

```
Exception in thread Thread-1:
Traceback (most recent call last):
  File "/usr/lib/python3.12/threading.py", line 1073, in _bootstrap_inner
    self.run()
  File ".../watchdog/observers/api.py", line 213, in run
    self.dispatch_events(self.event_queue)
  File ".../watchdog/observers/api.py", line 391, in dispatch_events
    handler.dispatch(event)
  File ".../watchdog/events.py", line 217, in dispatch
    getattr(self, f"on_{event.event_type}")(event)
  File ".../prax/apps/handlers/discovery/watcher.py", line 88, in on_created
    "size": py_file.stat().st_size,
            ^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/pathlib.py", line 842, in stat
    return os.stat(self, follow_symlinks=follow_symlinks)
FileNotFoundError: [Errno 2] No such file or directory:
  '.../src/aipass/api/apps/handlers/host/.archive/probe.py'
```

Note the last frame: `run` catches `queue.Empty` and nothing else, so the thread
simply ends. Nothing above it ever hears about it.

Two things came out of it, both pinned by tests that run against a **real**
watchdog observer (a mocked dispatcher cannot die, so a mocked test would pass
against the broken code):

- **The guard.** Discovery is best-effort by nature — the file it describes is a
  moving target — so a failure is reported and swallowed. Losing one module
  registration is a rounding error next to losing the watcher.
- **A liveness check that can actually fire.** `is_file_watcher_active()` already
  existed *and was already called* — but only from `SystemLogger._ensure_watcher`,
  whose body runs once per process behind a `_watcher_started` flag that is never
  reset. It answered at the one moment the watcher could not yet have died, and
  never again. `check_file_watcher_liveness()` runs throttled (~1 real check per
  60s) on the logging path, reports a death loudly **once** with the stranded
  queue depth, and fires `file_watcher_died` on the trigger bus. It never raises:
  it is called by the logger, and a health check that breaks logging is worse
  than the condition it detects.

The check is throttled *and* lock-free in the common case, both pinned — the
throttle moving inside the lock would change cost rather than answers, and would
put every log call in the ecosystem on one mutex with nothing to catch it.

## Logging API

### Pattern A — Canonical (use this)

```python
from aipass.prax import logger

logger.info("Processing started")
```

This works from any branch. Prax detects the caller via stack introspection and routes to the correct log file. If prax fails to import, a NullLogger fallback prevents crashes.

Four levels are available — `debug()`, `info()`, `warning()`, `error()`.

**Ruling 2026-08-30 — the object form stays recommended.** @seedgo widened the
`imports` standard to accept three spellings and asked prax, as the owner of the
logging contract, which one to recommend. The answer is this one, and the reason
is that the import form was never the thing doing damage.

The question arrived attached to a real measurement: one `@daemon` test performed
23 atomic writes into prax's live `prax_json/`, and the diagnosis was that
`from aipass.prax import logger` binds the logger *object*, so a conftest that
swaps `sys.modules["aipass.prax"]` cannot reach it. Measured here with an audit
hook before ruling, and the diagnosis does not survive:

| | import | 1st call | 2nd call |
|---|---|---|---|
| `from aipass.prax import logger` | 0 | **26** | 0 |
| `from aipass import prax` → `prax.logger` | 0 | **26** | 0 |
| `from ...modules.logger import system_logger as logger` | 0 | **26** | 0 |

**Importing prax writes nothing. The first `logger.info()` writes 26 times, and
the second writes nothing.** All three spellings are identical because the writes
come from the *call*, not the binding — the first call is what starts the file
watcher and auto-creates the per-module JSON. (It also fired
`trigger.fire("startup")` when this was measured; that fire was removed in
DPLAN-0339 step 3, see below.)
Changing the recommended import would have moved a number that does not depend
on it.

The rebindability claim also does not hold against the mechanism it names. With
the swap landing *after* the caller's import — the shape an autouse fixture
produces — every form returns the real logger, the module form included:

| swap timing | form 1 | form 2 (object) | form 3 (module) |
|---|---|---|---|
| `sys.modules` swap **after** import | REAL | REAL | **REAL** |
| `monkeypatch.setattr(prax, "logger", …)` | REAL | REAL | MOCK |
| `sys.modules` swap **before** import | **ModuleNotFoundError** | MOCK | MOCK |

Ordering decides this, not binding style. Two things follow that are worth more
than the ruling itself. First, a `sys.modules` swap that lands after import fixes
nothing in *any* spelling, so branches carrying that fixture are not protected
today and would not have been protected by migrating. Second, the form the
standard labels canonical — importing through `apps.modules.logger` — is the only
one that **crashes** against a mocked `aipass.prax`, because the mock package has
no `apps` submodule. A branch that follows the top recommendation and mocks prax
gets `ModuleNotFoundError`, not a mock.

Import cost was not load-bearing either: 131.0ms vs 130.7ms median over 5 samples
for the object and module forms — indistinguishable, because `prax/__init__.py`
eagerly imported `apps.modules.logger` at the time, so every spelling paid the
same package init. **That reason expired on 2026-09-03**: the init is lazy now
(PEP 562, see the json service section), so importing `aipass.prax` no longer
pays for the logger graph and only a spelling that actually *touches* `logger`
does. The ruling itself is unaffected — it never rested on the cost — and
consistency remains the tiebreak: one spelling across the fleet is worth more
than a rebindability property that does not work.

**The defect that section named is fixed for module documents, and survives for
path-based writes.** The json service resolves its directory per call from
`AIPASS_TEST_LOG_DIR`, so everything written *by module name* is redirected.
Measured 2026-09-05, one `logger.info()` in a fresh interpreter with the
variable set:

```
files written into the real src/aipass/prax/prax_json/ : 0
files written under AIPASS_TEST_LOG_DIR                : 18
```

What is **not** redirected is the handful of module-level path constants built
from `__file__`. Measured the same night, with `AIPASS_TEST_LOG_DIR` set:

```
config.load.PRAX_JSON_DIR         -> src/aipass/prax/prax_json     <- real tree
registry.save.REGISTRY_FILE       -> …/prax_json/prax_registry.json <- real tree
logging.operations.LOG_FILE       -> …/prax_json/prax_logger_log.json <- real tree
config.load.get_system_logs_dir() -> /tmp/<redirect>/system         <- redirected
```

Four modules still build paths that way — `handlers/config/load.py`,
`handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and
`handlers/registry/save.py` — and any write that goes through a *path* rather
than a module name (the module registry is the live one) lands in the real tree
under any suite. It is the same shape as before, one layer down. Reported
2026-09-05, unfixed here because this pass is documentation only.

### Mocking the logger — the contract

@seedgo corrected their own dispatch within ten minutes of sending it, and the
corrected question is the better one: prax never published a mocking technique,
so five branches invented five, and all five miss. Measured by object identity
against a real consumer:

| technique | reaches |
|---|---|
| `patch("aipass.prax.logger")` | REAL |
| `patch("…apps.modules.logger.system_logger")` | REAL |
| `setitem(sys.modules, "…apps.modules.logger")` | REAL |
| `setitem(sys.modules, "aipass.prax")` | REAL |
| `patch("<the consuming module>.logger")` | **MOCK** |

The cause is in this package's own `__init__.py`, and the lazy rewrite did not
change it: `__getattr__` resolves `logger` once and caches the object in
`globals()`, so the object is still copied at the package boundary and copied
again into each consumer's globals. Anything patched at or above `aipass.prax`
is upstream of a copy already taken. **The last dot must be resolved at call
time**, which only the consumer-module patch does. prax's own conftest was one of
the four that miss — this is prax's gap before it is anyone else's.

**Interim technique, correct today, one line per consuming module:**

```python
patch("aipass.<branch>.apps.handlers.<module>.logger")
```

**But do not build patch lists on it.** That is not the contract prax wants to
leave standing, because it asks 18 branches to maintain a per-module list for a
problem prax should solve once — and a branch that forgets a module gets silence,
not an error.

**Ruling on the test seam: extend the mechanism that already exists, do not add a
new one.** prax already auto-detects pytest and redirects — no env var, no fixture,
no cooperation from the caller. It simply covers the wrong half. Measured with
`PYTEST_CURRENT_TEST` set, one `logger.info()`:

```
 4 writes -> /tmp/aipass_test_logs/   (log files — already redirected)
24 writes -> real src/aipass/prax/prax_json/   (JSON state — not redirected)
```

So the seam is built, proven and automatic for 4 of 28 writes. Extending it to
`PRAX_JSON_DIR` closes the remaining 24 and every branch's number at once, with
no patches, no import changes and nothing for a caller to remember. A new
`silence()` API would need adoption across 385 call sites; a new env var would
need a fixture nobody sets — @daemon offered exactly that mitigation to @memory
in good faith and it fixed 0%, because the thing it targeted was never the cause.
The explicit override for the other half already exists as `AIPASS_TEST_LOG_DIR`,
so the escape-hatch pattern is settled too.

Callers need do nothing and should change nothing. Reported shares — @drone 7650,
@memory 1552, @daemon 1096, @backup 778 — are prax's to fix, not theirs.

## The fleet json service (DPLAN-0325)

**Prax owns the fleet's one JSON handler implementation.** Boardroom
`r/boardroom-json-service` post 8, Patrick's ruling 2026-09-03: the fleet's drift
no longer matters — one source, every branch follows the one file.

```python
from aipass.prax import json_handler          # the entry point, the only sanctioned import
```

- `apps/handlers/json/json_service.py` — the implementation. Stdlib only, so it
  imports without the logger graph. No `resolve()`, no `getcwd()`, no
  `inspect.stack()`: it runs with a deleted working directory.
- `apps/handlers/json/json_handler.py` — prax's own shim, byte-identical in all
  18 branches. **1724 bytes, sha256 `3456b766…cf0b7`** (verified 2026-09-05);
  seedgo accepts it by hash, not by substring. It BINDS the service's callables
  and never wraps them: a wrapper would add a stack frame and silently rename
  every entry in the operations log.
- The old handler and `json_templates/` are in
  `apps/handlers/json/.archive/`. The default document is in code now — a
  default that lives in a file can go missing, and a handler whose default is
  missing stops self-healing exactly when it is needed.

**What the entry point hands you.** `from aipass.prax import json_handler` gives
you the **service module** — `for_module()`, `JsonHandle`, `InvalidDocument`,
`WriteFailed`. That is what a branch's shim imports before binding a handle to
itself with `for_module(__file__)`. Branch code calls its own shim
(`from aipass.<branch>.apps.handlers.json import json_handler`) and gets the
bound names — `load_json`, `save_json`, `log_operation`, and the rest.

**Three documents per module, three jobs (FPLAN-0542, 2026-09-11).** The log
(`<module>_log.json`) is the per-module operation trail, one entry per
`log_operation`, rotating at the config's cap. The data document
(`<module>_data.json`) is lifetime state: every log write that lands also bumps
`operations_total` and stamps `last_operation` and `last_updated`, merging those
keys into the document and never replacing it, and a data document missing its
base keys (`created`/`last_updated` — `prax_json/prax_logger_data.json` is
literally `{}`) is healed, not refused. The config (`<module>_config.json`) is
the rotation cap, `config.max_log_entries`, default 100. The bump is telemetry:
a data write that fails logs a warning and `log_operation` still answers the
log's own `True`. There is no success/failure counter, because the call carries
no success signal; the old-era `operations_successful`/`operations_failed` keys
are left exactly as they are. The bump is a read-modify-write like the log
itself, so under racing writers `operations_total` is a lower bound, not an
exact count. It also costs one more staged write per call: median 9.5 ms before,
14.7 ms after, per `log_operation` (a single-machine reading, 5 interleaved runs
of 200 calls). `rate_tracker` keeps its `files` in that same
`rate_tracker_data.json`, and its save now sets only `files` (and `module_name`
when absent) on the document it loaded. The old save rebuilt the whole dict,
which re-stamped `created` on every scan and would have wiped the counters.

**Healing is per module, per call — there is no sweep.** `ensure_json_exists`
regenerates exactly one document (`<module>_<type>.json`) when it is missing,
empty, unreadable or structurally invalid. The one exception is a data document
that parses as a dict: it is healed in place (missing base keys added, every
other key kept) rather than regenerated. `ensure_module_jsons` does the
three types for one module. Nothing walks a directory and nothing repairs
another module's documents: a self-heal that ranges wider than the call that
triggered it would rewrite state nobody asked about, in a process that may only
have wanted to log one line.

**The package init is lazy** (PEP 562 `__getattr__` in `aipass/prax/__init__.py`).
`logger`, `append_jsonl` and `json_handler` resolve on first attribute access.
Measured, `from aipass.prax import json_handler` in a fresh interpreter:

| | aipass modules | third-party |
|---|---|---|
| eager init (before) | 30 | `watchdog` |
| lazy init (now) | **6** | **none** |

`aipass.trigger` and the whole watchdog edge stayed cold. Pinned by
`TestLazyInitImportFootprint` in `tests/test_logger_module.py`, which measures in
a subprocess — in-process the number is meaningless, pytest has already imported
prax's world.

**Return semantics changed with the service:** `save_json` raises `WriteFailed`
rather than answering `False` (a lost document must not look like success) and
`InvalidDocument` rather than `False` (a caller bug is not a disk failure).
`write_json` still answers `bool`. `log_operation` is telemetry and still answers
`False` on a write failure — it runs on the monitor's display and watchdog
threads, where a raising writer is silent half-death.

### The post-sweep bundle (2026-09-04, commit 08359ec2)

Four defects found after the migration, all in prax's tree, all fixed and pinned.

**A write no longer changes a mode nobody asked it to change.** The staged write
went through `tempfile.NamedTemporaryFile`, which creates at a hardcoded `0600`,
and `os.replace` carries the **staged** file's mode onto the target — so every
service write narrowed the document it rewrote, fleet-wide: a `664` config came
back `600` on its next write, and the group that could read it yesterday could
not today. Nothing failed loudly. Now an existing document keeps its own mode
(read off the target, applied to the staged fd with `fchmod`, which the umask
does not touch) and a new one is created with `0o666` for the **kernel** to
narrow by the process umask — byte for byte what `open(path, "w")` would have
produced. The umask is never read: `os.umask()` both sets and returns, so reading
it means briefly widening it for every other thread, and prax runs watchdog and
display threads. Pinned at 664/644/600/640, and for a fresh document against a
reference file created by a plain `open()` in the same directory in the same
breath — the expectation is measured, never the constant `0664`.

**NaN and Infinity are refused.** `json.dumps` defaults to `allow_nan=True` and
writes the bare tokens `NaN`/`Infinity`/`-Infinity`, which are not JSON: the
document lands, prax reads it back happily, and it fails in some other
language's strict parser days later, nowhere near the branch that wrote it. The
service passes `allow_nan=False` and lets json's own **`ValueError`** out — the
same answer it already gives an unknown `json_type`. `log_operation` still
answers `False` rather than raising, because it runs per event on threads where
a raising writer is silent half-death.

**A staged file's name must not read the clock.** The first cut of the mode fix
named temp files with `time.time_ns()`, and seedgo's cross-branch contract stubs
the module's `time` to take the sleep out of the bounded retry — 45 contract
tests across 15 branches went red on `AttributeError`. Names come from
`os.getpid()` + `itertools.count()` now. Worth writing down: the fleet contract
caught a prax defect within minutes of it existing.

**Superseded 2026-09-12 (DPLAN-0339 step 4): the logger starts no watcher at all
any more.** The section below is the record of how the cost was chased around
the process before the walk was removed from the logging path entirely; see
"Discovery is a scheduled scan" above.

**The watcher start does not block the first log line.** `SystemLogger._ensure_watcher`
called `start_file_watcher()` inline, and watchdog installs one inotify watch per
directory under the ecosystem root. Measured 2026-09-04 on this machine, 1605
directories: **0.119 s** when the calling thread is alone, **13.949 s (117×)**
when one other Python thread is CPU-busy — each `inotify_add_watch` drops the GIL
and then has to win it back from a thread that never blocks, so the walk pays up
to a full switch interval (5 ms) per directory. A suite whose only crime was to
log something waited seconds for a watcher it never asked about. The logger now
calls `start_file_watcher_in_background()`: same walk, same watches, on a thread
nobody joins — caller blocked **5.72 ms**, the walk finishing ~4.5 s later off to
the side. Neither cure first proposed would have worked: yielding between
directories adds handoffs to a walk already starving on them, and bounding the
walk to `apps/` (what Mission Control does) would stop discovering the 113 of 196
registered modules that live in `tests/` and elsewhere (counted 2026-09-05). `start_file_watcher()`
itself still blocks, for its one remaining caller
(`lifecycle.run_initialization`, which explicitly asked to initialise), and both
doors share one lock — without it each finds no observer, each walks, and the
second assignment orphans the first: two watches per directory and every event
delivered twice.

---

**`AIPASS_TEST_LOG_DIR` is the fleet contract, and the service made it simple.**
Every branch's documents are redirected by one variable, honoured by the service
itself:

```python
@property
def json_dir(self) -> Path:                      # json_service.py
    name = self.branch_root.name
    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        return Path(test_dir) / name / f"{name}_json"
    return self.branch_root / f"{name}_json"
```

**Resolved per call, never captured at import**, and that is the whole reason it
works. The two predecessors of this design both failed on import order — a
module-level constant cannot be redirected by a conftest that runs after
something already imported the module, and the "compare against the import-time
value" refinement that followed broke on `importlib.reload` (a monkeypatch
teardown writes the pre-reload Path onto the post-reload module, and the redirect
dies silently for the rest of the session — measured against @daemon's adoption,
2026-08-30). A property has no fixed point to go stale: there is nothing to
compare and nothing to write back. Both of those older mechanisms retired with
the old handler and are in `apps/handlers/json/.archive/json_handler.py` if
anyone needs the reasoning.

An **empty** value is absence, not a redirect — `Path("") / "prax"` is relative
and would scatter state wherever the process happens to stand. Pinned in
`tests/test_json_handler.py`, and in subprocesses (both import orderings) in
`tests/test_json_durability.py`, because in-process the ordering under test is
already decided.

Each branch gets this by binding the service; no branch adopts a spelling of its
own. And the per-module logger patch stays **opt-in per module, never blanket
autouse** — @daemon proved a blanket mock silenced their refused-and-named
`caplog` pin, and a suite that cannot show its refusals are loud has traded
evidence for a number.

### Log levels

`debug()` is silent by default. Nothing it logs reaches a file until the level is
lowered, which is the point: use it for the verbose trail you want available on
demand but absent from normal operation.

```bash
AIPASS_LOG_LEVEL=DEBUG drone @yourbranch yourcommand   # verbose run
```

The level can also be set per tier in `prax_json/prax_logger_config.json`, so a
branch can keep a verbose local log while the central aggregation stays quiet:

```json
{"config": {"system_logs": {"log_level": "INFO"}, "local_logs": {"log_level": "DEBUG"}}}
```

Precedence is `AIPASS_LOG_LEVEL` → the tier's `log_level` → `INFO`. An
unrecognised value warns once and falls back to `INFO` rather than silently
picking a level nobody asked for.

**Levels bind when a logger is created, not per call.** A long-running process
(Mission Control, a daemon, a bot) picks up a level change on restart — setting
the env var mid-flight does nothing for loggers that already exist.

### Pattern B — Direct Logger (for prax internals)

```python
from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()
logger.info("Direct log entry")
```

Use this in prax handler files that run in watchdog threads or sit in the import chain. Resolves module/branch at creation time, bypassing the runtime event pipeline.

### Programmatic Dashboard API

```python
from aipass.prax.apps.modules.dashboard import write_section

write_section(branch_path, "ai_mail", {"new": 3, "total": 5})
```

**quick_status has many writers.** prax refresh, `push-template`,
`write_section()` and other branches (@flow's push) all touch the same block.
Every prax write path now *merges*: it recomputes the keys prax owns
(`new_mail`, `opened_mail`, `active_plans`, `todo_count`, `action_required`,
`summary`) and carries every other key through untouched. The invariant, agreed
with @flow: **no writer deletes a key it did not write.** The calculation itself
lives in exactly one place
(`handlers/dashboard/status.py::calculate_quick_status`) — `refresh.py`,
`operations.py` and `template_pusher.py` all delegate to it.

**`sections.flow` has two writers too.** @flow's push and prax's refresh both
build that section wholesale, so the same invariant applies one level up. prax
mirrors @flow's five-key contract exactly — `managed_by`, `active_plans` (an int
count), `open_recent` (the 5 newest open plans, newest first), `recently_closed`
(closed inside the same 7-day window @flow uses), `total_plans` — pinned in
`tests/test_flow_section_contract.py` so the two writers cannot drift apart
again. `total_plans` is the one key prax has no honest source for, so it carries
@flow's value through instead of deriving one: the central file's per-branch
`statistics.total_closed` reads its own already-capped 5-entry list as the
closed universe, and reports 5 for a branch with 104 closed plans.

`action_required` is true when any counter the block renders in `summary` is
non-zero, todos included. It previously ignored `todo_count`, so a branch could
publish `"1 todos"` and `action_required: false` side by side — measured by
@flow against their own writer, which does count them.

`push-template` was the last independent copy, and the most dangerous one
because it writes every branch in the registry. It carried its own calculator
with no `todo_count`, assigned the block wholesale rather than merging, and
listed `commons_mentions` as a *deprecated key to delete*. prax did once own
that key, but @flow took it over instead of retiring it, so the list outlived
the ownership change: one push would have deleted a live key fleet-wide by
declared policy. Fixed 2026-08-13 — `template_pusher.DEPRECATED_QUICK_STATUS_KEYS`
now holds only `pending_bulletins`, and a key qualifies for it only when nobody
writes it.

**The fix reached the writer, not the adviser.** `template_differ.py` carries its
own copy of that list and it still reads
`["pending_bulletins", "commons_mentions"]`. The differ never writes, so nothing
is deleted — but `diff-template` still *recommends* deleting a live key.
Reproduced 2026-08-25 against prax's own dashboard:

```
  PRAX (needs_update)
    + ai_mail section
    ~ quick_status: remove commons_mentions
```

@flow writes `commons_mentions`; prax's own `calculate_quick_status` carries it
through untouched. So the advice contradicts the invariant the writers already
honour, and anyone who acts on it by hand does the deletion the pusher was fixed
not to do. Two copies of one policy list is the defect underneath; a single
shared constant is the fix. Not changed here — this pass documents, it does not
rewrite handlers.

## Architecture

```
prax/
├── __init__.py                        # Public API, LAZY (PEP 562): `logger`, `append_jsonl`, `json_handler` resolve on first access; NullLogger fallback
├── apps/
│   ├── prax.py                        # Entry point — auto-discovers modules, routes commands
│   ├── modules/                       # Business logic (6 command modules)
│   │   ├── logger.py                  # SystemLogger — auto-routing, two-tier logging
│   │   ├── monitor.py                 # Mission Control — 4-thread real-time monitoring
│   │   ├── dashboard.py               # Dashboard — template management, refresh, write-through
│   │   ├── status.py                  # System status — health display (`status sync` still writes STATUS.md)
│   │   ├── log_audit.py              # Log audit — scan, health summary, enforce, sweep
│   │   └── log_health.py             # Log health — rate overview (scan/snapshot)
│   ├── plugins/
│   │   └── devpulse_dashboard/        # Per-branch dashboard sections (git, session, dispatch)
│   └── handlers/                      # Implementation details (11 handler directories)
│       ├── central/                   # Central file reader (.ai_central/*.central.json)
│       ├── config/                    # Path resolution, log config, ignore patterns
│       ├── dashboard/                 # Refresh, operations, template push/diff, agent status
│       ├── discovery/                 # Module scanning, filtering, file watcher for new .py
│       ├── cli/                       # Help-flag detection and the unknown-argument gate (pure predicates, no I/O)
│       ├── json/                      # The fleet json service + prax's own shim (config/data/log per module)
│       ├── logging/                   # Setup, rotation, introspection, override, direct logger, log watchdog, jsonl writer
│       ├── monitoring/                # Event queue, branch detector, branch scope, stream output, log watcher, rate tracker, filters, commons feed, telegram relay, instance lock, CLI-session handler, pid cache
│       ├── registry/                  # Module registry load/save
│       ├── status/                    # STATUS.md sync handler (trigger unwired, but `status sync` still reaches it)
│       └── watcher/                   # Background system watchers
├── .daemon/schedule.json              # Daemon command job: tmp-sweep-weekly (DPLAN-0338)
├── prax_json/                         # Auto-created per-module config/data/log files
├── templates/                         # Dashboard template schema (DASHBOARD.template.json)
└── tests/                             # 1421 test functions, 36 files (1510 cases)
```

### Design Pattern

The entry point (`prax.py`) has zero business logic — it auto-discovers modules in `apps/modules/` and routes commands. Each module is a thin orchestrator over its handlers. Handlers are never imported by external branches.

### Command Routing

```
drone @prax monitor run
  → prax.py discovers modules (glob apps/modules/*.py)
  → calls monitor.handle_command("monitor", ["run"])
  → monitor.py delegates to handlers/monitoring/*
```

### The unknown-argument gate

Patrick's standing ruling: **an unknown command or argument FAILS** — non-zero
exit, a message naming the token, a did-you-mean where one is close. @devpulse's
fleet CLI sweep (2026-09-07) found prax breaking it in six places, and they
broke it two different ways:

- `drone @prax --definitely-not-a-flag` printed the self-map and exited **0** —
  output byte-identical to a clean no-args run. argparse's `parse_known_args`
  hands an unrecognised flag back instead of erroring, so nothing ever looked at
  it. `status bogus` was the same silence at the module level: the normal status
  block, no complaint, exit 0.
- `log-audit`, `log-health`, `monitor` and `dashboard` each printed the right
  refusal and then **returned `True`**, which the router reads as "handled" and
  turns into exit 0. Truth on screen, a lie in `$?`.

The cure is one gate, `handlers/cli/arg_gate.py`. It DECIDES and does not
display: `refuse()` logs the refusal through `json_handler` and raises
`UnknownArgument`; `prax.py` catches it once, renders through cli, returns 1.
`route_command` re-raises it past its own blanket `except Exception`, because a
refusal reported as "Handler failed" loses the token the caller needs. The
modules import the gate directly; the entry point imports it re-exported through
`apps/modules/__init__.py`, since an entry point never reaches into handlers.

Help still wins over the gate everywhere: `wants_help(args)` runs first, so
`status sync -h` and `dashboard refrsh --help` explain themselves rather than
failing. A question is never a bad argument.

### The exit seam

The gate above covers refusals prax *raises*. It does not cover the other way a
command fails: a handler that routes fine, prints an error, and returns. cli's
`error()` sets a process-level failure flag, but a flag only becomes an exit
code where somebody reads it — and `main()` returned a bare `0` on any routed
command, so `error()` changed the colour on screen and nothing else.

Closed 2026-09-08 (FPLAN-0512, the fleet rule @devpulse landed in memory first):
`main()` calls `reset_command_state()` at entry, and `_run()` returns
`resolve_exit(True)` instead of `0` when `route_command` handles the command.
A handler that called `error()` now exits **2**; an unknown token still exits 1;
a clean run still exits 0. The reset is at the entry point so a flag left set by
an earlier in-process run cannot leak into the next.

Measured after the change: `dashboard refresh @nosuchbranch` → **2** (it printed
`Branch 'NOSUCHBRANCH' not found in registry` and exited **0** before), `status`
→ **0**.

The one caller this changed is `dashboard refresh --all`. A partial refresh —
some branches updated, some failed — announced itself through `warning()`, which
does not set the flag, so a run that left branches stale exited 0. It now goes
through `error()`.

## How It Works

1. **Auto-routing** — `logger.info()` inspects the call stack to identify the caller's module, branch, and file path, then routes the log entry to the correct per-module log file.
2. **Two-tier logging** — Each log entry goes to both `system_logs/` (central, all branches) and `<branch>/logs/` (branch-local), both with size-based rotation.
3. **Self-healing** — Auto-creates missing log directories, falls back to `system_logs/external/` for unknown modules, provides NullLogger if prax itself fails to import.
4. **Mission Control** — Four threads: display worker (pulls from event queue), file watcher (watchdog on branch `apps/` dirs), log watcher (tails `system_logs/*.log`), rate tracker (scans `system_logs/` for runaway growth every 10s). Falls back to polling when inotify is exhausted.
5. **Multi-CLI monitoring** — Watches Claude Code JSONL and Codex JSONL session files. Extracts agent activity (thinking, tool use, responses) with model detection and branch resolution.
6. **Runaway-log detection** — Rate tracker measures byte growth per log file, estimates lines/min from byte deltas. Sustained thresholds: WARNING (>100 lines/min for 2 min), CRITICAL (>10 lines/sec for 1 min). Fires `runaway_log_detected` on the trigger event bus. State persists to disk across process restarts. Per-file suppression available.
7. **Dashboard** — Template-based per-branch dashboard files. Refreshes from central files (`*.central.json`). Write-through API for services to update sections directly.
8. **STATUS sync** — *(Decommissioned by TDPLAN-0007, but still reachable.)* Scans all branch `STATUS.local.md` files and writes an aggregated `STATUS.md` to the repo root. The automatic path is genuinely dead — the trigger registration was unwired — but the `status sync` subcommand still calls the engine, so running it recreates a file the fleet deleted. See the Status command section.

## Tests

**1421 test functions across 36 files; pytest expands them to 1510 cases**, all
passing from both rootdirs (measured 2026-09-11). The two numbers differ because
of parametrisation — the table below counts collected cases, which is what a
suite run reports.

| Test File | Cases | Coverage |
|-----------|-------|----------|
| test_filesystem_handler.py | 141 | Multi-CLI adapters, Codex branch detection |
| test_monitoring_handlers.py | 141 | Branch detector, stream output, event handling, the registry read that opens instead of checking |
| test_operations.py | 104 | Dashboard operations, write-through; `refresh @branch` through the caller's project registry (core wins a collision), the caller's directory over the process cwd, mail counted from the branch's own inbox |
| test_json_handler.py | 96 | The fleet json service: branch resolution, the per-call seam, document modes, the NaN refusal, the exception table, bounded retry, the log cap, the data-leg bump and heal (incl. rate_tracker sharing the document), the shim binds-never-wraps |
| test_log_watcher.py | 84 | Log file tailing, agent activity parsing |
| test_monitor_module.py | 80 | Monitor commands, thread lifecycle (4-thread), branch scoping |
| test_telegram_relay.py | 62 | Telegram relay, buffering, pause control |
| test_config.py | 61 | Config loading, path resolution, log levels |
| test_repo_root.py | 55 | Repo-root resolution with a dead working directory, per-platform expectation tables |
| test_logger_module.py | 52 | Logger init, routing, lifecycle, NullLogger fallback, lazy-init import footprint (subprocess) |
| test_event_queue.py | 49 | Thread-safe event buffering, scope suppression |
| test_logging_handlers.py | 48 | Setup, rotation, introspection, direct logger |
| test_logging.py | 47 | Core logging system, debug level gating |
| test_watcher.py | 47 | File watcher behaviour; dispatcher survives handler failure (real observer); liveness reporting; the background start that does not block its caller |
| test_monitoring_filters.py | 39 | Event filtering rules |
| test_branch_scope.py | 37 | Branch scope parsing, label matching, attribution |
| test_dashboard_merge.py | 36 | quick_status merge, foreign-key preservation, plan-count shapes, push-template writer, action_required/summary agreement |
| test_help_flag_safety.py | 34 | Help flags in any position never execute; ownership before help; free-text safety; the unknown-argument gate (top-level flag, sub-argument, exit code, did-you-mean) |
| test_rate_tracker.py | 34 | Rate tracking, thresholds, persistence (incl. rate history), suppression |
| test_instance_lock.py | 28 | Single-instance locking, stale reclaim |
| test_commons_feed.py | 27 | Commons live feed, cursors, room filtering, full-body rendering |
| test_discovery.py | 25 | Module scanning |
| test_display_resilience.py | 25 | Markup escaping, display-worker survival, standalone args |
| test_flow_section_contract.py | 22 | `sections.flow` five-key contract; per-branch recently_closed; total_plans carried, not derived |
| test_registry.py | 22 | Module registry |
| test_project_citizens.py | 20 | projects/* registry sweep, passport resolution, collision precedence, CWD-independent paths |
| test_central.py | 14 | Central reader |
| test_log_audit.py | 13 | Log audit |
| test_help_markup.py | 12 | Rendered console output (real Rich console), help covers every routable command |
| test_pid_cache.py | 11 | PID resolution cache |
| test_devpulse_dashboard_plugin.py | 9 | Dashboard plugin (git, session, dispatch) |
| test_jsonl_writer.py | 9 | JSONL append writer |
| test_status.py | 9 | Status commands; an unknown sub-argument is refused rather than ignored |
| test_log_health.py | 7 | Snapshot staleness reporting, rate display, routing |
| test_sweep.py | 6 | Log sweep |
| test_json_durability.py | 4 | `AIPASS_TEST_LOG_DIR` seam, measured in subprocesses (both import orderings) |

## Integration Points

### Depends On
- `aipass.cli` — Console output, headers, success/error formatting (imported)
- `aipass.trigger` — Optional event firing (`module_discovered`,
  `runaway_log_detected`, `file_watcher_died`). Every import site is guarded by
  `except (ImportError, OSError)`: prax runs without it. The logging path no
  longer touches it at all — the per-process `startup` fire was removed in
  DPLAN-0339 step 3, and the events that remain fire only from the discovery
  watcher, which now runs only when an operator starts it explicitly.
- `watchdog` is no longer on the logging path either (step 4). It is imported by
  the discovery watcher and by Mission Control, both of which are started on
  purpose by somebody.
- `watchdog` — File system monitoring (inotify + polling fallback)
- Python stdlib (`pathlib`, `logging`, `threading`, `argparse`, `importlib`)
- **@drone is not an import.** prax never imports drone; it *parses* the
  `[CALLER:BRANCH]` marker drone writes into its own log lines
  (`handlers/monitoring/log_watcher.py`), and reads `AIPASS_CALLER_CWD` from the
  environment. The coupling is a text format, not a dependency — verified
  2026-09-05, no `aipass.drone` import exists anywhere in the tree.
- The json service imports **stdlib only**, on purpose: measured 2026-09-05,
  `from aipass.prax import json_handler` in a fresh interpreter loads 6 aipass
  modules and no third-party package at all.

*(All import claims here re-verified 2026-09-05.)*

### Provides To
- All branches — Unified logging via `from aipass.prax import logger`
- All branches — Real-time monitoring via Mission Control
- All branches — Per-branch dashboard files
- System — Log audit enforcement

## Known Issues
- **inotify pressure** — The monitor and log watcher fall back to polling when inotify watches run out (functional but slower). Earlier revisions said the system is "often near" the limit; measured again 2026-09-05 it is not — **8,340 watches held across all processes against a `max_user_watches` of 65,536**, about 13% (it was 7,664 on 2026-08-25). The fallback is real and tested. It is a single-machine reading, not a fleet property.
- **`monitor run` is not single-instance.** `instance_lock` guards the *Telegram relay* only, so N concurrent Mission Controls start cleanly and each adds its own watches on top of every other watcher (see the inotify note above). Verified 2026-08-13 by launching five alongside the then-live systemd service; none complained. That service is retired as of 2026-08-18 (monitor is on-request only), so the everyday risk is now several forgotten terminals rather than a daemon plus terminals — but the missing guard is unchanged.
- ~~**Error paths exit 0.**~~ **Fixed 2026-09-07** (FPLAN-0492 wave 3). Every unknown token now exits **1** with the token named on stderr: measured after the change, `--definitely-not-a-flag`, `monitor bogus`, `log-audit bogus`, `log-health bogus`, `dashboard bogus` and `status bogus` all return 1, and `status`, `log-health scan`, `dashboard status`, `log-audit audit`, `monitor --help` and `dashboard template-status` still return 0. See the unknown-argument gate under Command Routing.
- **The test seam does not cover path-based writes.** `AIPASS_TEST_LOG_DIR` redirects everything the json service writes by module name (measured 2026-09-05: 0 files into the real `prax_json/`, 18 into the redirect). It does not reach the module-level constants in `handlers/config/load.py`, `handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and `handlers/registry/save.py`, which resolve to the real tree even with the variable set — so a registry save under any suite writes the live `prax_registry.json`. See the json service section.
- **The module registry never prunes.** `prax_registry.json` gains an entry when a `.py` file appears and loses one only if someone removes it by hand. Counted 2026-09-05: **196 modules registered, 63 of which name a file that is no longer on disk** — probes, scratch files and archived tests from a dozen branches' sweeps. Stale rows mislead rather than break (every reader opens the path), but a third of the registry describing files that do not exist is not a registry anyone should trust for a count.
- **No runtime filtering in Mission Control** — `_handle_interactive_cmd` dispatches
  only `help` and `status`; `watch` and `filter` fall through to "Unknown command". Branch
  selection is launch-time only (`monitor run seedgo,cli`) and cannot be changed without a
  restart. Commons feed mode is the exception: it implements `filter <room>` / `filter clear`
  live. `watch` exists in neither mode.

---

*Last Updated: 2026-09-11*

---
[← Back to AIPass](../../../README.md)
