# Handler Standards
**Status:** Complete v1.1
**Last Updated:** 2026-02-10

## What This Covers

Standards specific to handlers (implementation layer).

## Key Principles

- Self-contained and transportable (marketplace requirement)
- Same-branch handler imports: ALLOWED (even across packages)
- Cross-branch handler imports: BLOCKED (use modules instead)
- Domain-based organization
- File size guidelines (<300 lines ideal, 500-700 heavy, 700+ consider extensions)
- Pure implementation, no orchestration logic

---

## Auto-Detection Pattern

**Status:** ✅ Standard (2025-11-12)

**Core principle:** Handlers should auto-detect their caller instead of requiring modules to pass their own name.

### The Pattern

**Use Python's `inspect.stack()` to determine which module is calling:**

```python
import inspect
from pathlib import Path

def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack"""
    try:
        stack = inspect.stack()
        # Skip frames to get actual caller
        if len(stack) > 2:
            caller_frame = stack[2]  # [0]=this, [1]=public function, [2]=caller
            caller_path = Path(caller_frame.filename)
            return caller_path.stem  # "my_module" from "my_module.py"
        return "unknown"
    except Exception:
        return "unknown"

def handler_function(operation: str, module_name: str | None = None):
    """Handler with auto-detection"""
    if module_name is None:
        module_name = _get_caller_module_name()
    # ... use module_name
```

### Why This Matters

**Modules should just import and use - no boilerplate:**

```python
# ✅ GOOD - Like Prax logger
from aipass.seedgo.apps.handlers.json import json_handler
json_handler.log_operation("operation", data)

# ❌ BAD - Modules shouldn't pass their own name
from aipass.seedgo.apps.handlers.json import json_handler
json_handler.log_operation("my_module", "operation", data)  # Typo-prone, boilerplate
```

### When to Apply

**Use auto-detection when handler needs to:**
- Create module-specific files
- Log caller identity
- Route behavior based on caller

**Don't use when:**
- Handler is pure utility (no caller-specific behavior)
- Explicit parameter makes more semantic sense

**Reference:** See `json_structure.md` for complete implementation example.

---

## Default Handlers

**Status:** Standard (packaged by Spawn into all branches)

### json_handler.py - JSON Operations

**Location:** `handlers/json/json_handler.py`
**Purpose:** Auto-creating, self-healing JSON system for module config/data/log files
**Status:** Default handler - comes pre-packaged in every branch

**API Contract:**
- `load_json(module_name, json_type)` - Auto-creating load with validation
- `save_json(module_name, json_type, data)` - Validated save with timestamp updates
- `log_operation(operation, data, module_name=None)` - Auto-rotating operation logs
- `increment_counter(module_name, counter_name, amount=1)` - Counter management
- `update_data_metrics(module_name, **metrics)` - Metric updates
- `_get_caller_module_name()` - Auto-detection via stack inspection

**Key Features:**
- Auto-creates missing JSON files from templates
- Self-heals corrupted files
- Auto-detects calling module (no module_name needed)
- Log rotation (prevents unbounded growth)
- Structure validation

**Usage Pattern:**
```python
from aipass.seedgo.apps.handlers.json import json_handler

# Module just calls - handler auto-detects caller
json_handler.log_operation("validation_run", {"files": 42})
```

**Spawn Integration:** This handler is packaged into every branch by Spawn during branch creation/updates. All branches use identical or near-identical implementations.

**3-Tier Compliance:** Default handlers follow the same 3-tier error handling rules as custom handlers. Location (`handlers/`) determines rules, not conceptual role. json_handler.py raises exceptions; calling modules handle logging. See `error_handling.md` for 3-tier architecture details.

**Reference:** See `json_structure.md` for complete three-JSON pattern details.

---

## Handler Independence Rules

**Core principle:** Handlers cannot import MODULES from their own branch (prevents circular dependencies).

### Why This Matters

**Circular dependency prevention:** If handlers import modules, and modules import handlers, you get import loops.

```
Module → imports Handler ✓
Handler → imports Module ✗ (creates cycle)
```

**Marketplace transportability:** Handlers must be self-contained so they can be moved between branches.

### The Rules

**✅ ALLOWED - Same-branch handler imports (even across packages):**

```python
# seedgo/apps/standards/aipass/handlers/standards/imports_check.py
from aipass.seedgo.apps.handlers.json import json_handler  # ✅ OK - same branch

# flow/apps/handlers/plan/create.py
from aipass.flow.apps.handlers.registry.load import load_registry  # ✅ OK - same branch
```

**Why allowed:** Handlers within the same branch are coworkers. The security boundary is at BRANCH level.

**✅ ALLOWED - Relative imports within package:**

```python
# error/decorators.py
from .result_types import OperationResult, OperationStatus
from .logger import log_operation_start, log_operation_end
```

**Why allowed:** Same package = definitely same branch.

**❌ FORBIDDEN - Handler imports own branch's modules:**

```python
# seedgo/apps/standards/aipass/handlers/json/json_handler.py
from aipass.seedgo.apps.modules.create_thing import something  # ❌ NO - circular risk
```

**Why forbidden:** Creates circular dependency risk. Modules import handlers, not the other way.

**❌ FORBIDDEN - Cross-branch handler imports:**

```python
# flow/apps/modules/list_plans.py
from aipass.prax.apps.handlers.logging.setup import get_logger  # ❌ BLOCKED

# ✅ CORRECT - use the module (public API)
from aipass.prax.apps.modules.logger import system_logger as logger
```

**Why forbidden:** Handlers are internal implementation. External branches use MODULES.

### Real Example - Error Package

The error handler package shows correct within-package imports:

```
handlers/error/
  ├── __init__.py         → Public API
  ├── result_types.py     → Core types (no imports)
  ├── logger.py           → Uses result_types
  ├── formatters.py       → Uses result_types
  └── decorators.py       → Uses result_types, logger, formatters
```

**File: error/decorators.py**
```python
from .result_types import OperationResult, OperationStatus
from .logger import log_operation_start, log_operation_end
from .formatters import format_result, format_batch_header
```

**This is fine** - all within error package and same branch.

### Modules Can Import Many Handlers

**This is by design:**

```python
# modules/imports_standard.py
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.cli import prompts
from aipass.seedgo.apps.handlers.standards import imports_check
```

**Why this works:** Dependencies flow ONE way (modules → handlers). Better one module imports 20 handlers than handlers importing each other.

### Package-Level Exceptions

**Error handlers are system-wide service:**

```python
# Any handler can import error system (current: cli)
from aipass.cli.apps.handlers.error import track_operation
from aipass.cli.apps.handlers.error.result_types import OperationResult

@track_operation
def create_branch(name):
    # Business logic
    return True
```

**Why exception:** Error handlers are infrastructure service - three-tier output (JSON log, system log, console). Not domain logic, but framework service.

**Current reality:** Error system lives in `aipass.cli.apps.handlers.error` and is imported by handlers across branches. This creates dependency on cli, but is necessary for consistent error handling across system.

**Current direction:** Error system in `aipass.cli.apps.handlers.error` — clearly infrastructure, not branch-specific.

**Rule:** Service providers (infrastructure shared across ALL branches) can be imported cross-domain.

---

## Handler Boundaries & External Access

**Status:** ✅ Standard (2025-11-29)

**Core principle:** Handlers are INTERNAL to their branch. External consumers use MODULES as the public API.

### The Import Hierarchy

```
External Branch
      ↓
  Entry Point (prax.py, drone.py, cli.py)
      ↓
    Modules (prax/apps/modules/*.py)  ← EXTERNAL STOPS HERE
      ↓
    Handlers (prax/apps/handlers/*/*.py)  ← NEVER EXPOSED
```

**Rule:** External consumers stop at MODULES. They never touch handlers.

### Two Types of Branches

1. **CLI Tools** - Used via command line, not imported
   - Flow, Seedgo, AI_Mail, Spawn, Drone
   - You run `drone @flow create`, you don't `import flow` or `import drone`
   - Drone is a CLI router that resolves @ and routes commands to branches

2. **Library Services** - Imported by other code
   - Prax (logging), CLI (formatting), API (LLM calls), Memory Bank (vectors)
   - You `import aipass.prax` then `from aipass.prax.apps.modules.logger import logger`
   - **NOTE:** Drone is NOT a library service - it's a CLI router, never imported

### Same-Branch Handler Imports - ALLOWED

Handlers within the SAME BRANCH can import each other freely, even across packages:

```python
# flow/apps/handlers/plan/create.py
from aipass.flow.apps.handlers.registry.load import load_registry  # ✅ OK - same branch
from aipass.flow.apps.handlers.json.json_handler import log_operation  # ✅ OK - same branch
```

**Rationale:** Handlers are unique to each branch. The security boundary is at the BRANCH level, not package level. Trying to enforce package-level isolation adds complexity without benefit.

### Cross-Branch Handler Imports - BLOCKED

**Absolute rule:** Never import another branch's handlers. Hard security block.

```python
# ❌ WRONG - reaching into Prax handlers from Flow
from aipass.prax.apps.handlers.logging.setup import get_logger

# ✅ RIGHT - import Prax module (public API)
from aipass.prax.apps.modules.logger import system_logger as logger
```

```python
# ❌ WRONG - reaching into CLI handlers from Spawn
from aipass.cli.apps.handlers.error_handler import track_operation

# ✅ RIGHT - import CLI module (public API)
from aipass.cli.apps.modules.error_tracking import track_operation
```

### Security Guard Implementation

**Location:** Each branch's `handlers/__init__.py`

**Reference implementation:** `<project_root>/prax/apps/handlers/__init__.py`

**How it works:**
1. Guard runs at import time when `handlers/` package is imported
2. Walks the call stack to find the real caller file
3. Extracts the actual import statement from code context
4. Checks if caller is from the same branch
5. If external caller → raises `ImportError` with detailed message

**Example error output:**

```
============================================================
ACCESS DENIED: Cross-branch handler import blocked
============================================================
  Caller branch: flow
  Caller file:   list_plans.py
  Blocked:       from aipass.prax.apps.handlers.logging.setup import get_logger

  Handlers are internal to their branch.
  Use the module API instead:
    from aipass.prax.apps.modules.<module> import <function>

  Example:
    from aipass.prax.apps.modules.logger import logger

  For full standards guide:
    drone @seedgo handlers
============================================================
```

**Known limitation:** Python module caching means the guard only runs ONCE per Python process. If a valid internal import runs first, subsequent external imports in the same process bypass the guard. This catches violations at development time, not runtime.

### Why This Matters

**Without boundaries:**
- Fragile dependencies (change handler, break unknown consumers)
- No service contract (anyone can reach into your guts)
- Debugging nightmares (why did Flow break when we changed Prax?)

**With boundaries:**
- Clean contracts between services
- Safe to refactor handler internals
- Dependencies are explicit at module level

### Service Contracts

Each library service defines what it exposes:

| Service | Exposes via Modules | Handlers (Internal) |
|---------|---------------------|---------------------|
| Prax | logger, watcher | logging/*, watch/* |
| CLI | header, success, error, warning | output/*, formatting/* |
| API | get_response | llm/*, cache/* |
| Memory Bank | vector operations | storage/*, search/* |

**Modules are the contract. Handlers are the implementation.**

**NOTE:** Drone is NOT in this table because it's a CLI router, not a library service. Branches receive commands FROM Drone (via CLI), they never import it.

### Transitive Dependencies

Example with library services:
- Flow imports Prax
- Flow gets logging capabilities
- Flow does NOT import internal Prax dependencies
- Prax owns its internal implementation relationships

**You import the service that owns the capability.** You don't care about its internal dependencies.

**Important:** CLI branches like Flow, Seedgo, AI_Mail don't import each other or Drone. They're invoked via `drone @branch command`, not imported.

---

## Drone Architecture - CLI Router, Not Library

**Status:** ✅ Critical Architecture Rule (2025-11-29)

**Core principle:** Drone is a CLI router that resolves @ symbols and routes commands to branches. It is NEVER imported as a library.

### What Drone Does

Drone routes commands from CLI to branches:
```bash
drone @flow create "new plan"
# Drone resolves @flow → <project_root>/flow/flow.py
# Drone runs: python3 <project_root>/flow/flow.py create "new plan"
```

The @ symbol is resolved by Drone BEFORE the command reaches the branch.

### What Branches Receive

When a branch is invoked via Drone:
1. Drone has already resolved all @ symbols in the command
2. Branch receives clean arguments without @ symbols
3. Branch never sees or handles @ resolution
4. Branch never imports Drone

**Example:**
```bash
# User types:
drone @flow create @project1 --name "test"

# Drone resolves @ symbols:
@flow → <project_root>/flow/flow.py
@project1 → <project_root>/projects/project1

# Flow receives:
sys.argv = ["flow.py", "create", "<project_root>/projects/project1", "--name", "test"]
```

### Architectural Debt - @ Handling in Branches

**If you see this pattern in a branch, it's architectural debt:**

```python
# ❌ WRONG - Branch should NEVER handle @ resolution
from aipass.drone.apps.modules.resolve import resolve_path

def some_function(path_arg):
    if "@" in path_arg:
        resolved = resolve_path(path_arg)  # NO! Drone already did this!
```

**Why this is wrong:**
1. Drone resolves @ BEFORE calling the branch
2. Branch never receives @ symbols (already resolved)
3. Importing Drone creates unnecessary coupling
4. Violates single responsibility (routing vs execution)

**If a branch has @ handling code:**
- It's legacy from before Drone architecture was clarified
- Should be removed
- Branch should expect pre-resolved paths

### The Correct Pattern

**Branch receives clean, resolved arguments:**

```python
# ✅ CORRECT - Branch expects resolved paths
def create_plan(project_path: str, name: str):
    """
    Args:
        project_path: Absolute path to project (already resolved by Drone)
        name: Plan name
    """
    # Just use the path - no @ handling needed
    plan_file = Path(project_path) / "plans" / f"{name}.json"
```

### Two Types of Branches (Updated)

**1. CLI Tools** - Invoked via Drone, never imported:
- Flow, Seedgo, AI_Mail, Spawn, **Drone itself**
- Usage: `drone @branch command`
- Communication: Via CLI arguments (@ pre-resolved)
- Never import each other

**2. Library Services** - Imported by other code:
- Prax (logging), CLI (formatting), API (LLM calls), Memory Bank (vectors)
- Usage: `from aipass.prax.apps.modules.logger import logger`
- Communication: Via Python imports
- Can be imported by any branch

**Drone is special:** It's a CLI tool that routes TO other CLI tools, but is never imported.

### Summary

- **Drone = CLI router** (resolves @, routes commands)
- **Branches = CLI executors** (receive pre-resolved paths)
- **If branch imports Drone** = architectural debt
- **If branch handles @** = architectural debt
- **@ resolution happens ONCE** (in Drone, before branch invocation)

---

## File Size Guidelines

**Target:** <300 lines ideal, 500-700 acceptable, 700+ signals need for splitting.

### Why File Size Matters

**AI comprehension drops with file size:**
- **<300 lines:** AI quick scan, full comprehension, few errors
- **300-500 lines:** Good - manageable for AI and humans
- **500-700 lines:** Getting heavy - AI context starts degrading
- **700+ lines:** AI makes more errors, humans struggle to scan

**Human factor:**
- 300-line file = scan in 1 minute, hold in working memory
- 2000-line file = overwhelming, can't comprehend structure

**Context efficiency:**
- Small files = faster processing, cleaner context
- Agent can process large file separately, return summary (keep main context clean)

### Real Examples From Codebase

**✅ GOOD - Single-purpose handlers:**

```
json_handler.py:           279 lines  (JSON file operations - seedgo)
                          356 lines  (spawn version)
decorators.py:            257 lines  (Error decorators)
formatters.py:            194 lines  (Console formatting)
result_types.py:          248 lines  (Result type definitions)
metadata.py:              119 lines  (Branch metadata)
prompts.py:                72 lines  (CLI prompts - seedgo)
                           59 lines  (spawn version)
```

**These are perfect:** Each file has single clear purpose. AI processes fast, minimal context burn.

**⚠️ GETTING HEAVY - Complex handlers:**

```
file_ops.py:              845 lines  (Branch file operations - spawn)
                          892 lines  (Other branches)
                          981 lines  (spawn - most complex)
json_ops.py:              762 lines  (JSON migrations - spawn)
```

**Why still okay:**
- Complex domain (many related operations)
- Well-structured with clear sections
- Breaking up would create artificial boundaries
- Functions are small and focused

**❌ ANTI-PATTERN - Should be split:**

```
hypothetical_god_object.py:  2000+ lines
```

**Problems:**
- AI context degradation → more errors
- Human overwhelm → can't scan quickly
- Mixed concerns → multiple domains tangled
- Change risk → touching one thing breaks others

### When 700+ Lines Is Okay

**Complex domains with many related operations:**

```python
# json_ops.py (762 lines in spawn)
# All JSON migration operations - breaking up would separate related logic

def migrate_key(data, old_key, new_key):
    # 20 lines

def migrate_structure_add_field(data, field, default):
    # 25 lines

def migrate_structure_rename_field(data, old, new):
    # 30 lines

# ... 20 more migration functions
```

**Why acceptable:** All operations related to JSON migrations. Breaking into multiple files would make finding operations harder.

### When to Split

**Signals you need to split:**

1. **Multiple domains mixed:** "This file handles JSON AND registry AND error logging"
2. **"God object" syndrome:** "This does everything"
3. **Scrolling fatigue:** "Where was that function again?"
4. **Merge conflicts:** Multiple devs editing same file constantly
5. **Hard to name:** "handler_utils_ops_helpers.py" signals lack of focus

**How to split:**

```
# Before: heavy_handler.py (1200 lines)
- 400 lines: JSON operations
- 300 lines: File operations
- 500 lines: Registry operations

# After: Split by subdomain
heavy_handler/
  ├── __init__.py         → Public API
  ├── json_ops.py         → 400 lines
  ├── file_ops.py         → 300 lines
  └── registry_ops.py     → 500 lines
```

### File Size Summary

**Guidelines:**
- **<300 lines:** Perfect - keep this as target
- **300-500:** Good - still manageable
- **500-700:** Watch it - ensure single clear purpose
- **700+:** Consider splitting unless truly cohesive domain

**Remember:** These are guidelines, not hard limits. Cohesive 700-line file beats artificial split into 3 poorly-organized 250-line files.

---

## Domain Organization

**Organize by business purpose, not technical role.**

### The Pattern

```
handlers/
  ├── json/           → Everything about JSON operations
  ├── error/          → Everything about error handling
  ├── cli/            → Everything about user interaction
  ├── branch/         → Everything about branch lifecycle
  ├── registry/       → Everything about registry management
  └── standards/      → Everything about standards checking
```

### Why Domain Organization Works

**Technical organization (ANTI-PATTERN):**

```
handlers/
  ├── utils/          → What kind of utils? For what?
  ├── helpers/        → Helping with what?
  ├── operations/     → What operations?
  └── validators/     → Validating what?
```

**Problem:** "I need to validate JSON" → check validators/ AND utils/ AND operations/ maybe?

**Domain organization:**

"I need to validate JSON" → `handlers/json/` (everything JSON-related is there)

**Mental model:**
- Technical organization: requires mental translation ("What technical category is this?")
- Domain organization: direct mapping ("What am I working with?")

### Real Example - Seedgo Handlers

**Current structure:**

```
<project_root>/seedgo/apps/standards/aipass/handlers/
  ├── json/
  │   ├── json_handler.py          → JSON file operations (279 lines)
  │   └── test_auto_detection.py   → Tests
  ├── standards/
  │   ├── architecture_check.py    → Architecture validation (29 lines)
  │   ├── cli_check.py             → CLI standards check (29 lines)
  │   ├── imports_check.py         → Import validation (30 lines)
  │   ├── cli_content.py           → CLI content generation (96 lines)
  │   ├── handlers_content.py      → Handlers standards (79 lines)
  │   └── [other content handlers]  → ~60-140 lines each
  ├── cli/
  │   └── prompts.py               → User prompts (72 lines)
  ├── domain1/
  │   └── ops.py                   → Domain operations (103 lines)
  └── domain2/
      └── ops.py                   → Domain operations
```

**Benefits:**
1. **Fast navigation:** Need JSON? → `json/`
2. **Clear boundaries:** All JSON operations in one place
3. **Easy extension:** Add new JSON operation → obvious where it goes
4. **Marketplace ready:** Grab entire `json/` package → self-contained

### Real Example - Spawn Handlers

**Branch/registry/error separation:**

```
<project_root>/spawn/apps/handlers/
  ├── branch/
  │   ├── file_ops.py       → 845 lines (file operations)
  │   ├── metadata.py       → 119 lines (branch metadata)
  │   ├── registry.py       → 259 lines (branch registry)
  │   └── placeholders.py   → 234 lines (placeholder handling)
  ├── registry/
  │   ├── meta_ops.py       → 358 lines (registry operations)
  │   └── registry_ignore.py → 134 lines (ignore patterns)
  ├── error/
  │   ├── decorators.py     → 257 lines (error decorators)
  │   ├── formatters.py     → 194 lines (output formatting)
  │   ├── logger.py         → 235 lines (error logging)
  │   └── result_types.py   → 248 lines (result types)
  ├── json/
  │   ├── json_handler.py   → 356 lines (JSON operations)
  │   └── json_ops.py       → 762 lines (JSON migrations)
  └── cli/
      └── prompts.py        → 59 lines (user prompts)
```

**Note:** Spawn handlers currently import from `aipass.cli.apps.handlers.error` for error tracking. This is the service provider exception - error handlers are infrastructure used across all branches.

**Notice:**
- Each domain self-contained
- Clear separation (branch ≠ registry ≠ error)
- File sizes manageable within domains
- Easy to understand what each package does

### Domain Naming Standards

**Use business/feature names, not technical terms:**

**✅ GOOD:**
- `branch/` - operations on branches
- `json/` - JSON file handling
- `registry/` - registry management
- `standards/` - standards checking
- `ai_mail/` - AI mail system

**❌ BAD:**
- `utils/` - too generic, what kind?
- `helpers/` - helps with what?
- `core/` - what's "core" vs not core?
- `common/` - common to what?

**Exception:** `error/` and `cli/` are technical but clearly scoped. Everyone knows what "error handling" means.

### When to Create New Domain

**Create new domain package when:**

1. **Distinct business purpose:** "This is about AI mail, not JSON or branches"
2. **Self-contained logic:** Could be marketplace package
3. **Clear naming:** Can give it obvious domain name
4. **Multiple files:** Not just one 50-line file (put in existing domain first)

**Add to existing domain when:**

1. **Related to existing domain:** "This is JSON validation" → add to `json/`
2. **Small addition:** Single small file fits in existing package
3. **Shared concepts:** Uses same types/models as existing domain

### Package Structure Within Domain

**Each domain package:**

```
domain_name/
  ├── __init__.py     → Public API exports
  ├── core_ops.py     → Main operations
  ├── helpers.py      → Domain-specific helpers (optional)
  └── types.py        → Domain-specific types (optional)
```

**Example - error package:**

```
error/
  ├── __init__.py       → Exports OperationResult, track_operation, etc.
  ├── result_types.py   → Core types (foundation)
  ├── logger.py         → Logging operations (uses result_types)
  ├── formatters.py     → Output formatting (uses result_types)
  └── decorators.py     → Decorators (uses all above)
```

**Dependency flow within package:** Foundation types → specific operations → decorators/facades

---

## Handler Testing Requirements

**Status:** Testing infrastructure in progress (not yet standardized).

### Current Reality

**No formal test infrastructure yet:**
- AIPass is custom system, building from scratch
- JSONs + Prax logs = current debugging infrastructure
- Fast iteration with manual testing
- pytest framework (future direction)

### Testing Approach When Infrastructure Ready

**Three testing levels for handlers:**

### 1. Unit Tests - Pure Functions

**Test handlers in isolation:**

```python
# test_json_handler.py
import pytest
from aipass.seedgo.apps.handlers.json import json_handler

def test_validate_json_structure_config():
    """Test config JSON validation"""
    valid_config = {
        "module_name": "test",
        "version": "1.0.0",
        "config": {}
    }
    assert json_handler.validate_json_structure(valid_config, "config") is True

def test_validate_json_structure_invalid():
    """Test invalid JSON rejected"""
    invalid_config = {"random": "data"}
    assert json_handler.validate_json_structure(invalid_config, "config") is False
```

**What to test:**
- Input validation
- Data transformations
- Return values
- Edge cases (empty inputs, malformed data)

### 2. Integration Tests - File Operations

**Test handlers with actual files:**

```python
# test_json_handler_integration.py
import pytest
from pathlib import Path
from aipass.seedgo.apps.handlers.json import json_handler

@pytest.fixture
def temp_json_dir(tmp_path):
    """Create temporary JSON directory"""
    json_dir = tmp_path / "seedgo_json"
    json_dir.mkdir()
    # Temporarily override SEEDGO_JSON_DIR
    original = json_handler.SEEDGO_JSON_DIR
    json_handler.SEEDGO_JSON_DIR = json_dir
    yield json_dir
    json_handler.SEEDGO_JSON_DIR = original

def test_ensure_module_jsons_creates_files(temp_json_dir):
    """Test JSON auto-creation"""
    json_handler.ensure_module_jsons("test_module")

    assert (temp_json_dir / "test_module_config.json").exists()
    assert (temp_json_dir / "test_module_data.json").exists()
    assert (temp_json_dir / "test_module_log.json").exists()

def test_log_operation_rotation(temp_json_dir):
    """Test log rotation when max entries exceeded"""
    # Create module with max 5 entries
    # ... test implementation
```

**What to test:**
- File creation/deletion
- File reading/writing
- Directory operations
- Error conditions (permissions, missing files)

### 3. Mock External Dependencies

**Handler shouldn't depend on external services running:**

```python
# test_registry_handler.py
import pytest
from unittest.mock import patch, Mock
from aipass.seedgo.apps.handlers.registry import registry_ops

@patch('aipass.seedgo.apps.handlers.registry.registry_ops.Path.exists')
def test_validate_registry_missing_file(mock_exists):
    """Test registry validation when file missing"""
    mock_exists.return_value = False

    result = registry_ops.validate_registry()
    assert result.status == "error"
    assert "not found" in result.message
```

**What to mock:**
- File system operations (when testing logic, not I/O)
- Network calls
- External APIs
- System commands

### 4. Test Error Paths

**Don't just test happy path:**

```python
def test_load_json_corrupted_file(temp_json_dir):
    """Test handling corrupted JSON file"""
    # Create corrupted JSON
    corrupted_file = temp_json_dir / "test_config.json"
    corrupted_file.write_text("{ invalid json }")

    result = json_handler.load_json("test", "config")
    # Should return None and log error, not crash
    assert result is None

def test_log_operation_no_permissions(temp_json_dir):
    """Test handling permission denied"""
    # Make directory read-only
    temp_json_dir.chmod(0o444)

    result = json_handler.log_operation("test_op")
    assert result is False  # Operation failed gracefully
```

**What to test:**
- Corrupted files
- Missing dependencies
- Permission errors
- Invalid inputs
- Edge cases

### Test Organization

**Mirror handler structure:**

```
handlers/
  ├── json/
  │   ├── json_handler.py
  │   └── json_ops.py
  └── error/
      ├── decorators.py
      └── formatters.py

tests/handlers/
  ├── json/
  │   ├── test_json_handler.py          → Unit tests
  │   └── test_json_handler_integration.py → Integration tests
  └── error/
      ├── test_decorators.py
      └── test_formatters.py
```

### Test File Naming

**Standard pattern:**
- `test_*.py` - pytest discovery
- `test_{handler_name}.py` - unit tests
- `test_{handler_name}_integration.py` - integration tests

### Current Testing Reality

**Until pytest infrastructure complete:**

1. **Manual testing:** Run handlers, check JSONs
2. **Prax logs:** Watch system_log for errors
3. **JSON inspection:** Check created files match expectations
4. **Console output:** Verify user-facing messages

**Example manual test:**

```bash
# Test json_handler auto-creation
rm -rf <project_root>/seedgo/seedgo_json/test_*

# Run handler
python3 -c "from aipass.seedgo.apps.handlers.json import json_handler; json_handler.log_operation('test_op')"

# Check created files
ls <project_root>/seedgo/seedgo_json/
# Expected: test_module_config.json, test_module_data.json, test_module_log.json

# Inspect contents
cat <project_root>/seedgo/seedgo_json/test_module_log.json
# Verify: operation logged with timestamp
```

### Future Direction

**When pytest framework ready:**

1. **Write tests for new handlers** (test-driven development)
2. **Gradually add tests to existing handlers** (priority: critical paths)
3. **CI/CD integration** (run tests on commit)
4. **Coverage tracking** (identify untested code)

**But remember:** No tests doesn't mean no quality control. JSONs + logs + manual testing works until automated testing infrastructure ready.

---

## Approved Handler Patterns

**Status:** ✅ Standard (2026-02-10)

Patterns observed across production handlers that solve real problems. Each emerged from working code and was reviewed for standards compliance.

### 1. Callback Injection Pattern

**Problem:** Handlers need to call module-layer functions (e.g., send email, fire events) but cannot import modules (handler independence rule).

**Solution:** Module layer injects a callback function into the handler at startup. Handler stores it in a module-level variable and calls it when needed.

#### Parameter Injection (setter function)

**Reference:** `trigger/apps/handlers/events/error_detected.py`

```python
# Handler layer - stores callback, never imports modules
_send_email: Optional[Callable[..., bool]] = None

def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """
    Set the callback function for sending emails.
    Must be called by the module/registry layer before events fire.
    This avoids handler importing from modules (maintains independence).
    """
    global _send_email
    _send_email = callback

def handle_error_detected(event_data: Dict[str, Any]) -> None:
    """Handle error_detected events."""
    if _send_email is None:
        return  # No callback = silent no-op
    # ... build notification, then:
    _send_email(to=recipient, subject=subject, message=body, auto_execute=True)
```

```python
# Module layer - injects the callback at startup
from aipass.trigger.apps.handlers.events.error_detected import set_send_email_callback
set_send_email_callback(send_email_direct)
```

**Reference:** `trigger/apps/handlers/log_watcher.py`

```python
# Same pattern for event firing
_fire_event: Optional[Callable[..., None]] = None

def set_event_callback(callback: Callable[..., None]) -> None:
    """Set the callback function for firing events."""
    global _fire_event
    _fire_event = callback
```

**When to use:**
- Handler needs to call a module-layer function
- Direct import would violate handler independence
- Callback is set once at startup and used throughout handler lifetime

**When NOT to use:**
- Handler can accomplish its goal with pure return values
- Only one call site exists (just return data and let module call)

---

### 2. Rate-Limited Notifications Pattern

**Problem:** Event-driven handlers can fire rapidly, overwhelming recipients with notifications.

**Solution:** Track timestamps per recipient in a module-level dict. Prune old entries on each call, reject if count exceeds limit within window.

**Reference:** `ai_mail/apps/handlers/email/delivery.py` (desktop notifications)

```python
_NOTIFICATION_TIMESTAMPS: Dict[str, List[float]] = {}
_NOTIFICATION_MAX = 3
_NOTIFICATION_WINDOW = 30.0  # seconds

def _send_desktop_notification(sender: str, recipient: str, subject: str) -> None:
    """Rate-limited: max 3 notifications per recipient within 30 seconds."""
    now = time.time()
    cutoff = now - _NOTIFICATION_WINDOW

    if recipient in _NOTIFICATION_TIMESTAMPS:
        _NOTIFICATION_TIMESTAMPS[recipient] = [
            t for t in _NOTIFICATION_TIMESTAMPS[recipient] if t > cutoff
        ]
    else:
        _NOTIFICATION_TIMESTAMPS[recipient] = []

    if len(_NOTIFICATION_TIMESTAMPS[recipient]) >= _NOTIFICATION_MAX:
        return  # Rate limited - silently skip

    # ... send notification ...
    _NOTIFICATION_TIMESTAMPS[recipient].append(now)
```

**Reference:** `trigger/apps/handlers/events/error_detected.py` (dispatch throttling)

```python
_dispatch_timestamps: Dict[str, List[float]] = {}
MAX_DISPATCHES_PER_WINDOW = 3
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes

def _is_rate_limited(branch_email: str) -> bool:
    """Check if branch has exceeded dispatch rate limit."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []

    _dispatch_timestamps[branch_email] = [
        ts for ts in _dispatch_timestamps[branch_email] if ts > cutoff
    ]

    return len(_dispatch_timestamps[branch_email]) >= MAX_DISPATCHES_PER_WINDOW
```

**Key principles:**
- Constants at module level (UPPER_CASE, easy to tune)
- Prune before checking (prevents memory leak)
- Silent rejection (caller doesn't need to know)
- Per-recipient tracking (one noisy branch doesn't block others)

---

### 3. Persistent Hash Deduplication with Size Limits

**Problem:** Event handlers need to avoid processing the same event twice, even across restarts.

**Solution:** Hash event content, store hashes in a set with a size cap. Persist to disk for restart survival.

**Reference:** `trigger/apps/handlers/log_watcher.py`

```python
_seen_error_hashes: Set[str] = set()
MAX_SEEN_HASHES = 2000

def _generate_error_hash(source_module: str, message: str) -> str:
    """8-character MD5 hash for deduplication."""
    content = f"{source_module}:{message}"
    return hashlib.md5(content.encode()).hexdigest()[:8]

def _is_duplicate_error(error_hash: str) -> bool:
    """Check if error has been seen before."""
    global _seen_error_hashes

    if error_hash in _seen_error_hashes:
        return True

    _seen_error_hashes.add(error_hash)
    if len(_seen_error_hashes) > MAX_SEEN_HASHES:
        # Evict oldest half when limit exceeded
        _seen_error_hashes = set(list(_seen_error_hashes)[MAX_SEEN_HASHES // 2:])

    _save_seen_hashes()  # Persist to trigger_data.json
    return False
```

**Persistence layer:**

```python
TRIGGER_DATA_FILE = AIPASS_ROOT / "trigger" / "trigger_data.json"

def _load_seen_hashes() -> None:
    """Load persisted dedup hashes from disk on startup."""
    global _seen_error_hashes
    try:
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding='utf-8'))
            _seen_error_hashes = set(data.get('seen_error_hashes', []))
    except Exception:
        _seen_error_hashes = set()  # Start fresh on failure

def _save_seen_hashes() -> None:
    """Persist dedup hashes, merging with existing file content."""
    try:
        data: Dict[str, Any] = {}
        if TRIGGER_DATA_FILE.exists():
            data = json.loads(TRIGGER_DATA_FILE.read_text(encoding='utf-8'))
        data['seen_error_hashes'] = list(_seen_error_hashes)
        TRIGGER_DATA_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception:
        return  # Write failure - hashes remain in memory only
```

**Key principles:**
- Short hashes (8 chars) - unique enough for dedup, memory-efficient
- Size cap with eviction (prevents unbounded growth)
- Merge-on-write (doesn't clobber other keys in the JSON file)
- Silent failure (disk issues don't crash the handler)

---

### 4. Auto-Migration for JSON Schema Upgrades

**Problem:** JSON file schemas evolve over time. Old-format files need to work with new code without manual migration.

**Solution:** Detect old format on load, transform in-place, persist the upgrade.

**Reference:** `ai_mail/apps/handlers/email/delivery.py`

```python
def _migrate_inbox_format(inbox_data: Dict, inbox_file: Path) -> Dict:
    """
    Auto-migrate old inbox format to v2 schema.

    Old format: {"inbox": [...]}
    New format: {"mailbox": "inbox", "total_messages": N, "unread_count": N, "messages": [...]}
    """
    migrated = False

    # Case 0: inbox_data is a list instead of a dict (corrupted)
    if isinstance(inbox_data, list):
        inbox_data = {"messages": inbox_data}
        migrated = True

    # Case 1: Old format with "inbox" key instead of "messages"
    if "inbox" in inbox_data and "messages" not in inbox_data:
        old_messages = inbox_data.pop("inbox", [])
        inbox_data["messages"] = old_messages if isinstance(old_messages, list) else []
        migrated = True

    # Case 2: Missing "messages" key entirely
    if "messages" not in inbox_data:
        inbox_data["messages"] = []
        migrated = True

    # Ensure v2 metadata fields
    for field, default_fn in [
        ("mailbox", lambda: "inbox"),
        ("total_messages", lambda: len(inbox_data["messages"])),
        ("unread_count", lambda: sum(1 for m in inbox_data["messages"] if m.get("status") == "new")),
    ]:
        if field not in inbox_data:
            inbox_data[field] = default_fn()
            migrated = True

    # Persist migration to disk
    if migrated:
        try:
            with open(inbox_file, 'w', encoding='utf-8') as f:
                json.dump(inbox_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Return migrated data even if write fails

    return inbox_data
```

**Key principles:**
- Detect-and-fix, not reject (old data still works)
- Handle multiple migration cases (rename, missing fields, corrupted structure)
- Persist only if changes were made (avoid unnecessary writes)
- Graceful on write failure (in-memory migration still applies)

---

### 5. Direct AIPASS_REGISTRY.json Reads

**Problem:** Handlers need branch routing data but can't import modules. Using subprocess to call drone is slow and fragile.

**Solution:** Read AIPASS_REGISTRY.json directly. It's a stable, well-defined JSON file at a known path.

**Reference:** `ai_mail/apps/handlers/email/delivery.py`

```python
def get_all_branches() -> List[Dict]:
    """Read branch registry directly for email routing."""
    registry_file = Path("<project_root>/AIPASS_REGISTRY.json")

    if not registry_file.exists():
        return []

    try:
        with open(registry_file, 'r', encoding='utf-8') as f:
            registry_data = json.load(f)

        branches = []
        for branch in registry_data.get("branches", []):
            branch_name = branch.get("name", "")
            path = branch.get("path", "")
            email = branch.get("email", "")
            if branch_name and path:
                branches.append({"name": branch_name, "path": path, "email": email})
        return branches
    except Exception:
        return []
```

**Reference:** `trigger/apps/handlers/events/error_detected.py`

```python
AIPASS_REGISTRY_FILE = AIPASS_ROOT / "AIPASS_REGISTRY.json"

def _get_registered_emails() -> set:
    """Read registered branch emails from AIPASS_REGISTRY.json."""
    try:
        if AIPASS_REGISTRY_FILE.exists():
            data = json.loads(AIPASS_REGISTRY_FILE.read_text(encoding='utf-8'))
            return {b["email"] for b in data.get("branches", [])}
    except Exception:
        return set()
    return set()
```

**Key principles:**
- Hardcoded path (`<project_root>/AIPASS_REGISTRY.json`) - it's a system constant
- Read-only (handlers never write to registry)
- Defensive reads (missing file → empty result, not crash)
- No module import needed (pure file I/O)

**When to use:**
- Handler needs branch routing, naming, or path data
- The data is in AIPASS_REGISTRY.json (it usually is)

**When NOT to use:**
- Need to modify the registry (use Spawn module API)
- Need complex registry queries (consider whether a module should handle this)

---

## TODO

- [x] Handler independence rules detailed (2025-11-13)
- [x] File size guidelines with reasoning (2025-11-13)
- [x] Domain organization examples (2025-11-13)
- [x] Package-level exceptions (error handlers, etc.) (2025-11-13)
- [x] Handler testing requirements (2025-11-13)
- [x] Auto-detection pattern documented (2025-11-12)
- [x] Handler boundaries & external access - security guard (2025-11-29)
- [x] Approved handler patterns from production code (2026-02-10)
