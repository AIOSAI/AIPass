# Commented Logger Standard
**Status:** Draft v1
**Date:** 2026-03-22

---

## What This Standard Is

Commented-out logger calls are dead logging. Lines like `# logger.info(...)` or `# logger.error(...)` indicate intentionally disabled logging that should either be restored or removed entirely. Dead logging is noise -- it clutters the codebase, confuses readers about what is actually being logged, and suggests incomplete cleanup.

---

## Why It Matters

- **Noise reduction:** Commented-out code obscures real code. Every commented logger call is a line a developer or AI must read and mentally skip.
- **Intent ambiguity:** Was the logging disabled temporarily? Permanently? By accident? The comment gives no answer.
- **Maintenance debt:** Commented code rots. The surrounding code changes, making the commented call incorrect if it were ever uncommented.
- **Clean signal:** Active logger calls should be the only logger calls in the file. If something is worth logging, log it. If not, delete the line.

---

## What the Checker Scans For

The checker uses a regex to detect lines matching:

```
# logger.error(...)
# logger.warning(...)
# logger.warn(...)
# logger.info(...)
# logger.debug(...)
# logger.critical(...)
# logger.exception(...)
```

The pattern: `#\s*logger\.(error|warning|warn|info|exception|critical|debug)\s*\(`

### Exclusions

- **Docstrings:** Docstring lines, read from the parse tree, and the body lines of a multi-line string literal are skipped. Documented examples inside docstrings do not trigger false positives.
- **`__init__.py`:** Package init files are skipped entirely.
- **Non-.py files:** Only `.py` files are scanned.

---

## Code Examples

### Violation

```python
def process_data(items):
    # logger.info("Starting processing")     # <-- VIOLATION
    for item in items:
        result = transform(item)
        # logger.debug(f"Transformed: {result}")  # <-- VIOLATION
    # logger.error("This should not happen")  # <-- VIOLATION
    return results
```

### Fix -- Restore the Logging

```python
def process_data(items):
    logger.info("Starting processing")
    for item in items:
        result = transform(item)
        logger.debug(f"Transformed: {result}")
    return results
```

### Fix -- Remove Entirely

```python
def process_data(items):
    for item in items:
        result = transform(item)
    return results
```

---

## Scoring

- **Check:** One check per file -- "Commented logger calls"
- **Pass:** Zero commented-out logger calls found
- **Fail:** Any commented-out logger calls detected. The violation message reports the count and first three line numbers (e.g., `3 commented-out logger call(s) on lines 42, 78, 115`)
- **Score:** 100 if passed, 0 if failed
- **Threshold:** Score >= 75 to pass overall

---

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{
    "standard": "commented_logger",
    "file": "path/to/file.py"
}
```

Bypassed files return score 100 automatically.

---

## Audit Scope

`AUDIT_SCOPE = "all_files"` -- the checker runs against every `.py` file in the branch, not just the entry point.

---

## Reference

- Checker: `commented_logger_check.py`
- Standards pack: seedgo standards (commented_logger)
