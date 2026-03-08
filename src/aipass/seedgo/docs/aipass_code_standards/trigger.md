# Trigger Standards
**Status:** Draft v1
**Date:** 2025-12-04

---

## The Event Bus Pattern

AIPass uses a centralized event system to replace scattered cross-branch function calls:

```
Before (hardcoded):
    flow/close_plan.py → directly calls → dashboard/update_local()
    flow/close_plan.py → directly calls → mbank/process_closed_plans()
    prax/logger.py → directly calls → memory/check_and_rollover()

After (event-driven):
    flow/close_plan.py → trigger.fire('plan_closed') → handlers respond
    prax/logger.py → trigger.fire('startup') → handlers respond
```

**WHY:** Without events, every cross-branch integration is a hardcoded import. Add a new reaction? Edit the source file. Change behavior? Find all callers. Remove a feature? Hunt through imports. Events decouple action from reaction.

**Result:** Branches fire events for their lifecycle transitions. Trigger owns all cross-branch reaction logic. New handlers plug in without touching source branches.

---

## Core API

```python
from aipass.trigger import trigger

# Fire an event (branches do this)
trigger.fire('event_name', **data)

# Register a handler (only in trigger/apps/handlers/events/)
trigger.on('event_name', handler_function)

# Check what's registered
trigger.status()  # Returns {'startup': 1, 'plan_closed': 2, ...}
```

---

## Import Patterns

### Standard Import (Most Modules)
```python
from aipass.trigger import trigger

def some_function():
    trigger.fire('event_name', key=value)
```

### Lazy Import (Avoid Circular Dependencies)
```python
# Use when importing at module level causes circular import
_trigger = None
_trigger_loaded = False

def _ensure_trigger():
    global _trigger, _trigger_loaded
    if not _trigger_loaded:
        _trigger_loaded = True
        try:
            from aipass.trigger.apps.modules.core import trigger as t
            _trigger = t
        except ImportError:
            pass  # Trigger not available, silent fallback

def fire_event(name, **data):
    _ensure_trigger()
    if _trigger:
        _trigger.fire(name, **data)
```

**Current Lazy Loaders:**
- `prax/apps/modules/logger.py` - Fires `startup`
- `cli/apps/modules/display.py` - Fires `cli_header_displayed`

---

## Event Naming Convention

**Format:** `{scope}_{action}` or just `{action}` for system-wide events

| Event Name | Scope | Meaning |
|------------|-------|---------|
| `startup` | system | First logger use, system initializing |
| `plan_created` | flow | New PLAN file created |
| `plan_closed` | flow | PLAN marked as closed |
| `memory_saved` | memory | Memory file updated |
| `backup_completed` | backup | Backup operation finished |
| `cli_header_displayed` | cli | Header printed to console |

**Rules:**
- All lowercase
- Underscore-separated words
- Past tense for completed actions (`created`, `closed`, `saved`)
- Present tense for ongoing states (`displayed`, `running`)

---

## Handler Requirements

Handlers live in `src/aipass/trigger/apps/handlers/events/`

### Handler Interface
```python
def handle_{event_name}(**kwargs) -> None:
    """
    Process event. Must be silent - no prints, no logger.

    Args:
        **kwargs: Event data passed from fire() call
    """
    # Do work silently
    pass
```

### Critical Rules

1. **NO LOGGER IMPORTS**
   ```python
   # FORBIDDEN - causes infinite recursion
   from aipass.prax.apps.modules.logger import system_logger

   # Logger calls trigger → trigger calls handler → handler calls logger → loop
   ```

2. **NO PRINT STATEMENTS**
   ```python
   # FORBIDDEN - handlers must be silent
   print("Handling event...")

   # Events are logged by trigger.fire() in core.py automatically
   ```

3. **SILENT FAILURE**
   ```python
   # CORRECT - catch and continue
   try:
       do_something()
   except Exception:
       pass  # Silent - can't log, can't print

   # WRONG - re-raises or logs
   except Exception as e:
       logger.error(f"Failed: {e}")  # NO!
   ```

### Registering Handlers

All handlers registered in `src/aipass/trigger/apps/handlers/events/registry.py`:

```python
from aipass.trigger.apps.modules.core import trigger
from .startup import handle_startup
from .flow import handle_plan_created, handle_plan_closed

def setup_handlers():
    """Wire all event handlers - called on first trigger.fire()"""
    trigger.on('startup', handle_startup)
    trigger.on('plan_created', handle_plan_created)
    trigger.on('plan_closed', handle_plan_closed)
```

---

## When to Fire Events

### DO Fire Events For:

1. **Lifecycle Transitions**
   - Startup/shutdown
   - Plan create/close
   - Backup start/complete

2. **Cross-Branch Side Effects**
   - Dashboard updates after plan changes
   - Memory Bank rollover checks on startup
   - Email notifications on errors

3. **State Changes Other Branches Care About**
   - Memory file saved (for rollover monitoring)
   - Module discovered (for registry updates)

### DON'T Fire Events For:

1. **Internal Operations**
   - Function calls within same module
   - Handler-to-handler communication within same branch

2. **High-Frequency Operations**
   - Every log message
   - Every file read
   - Per-line processing

3. **Simple Return Values**
   - If caller needs the result, use function call not event

---

## Replacing Hardcoded Patterns

### Before: Direct Cross-Branch Calls
```python
# flow/close_plan.py - WRONG
from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
from aipass.flow.apps.handlers.mbank.process import process_closed_plans

def close_plan():
    # ... close logic ...
    update_dashboard_local()  # Hardcoded
    process_closed_plans()    # Hardcoded
```

### After: Event-Driven
```python
# flow/close_plan.py - CORRECT
from aipass.trigger import trigger

def close_plan():
    # ... close logic ...
    trigger.fire('plan_closed', plan_number=num, subject=subj)
    # Dashboard and mbank handlers respond automatically
```

```python
# trigger/apps/handlers/events/flow.py - Handlers
def handle_plan_closed(**kwargs):
    """React to plan closure"""
    from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
    from aipass.flow.apps.handlers.mbank.process import process_closed_plans

    update_dashboard_local()
    process_closed_plans()
```

---

## Bypass Configuration

Some cross-branch handler imports are intentional in Trigger. Configure in `.seedgo/bypass.json`:

```json
{
  "bypass": [
    {
      "file": "apps/handlers/events/startup.py",
      "standard": "encapsulation",
      "lines": [38],
      "reason": "Trigger's purpose is centralizing cross-branch calls. Memory Bank has no modules API."
    }
  ]
}
```

**Trigger is the ONE place cross-branch handler imports are acceptable** - it's literally the centralization point for these calls.

---

## Design Principles

1. **Auto-Initialization**
   - Handlers register on first `fire()` call
   - No setup required by calling branches
   - Lazy loading prevents import-time issues

2. **Recursion Guard**
   - `_firing` flag prevents logger→trigger→logger loops
   - If already firing, new fire() calls are ignored

3. **Caller Introspection**
   - `trigger.fire()` logs which branch fired the event
   - Uses `inspect.stack()` to identify caller
   - Example log: `[TRIGGER] prax fired: startup`

4. **Graceful Degradation**
   - If Trigger not available, imports fail silently
   - Branches continue to work without events
   - No hard dependencies on Trigger existing

---

## Detected Pattern Categories (10)

The trigger checker (`trigger_check.py v1.0.0`) detects these event-worthy patterns:

### Function Definitions (Patterns 1-9)

1. **FileSystemEventHandler Methods**
   - `on_created`, `on_deleted`, `on_modified`, `on_moved`
   - Watchdog event handlers that should fire events

2. **Lifecycle Functions**
   - `create_*`, `close_*`, `delete_*`, `restore_*`
   - State transitions that other branches may care about

3. **Messaging Functions**
   - `deliver_*`, `send_*`
   - Outbound communication that may need tracking

4. **State Change Functions**
   - `mark_as_*`, `archive_*`
   - Status updates worth broadcasting

5. **Registry Functions**
   - `save_registry`, `ping_registry`, `sync_*registry`
   - Registry mutations that affect system state

6. **Central Functions**
   - `update_central`, `write_central_*`, `push_to_central`, `aggregate_central`
   - Central data updates that cascade to dashboards

7. **Repair/Recovery Functions**
   - `auto_close_*`, `recover_*`, `heal_*`
   - Self-healing operations worth logging

8. **Cleanup/Backup Functions**
   - `cleanup_*`, `backup_*`
   - Maintenance operations with system-wide impact

9. **System Lifecycle Functions**
   - `initialize_*_system`, `shutdown_*_system`
   - System-level lifecycle events

### Inline Operations (Pattern 10)

10. **Filesystem Method Calls**
    - `.unlink()` - File deletion inline
    - `.rename()` - File move/rename inline
    - These are NOT function definitions but method calls that modify filesystem

**Note:** Pattern 10 catches inline operations that may be buried in code, not explicit function names. Even cleanup operations like `temp_file.unlink()` are detected - decide at review time whether to fire events or bypass.

---

## Current Integration Status

| Branch | Integration | Events |
|--------|-------------|--------|
| Prax | `trigger.fire('startup')` in logger.py | startup |
| CLI | `trigger.fire('cli_header_displayed')` in display.py | cli_header_displayed |
| Flow | JSON logging only | needs migration |
| Drone | No events | ready to adopt |
| Backup | No events | needs events |
| AI_Mail | Watchdog file watcher | partial |

---

## Compliance Checklist

For branches using Trigger:

- [ ] Import pattern correct (`from aipass.trigger import trigger` or lazy-load)
- [ ] Events named correctly (lowercase, underscore, past tense)
- [ ] Handlers have no logger imports
- [ ] Handlers have no print statements
- [ ] Handlers registered in registry.py
- [ ] Cross-branch reactions moved from source to handlers

For Trigger branch itself:

- [ ] Handler import guard active (blocks external access)
- [ ] Recursion guard in fire()
- [ ] Caller introspection logging
- [ ] Bypass.json documents intentional encapsulation violations

---

## Reference

- **Trigger Core:** `src/aipass/trigger/apps/modules/core.py`
- **Handler Registry:** `src/aipass/trigger/apps/handlers/events/registry.py`
- **Event Handlers:** `src/aipass/trigger/apps/handlers/events/*.py`
- **Standard:** `src/aipass/seedgo/docs/aipass_code_standards/trigger.md`
