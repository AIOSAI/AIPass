# Shebang Standard
**Status:** Active v1
**Date:** 2026-03-09

---

## Core Rule: No Shebangs in pip-installable Packages

AIPass is a pip-installable package. All execution goes through `pyproject.toml` entry points or `python3 -m`. Shebang lines (`#!/...`) are unnecessary and must not appear in any `.py` file.

---

## Why Shebangs Are Wrong for AIPass

**What a shebang does:**
```python
#!/usr/bin/env python3
```
This tells the OS kernel which interpreter to use when executing the file directly (e.g., `./script.py`). It's designed for standalone scripts.

**Why AIPass doesn't need them:**
1. **pip entry points handle execution** - `pyproject.toml` defines CLI commands that resolve to Python functions. The package manager handles interpreter selection.
2. **`python3 -m` handles module execution** - Running modules through the Python interpreter doesn't use shebangs.
3. **No files are executed directly** - Nobody runs `./sentry.py`. They run `sentry` (entry point) or `python3 -m aipass.sentry`.
4. **They're noise** - A line that does nothing but takes up space in every file.
5. **They can mislead** - Suggests the file is a standalone script when it's a module in a package.

---

## What the Checker Validates

The shebang standard checks **one thing**: does line 1 of a Python file start with `#!`?

- **Scope:** `AUDIT_SCOPE = "all_files"` -- every `.py` file is checked
- **Pass:** Line 1 does NOT start with `#!` → score 100
- **Fail:** Line 1 starts with `#!` → score 0

---

## Examples

**Good -- no shebang:**
```python
# =================== AIPass ====================
# Name: sentry.py
# Description: Sentry Entry Point
...
```

**Good -- comment on line 1 that isn't a shebang:**
```python
# This module handles plan creation
```

**Bad -- shebang on line 1:**
```python
#!/usr/bin/env python3
# =================== AIPass ====================
...
```

**Bad -- any shebang variant:**
```python
#!/usr/bin/python3
```
```python
#!/usr/bin/python
```

---

## Scoring

| Condition | Score |
|-----------|-------|
| No shebang on line 1 | 100 |
| Shebang found on line 1 | 0 |
| File not found | 0 |
| File not readable | 0 |
| Bypassed via `.sentry/bypass.json` | 100 |

Binary pass/fail -- there is no partial credit. Either the file has a shebang or it doesn't.

---

## How to Fix

Remove the shebang line. That's it.

**Before:**
```python
#!/usr/bin/env python3
# =================== AIPass ====================
# Name: example.py
```

**After:**
```python
# =================== AIPass ====================
# Name: example.py
```

---

## Bypass

If a file genuinely needs a shebang (edge case -- scripts outside the pip package), add a bypass rule in `.sentry/bypass.json`:

```json
{
  "standard": "shebang",
  "file": "path/to/script.py"
}
```

---

## Summary

1. **No shebangs** -- AIPass is pip-installed, not script-executed
2. **All `.py` files checked** -- scope is `all_files`
3. **Binary scoring** -- 100 (no shebang) or 0 (shebang found)
4. **Fix is simple** -- delete line 1 if it starts with `#!`
