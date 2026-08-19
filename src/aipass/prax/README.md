[← Back to AIPass](../../../README.md)

# PRAX

**Purpose:** System-wide logging, real-time monitoring, and dashboard infrastructure for AIPass.
**Module:** `aipass.prax`
**Version:** 2.4.0
**Last Updated:** 2026-08-13

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
  a recursive ~1413-watch observer over `src/aipass` (see DPLAN-0307). That design
  is under review precisely because always-on processes multiply it.

Real-time unified console showing:
- File changes, log events, drone commands, agent activity
- **Branch scoping** — `monitor run seedgo,cli` shows only those branches (see below)
- **Caller attribution** — `CALLER → TARGET` for drone commands
- **Model tags** — `[BRANCH/model]` (e.g., `[DEVPULSE/opus]`, `[DEVPULSE/gpt-5.4]`)
- **Multi-CLI** — Claude Code (JSONL), Codex (JSONL) session monitoring
- **Rate tracking** — 4th background thread scans `system_logs/` for runaway log growth every 10s
- **Polling fallback** — automatic fallback when inotify watches are exhausted
- **Soft start** — only shows new activity after launch (seeks to EOF on startup)

Interactive commands inside the monitor: `help`, `status`, `quit`/`exit`.

**Who counts as a branch.** Names and paths come from declarations, never from
path shape. Three sources, in precedence order: `AIPASS_REGISTRY.json` for
`src/aipass/*` branches; then a sweep of `projects/*/*_REGISTRY.json` for in-repo
project citizens (BAUD, EARMARK, MARKETSTAND, AIPASS_SITE, TESTING); then, for
any file still unresolved, the nearest `.trinity/passport.json` walking up to the
repo root. A relative registry path is resolved against *its own registry's*
directory, not the process CWD. First registration wins, so a project cannot
claim a name AIPass already uses.

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
drone @prax status                       # System health (modules, loggers, watcher state)
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
same day.

### Dashboard

```bash
drone @prax dashboard                    # Show dashboard sections
drone @prax dashboard refresh --all      # Refresh all branch dashboards from centrals
drone @prax dashboard refresh @flow      # Refresh a specific branch
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
declared policy. Fixed 2026-08-13 — the deprecation list now holds only
`pending_bulletins`, and a key qualifies for it only when nobody writes it.

## Architecture

```
prax/
├── __init__.py                        # Public API: exports `logger` (NullLogger fallback)
├── apps/
│   ├── prax.py                        # Entry point — auto-discovers modules, routes commands
│   ├── modules/                       # Business logic (6 command modules)
│   │   ├── logger.py                  # SystemLogger — auto-routing, two-tier logging
│   │   ├── monitor.py                 # Mission Control — 4-thread real-time monitoring
│   │   ├── dashboard.py               # Dashboard — template management, refresh, write-through
│   │   ├── status.py                  # System status — health display (STATUS.md sync dormant)
│   │   ├── log_audit.py              # Log audit — scan, health summary, enforce, sweep
│   │   └── log_health.py             # Log health — rate overview (scan/snapshot)
│   ├── plugins/
│   │   └── devpulse_dashboard/        # Per-branch dashboard sections (git, session, dispatch)
│   └── handlers/                      # Implementation details (12 handler directories)
│       ├── central/                   # Central file reader (.ai_central/*.central.json)
│       ├── config/                    # Path resolution, log config, ignore patterns
│       ├── dashboard/                 # Refresh, operations, template push/diff, agent status
│       ├── discovery/                 # Module scanning, filtering, file watcher for new .py
│       ├── cli/                       # Help-flag detection (pure predicate, no I/O)
│       ├── json/                      # Auto-creating JSON handler (config/data/log per module)
│       ├── json_templates/            # Default JSON templates for auto-creation
│       ├── logging/                   # Setup, rotation, introspection, override, direct logger, log watchdog, jsonl writer
│       ├── monitoring/                # Event queue, branch detector, branch scope, stream output, log watcher, rate tracker
│       ├── registry/                  # Module registry load/save
│       ├── status/                    # STATUS.md sync handler (trigger unwired, but `status sync` still reaches it)
│       └── watcher/                   # Background system watchers
├── prax_json/                         # Auto-created per-module config/data/log files
├── templates/                         # Dashboard template schema (DASHBOARD.template.json)
└── tests/                             # 1371 tests across 36 files
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

1371 tests across 36 files (1370 pass, 1 skipped), covering all major components:

| Test File | Tests | Coverage |
|-----------|-------|----------|
| test_filesystem_handler.py | 142 | Multi-CLI adapters, Codex branch detection |
| test_monitoring_handlers.py | 139 | Branch detector, stream output, event handling |
| test_operations.py | 99 | Dashboard operations, write-through |
| test_log_watcher.py | 90 | Log file tailing, agent activity parsing |
| test_monitor_module.py | 82 | Monitor commands, thread lifecycle (4-thread), branch scoping |
| test_telegram_relay.py | 62 | Telegram relay, buffering, pause control |
| test_config.py | 61 | Config loading, path resolution, log levels |
| test_logging_handlers.py | 49 | Setup, rotation, introspection, direct logger |
| test_logging.py | 47 | Core logging system, debug level gating |
| test_logger_module.py | 46 | Logger init, routing, lifecycle, NullLogger fallback |
| test_event_queue.py | 49 | Thread-safe event buffering, scope suppression |
| test_monitoring_filters.py | 39 | Event filtering rules |
| test_commons_feed.py | 28 | Commons live feed, cursors, room filtering |
| test_instance_lock.py | 28 | Single-instance locking, stale reclaim |
| test_rate_tracker.py | 34 | Rate tracking, thresholds, persistence (incl. rate history), suppression |
| test_discovery.py | 25 | Module scanning |
| test_registry.py | 24 | Module registry |
| test_watcher.py | 39 | File watcher behavior; dispatcher survives handler failure (real observer), liveness reporting |
| test_json_handler.py | 18 | JSON auto-creation |
| test_central.py | 14 | Central reader |
| test_log_audit.py | 13 | Log audit |
| test_pid_cache.py | 12 | PID resolution cache |
| test_devpulse_dashboard_plugin.py | 9 | Dashboard plugin (git, session, dispatch) |
| test_jsonl_writer.py | 9 | JSONL append writer |
| test_branch_scope.py | 37 | Branch scope parsing, label matching, attribution |
| test_display_resilience.py | 25 | Markup escaping, display-worker survival, standalone args |
| test_dashboard_merge.py | 36 | quick_status merge, foreign-key preservation, plan-count shapes, push-template writer, action_required/summary agreement |
| test_help_markup.py | 12 | Rendered console output (real Rich console), help covers every routable command |
| test_help_flag_safety.py | 29 | Help flags in any position never execute; ownership before help; free-text safety |
| test_project_citizens.py | 20 | projects/* registry sweep, passport resolution, collision precedence, CWD-independent paths |
| test_log_health.py | 7 | Snapshot staleness reporting, rate display, routing |
| test_status.py | 8 | Status commands |
| test_sweep.py | 6 | Log sweep |
| test_scaffold.py | 1 | Scaffold placeholder (skipped — branch conftest) |

## Integration Points

### Depends On
- `aipass.cli` — Console output, headers, success/error formatting
- `aipass.drone` — Caller attribution via `[CALLER:BRANCH]` log markers
- `aipass.trigger` — Optional event firing (module_discovered, error_detected)
- `watchdog` — File system monitoring (inotify + polling fallback)
- Python stdlib (`pathlib`, `logging`, `threading`, `argparse`, `importlib`)

### Provides To
- All branches — Unified logging via `from aipass.prax import logger`
- All branches — Real-time monitoring via Mission Control
- All branches — Per-branch dashboard files
- System — Log audit enforcement

## Known Issues
- **inotify exhaustion** — System often near `max_user_watches` limit. Monitor uses polling fallback (functional but slower).
- **`monitor run` is not single-instance.** `instance_lock` guards the *Telegram relay* only, so N concurrent Mission Controls start cleanly and each adds its own watches to a system already near the watch limit (above). Verified 2026-08-13 by launching five alongside the then-live systemd service; none complained. That service is retired as of 2026-08-18 (monitor is on-request only), so the everyday risk is now several forgotten terminals rather than a daemon plus terminals — but the missing guard is unchanged.
- **Error paths exit 0.** `monitor bogus`, `log-audit bogus`, `log-health bogus` and `dashboard refresh @nosuchbranch` all print an error and return exit code 0. `status` is worse: an unknown subcommand or unknown flag is dropped silently and the normal status block prints. Nothing scripted can detect a prax command failure from `$?`.
- **No runtime filtering in Mission Control** — `_handle_interactive_cmd` dispatches
  only `help` and `status`; `watch` and `filter` fall through to "Unknown command". Branch
  selection is launch-time only (`monitor run seedgo,cli`) and cannot be changed without a
  restart. Commons feed mode is the exception: it implements `filter <room>` / `filter clear`
  live. `watch` exists in neither mode.

---

*Last Updated: 2026-08-13*

---
[← Back to AIPass](../../../README.md)
