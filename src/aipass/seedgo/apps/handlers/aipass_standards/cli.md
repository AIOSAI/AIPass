# CLI Standards
**Status:** Active - Service Provider Pattern Implemented
**Date:** 2025-11-13 (Updated)
**Last Major Update:** CLI Error Handler Migration Complete

## What This Covers

Command-line interface design, arguments, the dual approach (interactive for humans, arguments for AI), and the CLI service provider pattern for consistent formatting across AIPass.

---

## The Problem: Interactive CLIs Don't Work Well for AI

**Scenario:** AI_Mail has an interactive menu:
- View mail
- Send mail
- Delete mail
- Archive mail
- Settings

**Problem:** AI has to navigate the menu, make selections, wait for prompts. It's slow, error-prone, and inefficient.

**Solution:** Every interactive CLI needs an **argument-based equivalent**.

---

## The Dual Approach

**For Humans:** Interactive CLI with Rich formatting, questionary menus, visual feedback
- Navigate with arrow keys
- See beautiful output
- Guided workflow

**For AI:** Argument-based commands via Drone
- `drone email send @recipient "subject" "message"`
- `drone dev add @flow "category" "note"`
- Fast, scriptable, no interaction needed

**Rule:** If you build an interactive CLI, you MUST build argument equivalents.

---

## Drone Pattern: The Standard

All modules conform to Drone's argument structure:

```bash
drone <module> <command> [options] [arguments]

Examples:
drone email send @flow "Update" "Plan created successfully"
drone plan create @flow "New Feature" "Add handler marketplace"
drone dev add @prax "bug" "Logger not writing to file"
```

**Why this matters:**
- Consistency across ALL modules
- AI can script operations
- Terminal-first workflow
- Fast execution without navigation

---

## Arguments Mirror Interactive Options

Every page/path in your interactive CLI = one argument command.

**Interactive flow:**
1. Main menu → Select "Send email"
2. Enter recipient
3. Enter subject
4. Enter message
5. Confirm

**Argument equivalent:**
```bash
drone email send @recipient "subject" "message"
```

One line, done. No navigation.

---

## Key Principles

1. **Interactive is for exploration** (humans learning the tool)
2. **Arguments are for execution** (AI and power users getting work done)
3. **Every interactive path needs an argument**
4. **Drone pattern is universal** (consistency enables speed)

---

## Command Naming Convention

**RULE:** All command names use lowercase with hyphens for multi-word commands (kebab-case).

**Pattern:**
- Single-word: `send`, `create`, `delete`, `list`, `check`, `track`
- Multi-word: `caller-usage`, `force-sync`, `check-status`

**PROHIBITED:**
- ✗ Abbreviations: `create` not `cr`
- ✗ Aliases: `delete` not `del` or `rm`
- ✗ camelCase: `checkStatus`
- ✗ snake_case: `check_status`

**WHY:** Explicit over implicit - users and AI understand intent. Matches file naming standard (snake_case files → kebab-case commands). Predictable across all modules.

**Session 14:** All command aliases removed system-wide. One descriptive command per module.

---

## Output Standard: Rich console.print() Only

**POLICY: Rich formatting is THE standard for ALL AIPass output.**

### Approved Output Method

```python
from aipass.cli.apps.modules import console

console.print("[cyan]This is the ONLY approved way to output text[/cyan]")
```

### Deprecated: Bare print()

**NO bare `print()` statements** - except in:
- Test modules (temporary/throwaway code)
- Quick debugging (should be removed before commit)

**Why:** We don't mix output methods. Rich formatting provides:
- Consistent visual design across all AIPass tools
- Color, bold, dim, and other markup
- Better readability for both humans and AI

### Help Output: Manual Rich Formatting

**DO NOT use `parser.print_help()`** - it outputs plain text.

**Argparse is for PARSING arguments only, NOT for help output.**

**Correct pattern:**
```python
def print_help():
    """Print help using Rich formatting"""
    console.print()
    console.print("[bold cyan]Module Name[/bold cyan]")
    console.print("Module description")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  Commands: cmd1, cmd2, --help")
    console.print()
    console.print("  [cyan]cmd1[/cyan]  - Description")
    console.print("  [cyan]cmd2[/cyan]  - Description")
    console.print()
```

**Wrong:**
```python
# DON'T DO THIS - outputs plain text
parser = argparse.ArgumentParser(...)
parser.print_help()
```

---

## CLI Service Provider Pattern

**Philosophy:** CLI branch provides formatting services, just like Prax provides logging services.

### Single Import Pattern

```python
# Import CLI services
from aipass.cli.apps.modules import console, header, success, error, warning

# Use throughout your module
console.print("[bold cyan]Starting operation...[/bold cyan]")
header("My Operation")
success("Operation complete!")
```

### What CLI Provides

**Console Service:**
- `console` - Rich Console instance for formatted output
- Replace all `print()` with `console.print()` for Rich markup support

**Display Functions:**
- `header(title, details)` - Section headers with Rich Panel
- `success(message, **details)` - Success messages with checkmark
- `error(message, suggestion, error_result)` - Error messages with context
- `warning(message, **details)` - Warning messages with alert icon
- `section(title)` - Sub-section headers

**Operation Templates:**
- `operation_start(operation, **details)` - Standard operation beginning
- `operation_complete(success, results, **summary)` - Standard operation end

**Error Handling:**
- `error_handler` - Complete error handling service
- `OperationResult` - Success/skip/fail result objects
- `@track_operation` - Auto-logging decorator
- `@continue_on_error` - Migration-style execution
- `@collect_results` - Batch operation aggregation

### Rich Formatting Quick Reference

**Colors:**
```python
console.print("[red]red[/red] [green]green[/green] [yellow]yellow[/yellow]")
console.print("[blue]blue[/blue] [cyan]cyan[/cyan] [magenta]magenta[/magenta]")
```

**Styles:**
```python
console.print("[bold]bold[/bold] [italic]italic[/italic] [dim]dim[/dim]")
console.print("[underline]underline[/underline]")
```

**Combined:**
```python
console.print("[bold green]Success![/bold green]")
console.print("[dim yellow]Warning:[/dim yellow] Check this")
console.print("[red bold]Error:[/red bold] Failed")
```

**Emojis:**
- ✅ Success
- ❌ Error
- ⚠️ Warning
- ℹ️ Info
- ⚙️ Processing
- 📝 Note
- 🔍 Search
- ✨ Feature

### Migration Pattern

**Before (old style):**
```python
print("Starting operation...")
print("=" * 70)
print("MY OPERATION")
print("=" * 70)
print("✅ Success!")
```

**After (CLI service):**
```python
from aipass.cli.apps.modules import console, header, success

console.print()
header("My Operation")
success("Operation complete!")
```

### Benefits

1. **Consistency:** All branches use same formatting
2. **Maintainability:** Update CLI once, affects entire system
3. **Rich Features:** Tables, panels, progress bars, colors
4. **Error Handling:** Integrated with OperationResult pattern
5. **Single Source:** No duplicate formatting code

### Implementation Notes

- CLI branch provides service (like Prax for logging)
- Branches import from `aipass.cli.apps.modules`
- Public API in `apps/modules/`, implementation in `apps/handlers/`
- Backward compatible (old usage still works)

**Reference:**
- Standard: `src/aipass/seedgo/docs/aipass_code_standards/cli.md`
- Implementation: `src/aipass/cli/`
- Example Usage: `src/aipass/seedgo/apps/modules/test_cli_errors.py`
- Interactive Demo: `<project_root>/planning/cli_layout_demo.py`
- Module Demo: `python3 src/aipass/seedgo/apps/modules/cli_standard.py`

---

## Drone Compliance

All modules must respond to `--help` flag with specific format:

```
Commands: command1, command2, --help

USAGE:
  drone <branch> <command>
  python3 module.py
  python3 module.py --help
```

**Requirements:**
- Help output includes "Commands:" line
- Commands comma-separated with flags
- Shows both drone and standalone usage

---

## Argument Parsing Standards

**Philosophy:** Every module should support both interactive and argument-based execution. Arguments enable AI to script operations without navigating menus.

### Basic Pattern

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Module description')
    parser.add_argument('command', help='Command to execute')
    parser.add_argument('--option', help='Optional parameter')
    parser.add_argument('--flag', action='store_true', help='Boolean flag')

    args = parser.parse_args()

    # Route to handler
    if args.command == "create":
        handle_create(args)
```

### Simple sys.argv Pattern

For modules with simple argument needs, use `sys.argv` directly:

```python
if __name__ == "__main__":
    # Check for help
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    # Get arguments
    if len(sys.argv) < 2:
        print("Usage: python3 module.py <command> [args]")
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]  # Remaining arguments

    # Route command
    if command == "create":
        handle_create(*args)
    elif command == "delete":
        handle_delete(*args)
```

**Real example from delete_plan.py:**
```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Delete PLAN file')
    parser.add_argument('plan_number', help='Plan number (e.g., 0001, 1, 42)')
    parser.add_argument('--yes', action='store_true', help='Skip confirmation')

    args = parser.parse_args()

    success = delete_plan(args.plan_number, confirm=not args.yes)
    sys.exit(0 if success else 1)
```

### argparse Pattern (Complex Modules)

For modules with many options, use argparse:

```python
import argparse

parser = argparse.ArgumentParser(
    description='Backup CLI',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
EXAMPLES:
  python backup.py snapshot
  python backup.py versioned --note "Before changes"
    """
)

# Positional arguments
parser.add_argument('mode', choices=['snapshot', 'versioned', 'all'])

# Optional arguments
parser.add_argument('--note', type=str, help='Backup note')
parser.add_argument('--dry-run', action='store_true', help='Show what would be backed up')

# Flags
parser.add_argument('--verbose', '-v', action='store_true')

args = parser.parse_args()
```

**Real example from backup_cli.py:**
```python
parser.add_argument('mode', nargs='?',
                   choices=list(BACKUP_MODES.keys()) + ['all', 'test'])
parser.add_argument('--note', type=str, help='Note for backup operation')
parser.add_argument('--list-modes', action='store_true',
                   help='List available backup modes')
parser.add_argument('--diff', type=str, help='Show diff for specified file')
parser.add_argument('--v1', type=str, help='First version for comparison')
```

### Help Flag Standard

**Every module MUST respond to `--help` using Rich formatting:**

```python
from aipass.cli.apps.modules import console

if __name__ == "__main__":
    # Check for help FIRST
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

def print_help():
    """Print help using Rich console.print()"""
    console.print()
    console.print("[bold cyan]MODULE NAME[/bold cyan]")
    console.print("Short Description")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print("  python3 module.py <command> [options]")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [cyan]create[/cyan]  - Create new item")
    console.print("  [cyan]delete[/cyan]  - Delete item")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  python3 module.py create @location \"subject\"")
    console.print()
```

**Reference: See any seedgo module for complete examples**
```bash
# See proper help formatting in action
python3 src/aipass/seedgo/apps/modules/imports_standard.py --help
```

### Argument Types

**Positional (required):**
```python
parser.add_argument('target', help='Target directory')
parser.add_argument('name', help='Branch name')
```

**Optional (named):**
```python
parser.add_argument('--subject', type=str, default='', help='Subject line')
parser.add_argument('--template', type=str, default='default')
```

**Flags (boolean):**
```python
parser.add_argument('--verbose', '-v', action='store_true')
parser.add_argument('--yes', action='store_true', help='Skip confirmation')
parser.add_argument('--dry-run', action='store_true')
```

**Choices (constrained values):**
```python
parser.add_argument('mode', choices=['snapshot', 'versioned', 'all'])
parser.add_argument('--level', choices=['debug', 'info', 'warning'])
```

### Exit Codes

**Standard exit codes:**
```python
sys.exit(0)    # Success
sys.exit(1)    # General error
sys.exit(2)    # Invalid arguments
```

**Real example from create_plan.py:**
```python
if success:
    print(f"\n✅ Created PLAN{num:04d}")
    sys.exit(0)
else:
    print(f"\n❌ Failed: {error}")
    sys.exit(1)
```

---

## Command Routing Structure

**Philosophy:** Main entry point dispatches to handler functions. Keep routing simple and obvious.

### Basic Routing Pattern

```python
def main():
    if len(sys.argv) < 2:
        # No arguments - run interactive mode
        interactive_menu()
        return

    command = sys.argv[1]

    # Route to handlers
    if command == "--help":
        print_help()
    elif command == "create":
        handle_create()
    elif command == "delete":
        handle_delete()
    elif command == "list":
        handle_list()
    else:
        print(f"Unknown command: {command}")
        print("Run with --help for usage")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### argparse Routing Pattern

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', help='Command to execute')
    parser.add_argument('--option', help='Optional parameter')

    args = parser.parse_args()

    # Route based on command
    if args.command == "create":
        result = handle_create(args.option)
    elif args.command == "delete":
        result = handle_delete(args.option)
    else:
        print(f"Unknown command: {args.command}")
        return 1

    return 0 if result else 1

if __name__ == "__main__":
    sys.exit(main())
```

### Module Discovery Pattern (Advanced)

**Real example from drone.py:**
```python
def discover_modules() -> List[Any]:
    """Auto-discover modules from modules/ directory"""
    modules = []

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module = importlib.import_module(file_path.stem)

        # Check for required interface
        if hasattr(module, 'handle_command'):
            modules.append(module)

    return modules

def route_command(args: argparse.Namespace, modules: List[Any]) -> bool:
    """Route command to appropriate module"""
    for module in modules:
        if module.handle_command(args):
            return True
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', help='Command to execute')
    args = parser.parse_args()

    # Discover and route
    modules = discover_modules()
    if route_command(args, modules):
        return 0
    else:
        print(f"Unknown command: {args.command}")
        return 1
```

### Orchestrator Interface Pattern

For modules that can be called standalone OR through orchestrator:

```python
def handle_command(args) -> bool:
    """
    Orchestrator interface - called by main orchestrator

    Args:
        args: Command line arguments

    Returns:
        True if command was handled, False otherwise
    """
    if not hasattr(args, 'command'):
        return False

    # Handle this module's commands
    if args.command in ["create", "new"]:
        result = create_item(args.target)
        return True

    if args.command == "delete":
        result = delete_item(args.target)
        return True

    # Not our command
    return False

# Standalone execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('command')
    parser.add_argument('target')
    args = parser.parse_args()

    success = handle_command(args)
    sys.exit(0 if success else 1)
```

**Real example from create_branch.py:**
```python
def handle_command(args) -> bool:
    """Orchestrator interface - called by drone.py"""
    if not hasattr(args, 'command'):
        return False

    # Handle create branch command
    if args.command in ["create-branch", "create", "new"]:
        if not hasattr(args, 'target_directory'):
            print("Error: target_directory required")
            return True

        target_dir = Path(args.target_directory).resolve()
        return create_branch(target_dir)

    return False
```

### Error Handling in Routing

```python
def main():
    try:
        args = parse_arguments()

        # Route command
        if args.command == "create":
            return handle_create(args)
        elif args.command == "delete":
            return handle_delete(args)
        else:
            print(f"Unknown command: {args.command}")
            return 1

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 130  # Standard cancel exit code
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"ERROR: {e}")
        return 1
```

---

## Good Argument Design

**Philosophy:** Arguments should be intuitive, consistent, and mirror interactive flows.

### AIPass Argument Conventions

**@-notation for targets:**
```bash
drone email send @flow "Subject" "Message"
drone plan create @flow "Feature" "Description"
```

Implementation:
```python
if target.startswith("@"):
    # Remove @ and resolve to branch
    branch_dir = AIPASS_ROOT / target[1:]
```

**Verb-noun pattern:**
```bash
drone plan create    # verb noun
drone email send     # verb noun
drone dev add        # verb noun
```

**Required args first, flags after:**
```bash
# Good
python module.py create target_dir --template advanced --verbose

# Bad
python module.py create --verbose --template advanced target_dir
```

**Quote strings with spaces:**
```bash
drone email send @flow "Update Complete" "All tests passing"
```

**Boolean flags don't need values:**
```bash
# Good
python backup.py snapshot --dry-run

# Bad
python backup.py snapshot --dry-run=true
```

### Real Examples from AIPass

**create_plan.py:**
```bash
# Simple positional args
python create_plan.py @flow "New Feature" default

# With flags
python create_plan.py @flow "New Feature" --template master
```

**delete_plan.py:**
```bash
# With confirmation
python delete_plan.py 0042

# Skip confirmation
python delete_plan.py 0042 --yes
```

**backup_cli.py:**
```bash
# Mode selection
python backup_cli.py snapshot
python backup_cli.py versioned --note "Before changes"

# Special commands
python backup_cli.py --list-modes
python backup_cli.py --diff "file.py"
python backup_cli.py --diff "file.py" --v1 20241101 --v2 20241102
```

### Argument Design Checklist

- [ ] **Consistent with Drone pattern** (verb-noun structure)
- [ ] **@-notation for branch targets** (if applicable)
- [ ] **Required args are positional** (no flag needed)
- [ ] **Optional args use --flags**
- [ ] **Boolean flags use action='store_true'**
- [ ] **Help flag works** (`--help`, `-h`, `help`)
- [ ] **Reasonable defaults** (don't require every flag)
- [ ] **Clear error messages** (explain what's wrong)
- [ ] **Exit codes meaningful** (0=success, 1=error)

### Bad Argument Design

**❌ Unclear abbreviations:**
```bash
python module.py -t @c -s "msg"  # What is -t? What is -s?
```

**❌ Inconsistent ordering:**
```bash
# Sometimes target first
python module.py create target --option value

# Sometimes target last
python module.py delete --option value target
```

**❌ Boolean flags with values:**
```bash
python module.py --verbose true   # Redundant
python module.py --dry-run=false  # Confusing
```

**❌ No help:**
```bash
python module.py --help
# (no output, or generic argparse output with no examples)
```

### Good Argument Design

**✅ Clear, consistent, documented:**
```bash
# Help shows usage
python module.py --help

# Arguments are obvious
python module.py create @branch "Subject" --template advanced

# Boolean flags are simple
python module.py delete 42 --yes

# Error messages are helpful
python module.py create
# Error: Missing required argument: target
# Usage: python module.py create <target> [subject] [--template TYPE]
```

---

## Keeping Interactive and Arguments in Sync

**Philosophy:** Every interactive path needs an argument equivalent. Same handlers, different entry points.

### The Pattern

```python
# ==========================================
# CORE HANDLER (used by both paths)
# ==========================================

def create_item(target: str, subject: str = "", template: str = "default"):
    """
    Core handler - pure logic, no UI

    Args:
        target: Target location
        subject: Item subject
        template: Template to use

    Returns:
        (success: bool, item_id: int, error: str)
    """
    # Pure logic here
    return True, 42, ""

# ==========================================
# INTERACTIVE PATH (human users)
# ==========================================

def interactive_menu():
    """Interactive CLI for humans"""
    print("\n=== Create Item ===")

    # Collect inputs with questionary/Rich prompts
    target = questionary.text("Target location:").ask()
    subject = questionary.text("Subject:").ask()
    template = questionary.select(
        "Template:",
        choices=["default", "advanced", "minimal"]
    ).ask()

    # Call shared handler
    success, item_id, error = create_item(target, subject, template)

    if success:
        console.print(f"[green]✅ Created item {item_id}[/green]")
    else:
        console.print(f"[red]❌ Failed: {error}[/red]")

# ==========================================
# ARGUMENT PATH (AI and power users)
# ==========================================

def main():
    if len(sys.argv) < 2:
        # No arguments -> interactive
        interactive_menu()
        return

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('command')
    parser.add_argument('target')
    parser.add_argument('subject', nargs='?', default='')
    parser.add_argument('--template', default='default')

    args = parser.parse_args()

    # Call shared handler
    if args.command == "create":
        success, item_id, error = create_item(
            args.target,
            args.subject,
            args.template
        )

        if success:
            print(f"✅ Created item {item_id}")
            sys.exit(0)
        else:
            print(f"❌ Failed: {error}")
            sys.exit(1)
```

### Key Principles

1. **Shared handler functions** - Both paths call same logic
2. **No UI in handlers** - Pure logic, return data
3. **Different entry points** - Interactive collects inputs, arguments provide them
4. **Same outcomes** - Both paths produce identical results
5. **Test both paths** - Ensure equivalence

### Real Example from Flow System

**create_plan.py structure:**

```python
# ==========================================
# CORE HANDLER
# ==========================================
def create_plan(location, subject, template_type):
    """Pure logic - creates PLAN file and updates registry"""
    # ... logic ...
    return success, plan_num, location, template, error

# ==========================================
# STANDALONE EXECUTION (arguments)
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('location', nargs='?')
    parser.add_argument('subject', nargs='?', default='')
    parser.add_argument('template', nargs='?', default='default')

    args = parser.parse_args()

    # Call handler with parsed args
    success, num, loc, tmpl, error = create_plan(
        args.location,
        args.subject,
        args.template
    )
```

**Used by Flow interactive menu:**

```python
# flow.py interactive path
def interactive_create_plan():
    """Interactive menu for creating plans"""
    print("\n=== Create PLAN ===")

    location = questionary.text("Location (@branch):").ask()
    subject = questionary.text("Subject:").ask()
    template = questionary.select(
        "Template:",
        choices=["default", "master", "minimal"]
    ).ask()

    # Call same handler
    success, num, loc, tmpl, error = create_plan(
        location, subject, template
    )

    # Format results for human
    if success:
        console.print(f"[green]✅ Created PLAN{num:04d}[/green]")
```

**Used by Drone command:**

```bash
# Direct argument path
drone plan create @flow "New Feature" default
```

### Synchronization Checklist

- [ ] **Every interactive menu option has argument equivalent**
- [ ] **Both paths use same handler functions**
- [ ] **Handlers return data, don't print directly**
- [ ] **Arguments provide all required inputs**
- [ ] **Test both paths produce same results**
- [ ] **Documentation shows both usage patterns**

### Testing Equivalence

```python
# Test both paths produce same result
def test_equivalence():
    # Argument path
    success1, id1, _ = create_item("@test", "subject", "default")

    # Simulated interactive path (with mocked inputs)
    success2, id2, _ = create_item("@test", "subject", "default")

    assert success1 == success2
    assert id1 == id2
```

---

## TODO

- [x] ~~Document argument parsing standards~~ ✅ DONE
- [x] ~~Show how to structure command routing~~ ✅ DONE
- [x] ~~Examples of good argument design~~ ✅ DONE
- [x] ~~How to keep interactive and arguments in sync~~ ✅ DONE
- [x] ~~error_handler.py and formatters.py implemented~~ ✅ DONE
- [ ] Expand CLI branch self-adoption (currently minimal - most CLI code predates service pattern)
- [ ] Document external branch migration process
- [ ] Create CLI service adoption checklist

---

## Notes

This isn't about making things harder by building two interfaces. It's about making the system work for both humans AND AI. Interactive CLIs are beautiful for humans but slow for AI. Arguments are fast for AI but cryptic for humans learning the tool.

**Service Provider Pattern:** CLI transforms all CLI activities through single import. Import console, use it throughout. Consistency across the system, maintained in one place.

Build both. Serve both audiences.
