# Introspection Standards
**Status:** Active v1.0
**Date:** 2026-03-08

---

## What This Covers

The two-level auto-discovery pattern that makes branch structure visible from the terminal. When run without arguments, entry points and modules reveal their structure automatically — no directory browsing, no reading imports, no guessing.

---

## The Problem: Hidden Structure

**Without introspection:**
- Navigate directories manually to find modules
- Open 10+ files to understand handler dependencies
- Scan imports line by line to map relationships
- Takes 5-10 minutes, burns context, error-prone

**With introspection:**
- One command: instant module list (main entry point)
- One command: instant handler dependencies (module)
- Takes 5 seconds total
- No context pollution

---

## The Two-Level Pattern

### Level 1: Entry Point Introspection

When `apps/{name}.py` is run with **no arguments**, it shows branch structure:

```python
def print_introspection():
    """Show branch structure via auto-discovery"""
    console.print()
    console.print("[bold cyan]Flow[/bold cyan] - PLAN Management System")
    console.print()
    console.print("Task orchestration and workflow management")
    console.print()

    # Auto-discover modules
    modules_dir = Path(__file__).parent / "modules"
    discovered = []

    for file_path in sorted(modules_dir.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, 'handle_command'):
            discovered.append(file_path.stem)

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(discovered)}")
    console.print()

    for name in discovered:
        console.print(f"  [cyan]{name}[/cyan]")

    console.print()
    console.print("[dim]Run 'python3 flow.py --help' for usage information[/dim]")
    console.print()
```

**Output:**
```
Flow - PLAN Management System

Task orchestration and workflow management

Discovered Modules: 5

  create_plan
  delete_plan
  list_plans
  close_plan
  archive_plan

Run 'python3 flow.py --help' for usage information
```

**Level 1 shows:** Module list ONLY (no handlers, no commands, no usage details).

### Level 2: Module Introspection

When `apps/modules/*.py` is run with **no arguments**, it shows its handler dependencies:

```python
def print_introspection():
    """Show module structure - connected handlers"""
    console.print()
    console.print("[bold cyan]create_plan[/bold cyan] Module")
    console.print()

    # Discover connected handlers from imports
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [dim]handlers/plan/[/dim]")
    console.print("    - command_parser.py")
    console.print("    - resolve_location.py")
    console.print("    - create_file.py")
    console.print()
    console.print("  [dim]handlers/registry/[/dim]")
    console.print("    - load_registry.py")
    console.print("    - save_registry.py")
    console.print()
    console.print("[dim]Run 'python3 create_plan.py --help' for usage[/dim]")
    console.print()
```

**Output:**
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

**Level 2 shows:** Handler dependencies grouped by domain directory.

---

## Execution Order in main()

**STRICT ORDER — No exceptions:**

```python
def main():
    # 1. No args → introspection (FIRST)
    if len(sys.argv) < 2:
        print_introspection()
        return

    command = sys.argv[1]

    # 2. --help/-h → help (SECOND)
    if command in ['--help', '-h', 'help']:
        print_help()
        return

    # 3. --version/-V → version
    if command in ['--version', '-V']:
        console.print(f"v{VERSION}")
        return

    # 4. Command routing
    handle_command(command, sys.argv[2:])

if __name__ == "__main__":
    main()
```

**Why this order matters:**
1. **No args = introspection** — Discovery first. What IS this branch? What modules exist?
2. **--help = usage** — HOW do I use this? What commands are available?
3. **--version = version** — Quick version check.
4. **Commands = execution** — Do the work.

---

## Key Distinction: Introspection vs Help

| | Introspection (no args) | Help (--help) |
|---|---|---|
| **Purpose** | Structure/discovery | Usage/commands |
| **Function** | `print_introspection()` | `print_help()` |
| **Trigger** | No arguments | `--help` or `-h` flag |
| **Shows** | What exists (modules, handlers) | How to use (commands, flags, examples) |
| **Audience** | "What is this?" | "How do I use this?" |
| **Auto-discovery** | Yes — scans filesystem | No — static command list |

**Different functions, different purposes.** Never combine them.

---

## Auto-Discovery Requirements

### Level 1: Module Discovery

Entry points MUST auto-discover modules dynamically:

```python
# ✅ CORRECT - Auto-discovery
modules_dir = Path(__file__).parent / "modules"
for file_path in sorted(modules_dir.glob("*.py")):
    if file_path.name.startswith("_"):
        continue
    # Check for handle_command interface
    ...

# ❌ WRONG - Hardcoded list
MODULES = ["create_plan", "delete_plan", "list_plans"]
```

**Why auto-discovery:**
- Add a module file → automatically appears in introspection
- Remove a module file → automatically disappears
- Zero maintenance overhead
- No hardcoded lists to keep in sync

### Level 2: Handler Discovery

Modules show their connected handlers. This can be:
- **Static** — List known handler imports (acceptable for most modules)
- **Dynamic** — Parse own imports to discover handlers (advanced)

The key requirement is accuracy — listed handlers must match actual dependencies.

---

## Function Naming

| Level | Function | Location |
|-------|----------|----------|
| Level 1 | `print_introspection()` | `apps/{name}.py` |
| Level 2 | `print_introspection()` | `apps/modules/*.py` |

Both levels use `print_introspection()` as the function name. Same name, different scope.

**Not** `print_info()`, `show_structure()`, or `display_overview()`. The standard name is `print_introspection()`.

---

## Rich Formatting Requirement

Introspection output MUST use Rich markup tags for consistent presentation across all branches. Plain `console.print("flat text")` without any formatting tags fails the standard.

**Required:** At least one Rich tag in introspection output strings (e.g. `[bold cyan]`, `[dim]`, `[yellow]`, `[green]`, `[/dim]`).

```python
# ✅ CORRECT - Rich formatting
console.print("[bold cyan]Flow[/bold cyan] - PLAN Management System")
console.print(f"[yellow]Discovered Modules:[/yellow] {count}")
console.print(f"  [cyan]{name}[/cyan]")

# ❌ WRONG - Flat plain strings
console.print("Flow - PLAN Management System")
console.print(f"Discovered Modules: {count}")
console.print(f"  {name}")
```

**Delegation:** If `print_introspection()` delegates to a `_`-prefixed helper function (e.g. `_show_branch_introspection()`), the helper must contain Rich markup. The check walks into same-file helpers to verify formatting.

---

## Compliance Checklist

For entry points (`apps/{name}.py`):

- [ ] `print_introspection()` function exists
- [ ] No args triggers `print_introspection()` FIRST in main()
- [ ] Shows branch name and description
- [ ] Auto-discovers modules from `modules/*.py`
- [ ] Filters modules by `handle_command()` presence
- [ ] Lists discovered module names
- [ ] Points to `--help` for usage
- [ ] Uses Rich markup tags (not flat plain strings)

For modules (`apps/modules/*.py`):

- [ ] `print_introspection()` function exists
- [ ] No args triggers `print_introspection()` FIRST in main()
- [ ] Shows module name
- [ ] Lists connected handlers grouped by domain
- [ ] Points to `--help` for usage
- [ ] Uses Rich markup tags (not flat plain strings)

For execution order:

- [ ] No args → `print_introspection()` (position 1)
- [ ] `--help`/`-h` → `print_help()` (position 2)
- [ ] `--version`/`-V` → version (position 3)
- [ ] Commands → routing (position 4)

---

## Reference

- **Architecture context:** `src/aipass/sentry/docs/aipass_code_standards/architecture.md` (Terminal Visibility section)
- **Reference implementation:** `src/aipass/sentry/apps/sentry.py` (Level 1 entry point)
- **Standard:** `src/aipass/sentry/docs/aipass_code_standards/introspection.md`
