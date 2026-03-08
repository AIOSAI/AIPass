# Log Handler Rotation Standard

**Standard:** LOG_HANDLER
**Created:** 2026-02-26
**Version:** 1.0.0

---

## Purpose

All logging in AIPass MUST use `RotatingFileHandler` via prax's `system_logger`. Raw `logging.FileHandler` and `logging.StreamHandler` are prohibited because they cause unbounded log growth that can crash the entire system infrastructure.

## The Rules

### PROHIBITED

1. **`logging.FileHandler()`** — No rotation capability, log files grow without bound
2. **`logging.StreamHandler()` alongside file logging** — Bypasses prax's centralized logging
3. **Any custom log handler setup writing to `system_logs/`** — Must go through prax

### REQUIRED

1. **Use prax system_logger** — `from aipass.prax.apps.modules.logger import system_logger as logger`
2. **All log output via logger methods** — `logger.info()`, `logger.warning()`, `logger.error()`
3. **Prax handles rotation automatically** — maxBytes + backupCount configured centrally

### EXEMPT

1. **Prax's own logging infrastructure** — It IS the RotatingFileHandler implementation
2. **Test files** — May set up temporary loggers for testing purposes

## Examples

### BAD

```python
# WRONG: Raw FileHandler — no rotation, grows forever
import logging
handler = logging.FileHandler('system_logs/my_service.log')
my_logger = logging.getLogger('my_service')
my_logger.addHandler(handler)

# WRONG: StreamHandler alongside file logging — bypasses prax
my_logger.addHandler(logging.StreamHandler())
my_logger.addHandler(logging.FileHandler(log_file))
```

### GOOD

```python
# CORRECT: Use prax system_logger (handles rotation automatically)
from aipass.prax.apps.modules.logger import system_logger as logger

logger.info("Operation completed successfully")
logger.warning("Invalid user input: %s", user_input)
logger.error("Connection failed: %s", error)
```

## Why This Matters

On 2026-02-26, the entire AIPass command infrastructure crashed because telegram bot logging used plain `FileHandler` instead of `RotatingFileHandler`. The result:

- **181,566 log lines** accumulated across telegram log files (~100K ERROR lines)
- **Error catchup scanner** tried to process 100K errors on every command startup
- **Python recursion limit hit** at 1000 levels deep, cascading `RecursionError`
- **Every `drone` command failed** — 30+ second hangs then crash

All other branches using prax's `system_logger` rotated correctly (verified: `.log.1` backups exist). The telegram bots were the only code bypassing prax. (Telegram integration has since been removed from AIPass.)

## Checker

**File:** `src/aipass/seedgo/apps/standards/aipass/handlers/standards/log_handler_check.py`

Checks:
1. No raw `logging.FileHandler()` usage
2. No raw `logging.StreamHandler()` alongside file-based logging
3. Prax logging infrastructure is automatically exempt
4. Files without log handler setup are automatically passed
