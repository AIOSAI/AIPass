# Architecture Standards
**Status:** Draft v1
**Date:** 2025-11-11

---

## The 3-Layer Pattern

Every branch follows this structure:

```
apps/branch.py (Main Entry Point)
    ↓ auto-discovers modules
    ↓ routes commands

apps/modules/ (Orchestration Layer)
    ↓ coordinates workflow
    ↓ imports handlers
    ↓ minimal business logic

apps/handlers/ (Implementation Layer)
    ↓ organized by domain
    ↓ contains ALL business logic
    ↓ self-contained and transportable
```

**WHY:** Without separation, business logic, workflow, and routing tangle together. A 2000-line file contains "what to do," "how to do it," and "when to do it" all mixed up. Change one piece, risk breaking others.

**Result:** 25 files at 200-400 lines = AI processes fast, maintains context, makes fewer errors. Humans can scan any file in under a minute.

**Note:** All branches use `apps/` subdirectory for their code (e.g., `spawn/apps/`, `seedgo/apps/`, `flow/apps/`).

---

## Template Baseline Compliance

**Rule:** All branches must match the Spawn template structure.

**Source of Truth:** `src/aipass/spawn/templates/builder/.template_registry.json`

**What it checks:**
- All required files from template exist in branch (with proper name transformations)
- All required directories from template exist in branch
- Template defines 30 files + 20 directories = 50 structural requirements

**Name transformations applied:**
- `{{BRANCH}}` placeholder → Branch name in uppercase (e.g., `SEEDGO`, `API`, `SPAWN`)
- `BRANCH.ID.json` → `.trinity/passport.json` (identity file for every branch)
- `LOCAL.json` → `{BRANCHNAME}.local.json` (e.g., `SEEDGO.local.json`)
- `OBSERVATIONS.json` → `{BRANCHNAME}.observations.json`
- `AI_MAIL.json` → `{BRANCHNAME}.ai_mail.json`
- `BRANCH.py` → `{branchname}.py` (e.g., `seedgo.py`)
- `README.md` → `README.md` (branches keep their README as markdown)

**WHY:** Spawn creates branches from template. If branches drift from template structure (missing files/directories), updates break and branch becomes non-standard. Template is the contract - all branches must honor it.

**Verification:** Standards checker compares each branch against template registry, reports missing items.

**Example compliance scores:**
- TRIGGER: 98% (missing 1 directory)
- SEEDGO: 98% (missing 1 directory)
- FLOW: 94% (missing 3 items)
- API: 86% (missing 7 items)

**Regenerate template registry:** When template structure changes, run:
```bash
python3 -m aipass.spawn.apps.modules.regenerate_template_registry
```

---

## No Shebangs or Execute Permissions Required

AIPass is a pip package. All execution goes through entry points defined in `pyproject.toml` or `python3 -m`. Shebangs and execute permissions are not needed.

---

## Handler Independence: The Marketplace Vision

**Rule:** Handlers cannot import MODULES from their own branch (circular dependency risk). Handlers CAN import other handlers within the same BRANCH (even across packages).

**WHY:** If handlers depend on modules, you create circular dependencies. Handlers must be self-contained so they can be moved to a marketplace.

**Future vision:** Branches browse marketplace → grab handler → drop it in → works immediately. No dependency hell.

**Handler import rules:**
- ✅ Same-branch handler imports: ALLOWED (even across packages)
- ❌ Cross-branch handler imports: BLOCKED (use modules instead)
- ❌ Handler imports own-branch modules: FORBIDDEN (circular risk)

**Current reality:** Handlers commonly import from service branches like `prax.apps.modules.logger` for system logging. This is acceptable because Prax is a system-wide service provider, not a module within the same branch.

**Modules CAN import 20+ handlers** - this is by design. Better one module imports many handlers than handlers importing each other. Dependencies flow ONE WAY: modules → handlers.

---

## Foundation Service Independence

**CRITICAL RULE:** Foundation service providers (CLI, Prax) MUST NOT import each other. Drone (CLI router) is NOT a foundation service - it's infrastructure.

**WHY:** Foundation services are system-wide infrastructure used by ALL branches. If they import each other, you create circular dependencies that break the entire system.

**The Problem:**
```
CLI modules import Prax logger
    ↓
Prax setup imports CLI console
    ↓
CIRCULAR DEPENDENCY: prax → cli → prax
    ↓
Result: ImportError on all drone commands, system broken
```

**The Fix:**
- CLI is a display service provider → does not need logging
- Prax is a logging service provider → does not need display formatting
- Foundation services must be independent building blocks

**What CAN import foundation services:**
- Higher-level modules (Seedgo, Spawn, Flow, API, etc.) can import BOTH CLI and Prax
- Business logic can use both services together
- This is the correct pattern

**What CANNOT import foundation services:**
- Foundation services cannot import other foundation services
- CLI cannot import Prax
- Prax cannot import CLI

**Drone's Special Role:**
- Drone is NOT a foundation service - it's a CLI router (infrastructure layer)
- Drone CAN import CLI for display formatting (it's above foundation layer)
- Branches should NEVER import Drone (it routes TO them, not used BY them)
- See "Drone: The CLI Router" section for details on @ resolution

**Consequence of violation:** System-wide breakage. All branches that depend on foundation services fail to import, entire AIPass ecosystem becomes non-operational.

**Discovery:** This rule was learned 2025-11-22 when CLI added Prax logging imports, breaking all drone commands system-wide.

---

## File Size Guidelines

- **Under 300 lines:** Perfect - AI quick scan, full comprehension, few errors
- **300-500 lines:** Good - manageable for AI and humans (most Spawn modules here)
- **500-700 lines:** Getting heavy - watch it
- **700+ lines:** Consider splitting - AI context degrades, humans struggle (example: `spawn/apps/modules/update_branch.py` at 916 lines)

**WHY:** AI comprehension drops with file size. Small files mean faster processing, cleaner context, fewer errors. Read a summary in seconds vs spending minutes processing a massive file.

**Human factor:** 300-line file = scan in 1 minute. 2000-line file = overwhelming, can't hold in working memory.

**Context efficiency:** Agents can process large files separately and return summaries. Your main context stays clean - no 200k token burn just to understand structure.

---

## Domain-Based Organization

**Organize by business purpose, not technical role:**

```
apps/handlers/
  ├── branch/     → Everything about branch lifecycle
  ├── error/      → Everything about error handling
  ├── json/       → Everything about JSON operations
  ├── registry/   → Everything about registry management
  └── cli/        → Everything about user interaction
```

**Verified from:** `src/aipass/spawn/apps/handlers/` - These are actual domains from Spawn.

**Note:** Actual domain names will vary by branch purpose. See naming.md for domain naming standards.

**WHY:** Technical organization (utils/, helpers/, operations/) tells you NOTHING about what code does. "Is this a utility or operation?" doesn't help you find JSON validation.

Domain organization: Need JSON? → `handlers/json/`. No mental translation required.

**Consequence of NOT doing this:** Navigation becomes guessing. Related code fragments across multiple folders. Can't see conceptual boundaries.

---

## Provider/Receiver Pattern

**Dependencies flow ONE direction:**

```
Modules (receivers)
    ↓ import and call
Handlers (providers)
    ↓ return results
    ↓ NEVER import modules
```

**Benefits:**
- **Change isolation:** Fix handler bug → all modules benefit automatically
- **Testing independence:** Test handlers alone (provide inputs, check outputs)
- **Clear failure boundaries:** Handler fails → returns error, module decides what to do

**What breaks without it:** Circular dependencies (A imports B, B imports A), ripple changes (fix one thing, update five call sites), testing nightmare.

---

## Error Handling via Decorators

**Centralize error handling, keep business logic clean:**

```python
# Clean business logic
@track_operation
def create_branch(name):
    # 5 lines of business logic
    return result
```

Instead of:
```python
# Error handling everywhere
def create_branch(name):
    try:
        # 5 lines of business logic
        # 15 lines of error handling
        return result
    except Exception as e:
        log_error(...)
        print_to_console(...)
        write_to_json_log(...)
        return failure_result
```

**WHY:** Fix once, works everywhere. Error formatting bug? Fix the decorator. All operations benefit immediately.

**Three-tier output automatic:** JSON log (machine-readable), system log (debug/audit), console output (user-friendly).

---

## Terminal Visibility - Two-Level Introspection

**PATTERN:** When run without arguments, branches show auto-discovered structure:

### Level 1: Main Entry Point (Shows Modules Only)

Run the main entry point to see discovered modules:

```bash
$ python3 flow.py
```

Output:
```
Flow - PLAN Management System

Task orchestration and workflow management

Discovered Modules: 5

  • create_plan
  • delete_plan
  • list_plans
  • close_plan
  • archive_plan

Run 'python3 flow.py --help' for usage information
```

**Main shows:** Module list ONLY (no handlers)

### Level 2: Individual Modules (Show Connected Handlers)

Run any module directly to see its handler dependencies:

```bash
$ python3 create_plan.py
```

Output:
```
create_plan Module

Connected Handlers:

  handlers/plan/
    - command_parser.py
    - resolve_location.py
    - create_file.py

  handlers/registry/
    - load_registry.py
    - save_registry.py

Run 'python3 create_plan.py --help' for usage
```

**Modules show:** Their specific handler dependencies

### WHY This Pattern Matters

**Without introspection:**
- Navigate directories manually
- Open 10+ files to understand dependencies
- Scan imports line by line
- Takes 5-10 minutes, burns context, error-prone

**With introspection:**
- One command: instant module list (main entry)
- One command: instant handler dependencies (module)
- Takes 5 seconds total
- No context pollution

**Auto-discovery benefits:**
- No hardcoded lists to maintain
- Add module → automatically appears
- Remove module → automatically gone
- Zero maintenance overhead

**Implementation:** See `src/aipass/seedgo/apps/seedgo.py` and `src/aipass/seedgo/apps/modules/architecture_standard.py` for reference pattern.

---

## Drone: The CLI Router (NOT a Library)

**CRITICAL RULE:** Drone is a CLI router that resolves @ symbols and routes commands to branches. It is NOT a library service that branches import.

### What Drone Does

Drone handles TWO critical responsibilities:

1. **@ Resolution:** Converts branch handles (@flow, @seedgo, @spawn) to absolute paths via AIPASS_REGISTRY.json
2. **Command Routing:** Routes the resolved command to the target branch's entry point

### How @ Resolution Works

**User types:**
```bash
drone @flow create @seedgo "plan_name" "description"
```

**Drone resolves @ symbols BEFORE passing to Flow:**
```bash
# What Drone does internally:
# 1. Sees target branch: @flow
# 2. Resolves @flow → <project_root>/flow
# 3. Resolves @seedgo → <project_root>/seedgo
# 4. Routes to: python3 <project_root>/flow/apps/flow.py create <project_root>/seedgo "plan_name" "description"
```

**What Flow receives:**
```python
# Flow's sys.argv:
['flow.py', 'create', '<project_root>/seedgo', 'plan_name', 'description']

# Flow receives the RESOLVED PATH, not the @ symbol
# Flow NEVER sees '@seedgo' - it sees '<project_root>/seedgo'
```

### The Architecture Boundary

```
User Command
    ↓
Drone CLI Router
    ↓ resolves ALL @ symbols
    ↓ routes to target branch
Target Branch Entry Point
    ↓ receives resolved paths (no @ symbols)
    ↓ routes to appropriate module
Module
    ↓ executes business logic
    ↓ uses resolved paths directly
Handlers
```

### NEVER Import Drone

**WRONG:**
```python
# DON'T DO THIS - Drone is NOT a library
from aipass.drone.apps.modules import resolve_branch
path = resolve_branch("@seedgo")
```

**RIGHT:**
```bash
# Drone is a CLI tool - use it via command line
drone @seedgo architecture-standard
```

**WHY:** Drone is a CLI router, not a service provider. It sits OUTSIDE the branch ecosystem, routing commands TO branches. Branches receive commands that have ALREADY been processed by Drone.

### Branches Should NEVER Handle @ Symbols

**WRONG PATTERN - Don't Do This:**
```python
# BAD - Branch handling @ resolution
def handle_command(command, args):
    target = args[0]
    if target.startswith('@'):
        # Resolving @ in branch code - WRONG!
        path = resolve_branch_handle(target)
```

**CORRECT PATTERN:**
```python
# GOOD - Branch receives resolved path from Drone
def handle_command(command, args):
    target = args[0]  # Already a path like '<project_root>/seedgo'
    if not os.path.exists(target):
        print(f"Error: Path does not exist: {target}")
        return False
    # Use the path directly
```

**WHY:** By the time your branch code runs, Drone has ALREADY resolved all @ symbols to paths. Your branch should validate paths (existence, permissions), not resolve @ symbols.

### Discovery: Foundation Service Separation

This rule was reinforced 2025-11-22 when CLI added Prax logging imports, breaking all drone commands system-wide. Drone depends on CLI for display formatting. If CLI depends on Prax, and Drone imports CLI, you create cascading dependencies that break the router.

**The lesson:** Drone is infrastructure. It routes commands. It doesn't participate in the business logic of the branches it routes to.

---

## Command Routing: handle_command() Pattern

**Rule:** Each module implements `handle_command(command, args)` returning True if handled.

**Context:** This is INTERNAL routing WITHIN a branch. This is different from Drone's routing which is EXTERNAL routing BETWEEN branches.

**Pattern:**
```python
def handle_command(command: str, args: List[str]) -> bool:
    """Handle primary command only - no aliases"""
    if command != "primary_command_name":
        return False
    # Handle command (args may contain resolved paths from Drone)
    return True
```

**NO ALIASES:** Session 14 removed all command aliases system-wide. One command per module.

**Note on args:** If command was routed through Drone, args will contain RESOLVED PATHS (like `<project_root>/seedgo`), not @ symbols (like `@seedgo`).

---

## Key Consequences of NOT Following These Patterns

1. **Marketplace vision dies** - Can't transport coupled handlers
2. **AI becomes unreliable** - Large files → context loss → more errors → slower processing
3. **Development velocity crashes** - Can't find code, can't change code, can't test code
4. **Scaling becomes impossible** - Context pollution, navigation overhead compounds, operations take hours instead of seconds
5. **Technical debt compounds** - Fixes require touching many files, changes create unpredictable ripples
6. **Duplicate @ resolution logic** - If branches handle @ themselves instead of relying on Drone, you get inconsistent resolution, maintenance burden, and unclear boundaries

---

## The Core Insight

This pattern optimizes for CONSTRAINTS:
- AI context and comprehension limits (keep context clean, agents do heavy lifting)
- Human working memory limits
- Speed and efficiency (seconds vs hours)
- Future marketplace requirements
- Scale to 50+ branches

**Why agents matter:** Agents handle exploration/analysis separately (their own 200k context). Your main context stays clean. Process massive amounts of information in seconds without context pollution.

**Speed example:** 480k tokens of agent work in 5 minutes = what would take a full day of back-and-forth coding. Spawn builds a branch in less than a second. Updates entire system in ~10 seconds.

**Ignore these constraints at your peril.** System will slow down, become unreliable, eventually unmaintainable.
