# Permission Flags Standard

**Standard:** PERMISSION_FLAGS
**Created:** 2026-02-26
**Version:** 1.0.0

---

## Purpose

Enforce a single, approved permission bypass pattern across all AIPass code. The only acceptable permission flag is `--permission-mode bypassPermissions`. All other bypass patterns are prohibited.

## The Rules

### APPROVED

1. **`--permission-mode bypassPermissions`** — The AIPass standard for autonomous agent execution

### PROHIBITED

1. **`--dangerously-skip-permissions`** — Deprecated Claude CLI flag, bypasses ALL safety checks
2. **`--skip-permissions`** — Non-standard bypass
3. **`--no-permissions`** — Non-standard bypass
4. **`--allow-dangerously-skip-permissions`** — Enables the dangerous flag

## Examples

### BAD

```python
# WRONG: Dangerous skip flag — bypasses ALL safety checks
claude_cmd = f"{CLAUDE_BIN} --dangerously-skip-permissions"

# WRONG: Non-standard bypass
subprocess.run(['claude', '--skip-permissions'])

# WRONG: Enabling dangerous flag
cmd = ['claude', '--allow-dangerously-skip-permissions']
```

### GOOD

```python
# CORRECT: AIPass standard permission flag
subprocess.run(['claude', '--permission-mode', 'bypassPermissions'])

# CORRECT: In command list construction
cmd = [
    CLAUDE_BIN,
    '--permission-mode', 'bypassPermissions',
    '-p', prompt
]
```

## Why This Matters

`--dangerously-skip-permissions` is a deprecated Claude CLI flag that bypasses ALL permission checks without any granularity. It provides no integration with AIPass's permission system and creates inconsistency across the codebase.

The AIPass standard `--permission-mode bypassPermissions` provides:
- Controlled permission bypass that integrates with the permission system
- Consistent flag usage across all branches and dispatch mechanisms
- A single pattern to audit and enforce

## Checker

**File:** `src/aipass/seedgo/apps/standards/aipass/handlers/standards/permission_flags_check.py`

Checks:
1. No `--dangerously-skip-permissions` usage in code (comments/docstrings excluded)
2. No `--skip-permissions` or `--no-permissions` variants
3. Files without any permission flag references are automatically passed
