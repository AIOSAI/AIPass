# Silent Catch Standards
**Status:** Draft v1
**Date:** 2026-03-22

---

## What It Is

The silent catch standard detects `except` blocks that silently swallow exceptions -- no logger call and no re-raise. These blocks hide failures and make debugging impossible. Every exception handler must either log the error or re-raise it.

---

## Why It Matters

A silent catch turns a visible error into an invisible one. The program continues in an unexpected state, data may be corrupted, and no one knows anything went wrong until much later -- if ever. Debugging silent failures is one of the most time-consuming problems in software development.

---

## What the Checker Scans For

The checker parses each Python file with `ast.parse()` and walks every `ExceptHandler` node in the AST. An except block is flagged as "silent" when its body:

1. Contains **no** `logger.<level>()` call (error, warning, warn, info, debug, exception, critical)
2. Contains **no** `raise` statement

**Logger detection:** Only recognizes calls to `logger.error()`, `logger.warning()`, `logger.info()`, etc. -- the standard Prax logger pattern used across AIPass.

**No-op body detection:** Also identifies bodies that are effectively no-ops:
- `pass`
- `...` (Ellipsis)
- Bare string constants (docstring-style placeholders)

**Skipped files:**
- `__init__.py`
- Non-`.py` files

---

## What is not a silent catch

Four shapes are not silent. Each is a separate named clause, so a finding removed from the
checker traces to the clause that removed it.

- **The exception becomes a value.** The handler names a specific exception type (not a bare
  `except:` or `except Exception`; dotted names compare whole, so `pytest.skip.Exception` is
  specific) and its body is exactly one `return` of a constant or of the empty answer of any
  type (`[]`, `{}`, `()`, `set()`, `frozenset()`, zero-argument `dict()` / `list()` / `tuple()`).
  `except FileNotFoundError: return "absent"` hands the caller the classification, and a logger
  call there would route production logging out of a test suite. A return that uses the bound
  exception (`except AssertionError as exc: return ("FAILED", str(exc))`) carries more than a
  constant and counts too. `return [1, 2]` or `set(c)` fabricates an answer and keeps its finding.
- **The failure reaches a stream.** A body that writes to `sys.stdout` or `sys.stderr` puts the
  exception on the operator's screen, which is not silence. This holds anywhere; whether a stream
  is the right instrument is the CLI standard's question, and that standard still asks it.
- **The handler guards a diagnostic.** The block it protects does nothing but report, so what
  is caught is the failure of the report.
- **The exception is handed on.** It leaves the handler as an argument.

---

## Code Examples

### Violations

```python
# BAD -- silent catch with pass
try:
    result = do_something()
except Exception:
    pass

# BAD -- catches and stores but never logs or raises
try:
    data = load_file(path)
except OSError as e:
    error_msg = str(e)

# BAD -- ellipsis placeholder
try:
    connect()
except ConnectionError:
    ...
```

### Fixes

```python
# GOOD -- log the error
try:
    result = do_something()
except Exception as e:
    logger.error(f"Operation failed: {e}")

# GOOD -- re-raise
try:
    data = load_file(path)
except OSError:
    raise

# GOOD -- log and handle gracefully
try:
    data = load_file(path)
except OSError as e:
    logger.warning(f"Could not load: {e}")
    data = default_value
```

---

## Scoring

- **Scope:** `AUDIT_SCOPE = "all_files"` -- checks every `.py` file individually via AST parsing
- **Checks per file:** 1 (silent catch blocks)
- **Score 100:** No silent catches found
- **Score 0:** One or more silent catches found
- **Failure message:** Reports the count and up to 3 offending line numbers
- **Overall pass threshold:** 75%

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `silent_catch` standard for a file
- **File-level bypass:** Match by file path substring

Example bypass rule:
```json
{
    "standard": "silent_catch",
    "file": "third_party_wrapper.py"
}
```

---

## Reference

- **Checker:** `silent_catch_check.py`
- **Scope:** `all_files`
- **Entry point:** `check_module(module_path, bypass_rules)`
- **Standard label:** `SILENT_CATCH`
