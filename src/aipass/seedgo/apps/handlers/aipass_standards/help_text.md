# Help Text Standards
**Status:** Draft v1
**Date:** 2026-03-22

---

## What It Is

The help text standard ensures that all user-facing string literals in AIPass code direct users to run commands via `drone @branch`, never via `python3 path/to/script.py`. AIPass is a pip package -- all execution goes through drone entry points.

---

## Why It Matters

When help text tells a user to run `python3 flow.py create`, it bypasses the standard entry point architecture. Drone handles `@` resolution, path routing, and consistent CLI behavior. Direct python3 invocations break this contract and confuse users who may not have the correct working directory or Python environment.

---

## What the Checker Scans For

The checker reads each Python file and scans **string literals in code** (both single-line and multiline/triple-quoted) for instructional references to `python3` or `python` as a command invocation. A docstring is prose, not help text, and is never read.

**Detected patterns:**
- `python3 some/script.py` inside string literals
- `python -m module` inside string literals
- `python -c "code"` inside string literals
- References inside triple-quoted help text (a string literal in code)

**Ignored (not flagged):**
- Shebangs (`#!/usr/bin/env python3`)
- Comment lines (`# python3 ...`)
- Docstrings (the first-statement string of a module, class or function)
- Non-instructional references (e.g., "python version", "python interpreter")
- `__init__.py` files (always skipped)

---

## Code Examples

### Violation

```python
# BAD -- tells user to run python3 directly
help_msg = "Run: python3 tools/scanner.py --check"
print("Usage: python3 flow.py create plan_name")
description = "Execute python -m aipass.seedgo"
```

### Fix

```python
# GOOD -- uses drone entry point
help_msg = "Run: drone @seedgo scan --check"
print("Usage: drone @flow create plan_name")
description = "Execute drone @seedgo"
```

---

## Scoring

- **Scope:** `AUDIT_SCOPE = "all_files"` -- checks every `.py` file individually
- **Checks per file:** 1 (help text references)
- **Score 100:** No violations found
- **Score 0:** One or more violations found
- **Failure message:** Reports the count and first 3 offending line numbers (plus overflow count)
- **Overall pass threshold:** 75%

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `help_text` standard for a file
- **File-level bypass:** Match by file path substring
- **Line-level bypass:** Skip specific line numbers within a file

Example bypass rule:
```json
{
    "standard": "help_text",
    "file": "legacy_helper.py",
    "lines": [42, 58]
}
```

---

## Reference

- **Checker:** `help_text_check.py`
- **Scope:** `all_files`
- **Entry point:** `check_module(module_path, bypass_rules)`
- **Standard label:** `HELP_TEXT`
