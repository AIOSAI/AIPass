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

### 2. Inside a Branch, Any Handler May Import Any Handler

Inside a branch, any handler may import any handler, in any package, absolute or relative.
Across branches, only the entry point: another branch's handlers are never imported (rule 1).

**GOOD:**
```python
# In sentry's handlers/aipass_standards/imports_check.py
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from ..bypass.utils import is_bypassed
```

**WHY:** The fence that matters is the branch boundary. A branch owns all its handlers and
changes them together, so a handler package importing its sibling couples nothing that is not
already one owner's code.

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

**Handlers an entry point may import:**
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

Configure bypass in `.sentry/bypass.json`:
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
2. **Direct handler imports** - Detects entry points importing handlers directly
3. **Handler guard** - `handlers/__init__.py` calls `_guard_branch_access()`, the runtime fence

A handler file is never judged on which of its own branch's handlers it imports.

**Detection Method:**
- Parses import statements for `apps.handlers` pattern
- Extracts branch name from import path
- Compares against current file's branch context
- Respects bypass rules from `.sentry/bypass.json`

**Strings, tests and the apps package:**
- **Strings are imports.** A handlers target passed as the string argument of `import_module` (any alias, a seam named `*import_module`), `pkgutil.resolve_name`, `patch` / `mock.patch` (first positional; `patch.object` is not read) or `<x>.setattr` (the string form) counts like an import statement, and so does a bare name bound once at module level to such a string. The conviction quotes the line and says `(string import)`. A string anywhere else (a docstring, a comment, an assignment, a log message) is prose and stays acquitted. Same-branch targets stay allowed.
- **Tests are kin to their own branch only.** A file under `tests/` is asked one thing: whether it imports or patches ANOTHER branch's handlers. Its own branch's handlers stay allowed. Imports are read from the parse tree, so an import inside a triple-quoted source fixture is prose. The branch of a target is the segment after `aipass.` (`aipass.skills.lib.drone_commands.apps.handlers` is skills').
- **The apps package.** The guard row also reads `apps/__init__.py`. A line there that imports handlers (`from . import handlers`, `from aipass.<x>.apps import handlers`, `import aipass.<x>.apps.handlers`) fails it: "apps/__init__.py imports handlers: the fence sees its own package as every caller (2026-04-25)". A module-level `_guard_branch_access()` call in `handlers/__init__.py` is the v2 guard marker.

---

## Bypass Configuration

For legitimate architectural exceptions, configure `.sentry/bypass.json`:

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

- **Checker:** `src/aipass/sentry/apps/handlers/aipass_standards/encapsulation_check.py`
- **Handler Standard:** `src/aipass/sentry/docs/aipass_code_standards/handlers.md`
- **Architecture Standard:** `src/aipass/sentry/docs/aipass_code_standards/architecture.md`
