# Interface Proof — Checker Interface Compliance
**Version:** 1.0.1
**Created:** 2026-03-22
**Modified:** 2026-10-23
**Status:** Placeholder

---

## Purpose

The interface proof verifies that every checker in a pack declares the correct `AUDIT_SCOPE` variable and uses the function signature that the audit engine expects. Without these, the audit engine cannot scope or call the checker correctly.

---

## AUDIT_SCOPE

Every checker must declare `AUDIT_SCOPE` at module level. This tells the audit engine what to pass to the checker.

| Value | Meaning | What the checker receives |
|-------|---------|--------------------------|
| `"all_files"` | Checker runs once per Python file in the branch | `file_path`, `module_name`, `branch_path` |
| `"entry_point"` | Checker runs only on the main entry point | `file_path`, `module_name`, `branch_path` |
| `"branch_level"` | Checker runs once for the whole branch | `branch_path`, `module_name` |

```python
# Example declaration
AUDIT_SCOPE = "all_files"
```

---

## Function Signatures

The audit engine calls a specific function depending on the AUDIT_SCOPE:

### File-Level Checkers (`all_files` / `entry_point`)

```python
def check_module(module_path: str, bypass_rules: list | None = None) -> dict:
    """Validate a single file against the standard.

    Args:
        module_path: Absolute path to the file being checked
        bypass_rules: The branch's .seedgo/bypass.json rules, as branch_audit loads them

    Returns:
        {"passed": bool, "checks": [{"name": str, "passed": bool, "message": str}],
         "score": int, "standard": str}
    """
```

### Branch-Level Checkers (`branch_level`)

```python
def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Validate the branch as a whole against the standard.

    Args:
        branch_path: Absolute path to the branch root
        bypass_rules: The branch's .seedgo/bypass.json rules, as branch_audit loads them

    Returns:
        {"passed": bool, "checks": [{"name": str, "passed": bool, "message": str}],
         "score": int, "standard": str}
    """
```

---

## How the Audit Engine Discovers and Calls Checkers

1. **Discovery**: Glob `*_check.py` in the pack directory
2. **Import**: `importlib.import_module()` on each discovered file
3. **Scope read**: Read `AUDIT_SCOPE` from the module
4. **Dispatch**: Based on scope, call `check_module()` or `check_branch()` with the correct arguments
5. **Collect results**: Aggregate return dicts into the audit report

If `AUDIT_SCOPE` is missing, the engine cannot determine how to call the checker. If the function signature is wrong, the call raises `TypeError` at runtime.

---

## What the Scan Checks

1. **AUDIT_SCOPE exists** as a module-level variable in every `*_check.py`
2. **AUDIT_SCOPE value** is one of the three valid strings
3. **Function name** matches the scope: `check_module` for file-level, `check_branch` for branch-level
4. **Parameters**: the first is `module_path` (file-level) or `branch_path` (branch-level), and `bypass_rules` is the second positional or a keyword-only parameter

<!-- TODO: Detail the AST inspection approach vs import-based validation
     once the scanner implementation is finalized -->

---

## Common Failures

| Failure | Impact |
|---------|--------|
| Missing `AUDIT_SCOPE` | Audit engine skips or crashes on the checker |
| Wrong function name (`check` instead of `check_module`) | `AttributeError` at runtime |
| Wrong first parameter name, or no `bypass_rules` | `TypeError` when the audit engine passes `bypass_rules=` |
| Invalid scope value | Engine doesn't know how to route the checker |

---

## How to Fix

1. Add `AUDIT_SCOPE = "all_files"` (or `"entry_point"` / `"branch_level"`) at the top of the checker
2. Ensure the function name is `check_module` (file-level) or `check_branch` (branch-level)
3. Ensure the signature is `(module_path, bypass_rules=None)` or `(branch_path, bypass_rules=None)`

---

## Related

- **DPLAN-0044**: Self-audit tooling design
- **tools/interface_scanner.py**: Original prototype
- **Checker**: `interface.py` in this directory
