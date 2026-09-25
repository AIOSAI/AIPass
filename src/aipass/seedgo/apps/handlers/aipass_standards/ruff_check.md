# Ruff Check Standard
**Status:** v1.1 (gating)
**Date:** 2026-04-16, gating since 2026-09-25

---

## What This Standard Is

Ruff is the primary linter for AIPass code. Seedgo can report 100% clean while a branch carries hundreds of ruff violations — this standard closes that gap. It runs `ruff check` once per branch and scores based on violation count.

This standard **gates** (since 2026-09-25, owner ruling 00:33): its score counts in the branch's Overall like any other row, and `passed` is `False` whenever a non-bypassed lint or format finding exists. It was advisory from 2026-04-16 (DPLAN-0137) until CI ruff went green fleet-wide — during that time the row read 68% under 258 dead `noqa` markers while Overall read 93%, because advisory rows are left out of the average. It exists to keep ruff debt from silently re-accumulating after a cleanup.

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

## Gating

No `ADVISORY` flag — absence is how this family says "counts in the average" (`branch_audit.py` averages only standards without `ADVISORY = True`). `passed` is `False` on any active lint violation or any unformatted file; the score keeps its tiers (1–5 violations score 95, minus 2 per unformatted file, floor 25). Ruff not installed is a skip (`passed` True, score 100); a timeout or unreadable ruff output is a 0.

The row covers `ruff format --check` too: on a machine where format finds unformatted files, the row fails and loses 2 points per file even with zero lint hits.

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
