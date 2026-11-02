# Deep Nesting Standard
**Status:** Draft v1
**Date:** 2026-03-22

---

## What This Standard Is

Functions should not have deeply nested control flow. When `if` / `for` / `while` / `try` / `with` / `except` blocks nest more than 3 levels deep, the function is too complex and should be decomposed into smaller helpers.

---

## Why It Matters

- **Readability:** Each nesting level adds cognitive load. At depth 4+, readers lose track of which conditions are active.
- **Testability:** Deeply nested code requires many test paths to cover. Flat code with extracted helpers is easier to test in isolation.
- **AI comprehension:** AI models process deeply nested logic less accurately. Flatter functions produce fewer errors in AI-assisted development.
- **Error proneness:** The deeper the nesting, the more likely off-by-one errors, missed edge cases, and incorrect scope assumptions.

---

## What the Checker Scans For

The checker uses Python's `ast` module to parse source files and walk every function definition (both sync and async). For each function, it recursively measures the maximum nesting depth.

### Nesting Nodes

Each of these AST node types adds one level of nesting depth:

- `If`
- `For`
- `While`
- `Try`
- `With`
- `ExceptHandler`

### Threshold

**Maximum allowed depth: 3**

A function with depth 4 or greater is a violation.

### Exclusions

- `__init__.py` files are skipped
- Files with syntax errors are skipped (no crash, no false positives)

---

## Code Examples

### Violation -- Depth 4

```python
def process(items):
    for item in items:                    # depth 1
        if item.valid:                     # depth 2
            try:                           # depth 3
                if item.special:           # depth 4 -- VIOLATION
                    handle_special(item)
            except ValueError:
                log_error(item)
```

Result: `1 function exceeds nesting limit: process() depth 4 line 1`

### Fix -- Extract Helper

```python
def _handle_item(item):
    """Extracted helper keeps nesting shallow."""
    try:
        if item.special:
            handle_special(item)
    except ValueError:
        log_error(item)

def process(items):
    for item in items:                    # depth 1
        if item.valid:                     # depth 2
            _handle_item(item)             # depth stays at 2
```

### Fix -- Early Return

```python
def process_item(item):
    if not item.valid:
        return                             # guard clause
    if not item.special:
        handle_normal(item)
        return
    try:                                   # depth 1
        handle_special(item)               # flat!
    except ValueError:
        log_error(item)
```

### Fix -- Guard Clauses

```python
def validate_and_process(data):
    if not data:
        return None
    if not data.get("items"):
        return None
    # Main logic is flat after guards
    for item in data["items"]:             # depth 1
        if item.get("active"):             # depth 2
            process(item)                  # depth stays at 2
```

---

## Scoring

- **Check:** One check per file -- "Deep nesting"
- **Pass:** All functions have max nesting depth <= 3
- **Fail:** Any function exceeds depth 3. The violation message lists each offending function with its name, depth, and line number
- **Score:** 100 if passed, 0 if failed
- **Threshold:** Score >= 75 to pass overall

---

## Bypass

Add an entry to `.sentry/bypass.json`:

```json
{
    "standard": "deep_nesting",
    "file": "path/to/file.py"
}
```

Or bypass a specific function by line number:

```json
{
    "standard": "deep_nesting",
    "file": "path/to/file.py",
    "lines": [15]
}
```

---

## Audit Scope

`AUDIT_SCOPE = "all_files"` -- runs against every `.py` file in the branch. Skips `__init__.py`. Uses AST parsing, so files with syntax errors are silently skipped.

---

## Reference

- Checker: `deep_nesting_check.py`
- Standards pack: sentry standards (deep_nesting)
