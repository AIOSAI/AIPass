# Debug Print Standard
**Status:** Draft v1
**Date:** 2026-03-22

---

## What This Standard Is

Bare `print()` calls have no place in production AIPass code. All output should use structured logging (Prax logger) or Rich console output (CLI service). `print()` is unstructured, unsearchable by log systems, and invisible to monitoring infrastructure.

---

## Why It Matters

- **Structured logging:** Prax logger provides levels (info, debug, warning, error), timestamps, and machine-readable output. `print()` provides none of this.
- **Rich output:** The CLI service provides consistent, formatted output across all branches. `print()` breaks visual consistency.
- **Monitoring:** Log aggregation and alerting systems cannot process bare print output.
- **Cleanup discipline:** `print()` calls often start as debug aids and never get removed. This standard catches them before they accumulate.

---

## What the Checker Scans For

The checker uses the regex `(?<![.#\w])print\(` to detect bare `print()` calls. This pattern specifically excludes method calls like `console.print()` or `logger.print()` because of the negative lookbehind.

### Exclusions

The following are **not** flagged:

| Exclusion | Reason |
|-----------|--------|
| Docstrings | Docstring lines are read from the parse tree (`prose_lines.py`) |
| String bodies | The body lines of a multi-line string literal are data, never a call |
| Comment lines | Lines starting with `#` are skipped |
| Doctest lines | Lines starting with `>>>` or `...` are skipped |
| `if __name__ == "__main__":` blocks | Main blocks may legitimately use print for CLI tools |
| `console.print()` / method calls | The regex excludes `.print(` patterns |
| `__init__.py` files | Package init files are skipped |
| Test files | `test_*.py`, `*_test.py`, `conftest.py` are skipped |
| Inline comments | Code after `#` is stripped before matching |

---

## Code Examples

### Violation

```python
def process_items(items):
    print(f"Processing {len(items)} items")       # <-- VIOLATION
    for item in items:
        result = transform(item)
        print(f"DEBUG: result = {result}")         # <-- VIOLATION
    print("Done!")                                  # <-- VIOLATION
```

### Fix -- Use Structured Logging

```python
from aipass.prax.apps.modules.logger import system_logger as logger

def process_items(items):
    logger.info(f"Processing {len(items)} items")
    for item in items:
        result = transform(item)
        logger.debug(f"result = {result}")
    logger.info("Processing complete")
```

### Fix -- Use Rich Console Output

```python
from aipass.cli.apps.modules import console

def process_items(items):
    console.print(f"[cyan]Processing {len(items)} items[/cyan]")
    for item in items:
        result = transform(item)
    console.print("[green]Done![/green]")
```

### Allowed -- Main Block

```python
if __name__ == "__main__":
    print("This is allowed in __main__ blocks")
```

---

## Scoring

- **Check:** One check per file -- "Debug print calls"
- **Pass:** Zero bare print() calls found (after exclusions and bypass filtering)
- **Fail:** Any bare print() calls detected. The violation message reports the count and first three line numbers (e.g., `3 bare print() call(s) on lines 42, 78, 115`)
- **Score:** 100 if passed, 0 if failed
- **Threshold:** Score >= 75 to pass overall
- **Line-level bypass:** Individual lines can be bypassed, and are filtered out before counting violations

---

## Bypass

Add an entry to `.seedgo/bypass.json`:

```json
{
    "standard": "debug_print",
    "file": "path/to/file.py"
}
```

Or bypass specific lines:

```json
{
    "standard": "debug_print",
    "file": "path/to/file.py",
    "lines": [42, 78]
}
```

---

## Audit Scope

`AUDIT_SCOPE = "all_files"` -- runs against every `.py` file in the branch. Skips `__init__.py` and test files (`test_*.py`, `*_test.py`, `conftest.py`).

---

## Reference

- Checker: `debug_print_check.py`
- Standards pack: seedgo standards (debug_print)
