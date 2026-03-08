# Encapsulation Standards
**Status:** Draft v1
**Date:** 2025-12-04

---

## Core Principle

Handlers are implementation details. Modules are the public API.

**WHY:** When Branch A imports Branch B's handlers directly, it creates tight coupling that breaks when handlers change. Modules provide stable entry points that can evolve internally without breaking callers.

---

## The Three Rules

### 1. No Cross-Branch Handler Imports

**BAD:**
```python
# In api branch, importing flow's handlers
from aipass.flow.apps.handlers.plan.validator import validate_plan
```

**GOOD:**
```python
# Use module entry point
from aipass.flow.apps.modules.plan_validator import validate_plan
```

**WHY:** Handlers are internal to their branch. If Flow restructures its handlers, API breaks. Modules provide stable interfaces.

---

### 2. No Cross-Package Handler Imports

Within the same branch, handlers shouldn't import other handler packages.

**BAD:**
```python
# In handlers/standards/imports_check.py
from aipass.seedgo.apps.handlers.error.formatter import format_error
```

**GOOD:**
```python
# Either use module entry point
from aipass.seedgo.apps.modules.error_handler import format_error

# Or use allowed default handlers
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.file import file_handler
```

**Allowed Handler Imports:**
- `json_handler` - Default JSON operations
- `file_handler` - Default file operations
- Same-package relative imports (`from .validator import X`)

---

### 3. Entry Points Don't Import Handlers

Main entry points (`branch.py`) should use modules, not handlers directly.

**BAD:**
```python
# In api.py
from aipass.api.apps.handlers.openrouter.client import get_response
```

**GOOD:**
```python
# In api.py
from aipass.api.apps.modules.openrouter_client import get_response
```

**WHY:** Entry points are the first code users see. They should show clean architecture - modules orchestrating, not reaching into handler internals.

---

## Exception: Service Branches

These service imports ARE allowed everywhere because they provide system-wide utilities:

```python
# Prax logger - allowed anywhere
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services - allowed anywhere
from aipass.cli.apps.modules import console, header, success, error
```

**Note:** These are MODULE imports, not handler imports. Service branches expose functionality through modules, demonstrating the pattern.

---

## Exception: Trigger Branch

Trigger is the ONE place where cross-branch handler imports are acceptable:

```python
# In trigger/apps/handlers/events/startup.py
from aipass.memory.apps.handlers.rollover import check_and_rollover
```

**WHY:** Trigger's entire purpose is centralizing cross-branch reaction logic. It's the exception that proves the rule - instead of scattered cross-branch calls, Trigger owns them all in one place.

Configure bypass in `.seedgo/bypass.json`:
```json
{
  "bypass": [{
    "file": "apps/handlers/events/startup.py",
    "standard": "encapsulation",
    "reason": "Trigger centralizes cross-branch calls by design"
  }]
}
```

---

## Checker Implementation

The `encapsulation_check.py` validates:

1. **Cross-branch handler imports** - Detects imports from other branches' handlers
2. **Cross-package handler imports** - Detects handlers importing other handler packages
3. **Direct handler imports** - Detects entry points importing handlers directly

**Detection Method:**
- Parses import statements for `apps.handlers` pattern
- Extracts branch name from import path
- Compares against current file's branch context
- Respects bypass rules from `.seedgo/bypass.json`

---

## Bypass Configuration

For legitimate architectural exceptions, configure `.seedgo/bypass.json`:

```json
{
  "bypass": [{
    "file": "apps/handlers/events/startup.py",
    "standard": "encapsulation",
    "lines": [38, 42],
    "reason": "Trigger centralizes cross-branch handler calls"
  }]
}
```

---

## Reference

- **Checker:** `src/aipass/seedgo/apps/standards/aipass/handlers/standards/encapsulation_check.py`
- **Handler Standard:** `src/aipass/seedgo/docs/aipass_code_standards/handlers.md`
- **Architecture Standard:** `src/aipass/seedgo/docs/aipass_code_standards/architecture.md`
