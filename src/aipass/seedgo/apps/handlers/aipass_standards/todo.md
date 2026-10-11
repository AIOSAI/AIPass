# TODO/FIXME Standards
**Status:** Draft v1
**Date:** 2026-10-03

---

## What It Is

The TODO standard detects TODO, FIXME, HACK, and XXX comments in Python source files. These tags indicate incomplete work, known hacks, or code needing attention. Clean code resolves these before shipping.

---

## Why It Matters

TODO comments are promises to your future self that rarely get kept. They accumulate over time, creating a backlog of technical debt hidden inside the codebase. FIXME tags indicate known bugs left unfixed. HACK tags admit the code is a workaround. XXX tags flag dangerous code. All of these should be resolved or tracked in a proper task system (like flow plans) rather than buried in source files.

---

## What the Checker Scans For

The checker scans each Python file for comment lines containing these tags (case-insensitive):

| Tag | Meaning |
|-----|---------|
| `TODO` | Planned but unfinished work |
| `FIXME` | Known bug or broken behavior |
| `HACK` | Workaround that should be replaced |
| `XXX` | Dangerous or problematic code |

**Pattern:** Matches `# TODO: text`, `# FIXME(user): text`, inline `x = 1  # HACK ...`, etc.

**Only a real comment counts** (2026-10-03, seedgo fleet green leg 13). Comments are read from Python's tokenizer (its `COMMENT` tokens), so a `# TODO` inside any string or docstring is text and never flagged: `text = "# TODO: a specimen"` passes, and so does a `# FIXME` line inside an assigned triple-quoted string. Before this, a line scan read both as comments. A real comment after a string on the same line (`text = "# fine"  # TODO: real`) is still flagged.

**A file Python cannot tokenize** (an unclosed string, a bad dedent) fails by name with the check `File tokenizable`: its comments are unknown, so it never reads as clean.

**Skipped:**
- `__init__.py` files

---

## Code Examples

### Violations

```python
# TODO: implement retry logic
def send_request(url):
    return requests.get(url)

# FIXME: this breaks on empty input
def parse_data(raw):
    return json.loads(raw)

result = hack_around_bug()  # HACK: remove later

# XXX: dangerous -- needs security review
password = config["password"]
```

### Fixes

```python
# Resolve the TODO by implementing the feature
def send_request(url, retries=3):
    for attempt in range(retries):
        try:
            return requests.get(url, timeout=10)
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            logger.warning(f"Retry {attempt + 1}: {e}")

# Resolve the FIXME by handling the edge case
def parse_data(raw):
    if not raw:
        raise ValueError("raw data cannot be empty")
    return json.loads(raw)
```

If the work cannot be done now, create a flow plan or ticket instead of leaving a comment in the code.

---

## Scoring

- **Scope:** `AUDIT_SCOPE = "all_files"` -- checks every `.py` file individually
- **Checks per file:** 1 (TODO/FIXME comments)
- **Score 100:** No TODO-type comments found
- **Score 0:** One or more found
- **Failure message:** Reports total count and tag breakdown (e.g., `TODO: 2, FIXME: 1`)
- **Overall pass threshold:** 75%

---

## Bypass

Bypass rules are configured in `.seedgo/bypass.json`. Supports:

- **Standard-level bypass:** Skip the entire `todo` standard for a file
- **File-level bypass:** Match by file path substring
- **Line-level bypass:** Skip specific line numbers within a file

Example bypass rule:
```json
{
    "standard": "todo",
    "file": "work_in_progress.py"
}
```

---

## Reference

- **Checker:** `todo_check.py`
- **Scope:** `all_files`
- **Entry point:** `check_module(module_path, bypass_rules)`
- **Standard label:** `TODO`
