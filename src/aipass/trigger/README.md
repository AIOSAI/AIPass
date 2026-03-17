# Trigger

**Purpose:** Event bus for AIPass. Branches fire events, registered handlers react. Decouples producers from consumers — the module that detects a condition doesn't need to know what should happen next.
**Module:** `aipass.trigger`
**Last Updated:** 2026-03-17

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
Trigger.fire("plan_created", plan_id=42, branch="flow")

# Register a handler
def on_plan_created(**data):
    print(f"Plan {data['plan_id']} created")

Trigger.on("plan_created", on_plan_created)

# Remove a handler
Trigger.off("plan_created", on_plan_created)
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

| Event | Fired when |
|-------|------------|
| `startup` | Branch session starts |
| `plan_created` | New flow plan created |
| `plan_closed` | Flow plan closed |
| `error_logged` | Error detected in logs |
| `error_detected` | Error registered and ready for dispatch |
| `warning_logged` | Warning detected in logs |
| `memory_threshold_exceeded` | Memory file approaching line limit |
| `memory_template_updated` | Memory template changed |
| `bulletin_created` | New system bulletin posted |

## Medic

Built-in error monitoring subsystem. Watches logs for errors, fingerprints them via SHA1, deduplicates, and dispatches fix-it notifications to the responsible branch. Includes circuit breaker, per-branch rate limiting, and mute controls.

## Architecture

```
trigger/
├── apps/
│   ├── trigger.py             # Entry point (auto-discovers modules)
│   ├── modules/
│   │   ├── core.py            # Event bus (Trigger.fire/on/off)
│   │   ├── errors.py          # Error registry + cross-branch API
│   │   ├── medic.py           # Error monitoring commands
│   │   ├── branch_log_events.py  # Branch-level log event handling
│   │   └── log_events.py     # System-wide log event processing
│   └── handlers/
│       └── events/            # One handler per event type
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

*Last Updated: 2026-03-17*
