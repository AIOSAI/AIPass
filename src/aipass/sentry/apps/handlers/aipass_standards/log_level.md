# Log Level Hygiene Standards
**Status:** Active v1
**Date:** 2026-02-13
**Last Major Update:** 2026-02-13

---

## What This Covers

Correct usage of Python log levels to ensure ERROR means real system failure, WARNING means user input issues, and monitoring systems (Medic v2) can trust log severity.

---

## The Standard

### ERROR - System Failures Only

Reserved for situations where the system itself has broken. These trigger Medic v2 alerts.

```python
# CORRECT - real system failures
logger.error(f"Failed to connect to database: {e}")
logger.error(f"Import failed: {e}")
logger.error(f"File I/O error: {e}")
logger.error(f"Unhandled exception in handler: {e}")
logger.error(f"Timeout waiting for response: {e}")
```

**ERROR-worthy events:**
- Crashes and unhandled exceptions
- Timeouts and connection failures
- Import failures and missing dependencies
- File I/O errors (disk full, permission denied)
- Internal state corruption

### WARNING - User Input Errors

For when the user typed something wrong. Not a system failure - the system handled it correctly by rejecting bad input.

```python
# CORRECT - user input issues
logger.warning(f"Unknown command: {command}")
logger.warning(f"No module handled command: {args.command}")
logger.warning(f"Invalid argument: {arg}")
logger.warning(f"Plan not found: {plan_id}")
logger.warning(f"Unrecognized option: {option}")
```

**WARNING-worthy events:**
- Unknown or unrecognized commands
- Invalid arguments or bad syntax
- Missing required arguments
- Command routing failures (no module handled)
- User typos

### INFO - Normal Operations

```python
# CORRECT - business as usual
logger.info(f"Module discovered: {module_name}")
logger.info(f"Service started on port {port}")
logger.info(f"Configuration loaded from {config_path}")
logger.info(f"Backup completed: {file_count} files")
```

---

## Common Violations

### Using ERROR for Unknown Commands

```python
# BAD - unknown command is user input, not system failure
logger.error(f"Unknown command: {command}")

# GOOD - user typed wrong thing, system handled it fine
logger.warning(f"Unknown command: {command}")
```

### Using ERROR for Command Routing Failures

```python
# BAD - no module handling a command means user typed wrong thing
logger.error(f"No module handled command: {args.command}")

# GOOD - this is a warning, not an error
logger.warning(f"No module handled command: {args.command}")
```

### Using ERROR for Invalid Arguments

```python
# BAD - bad user input isn't a system error
logger.error(f"Invalid argument: {arg}")

# GOOD
logger.warning(f"Invalid argument: {arg}")
```

---

## Why This Matters

Medic v2 uses push-based error detection that monitors ERROR-level log entries to detect real system issues. If user typos trigger ERROR, Medic sees noise instead of signal.

**Clean log levels = accurate error detection = healthier system.**

| Level | Means | Medic Response | Example |
|-------|-------|----------------|---------|
| ERROR | System broke | Alert/investigate | Database connection failed |
| WARNING | User issue | Ignore | Unknown command typed |
| INFO | Normal | Ignore | Module discovered |

---

## Automated Checker

The `log_level_check.py` checker validates two things:

1. **ERROR reserved for system failures** - Detects `logger.error()` calls containing user-input patterns like "unknown command", "invalid argument", "unrecognized", etc.

2. **Command routing uses WARNING** - In files with command routing logic (`route_command`, `handle_command`, `args.command`), verifies that routing failures use WARNING not ERROR.

The checker uses AST-aware docstring tracking to avoid false positives from code examples in docstrings.

---

## Decision Record

| Date | Decision | By | Status |
|------|----------|----|--------|
| 2026-01-31 | ERROR vs WARNING distinction approved | User | Active |
| 2026-02-13 | Automated checker created | Sentry | Active |

---

*Part of AIPass Code Standards - maintained by Sentry branch*
