# Log Visibility Standard

**Category:** Logging
**Created:** 2026-02-27
**Checker:** `log_visibility_check.py`

---

## Purpose

ALL Python files (modules, handlers, entry points) MUST use prax `system_logger` so their logs appear in `system_logs/` and are visible to Prax monitor. Raw `logging.getLogger()` creates local log files that are invisible to system-wide monitoring. One logging system everywhere — Prax.

## The Problem

Audit found **92 local log files** with no `system_logs/` mirror — completely invisible to Prax monitor. Root cause: modules importing `logging` and calling `logging.getLogger()` instead of importing from `prax.apps.modules.logger`.

When any file uses raw `logging.getLogger()`:
- Logs write only to branch-local `logs/` directory
- Prax monitor never sees them (it watches `system_logs/`)
- Errors, warnings, and anomalies go undetected
- System observability has blind spots

## The Rules

### PROHIBITED

- Using `logging.getLogger()` in ANY file without also importing prax `system_logger`
- Creating loggers that only write to local `logs/` directories
- Any logging setup that bypasses Prax dual-handler (local + system_logs)

### REQUIRED

- Import prax system_logger: `from aipass.prax.apps.modules.logger import system_logger as logger`
- Use `system_logger` for ALL logging — modules, handlers, entry points
- If `logging.getLogger()` is needed for specific purposes, the prax import must also be present

### EXEMPT

- **Prax logging infrastructure** — it IS the implementation (exempt from both checks)
- **Test files** — test isolation (exempt from both checks)
- **Files with `.sentry/bypass.json` exceptions**

## Detection (Two-Check System v3.0.0)

### Check 1: Prax Import (ALL files — no handler exemption)
1. Scans for `logging.getLogger()` calls
2. If found, checks for `from aipass.prax.apps.modules.logger import`
3. If prax import is missing, flags as violation with line numbers
4. Applies to modules AND handlers — unified Prax logging everywhere

### Check 2: Local FileHandler (ALL files, no exemptions)
1. Scans for `logging.FileHandler()` creation
2. Checks surrounding context for `system_logs` path
3. If FileHandler writes to local paths (not system_logs/), flags as blind spot
4. No exemptions — creating a FileHandler to local logs is a visibility issue

## Examples

### Bad — Invisible to Prax

```python
import logging
logger = logging.getLogger(__name__)
logger.info("This only writes to local logs/")
```

### Good — Visible System-Wide

```python
from aipass.prax.apps.modules.logger import system_logger as logger
logger.info("Visible in Prax monitor and system_logs/")
```

### Acceptable — Both Present

```python
import logging
from aipass.prax.apps.modules.logger import system_logger as logger

# Raw logger for specific subprocess/library needs
subprocess_logger = logging.getLogger('subprocess')
# Prax logger for all application logging
logger.info("Application log — visible system-wide")
```

## Scoring

- **100%** — No violations found (no raw getLogger without prax, no local FileHandler)
- **0%** — Both checks fail (raw getLogger + local FileHandler)
- **50%** — One check passes, one fails
- **Pass threshold:** 75%

## Related Standards

- **log_handler** — Validates RotatingFileHandler usage (no raw FileHandler)
- **imports** — Validates import order and prax logger import pattern

---

*Part of AIPass Code Standards — maintained by sentry branch*
