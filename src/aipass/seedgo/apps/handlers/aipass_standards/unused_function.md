# Unused Function Standards
**Status:** Draft v1
**Date:** 2026-03-22

---

## What It Is

The unused function standard detects functions that are defined but never referenced elsewhere in the branch. Dead code is maintenance burden -- every function should earn its place. If it is not called, it should be removed or wired up.

---

## Why It Matters

Unused functions clutter the codebase, confuse readers, and waste context when AI processes files. They often represent abandoned features, refactoring leftovers, or copied code that was never cleaned up. Removing them keeps the branch lean and makes it clear what code is actually active.

---

## What the Checker Scans For

This is a **branch-level** checker that runs once per branch (not per file). It operates in four phases:

### Phase 1: Collect Files

Gathers all `.py` files in the branch, skipping irrelevant directories:

`__pycache__`, `.archive`, `logs`, `tests`, `json_templates`, `tools`, `.trinity`, `.aipass`, `.ai_mail.local`, `.venv`, `venv`, `node_modules`, `.git`, `site-packages`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `.spawn`, `backups`, `reports`, `docs`, `.sorting_unprocessed`

### Phase 2: Build Corpus

Reads all collected files and strips non-code content to prevent false positives:
- **Triple-quoted strings** (docstrings, multiline literals) -- removed
- **Comment lines** (`# ...`) -- removed
- **`if __name__ == "__main__":` blocks** -- removed (demo invocations, not real references)

### Phase 3: Extract Functions

AST-parses each file to find `def` and `async def` definitions. The following are **excluded from analysis** and will never be flagged:

- **Dunder methods:** `__init__`, `__str__`, `__repr__`, `__enter__`, `__exit__`, etc.
- **Framework conventions:** `main()` and `handle_command()`
- **Decorated functions:** Any function with a decorator (`@property`, `@staticmethod`, `@track_operation`, etc.)

### Phase 4: Reference Counting

For each extracted function name:
1. Count all word-bounded occurrences in the cleaned corpus
2. Subtract definition lines (`def func_name` / `async def func_name`)
3. If `call_refs <= 0`, the function is flagged as unused

---

## Code Examples

### Violations

```python
# Defined but never called anywhere in the branch
def _calculate_delta(a, b):
    return a - b

# Leftover from an old feature
def legacy_export(data):
    ...
```

### Fixes

**Option 1 -- Remove it:**
```python
# Delete the function entirely if it is truly dead code
```

**Option 2 -- Wire it up:**
```python
# If the function should be used, call it somewhere
result = _calculate_delta(current, previous)
```

**Option 3 -- Add a decorator:**
```python
# If the function is called externally (API, callback, test hook),
# add a decorator to exclude it from detection
@some_decorator
def external_callback(event):
    ...
```

---

## Scoring

- **Scope:** `AUDIT_SCOPE = "branch_level"` -- runs once per branch via `check_branch()`
- **Score formula:** `clean_functions / total_functions * 100`
- **No eligible functions:** Score = 100
- **Report:** Lists up to 15 unused functions with `file:line` locations
- **Overall pass threshold:** 75%

---

## Excluded from Flagging

These are never counted as violations, regardless of whether they are referenced:

| Category | Examples |
|----------|----------|
| Dunder methods | `__init__`, `__str__`, `__repr__`, `__eq__`, `__hash__` |
| Framework conventions | `main()`, `handle_command()` |
| Decorated functions | `@property`, `@staticmethod`, `@track_operation`, any decorator |

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `unused_function` standard for a branch
- **File-level bypass:** Match by file path substring
- **File+line-level bypass:** Skip a specific function by file and line number

Example bypass rule:
```json
{
    "standard": "unused_function",
    "file": "utility_helpers.py",
    "lines": [45]
}
```

---

## Reference

- **Checker:** `unused_function_check.py`
- **Scope:** `branch_level`
- **Entry point:** `check_branch(branch_path, bypass_rules)`
- **Standard label:** `UNUSED_FUNCTION`

## What this check actually measures

**"No caller in this branch"** — not "unused". It is a static, per-branch AST scan, so
**cross-branch and dynamic (`importlib`) callers are invisible to it in principle.**
Confirm before deleting.

**Why the wording matters.** On 2026-08-31 this check nominated
`memory/apps/handlers/json/entry_limits.changed_entries()` — called by `@hooks` at
`security/edit_gate.py:496` through a dynamic import. It is the entry-cap half of the
fleet's write gate; deleting it would have disabled that gate for every branch.

The danger is that this check is **useful**. `@memory` had correctly acted on it earlier
the same night and dropped a genuinely dead helper. An agent that trusts the word
"unused" will eventually delete a real cross-branch entry point to get a green audit —
and the audit will go green. The measurement was sound; only the word overclaimed.
