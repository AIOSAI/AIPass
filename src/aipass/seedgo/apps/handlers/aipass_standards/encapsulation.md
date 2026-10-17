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
- The branch's resolution shim: a top-level module under `apps/handlers/` that defines one of
  `module_file`, `find_repo_root`, `source_root` or `resolved_file` at module level. It is the
  one guarded spelling of `Path(__file__)` every module resolves through, so it cannot sit
  behind a module entry point (the entry point needs it first). The shim is found by what it
  publishes, not by file name, because the file name varies by branch. Being a leaf (importing
  nothing from its own `apps/`) is not enough: ordinary handlers with no local dependencies are
  leaves too.

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

**Since 2026-10-07 (DPLAN-0404, the wall):**
- **Strings are imports.** A handlers target passed as the string argument of `import_module` (any alias, a seam named `*import_module`), `pkgutil.resolve_name`, `patch` / `mock.patch` (first positional; `patch.object` is not read) or `<x>.setattr` (the string form) counts like an import statement, and so does a bare name bound once at module level to such a string. The conviction quotes the line and says `(string import)`. A string anywhere else (a docstring, a comment, an assignment, a log message) is prose and stays acquitted. Same-branch targets stay allowed.
- **Tests are kin to their own branch only.** A file under `tests/` is asked one thing: whether it imports or patches ANOTHER branch's handlers. Its own branch's handlers stay allowed. Imports are read from the parse tree, so an import inside a triple-quoted source fixture is prose. The branch of a target is the segment after `aipass.` (`aipass.skills.lib.telegram.apps.handlers` is skills').
- **The apps package.** The guard row also reads `apps/__init__.py`. A line there that imports handlers (`from . import handlers`, `from aipass.<x>.apps import handlers`, `import aipass.<x>.apps.handlers`) fails it: "apps/__init__.py imports handlers: the fence sees its own package as every caller (2026-04-25)". A module-level `_guard_branch_access()` call in `handlers/__init__.py` is the v2 guard marker.

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
