[← Back to AIPass](../../../README.md)

# Trigger

**Purpose:** Event bus and error dispatch for AIPass. Branches fire events, registered handlers react. Medic watches logs for errors, fingerprints them, gates dispatch through an 8-stage pipeline, and notifies the responsible branch.
**Module:** `aipass.trigger`
**Version:** 2.2.0
**Last Updated:** 2026-05-16

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
drone @trigger errors --help                # Error subcommand help

# Medic (error dispatch control)
drone @trigger medic on                     # Enable auto-dispatch
drone @trigger medic off                    # Disable auto-dispatch
drone @trigger medic status                 # Medic state + suppression stats
drone @trigger medic mute @branch           # Suppress dispatch to a branch
drone @trigger medic unmute @branch         # Resume dispatch to a branch
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

14 events registered via `handlers/events/registry.py` on first `Trigger.fire()`. All fire through the event bus.

| Event | Handler | Trigger | Action |
|-------|---------|---------|--------|
| `startup` | `startup.py` | Branch session starts | Error catch-up scan across log files, memory rollover check |
| `error_detected` | `error_detected.py` | Error registered via log watcher or `report_error()` | Full 8-gate Medic dispatch — emails fix-it to affected branch + `wake_branch()` |
| `error_logged` | `error_logged.py` | System log error (fallback path) | Monitor-only: logs the event, no dispatch |
| `warning_logged` | `warning_logged.py` | Warning in system logs | Logged for monitoring, no dispatch |
| `plan_file_created` | `plan_file.py` | New PLAN file detected | Updates Flow's PLAN_REGISTRY.json |
| `plan_file_deleted` | `plan_file.py` | PLAN file removed | Marks plan as deleted in registry |
| `plan_file_moved` | `plan_file.py` | PLAN file relocated | Updates registry location |
| `bulletin_created` | `bulletin_created.py` | New system bulletin posted | Propagates to branch dashboards |
| `memory_threshold_exceeded` | `memory_threshold_exceeded.py` | Memory file near limit (600 lines) | Emails compression notification to branch |
| `memory_template_updated` | `memory_template_updated.py` | Memory template changed | Pushes template updates to branches |
| `memory_saved` | `memory.py` | Memory file written | Placeholder for future rollover trigger |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |
| `pr_created` | `pr_status_sync.py` | PR opened on GitHub | Runs `drone @prax status sync` (fire-and-forget) |
| `pr_merged` | `pr_status_sync.py` | PR merged on GitHub | Runs `drone @prax status sync` (fire-and-forget) |

## Medic

Error monitoring subsystem. Watches branch and system logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch.

**Dispatch pipeline (8 gates):**

1. **Medic enabled** — global on/off toggle
2. **Branch not muted** — per-branch suppression
3. **Count >= 2** — first occurrence suppressed, dispatch on recurrence
4. **Not DEV_CENTRAL** — devpulse protected from self-dispatch
5. **Branch in registry** — target must be a registered citizen
6. **Circuit breaker closed** — trips after 10 errors in 60s, 300s cooldown
7. **Per-fingerprint backoff** — exponential backoff per unique error
8. **Rate limit** — prevents dispatch floods

On successful dispatch: sends email via `deliver_email_to_branch()` then calls `wake_branch()` to spawn an agent in the target branch immediately.

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
│   │   ├── errors.py               # Error registry CLI: list/stats/circuit-breaker
│   │   ├── medic.py                # Medic toggle: on/off/status/mute/unmute
│   │   ├── branch_log_events.py    # Branch log watcher CLI: start/stop/status
│   │   └── log_events.py           # System log watcher CLI: start/stop/status
│   └── handlers/
│       ├── error_registry.py       # SHA1 fingerprinting, circuit breaker, backoff
│       ├── error_reporter.py       # report_error() API + source fix emails
│       ├── log_watcher.py          # Branch log watcher (watchdog, position tracking)
│       ├── medic_state.py          # Medic config persistence (trigger_config.json)
│       ├── json/
│       │   └── json_handler.py     # JSON structure logging
│       ├── events/
│       │   ├── registry.py         # Auto-registers all 14 event handlers
│       │   ├── startup.py          # Startup catch-up scan
│       │   ├── error_detected.py   # 8-gate Medic dispatch
│       │   ├── error_logged.py     # Monitor-only (no dispatch)
│       │   ├── warning_logged.py   # Warning monitor
│       │   ├── plan_file.py        # Plan lifecycle events
│       │   ├── bulletin_created.py # Bulletin propagation
│       │   ├── memory_threshold_exceeded.py
│       │   ├── memory_template_updated.py
│       │   ├── memory.py           # memory_saved placeholder
│       │   ├── cli.py              # cli_header_displayed hook
│       │   └── pr_status_sync.py   # PR → prax status sync
│       └── watchers/
│           └── log_watcher.py      # System log watcher (system_logs/ dir)
├── tests/                          # 551 tests across 18 modules
├── trigger_json/                   # Runtime state files
│   ├── trigger_config.json         # Medic state, muted branches
│   ├── error_registry.json         # All tracked errors
│   └── trigger_cb_state.json       # Circuit breaker persistence
└── trigger_data.json               # Log watcher positions + dedup hashes
```

## Data Safety

- **Atomic writes:** All JSON state files use `config.atomic_write_json()` — writes to a temp file in the same directory, then `os.replace()` for atomic rename. No partial writes on crash.
- **File locking:** All read-modify-write cycles wrapped in `config.json_file_lock()` using `fcntl.flock` with `.lock` sidecar files. Prevents concurrent corruption from watcher + CLI.
- **Circuit breaker persistence:** Trip state, recent errors, per-fingerprint tracking all survive restarts via `trigger_cb_state.json`.

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

551 tests across 18 test modules, all passing. Coverage: 76/76 public functions (100%).

```bash
cd src/aipass/trigger && pytest    # Run all tests
```

Test files: `test_core`, `test_errors`, `test_medic`, `test_error_registry`, `test_error_reporter`, `test_medic_state`, `test_log_watcher`, `test_watchers_log_watcher`, `test_branch_log_events`, `test_log_events`, `test_json_handler`, `test_pr_status_sync`, `test_error_detected`, `test_event_handlers`, `test_log_watcher_service`, `test_plan_file_handler`, `test_startup_handler`, `test_trigger_entry`

## Compliance

Seedgo: 100% (34/34 standards). Zero type errors. All categories at 100%.

---

*Last Updated: 2026-05-16*

---
[← Back to AIPass](../../../README.md)
