# Ruff Check Standard
**Status:** Draft v1
**Date:** 2026-04-16

---

## What This Standard Is

Ruff is the primary linter for AIPass code. Seedgo can report 100% clean while a branch carries hundreds of ruff violations — this standard closes that gap. It runs `ruff check` once per branch and scores based on violation count.

This standard is **advisory**: it surfaces violations and affects branch scores but never blocks an audit. It exists to prevent ruff debt from silently re-accumulating after a cleanup.

---

## Why It Matters

- **Prevents regression.** After devpulse cleaned 338 ruff errors across 3 PRs, this standard ensures they don't drift back silently.
- **Closes the seedgo gap.** Other standards cover AIPass-specific patterns. Ruff covers Python best practices, unused imports, undefined names, complexity, and more.
- **Automated prevention is cheaper than cleanup.** Catching violations at audit time is far cheaper than periodic bulk cleanups.

---

## What the Checker Does

1. Checks for ruff binary via `shutil.which("ruff")` — skips gracefully if not installed
2. Runs `ruff check <branch>/apps/ --output-format=json`
3. Parses JSON output — a list of violation objects with `{code, filename, location, message}`
4. Filters violations against `.seedgo/ruff_bypass.json` (ruff-specific bypass)
5. Scores based on non-bypassed violation count

### Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| ruff not installed | SKIP — score 100, no penalty |
| subprocess timeout (60s) | FAIL — score 0 |
| JSON parse failure | FAIL — score 0, stderr shown |

---

## Scoring

| Violations | Score |
|-----------|-------|
| 0 | 100 |
| 1–5 | 95 |
| 6–20 | 85 |
| 21–50 | 70 |
| 51–100 | 50 |
| 101+ | 25 |

---

## Advisory Mode

`ADVISORY = True` — `passed` is always `True`. The score reflects reality, but the audit never fails because of this standard alone.

Promotion path: once all 11 branches hold at score 100 for two or more consecutive PR cycles, promote by removing the `passed = True` override and switching to `passed = score >= 75`.

---

## Audit Scope

`AUDIT_SCOPE = "branch_level"` — runs once per branch, not per file. Ruff walks the `apps/` directory itself. Respects the branch's own `pyproject.toml` or `ruff.toml` if present.

---

## Bypass — Standard Level

Add to `.seedgo/bypass.json` to skip ruff_check entirely for a branch:

```json
{"standard": "ruff_check", "file": "src/aipass/<branch>"}
```

---

## Bypass — Ruff-Specific

For fine-grained filtering, add entries to `.seedgo/ruff_bypass.json`. This file is a JSON array. All fields are optional — omitting a field means "match any".

### Examples

Skip all E501 violations in one file:

```json
[
    {"file": "apps/handlers/long_lines.py", "code": "E501"}
]
```

Skip a single violation at a specific line:

```json
[
    {"file": "apps/modules/thing.py", "code": "F401", "line": 42}
]
```

Skip all violations in a generated or vendor file:

```json
[
    {"file": "apps/handlers/generated.py"}
]
```

### Bypass Rule Fields

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Partial path match against violation's `filename`. Omit to match any file. |
| `code` | string | Exact ruff code (e.g., `"E501"`, `"F401"`). Omit to match any code. |
| `line` | int | Line number. Omit to match any line. |

---

## Code Examples

### Violation (F401 — unused import)

```python
import os  # never used
import json

def load_data(path):
    return json.loads(path.read_text())
```

### Fix

```python
import json  # removed unused 'os'

def load_data(path):
    return json.loads(path.read_text())
```

### Violation (E741 — ambiguous variable name)

```python
for l in lines:
    process(l)
```

### Fix

```python
for line in lines:
    process(line)
```

---

## Reference

- Checker: `ruff_check.py`
- Content handler: `ruff_check_content.py`
- Standards pack: seedgo standards (ruff_check)
- Ruff documentation: https://docs.astral.sh/ruff/
- Ruff rules reference: https://docs.astral.sh/ruff/rules/
