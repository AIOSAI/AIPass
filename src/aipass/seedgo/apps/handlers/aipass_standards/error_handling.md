# Error Handling Standards
**Status:** v1.0 — Consolidated from testing standard
**Date:** 2026-03-27

---

## What It Is

The error handling standard validates that try/except blocks handle errors meaningfully. Silent failures (`except: pass`) hide bugs and erode trust in the codebase.

Previously named "testing" — renamed for clarity. This checker has nothing to do with tests. It checks error handling patterns in production code.

---

## What the Checker Scans For

This is a **file-level** checker (`AUDIT_SCOPE = "all_files"`) that runs on every Python file.

### Detection Logic

1. Counts `try:` blocks in the file
2. If no try/except blocks exist → not applicable (100%)
3. Scans for silent failure patterns:
   - `except: pass`
   - `except Exception: pass`
   - Any except block where the only statement is `pass`
4. Tracks docstrings to avoid false positives in string content

### What Counts as Silent

An except block is "silent" if:
- The only non-comment statement after `except ...:` is `pass`
- No logging, no return, no re-raise, no other statements

---

## Code Examples

### Violation

```python
try:
    result = api_call()
except:
    pass  # Silent failure — error swallowed
```

### Fix

```python
try:
    result = api_call()
except Exception as e:
    logger.error(f"API call failed: {e}")
    return {"success": False, "error": str(e)}
```

---

## Error Handling Philosophy

**Fix error handling BEFORE fixing bugs.**

If errors lie, you can't debug effectively. The debug cycle:
1. Fix error handling — make errors tell the truth
2. Then fix the actual bug
3. See clean pass with honest outputs

---

## Scoring

- **Scope:** `AUDIT_SCOPE = "all_files"` — runs on every Python file via `check_module()`
- **Score formula:** `passed_checks / total_checks * 100`
- **No try/except blocks:** Score = 100 (not applicable)
- **Overall pass threshold:** 75%

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `error_handling` standard for a file
- **File-level bypass:** Match by file path substring
- **Line-level bypass:** Skip specific lines

Example bypass rule:
```json
{
    "standard": "error_handling",
    "file": "legacy_module.py",
    "reason": "Legacy code — silent catches are intentional during migration"
}
```

---

## History

- Renamed from `testing` to `error_handling` (2026-03-27)
- The `check_test_functions()` feature was removed (redundant with test_quality standard)
- Original checker focused on two things: error handling + test function presence
- Now focused solely on error handling, which is what it actually checks

---

## Reference

- **Checker:** `error_handling_check.py`
- **Scope:** `all_files`
- **Entry point:** `check_module(module_path, bypass_rules)`
- **Standard label:** `ERROR_HANDLING`
