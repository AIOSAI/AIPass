# Diagnostics Standards
**Status:** Draft v1
**Date:** 2025-12-04

---

## Core Principle

Type errors caught at development time are cheaper than runtime bugs.

**WHY:** AIPass uses Python type hints extensively. The diagnostics checker uses pyright (same engine as VS Code's Pylance) to catch type errors, undefined variables, and other static analysis issues before code runs.

---

## What It Checks

The diagnostics checker runs pyright on Python files to detect:

1. **Type Errors**
   - Function return type mismatches
   - Argument type mismatches
   - Incompatible assignments

2. **Undefined Variables**
   - Typos in variable names
   - Using variables before assignment
   - Missing imports

3. **Missing Attributes**
   - Accessing non-existent properties
   - Method name typos

4. **Import Errors**
   - Missing modules
   - Circular import issues

---

## Usage

### Single File
```bash
python3 src/aipass/seedgo/apps/standards/aipass/handlers/standards/diagnostics_check.py /path/to/file.py
```

### Entire Directory
```bash
python3 src/aipass/seedgo/apps/standards/aipass/handlers/standards/diagnostics_check.py src/aipass/seedgo/apps/
```

### Branch Check
```python
from aipass.seedgo.apps.handlers.standards.diagnostics_check import check_branch
result = check_branch('src/aipass/seedgo')
```

---

## Output Format

```python
{
    'total_files': 42,
    'files_with_errors': 3,
    'total_errors': 7,
    'total_warnings': 12,
    'results': [
        {
            'file': '/path/to/file.py',
            'errors': 2,
            'warnings': 1,
            'diagnostics': [
                {
                    'line': 45,
                    'severity': 'error',
                    'message': 'Type "str" cannot be assigned to "int"',
                    'rule': 'reportAssignmentType'
                }
            ]
        }
    ]
}
```

---

## Common Issues and Fixes

### 1. Type Mismatch
```python
# Error: Type "str" cannot be assigned to "int"
def get_count() -> int:
    return "5"  # Wrong!

# Fix:
def get_count() -> int:
    return 5
```

### 2. Undefined Variable
```python
# Error: "result" is not defined
def process():
    print(result)  # result not defined

# Fix:
def process():
    result = compute()
    print(result)
```

### 3. Missing Return Type
```python
# Warning: Return type is "None", should be "str"
def get_name() -> str:
    if condition:
        return name
    # Missing return!

# Fix:
def get_name() -> str:
    if condition:
        return name
    return ""  # or raise exception
```

---

## Ignore Patterns

The diagnostics checker respects audit ignore patterns from `ignore_handler.py`:

- `__pycache__/` - Compiled files
- `.git/` - Version control
- `venv/`, `.venv/` - Virtual environments
- `node_modules/` - Node dependencies
- Test fixtures and mocks

---

## Integration with Development

### VS Code
If you use VS Code with Pylance, you see the same errors in real-time. The diagnostics checker runs the same engine (pyright) for CI/audit purposes.

### Pre-commit Hook
```bash
# In .pre-commit-config.yaml
- repo: local
  hooks:
    - id: pyright
      name: pyright
      entry: python3 -m pyright
      language: system
      types: [python]
```

### Audit Integration
The standards audit can include diagnostics:
```bash
drone @seedgo audit --diagnostics
```

---

## Severity Levels

| Severity | Meaning | Action |
|----------|---------|--------|
| error | Type error, undefined variable | Must fix |
| warning | Potential issue, deprecated usage | Should fix |
| information | Style suggestion | Optional |

---

## Requirements

- **pyright** installed: `pip install pyright`
- Python 3.10+ (for type hint features)
- Type hints in code (the more hints, the better analysis)

---

## Reference

- **Checker:** `src/aipass/seedgo/apps/standards/aipass/handlers/standards/diagnostics_check.py`
- **Pyright Docs:** https://microsoft.github.io/pyright/
- **Python Typing:** https://docs.python.org/3/library/typing.html
