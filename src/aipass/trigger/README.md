# Trigger

**Purpose:** Event bus for AIPass. Branches fire events, registered handlers react. Decouples producers from consumers — the module that detects a condition doesn't need to know what should happen next.
**Module:** `aipass.trigger`
**Last Updated:** 2026-03-29

## Commands / Usage

```bash
drone @trigger fire <event> [data]              # Fire an event
drone @trigger list                             # List registered events
drone @trigger status                           # Event bus status
drone @trigger --help                           # Full help
```

## Usage

### CLI (via drone)

```bash
drone @trigger --help                    # Show available commands
drone @trigger medic on                  # Enable error auto-dispatch
drone @trigger medic off                 # Disable error auto-dispatch
drone @trigger medic status              # Show medic state
drone @trigger medic mute @branch        # Suppress errors from a branch
drone @trigger medic unmute @branch      # Resume errors from a branch
drone @trigger errors list               # List tracked errors
drone @trigger errors stats              # Error registry statistics
drone @trigger errors circuit-breaker    # Circuit breaker state
drone @trigger --version                 # Show version
```

### Python API

```python
from aipass.trigger.apps.modules.core import Trigger

# Fire an event — all registered handlers run
Trigger.fire("plan_file_created", path="/path/to/FPLAN-0042.md")

# Register a handler
def on_plan_file_created(**data):
    print(f"Plan created at {data['path']}")

Trigger.on("plan_file_created", on_plan_file_created)

# Remove a handler
Trigger.off("plan_file_created", on_plan_file_created)
```

### Cross-branch error reporting

```python
from aipass.trigger.apps.modules.errors import report_error

result = report_error(
    branch="api",
    error_type="ConnectionError",
    message="Timeout reaching upstream",
    source_file="client.py",
)
# Returns: {"is_new": True, "fingerprint": "abc123", "count": 1, ...}
```

## Events

12 events registered via `handlers/events/registry.py`. All fire through `Trigger.fire()`.

| Event | Handler | Fired when | Action |
|-------|---------|------------|--------|
| `startup` | `startup.py` | Branch session starts | Error catch-up scan, memory rollover check |
| `error_detected` | `error_detected.py` | Error registered in log watcher (Medic v2) | 8-gate dispatch pipeline, sends fix-it email to affected branch |
| `error_logged` | `error_logged.py` | Error detected in system logs (legacy) | Rate-limited notification with medic gating |
| `warning_logged` | `warning_logged.py` | Warning detected in system logs | Logged for monitoring, no dispatch |
| `plan_file_created` | `plan_file.py` | New PLAN file detected in filesystem | Updates Flow's PLAN_REGISTRY.json |
| `plan_file_deleted` | `plan_file.py` | PLAN file removed from filesystem | Marks plan as deleted in registry |
| `plan_file_moved` | `plan_file.py` | PLAN file moved or renamed | Updates registry location |
| `bulletin_created` | `bulletin_created.py` | New system bulletin posted | Propagates to all branch dashboards |
| `memory_threshold_exceeded` | `memory_threshold_exceeded.py` | Memory file approaches line limit (600 lines) | Sends compression notification to branch |
| `memory_template_updated` | `memory_template_updated.py` | Memory template modified | Pushes template updates to branches |
| `memory_saved` | `memory.py` | Memory file saved | Placeholder for future rollover trigger |
| `cli_header_displayed` | `cli.py` | CLI displays headers | Registration hook |

## Medic

Built-in error monitoring subsystem. Watches logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch. Includes circuit breaker, per-branch rate limiting, and mute controls.

## Architecture

```
trigger/
├── apps/
│   ├── trigger.py             # Entry point (auto-discovers modules)
│   ├── log_watcher_service.py # Persistent watcher process (systemd)
│   ├── modules/
│   │   ├── core.py            # Event bus (Trigger.fire/on/off)
│   │   ├── errors.py          # Error registry + cross-branch API
│   │   ├── medic.py           # Error monitoring commands
│   │   ├── branch_log_events.py  # Branch-level log event handling
│   │   └── log_events.py     # System-wide log event processing
│   └── handlers/
│       ├── events/            # One handler per event type
│       ├── log_watcher.py     # Branch log watcher (watchdog)
│       ├── error_registry.py  # SHA1 fingerprinting + circuit breaker
│       ├── error_reporter.py  # Cross-branch error API
│       └── medic_state.py     # Medic persistence (trigger_config.json)
└── tests/
```

**Note:** `branch_log_events` and `log_events` are auto-discovered modules that handle log-based event detection at branch and system levels respectively.

---

## Integration Points

### Depends On
- `aipass.prax` — Logging via `system_logger`
- `aipass.cli` — Console output and header formatting
- Python stdlib (`sys`, `pathlib`, `importlib`)

### Provides To
- All modules — event bus (`Trigger.fire`, `Trigger.on`, `Trigger.off`)
- All modules — cross-branch error reporting (`report_error`)
- All modules — medic error monitoring and dispatch

---

*Last Updated: 2026-03-29*
