---
name: branch_health
description: Quick health check -- test counts and file stats for AIPass branches
version: 1.0.0
tags: [system, monitoring, health, testing]
requires:
  pip: []
  bins: []
  config: []
has_handler: true
---

# Branch Health Skill

Quick health check for AIPass branches. Counts Python source files, test files, and test functions to give a snapshot of each branch's codebase and test coverage.

## Available Actions

| Action      | Description                                           |
|-------------|-------------------------------------------------------|
| `summary`   | Full stats for all branches (default)                 |
| `tests`     | Test-only stats (test files, test function counts)    |
| *branch*    | Stats for a single branch by name                     |

## Usage

```bash
drone @skills run branch_health summary
drone @skills run branch_health tests
drone @skills run branch_health flow
```

## Output Format

All actions return structured dicts:

```python
{"success": True, "output": "...", "error": None}
```

## Notes

- Scans `apps/` for source files and `tests/` for test files
- Counts `def test_` lines as test functions
- Missing directories are handled gracefully
- No external dependencies -- stdlib only
