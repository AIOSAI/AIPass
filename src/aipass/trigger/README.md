[← Back to AIPass](../../../README.md)

# Trigger

**Purpose:** Event bus and error dispatch for AIPass. Branches fire events, registered handlers react. Medic watches logs for errors, fingerprints them, gates dispatch through an 8-stage pipeline, and notifies the responsible branch.
**Module:** `aipass.trigger`
**Version:** 2.4.0
**Last Updated:** 2026-08-07

## Quick Start

```bash
drone @trigger status                        # Event bus + medic state
drone @trigger errors list                   # View tracked errors
drone @trigger medic status                  # Check dispatch gating
drone @trigger fire error_detected branch=api error_type=ImportError
```

## Commands

```bash
drone @trigger                              # Introspection (modules, version)
drone @trigger --help                       # Full command listing
drone @trigger --version                    # Version string

# Event bus
drone @trigger fire <event> [key=val ...]   # Fire an event with optional data
drone @trigger list                         # List all registered events + handlers
drone @trigger status                       # Event bus and medic state

# Error registry
drone @trigger errors list                  # View tracked errors
drone @trigger errors stats                 # Registry stats + circuit breaker
drone @trigger errors circuit-breaker       # Circuit breaker state
drone @trigger errors detail <fingerprint>  # Single error detail
drone @trigger errors suppress <id> [why]   # Silence an error — no dispatch while suppressed
drone @trigger errors unsuppress <id>       # Restore dispatch (existing backoff applies)
drone @trigger errors --help                # Error subcommand help

# Medic (error dispatch control)
drone @trigger medic on                     # Enable auto-dispatch
drone @trigger medic off                    # Disable auto-dispatch
drone @trigger medic status                 # Medic state + suppression stats
drone @trigger medic mute @branch           # Suppress error dispatch to a branch
drone @trigger medic unmute @branch         # Resume error dispatch to a branch
drone @trigger medic volume-mute @branch    # Suppress runaway alerts for a branch
drone @trigger medic volume-unmute @branch  # Resume runaway alerts for a branch
drone @trigger medic --help                 # Medic subcommand help

# Log watchers
drone @trigger branch_log_events status     # Branch log watcher state
drone @trigger branch_log_events --help     # Branch watcher help
drone @trigger log_events status            # System log watcher state
drone @trigger log_events --help            # System watcher help
```

## Python API

```python
from aipass.trigger.apps.modules.core import Trigger

# Fire an event — all registered handlers run
Trigger.fire("plan_file_created", path="/path/to/FPLAN-0042.md")

# Register a handler
def on_plan_created(**data):
    print(f"Plan created at {data['path']}")

Trigger.on("plan_file_created", on_plan_created)

# Remove a handler
Trigger.off("plan_file_created", on_plan_created)
```

```python
from aipass.trigger.apps.modules.errors import report_error

# Cross-branch error reporting
result = report_error(
    branch="api",
    error_type="ConnectionError",
    message="Timeout reaching upstream",
    source_file="client.py",
)
# Returns: {"is_new": True, "fingerprint": "abc123", "count": 1, ...}
```

## Events

16 events defined, 14 active (2 decommissioned by TDPLAN-0007). Registered via `handlers/events/registry.py` on first `Trigger.fire()`. All fire through the event bus.

| Event | Handler | Trigger | Action |
|-------|---------|---------|--------|
| `startup` | `startup.py` | Branch session starts | Error catch-up scan across log files, memory rollover check |
| `error_detected` | `error_detected.py` | Error registered via log watcher or `report_error()` | Full 8-gate Medic dispatch — emails fix-it to affected branch + `wake_branch()` |
| `error_logged` | `error_logged.py` | System log error (fallback path) | Monitor-only: logs the event, no dispatch |
| `warning_logged` | `warning_logged.py` | Warning in system logs | Logged for monitoring, no dispatch |
| `plan_file_created` | `plan_file.py` | New PLAN file detected | Updates Flow's PLAN_REGISTRY.json |
| `plan_file_deleted` | `plan_file.py` | PLAN file removed | Marks plan as deleted in registry |
| `plan_file_moved` | `plan_file.py` | PLAN file relocated | Updates registry location |
| `bulletin_created` | _(retired → .archive/)_ | New system bulletin posted | **Retired** — handler archived, no longer registered |
| `memory_threshold_exceeded` | `memory_threshold_exceeded.py` | Memory file near limit (600 lines) | Emails compression notification to branch |
| `memory_template_updated` | `memory_template_updated.py` | Memory template changed | Pushes template updates to branches |
| `memory_saved` | `memory.py` | Memory file written | Placeholder for future rollover trigger |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |
| `pr_created` | `pr_status_sync.py` | PR opened on GitHub | ~~Runs `drone @prax status sync`~~ **Decommissioned** (TDPLAN-0007) |
| `pr_merged` | `pr_status_sync.py` | PR merged on GitHub | ~~Runs `drone @prax status sync`~~ **Decommissioned** (TDPLAN-0007) |
| `runaway_log_detected` | `runaway_handler.py` | Prax rate tracker detects sustained high log volume | Per-file cooldown dispatch to responsible branch; gated by VOLUME mutes only (CRITICAL bypasses); UNKNOWN attribution falls back to @prax; writes alert to `.aipass/alerts.json` |
| `memory_pool_auto_processed` | `memory_pool.py` | Hook engine runs `auto_process()` | Logs result; on failure fires `error_detected` for Medic dispatch |

## Medic

Error monitoring subsystem. Watches branch and system logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch.

**Dispatch pipeline (8 gates):**

1. **Medic enabled** — global on/off toggle
2. **Branch not muted** — per-branch suppression
3. **Count >= 2** — first occurrence suppressed, dispatch on recurrence
4. **Not DEV_CENTRAL** — devpulse protected from self-dispatch
5. **Branch in registry** — target must be a registered citizen
6. **Circuit breaker closed** — trips after 10 errors in 60s, 300s cooldown
7. **Not suppressed + backoff elapsed** — `should_dispatch()` checks registry status first, then exponential backoff
8. **Rate limit** — prevents dispatch floods

On successful dispatch: sends email via `deliver_email_to_branch()` then calls `wake_branch()` to spawn an agent in the target branch immediately.

**Suppression is real silence (compass #219).** A fingerprint with status `suppressed` never dispatches while suppressed — no re-wakes, ever. Agents must not be woken forever for a judged-benign error; the cycle ends at wake → investigate → suppress → sleep. Guardrails:

- Bookkeeping continues — `count` and `last_seen` keep updating, so a wrong suppress stays fully auditable in `errors list` / `errors detail`.
- `errors unsuppress <id>` restores dispatch. Backoff state is preserved, not reset to immediate.
- `errors stats` prints a **Silenced** count so the silent set is never invisible.
- Only `suppressed` gates. `resolved` deliberately does **not** — a resolved error that recurs means the fix did not hold, which is genuine signal.
- Wrong-suppress risk is handled by fingerprint precision, not by periodic re-wake machinery.
- The status read fails open: a registry read error allows dispatch rather than silencing a real error.

**Two mute classes, deliberately independent:**

| Class | Config key | Gates | Set with |
|---|---|---|---|
| CONTENT | `muted_branches` | `error_detected` dispatch | `medic mute @branch` |
| VOLUME | `volume_muted_branches` | `runaway_log_detected` alerts | `medic volume-mute @branch` |

A content mute means "expect error lines from me while I build" — it says nothing about log volume. Because every dispatch checklist tells agents to medic-mute *before* build/edit work, and build windows are exactly when floods happen, gating runaway alerts on the content mute made that channel structurally dead in its own peak window (31/31 suppressions in `logs/runaway_suppressed.jsonl` were `branch_muted`). Volume mutes must be set deliberately, and CRITICAL runaways bypass even those.

Runaway gating decisions are appended to `logs/runaway_suppressed.jsonl` with an `outcome` field (`suppressed` / `delivered`), so suppressed-by-design and delivered-by-bypass are distinguishable. Entries predating that field are all suppressions.

**Persistent log watching** runs as a systemd user service (`trigger-log-watcher.service`). Starts both branch and system watchers, handles SIGTERM/SIGINT for clean shutdown.

```bash
systemctl --user status trigger-log-watcher    # Check watcher service
systemctl --user restart trigger-log-watcher   # Restart watcher
```

## Error Registry

SHA1 fingerprinting for error deduplication. Tracks: fingerprint, branch, error type, message, count, first/last seen, dispatch history, source fix status.

**Circuit breaker:** Trips after 10 errors within 60 seconds. Rejects all dispatch while open. Auto-resets after 300s cooldown. State persists across restarts in `trigger_cb_state.json`.

**Per-fingerprint tracking:** Each unique error has independent exponential backoff and dispatch count. State persists across restarts.

## Architecture

```
trigger/
├── apps/
│   ├── trigger.py                  # Entry point (auto-discovers modules/)
│   ├── config.py                   # Constants, atomic_write_json, json_file_lock
│   ├── log_watcher_service.py      # Persistent watcher daemon (systemd)
│   ├── modules/
│   │   ├── core.py                 # Event bus: Trigger.fire/on/off/status
│   │   ├── errors.py               # Error registry CLI: list/suppress/unsuppress/stats
│   │   ├── medic.py                # Medic toggle: on/off/status/mute/unmute
│   │   ├── branch_log_events.py    # Branch log watcher CLI: start/stop/status
│   │   └── log_events.py           # System log watcher CLI: start/stop/status
│   └── handlers/
│       ├── error_registry.py       # SHA1 fingerprinting, circuit breaker, suppression gate, backoff
│       ├── error_reporter.py       # report_error() API + source fix emails
│       ├── log_watcher.py          # Branch log watcher (watchdog, position tracking)
│       ├── medic_state.py          # Medic state persistence (medic_state.json)
│       ├── json/
│       │   └── json_handler.py     # JSON structure logging
│       ├── events/
│       │   ├── registry.py         # Auto-registers 14 active event handlers
│       │   ├── startup.py          # Startup catch-up scan
│       │   ├── error_detected.py   # 8-gate Medic dispatch
│       │   ├── error_logged.py     # Monitor-only (no dispatch)
│       │   ├── warning_logged.py   # Warning monitor
│       │   ├── plan_file.py        # Plan lifecycle events
│       │   ├── .archive/bulletin_created.py  # Retired
│       │   ├── memory_threshold_exceeded.py
│       │   ├── memory_template_updated.py
│       │   ├── memory.py           # memory_saved placeholder
│       │   ├── cli.py              # cli_header_displayed hook
│       │   ├── runaway_handler.py  # Runaway log dispatch (per-file cooldown, independent of Medic)
│       │   ├── pr_status_sync.py   # PR → prax status sync (decommissioned TDPLAN-0007)
│       │   └── memory_pool.py     # Pool auto-process observability
│       └── watchers/
│           └── log_watcher.py      # System log watcher (system_logs/ dir)
├── tests/                          # 723 tests across 21 modules
├── trigger_json/                   # Runtime state files
│   ├── medic_state.json            # Medic state, muted branches, breaker
│   ├── error_catchup.json          # Startup catch-up scan position + hashes
│   ├── error_registry.json         # All tracked errors
│   ├── trigger_cb_state.json       # Circuit breaker persistence
│   ├── trigger_<config|data|log>.json  # Inert json_handler trio placeholders
│   └── .archive/                   # Retired state files, never deleted
└── trigger_data.json               # Log watcher positions + dedup hashes
```

**Live state never sits on a trio filename.** `json_handler` owns every
`<module>_<config|data|log>.json` name in `trigger_json/`: it validates such a
file against its template and regenerates it when the shape does not match.
Medic state and catch-up state used to live at `trigger_config.json` and
`trigger_data.json` — both trio names for module `trigger`, both hand-written,
neither matching the template. Any trio call resolving to caller module
`trigger` would have replaced them with blank templates, dropping every live
mute, the persisted breaker state, and the processed-hash set that stops
already-handled errors being re-dispatched. The state moved to
`medic_state.json` and `error_catchup.json`; the trio names are now inert
placeholders that `json_handler` is free to own.

`config.migrate_json_file()` performs the move on first read: it is one-shot
(a file re-created at a legacy name afterwards belongs to its owner and is left
alone), never deletes — the old file moves to `trigger_json/.archive/` — and
leaves an unreadable legacy file in place for a human rather than guessing.

## Data Safety

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then `os.replace()` for atomic rename. No partial writes on crash.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` using `fcntl.flock` with `.lock` sidecar files. Prevents concurrent corruption from watcher + CLI.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.
- **Off the trio path:** Hand-written live state uses filenames `json_handler`'s trio machinery does not own — see the Architecture section.

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and formatting
- `aipass.ai_mail` — `deliver_email_to_branch()` for dispatch emails (lazy import, graceful fallback)

### Provides To
- All branches — Event bus (`Trigger.fire`, `Trigger.on`, `Trigger.off`)
- All branches — Cross-branch error reporting (`report_error()`)
- All branches — Automated error dispatch via Medic

## Testing

723 tests across 21 test modules, all passing. Coverage: 87/87 public functions (100%).

```bash
cd src/aipass/trigger && pytest    # Run all tests
```

Test files: `test_core`, `test_errors`, `test_medic`, `test_error_registry`, `test_error_reporter`, `test_medic_state`, `test_log_watcher`, `test_watchers_log_watcher`, `test_branch_log_events`, `test_log_events`, `test_json_handler`, `test_pr_status_sync`, `test_error_detected`, `test_event_handlers`, `test_log_watcher_service`, `test_plan_file_handler`, `test_startup_handler`, `test_trigger_entry`, `test_memory_pool_handler`, `test_runaway_handler`, `test_config_migration`

## Compliance

Seedgo: 100% (41/41 standards). Zero type errors. All categories at 100%.

---

*Last Updated: 2026-08-07*

---
[← Back to AIPass](../../../README.md)
