# Log Structure Standard

**Standard:** LOG_STRUCTURE
**Created:** 2026-03-06
**Version:** 1.1.0

---

## Purpose

AIPass follows a hierarchical log placement model: every directory containing `.py` code must have a sibling `logs/` directory. This keeps logs co-located with the code that produces them, enabling fast debugging without hunting across the filesystem.

Additionally, no hardcoded absolute paths should appear in logging configuration. All log paths must be relative or handled automatically by prax's `system_logger`.

## The Rules

### REQUIRED

1. **Sibling `logs/` directory** -- Every directory containing `.py` files must have a `logs/` directory at the same level
2. **No hardcoded absolute log paths** -- No `"/home/..."`, `"/tmp/..."`, `"/var/..."` paths pointing to `.log` files in source code
3. **No `/home/` references in log config** -- No `/home/username` patterns in logging-related lines

### DUAL LOGGING MODEL

AIPass uses two complementary log locations:

1. **`system_logs/`** at repo root -- Central aggregation using `{branch}_{module}.log` naming
2. **`logs/`** at every code level -- Hierarchical local placement, sibling to code directories

## Hierarchical Directory Pattern

```
src/aipass/{branch}/
  logs/                          <-- branch root logs
  apps/
    logs/                        <-- entry point level
    modules/
      logs/                      <-- module level
    handlers/
      logs/                      <-- handler root
      dispatch/
        logs/                    <-- sub-handler level
      email/
        logs/                    <-- sub-handler level
```

Every level with `.py` files gets its own `logs/` directory. Logs live where the code lives.

## Examples

### BAD

```python
# WRONG: All logs dumped at branch root only -- no hierarchy
LOG_DIR = Path(__file__).resolve().parents[3] / 'logs'
# All handlers write to branch/logs/ -- flat, no locality

# WRONG: Hardcoded absolute paths
path = '/home/user/aipass/system_logs/module.log'
path = Path.home() / 'logs' / 'module.log'
```

### GOOD

```python
# CORRECT: Use prax's system_logger (auto-routes to correct location)
from aipass.prax.apps.modules.logger import system_logger
system_logger.info('message')  # prax handles hierarchical placement

# ALSO CORRECT: Manual relative path to sibling logs/
LOG_DIR = Path(__file__).resolve().parent / 'logs'
log_path = LOG_DIR / 'my_handler.log'
```

## How It's Scored

The checker runs 3 checks against each file. The score is the percentage of checks passed (0-100).

| Check | What it validates |
|-------|-------------------|
| **Hierarchical logs/ directory** | A `logs/` directory exists as a sibling of the file's parent directory |
| **No hardcoded log paths** | No absolute paths (`/home/`, `/tmp/`, `/var/`, `/etc/`) pointing to `.log` files |
| **No /home/ in log config** | No `/home/username` patterns in lines containing "log" or "LOG" |

- **100** -- All 3 checks pass
- **66** -- 2 of 3 pass
- **33** -- 1 of 3 passes
- **0** -- All checks fail or file not found

Files can be exempted via `.seedgo/bypass.json` using the `log_structure` standard key.

## Checker

**File:** `src/aipass/seedgo/apps/handlers/aipass_standards/log_structure_check.py`

Checks:
1. Parent directory of file has a sibling `logs/` directory (hierarchical placement)
2. No hardcoded absolute log paths (`/home/`, `/tmp/`, `/var/`, `/etc/` to `.log`)
3. No `/home/` references in logging configuration lines

## Reference

- **Prax logger:** `src/aipass/prax/apps/modules/logger.py`
- **Hierarchical resolver:** `src/aipass/prax/apps/handlers/config/load.py`
