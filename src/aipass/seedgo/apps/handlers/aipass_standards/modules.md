# Module Standards
**Status:** Active v1.0
**Date:** 2025-11-13

---

## What This Covers

Standards specific to modules (orchestration layer). Modules coordinate workflows by calling handlers in sequence. They're the conductor, not the orchestra.

---

## Key Principles

- **Thin orchestration, no heavy business logic** - Modules direct, handlers implement
- **Coordinates workflow between handlers** - Call handlers in sequence to complete operations
- **Can import 20+ handlers** - That's fine, better than handlers importing each other
- **Minimal business logic** - Logic belongs in handlers, not modules
- **handle_command(args) -> bool pattern** - Standard entry point for drone routing
- **Each module accepts ONE primary command - no aliases (Session 14 standard)** - Simplify routing logic

### Doors — `apps/modules/door_<subject>.py` (DPLAN-0404, 2026-10-07)

A door is how another branch reaches this branch's handlers. It is a thin re-export and nothing else: it imports only from its OWN branch's `apps.handlers` (plus the stdlib) — a handlers package nested anywhere under the branch's tree is its own, so skills' door may re-export `aipass.skills.lib.telegram.apps.handlers` while `aipass.daemon.lib.x.apps.handlers` stays foreign (2026-10-08) — defines no function or class, carries `__all__`, and every name in `__all__` is one it imported. The checker reads it as a "Door shape" row in place of `handle_command`, and introspection does not ask a door for `print_introspection`. A handler in another branch may import `aipass.<owner>.apps.modules.door_<subject>`: a branch's modules are its public gateway.

```python
"""Door: memory's entry limits, for other branches."""

from aipass.memory.apps.handlers.json.entry_limits import check_file_budget, load_entry_limits

__all__ = ["load_entry_limits", "check_file_budget"]
```

---

## Module Responsibilities

### What Modules SHOULD Do

**1. Orchestrate Workflows**
Call handlers in the right sequence to complete operations:

```python
def create_new_thing(name: str, thing_type: str):
    """Orchestrate creation workflow"""
    # 1. Validate input
    if not validate_input(name, thing_type):
        error("Invalid input")
        return False

    # 2. Check preconditions
    if check_exists(name):
        warning(f"{name} already exists, skipping")
        return True

    # 3. Execute creation
    result = create_thing(name, thing_type)

    # 4. Display result
    if result.success:
        success(f"Created {name}")
    else:
        error(f"Failed to create {name}: {result.reason}")

    return result.success
```

**2. Route Commands**
Parse arguments and dispatch to appropriate functions:

```python
def handle_command(command: str, args: List[str]) -> bool:
    """Route commands to appropriate handlers"""
    if command not in ["cli", "display", "output"]:
        return False  # Not our command

    # Log module usage
    json_handler.log_operation("standard_displayed", {"command": command})

    # Execute workflow
    print_standard()
    return True
```

**3. Import Many Handlers**
Modules are the aggregation point for functionality:

```python
# Service imports (shared infrastructure)
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error

# Domain handler imports (business logic)
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.standards.cli_content import get_cli_standards
from aipass.seedgo.apps.handlers.validation import validate_input
from aipass.seedgo.apps.handlers.operations import create_thing, update_thing
```

**Why 20+ imports is fine:** Better one module imports 20 handlers than handlers importing each other. Dependencies flow ONE direction: modules → handlers.

**4. Light Validation**
Check arguments before calling handlers:

```python
def create_branch(name: str):
    """Create new branch with validation"""
    # Light validation in module
    if not name:
        error("Branch name required")
        return False

    # Heavy validation in handler
    result = validate_branch_name(name)
    if not result.success:
        error(result.reason)
        return False

    # Execute via handler
    return execute_create_branch(name)
```

**5. Use Services**
Leverage service branches for consistent behavior:

```python
# Prax logging service
logger.info("Starting create operation")

# CLI display service
header("Create New Branch", {"Name": branch_name})

# CLI error handling service
@track_operation
def create_branch(name: str):
    """Create branch with automatic error handling"""
    execute_create(name)
    return True
```

### What Modules SHOULD NOT Do

**1. Heavy Business Logic**
Business logic belongs in handlers:

```python
# ❌ BAD - business logic in module
def create_branch(path: str):
    """Module contains business logic"""
    branch_path = Path(path)
    branch_path.mkdir(parents=True, exist_ok=True)

    # Create config file
    config = {
        "name": branch_path.name,
        "created": datetime.now().isoformat(),
        "version": "1.0"
    }
    config_file = branch_path / ".trinity" / "passport.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    # Create handlers directory
    (branch_path / "apps" / "handlers").mkdir(parents=True)

    # Create modules directory
    (branch_path / "apps" / "modules").mkdir(parents=True)

    return True

# ✅ GOOD - orchestrate handler calls
def create_branch(name: str, template: str):
    """Module orchestrates workflow"""
    # Validate via handler
    if not validate_branch_name(name):
        return False

    # Create structure via handler
    result = create_branch_structure(name, template)

    # Initialize config via handler
    if result.success:
        initialize_branch_config(name)

    return result.success
```

**2. Direct File Operations**
Use handlers for file operations:

```python
# ❌ BAD - module does file operations
def update_config(branch: str, key: str, value: str):
    """Module handles files directly"""
    config_path = Path(f"src/aipass/{branch}/.trinity/passport.json")
    with open(config_path) as f:
        config = json.load(f)

    config[key] = value

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

# ✅ GOOD - module calls handler
def update_config(branch: str, key: str, value: str):
    """Module orchestrates via handler"""
    return json_handler.update_key(branch, key, value)
```

**3. Complex Algorithms**
Algorithms belong in handlers:

```python
# ❌ BAD - module contains algorithm
def calculate_scores(data: List[dict]):
    """Module implements scoring algorithm"""
    scores = []
    for item in data:
        # 50 lines of scoring logic
        score = complex_calculation(item)
        scores.append(score)
    return scores

# ✅ GOOD - module calls handler
def calculate_scores(data: List[dict]):
    """Module orchestrates scoring"""
    return scoring_handler.calculate_all_scores(data)
```

---

## File Size Expectations

Based on analysis of `src/aipass/seedgo/apps/modules/` (14 modules):

**Size Distribution:**
- **110-135 lines:** Simple modules (single operation, minimal workflow)
  - `imports_standard.py` - 110 lines
  - `modules_standard.py` - 114 lines
  - `naming_standard.py` - 113 lines

- **135-155 lines:** Standard modules (multiple operations, some complexity)
  - `cli_standard.py` - 135 lines (display + demo offer)
  - `create_thing.py` - 152 lines (showroom with demos)

- **250-300 lines:** Complex modules (multiple workflows, batch operations)
  - `test_cli_errors.py` - 283 lines (4 examples + demos)

**Guidelines:**

| Line Count | Classification | Indicators | Action |
|------------|----------------|------------|--------|
| < 150 | Simple | Single workflow, minimal branching | Perfect size |
| 150-250 | Standard | Multiple workflows, some complexity | Good size |
| 250-400 | Complex | Many workflows, batch operations | Watch it |
| 400-600 | Heavy | Many commands, extensive orchestration | Consider splitting |
| 600+ | Too Large | Context degradation begins | Split into domains |

**Why File Size Matters:**

1. **AI comprehension** - Small files process faster with fewer errors
2. **Human scanning** - 150-line file scans in 30 seconds, 600-line file takes 3 minutes
3. **Context efficiency** - Agent can summarize separately, keep main context clean
4. **Change isolation** - Smaller files = smaller blast radius for changes

**Example: CLI Display Module**
`<project_root>/cli/apps/modules/display.py` - 184 lines
- Public API for 5 display functions
- Light orchestration over handler implementation
- Includes docstrings, examples, demo
- Perfect size for AI + human comprehension

---

## Orchestration Patterns

### Pattern 1: Linear Workflow

Execute steps in sequence, stop on failure:

```python
def create_branch(name: str):
    """Linear workflow - each step depends on previous"""
    # Step 1: Validate
    if not validate_branch_name(name):
        error("Invalid branch name")
        return False

    # Step 2: Check preconditions
    if branch_exists(name):
        warning(f"Branch {name} already exists")
        return True

    # Step 3: Create structure
    result = create_branch_structure(name)
    if not result.success:
        error(f"Failed to create structure: {result.reason}")
        return False

    # Step 4: Initialize config
    initialize_config(name)

    # Step 5: Display success
    success(f"Branch {name} created successfully")
    return True
```

**Use when:** Steps must execute in order, each depends on previous success.

### Pattern 2: Batch Operations with Collection

Process multiple items, collect results:

```python
@collect_results
def update_all_branches() -> List[OperationResult]:
    """Batch workflow - collect all results"""
    results = []

    branches = get_all_branches()
    for branch in branches:
        result = update_branch(branch)
        results.append(result)

    return results  # Decorator displays summary
```

**Use when:** Processing multiple items, want summary of successes/failures.

### Pattern 3: Conditional Workflow

Branch based on conditions or user input:

```python
def publish_standard(standard_name: str):
    """Conditional workflow based on user choice"""
    # Display current standard
    print_standard(standard_name)

    # Offer next action
    response = input("Press Enter to see demo (or 'n' to skip): ").strip().lower()

    if response != 'n':
        run_demo(standard_name)
    else:
        console.print("Demo skipped")
```

**Use when:** User choice or runtime conditions determine next steps.

**Reference:** `src/aipass/seedgo/apps/modules/cli_standard.py` (135 lines)
```python
def print_standard():
    """Print cli standards - orchestrates handler call"""
    console.print()
    header("CLI Standards")
    console.print()
    console.print(get_cli_standards())  # Handler call
    console.print()
    console.print("─" * 70)
    console.print()

    # Conditional: offer demo
    response = input("Press Enter to see CLI demo (or 'n' to skip): ").strip().lower()
    if response != 'n':
        run_demo()  # Handler call
```

### Pattern 4: Error Handling with Decorators

Let decorators handle error catching and logging:

```python
@track_operation
def create_thing(name: str, thing_type: str):
    """Decorator handles errors automatically"""
    # No try/except needed
    validate_input(name, thing_type)
    result = create_operation(name, thing_type)
    return result  # Decorator formats output
```

**Use when:** Standard error handling is sufficient (most cases).

**Reference:** `src/aipass/seedgo/apps/modules/test_cli_errors.py`
```python
@track_operation
def example_success_operation():
    """Example operation that succeeds"""
    # Just return True - decorator handles everything
    return True

@track_operation
def example_failure_operation():
    """Example operation that fails"""
    # Raise exception - decorator catches and formats
    raise FileNotFoundError("Example file not found")
```

### Pattern 5: Service Integration

Combine multiple services for complete workflow:

```python
def create_and_configure(name: str):
    """Orchestrate multiple services"""
    # CLI service - display
    header("Create Branch", {"Name": name})

    # Prax service - logging
    logger.info(f"Starting branch creation: {name}")

    # Domain handlers - business logic
    result = create_branch_structure(name)

    # JSON handler - tracking
    json_handler.log_operation("branch_created", {
        "name": name,
        "success": result.success
    })

    # CLI service - output
    if result.success:
        success("Branch created successfully")
    else:
        error(f"Creation failed: {result.reason}")

    return result.success
```

**Use when:** Operation needs multiple system services.

**Reference:** `src/aipass/seedgo/apps/modules/cli_standard.py`
```python
def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'cli' command"""
    if command != "cli":
        return False

    # JSON handler - tracking
    json_handler.log_operation(
        "standard_displayed",
        {"command": command}
    )

    # Execute workflow
    print_standard()  # Uses CLI service internally
    return True
```

---

## When to Split Modules

### Clear Signs a Module Needs Splitting

**1. Handling 10+ Distinct Commands**

If `handle_command()` has 10+ branches, split by domain:

```python
# ❌ TOO MANY COMMANDS IN ONE MODULE
def handle_command(command: str, args: List[str]) -> bool:
    if command == "create": return create_handler()
    if command == "update": return update_handler()
    if command == "delete": return delete_handler()
    if command == "list": return list_handler()
    if command == "search": return search_handler()
    if command == "validate": return validate_handler()
    if command == "migrate": return migrate_handler()
    if command == "backup": return backup_handler()
    if command == "restore": return restore_handler()
    if command == "sync": return sync_handler()
    if command == "publish": return publish_handler()
    # ... 5 more commands
    return False

# ✅ SPLIT INTO DOMAIN MODULES
# modules/create_operations.py - create, update, delete
# modules/query_operations.py - list, search, validate
# modules/maintenance_operations.py - migrate, backup, restore, sync
```

**2. Multiple Unrelated Workflows**

If module handles distinct domains, split by domain:

```python
# ❌ MIXED DOMAINS
# single_module.py contains:
# - Branch management (create, delete, list branches)
# - Standard documentation (display, validate standards)
# - Testing infrastructure (run tests, check coverage)

# ✅ SPLIT BY DOMAIN
# modules/branch_management.py
# modules/standards_display.py
# modules/testing_operations.py
```

**3. File Approaching 600+ Lines**

Context degradation begins around 600 lines:

```python
# Check current size
wc -l module.py

# If > 600 lines, split by logical sections:
# - Commands group 1 → module_operations1.py
# - Commands group 2 → module_operations2.py
# - Helper functions → handlers (if they have logic)
```

**4. Team Members Working on Different Sections**

If git shows frequent merge conflicts in same file:

```bash
# Check git history
git log --oneline module.py

# If many developers editing same file, split to reduce conflicts
```

**5. Can Identify Clear Sub-Domains**

If you can name distinct responsibility areas:

```python
# Large standards module could split into:
# - standards_display.py (show standards)
# - standards_validate.py (check compliance)
# - standards_generate.py (create documentation)
```

### How to Split Effectively

**Step 1: Identify Domains**
Group related commands by purpose:

```python
# Original: standards_module.py (450 lines)
# Commands: display, validate, checklist, generate, publish, sync

# Group by domain:
# Display operations: display, publish
# Validation operations: validate, checklist
# Generation operations: generate, sync
```

**Step 2: Create New Modules**

```python
# modules/standards_display.py (150 lines)
def handle_command(command: str, args: List[str]) -> bool:
    if command in ["display", "publish"]:
        # Display logic
        return True
    return False

# modules/standards_validate.py (150 lines)
def handle_command(command: str, args: List[str]) -> bool:
    if command in ["validate", "checklist"]:
        # Validation logic
        return True
    return False

# modules/standards_generate.py (150 lines)
def handle_command(command: str, args: List[str]) -> bool:
    if command in ["generate", "sync"]:
        # Generation logic
        return True
    return False
```

**Step 3: Verify Auto-Discovery**

Modules are auto-discovered by main entry point, no manual registration needed:

```bash
# Both modules automatically discovered
python3 branch.py standards display
python3 branch.py standards validate
```

### When NOT to Split

**1. Module Under 400 Lines**
If file is under 400 lines and handles related operations, keep together.

**2. Commands Are Tightly Coupled**
If commands share significant workflow steps, splitting creates duplication.

**3. Single Responsibility**
If module already has one clear domain, don't split arbitrarily.

---

## Module Testing Requirements

### Integration Tests: Test Full Workflows

Modules orchestrate workflows, so test the complete operation:

```python
# tests/test_standards_module.py
import pytest
from aipass.seedgo.apps.modules.cli_standard import handle_command, print_standard

def test_handle_command_cli():
    """Test cli command routing"""
    result = handle_command("cli", [])
    assert result == True

def test_handle_command_unknown():
    """Test unknown command rejection"""
    result = handle_command("unknown", [])
    assert result == False

def test_print_standard_executes():
    """Test standard display workflow"""
    # Should not raise exception
    print_standard()
```

### Mock Handler Calls for Unit Tests

Module logic can be tested without executing handlers:

```python
# tests/test_branch_module.py
from unittest.mock import patch, MagicMock
from my_branch.apps.modules.branch_ops import create_branch

def test_create_branch_validates_input():
    """Test validation step in workflow"""
    with patch('my_branch.apps.handlers.validation.validate_branch_name') as mock_validate:
        mock_validate.return_value = False

        result = create_branch("invalid-name")

        assert result == False
        mock_validate.assert_called_once_with("invalid-name")

def test_create_branch_creates_structure():
    """Test creation step in workflow"""
    with patch('my_branch.apps.handlers.validation.validate_branch_name') as mock_validate:
        with patch('my_branch.apps.handlers.operations.create_branch_structure') as mock_create:
            mock_validate.return_value = True
            mock_create.return_value = MagicMock(success=True)

            result = create_branch("valid_name")

            assert result == True
            mock_create.assert_called_once_with("valid_name")
```

### Test Command Routing

Verify commands are routed to correct functions:

```python
# tests/test_routing.py
def test_handle_command_routes_correctly():
    """Test command routing to functions"""
    with patch('module.print_standard') as mock_print:
        result = handle_command("cli", [])

        assert result == True
        mock_print.assert_called_once()

def test_handle_command_returns_false_for_unknown():
    """Test unknown commands return False"""
    result = handle_command("not_a_command", [])
    assert result == False
```

### Test Argument Parsing

If module parses arguments, test parsing logic:

```python
# tests/test_args.py
def test_parse_create_args():
    """Test argument parsing for create command"""
    args = ["new_branch", "standard"]
    name, template = parse_create_args(args)

    assert name == "new_branch"
    assert template == "standard"

def test_parse_create_args_defaults():
    """Test default arguments"""
    args = ["new_branch"]
    name, template = parse_create_args(args)

    assert name == "new_branch"
    assert template == "basic"  # default
```

### Test Error Handling Paths

Verify error conditions are handled correctly:

```python
# tests/test_error_paths.py
def test_create_branch_handles_validation_failure():
    """Test workflow stops on validation failure"""
    with patch('handlers.validate_branch_name') as mock_validate:
        mock_validate.return_value = False

        result = create_branch("bad-name")

        assert result == False

def test_create_branch_handles_creation_failure():
    """Test workflow handles creation errors"""
    with patch('handlers.validate_branch_name') as mock_validate:
        with patch('handlers.create_branch_structure') as mock_create:
            mock_validate.return_value = True
            mock_create.return_value = MagicMock(success=False, reason="Permission denied")

            result = create_branch("good_name")

            assert result == False
```

### Test Decorator Integration

If using error handling decorators, test they work:

```python
# tests/test_decorators.py
from aipass.cli.apps.modules import track_operation

def test_track_operation_success():
    """Test decorator handles success"""
    @track_operation
    def test_operation():
        return True

    result = test_operation()
    assert result.success == True

def test_track_operation_exception():
    """Test decorator catches exceptions"""
    @track_operation
    def test_operation():
        raise FileNotFoundError("Test error")

    result = test_operation()
    assert result.success == False
    assert "Test error" in result.reason
```

### Testing Best Practices

1. **Test workflows, not implementation** - Test that steps execute in order, not how handlers work
2. **Mock external dependencies** - Don't require file system, network, or other branches
3. **Test error paths** - Verify graceful handling of failures
4. **Test edge cases** - Empty args, invalid input, missing files
5. **Integration over unit** - Modules orchestrate, so integration tests are primary
6. **Fast tests** - Mock slow operations (file I/O, network calls)

---

## Reference Examples

**Simple module (135 lines):** `src/aipass/seedgo/apps/modules/cli_standard.py`
- Single workflow (display standard)
- Conditional branching (offer demo)
- Service integration (CLI + JSON handler)

**Complex module (283 lines):** `src/aipass/seedgo/apps/modules/test_cli_errors.py`
- Multiple example workflows
- Decorator demonstrations
- Service integration examples
- Display integration

**Showroom module (152 lines):** `src/aipass/seedgo/apps/modules/create_thing.py`
- Documents module patterns
- Shows orchestration flow
- Demonstrates good practices

**Service module (184 lines):** `<project_root>/cli/apps/modules/display.py`
- Public API wrapper
- Thin orchestration over handlers
- Multiple function exports

---

## TODO

- [x] Module responsibilities detailed
- [x] File size expectations (300-700 lines typical)
- [x] Orchestration patterns
- [x] When to split modules
- [x] Module testing requirements
- [ ] Performance considerations for large batch operations
- [ ] Async/parallel orchestration patterns
- [ ] Module versioning and compatibility
