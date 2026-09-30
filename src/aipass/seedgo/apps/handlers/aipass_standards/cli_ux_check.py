# =================== AIPass ====================
# Name: cli_ux_check.py
# Description: CLI UX Standards Checker Handler
# Version: 1.0.0
# Created: 2026-07-17
# Modified: 2026-07-17
# =============================================

"""
CLI UX Standards Checker Handler

Validates that branch entry points follow the AIPass house pattern for CLI
help and introspection output.

Good entry points (flow.py, prax.py, drone.py, seedgo.py) all have:
  - print_introspection() and print_help() as separate two-tier functions
  - Rich console.print() output (no bare print())
  - Styled title, purpose/tagline, and --help pointer in introspection
  - Usage and Examples sections in help

Checks:
1. two_tier_help     - Both print_introspection() and print_help() exist
2. rich_console      - Help functions use console.print(), not bare print()
3. title_markup      - print_introspection() has a [bold styled title
4. purpose_line      - print_introspection() has a [dim] purpose/tagline line
5. help_pointer      - print_introspection() references --help
6. usage_section     - print_help() includes a Usage section
7. examples_section  - print_help() includes an Examples section
8. no_internal_modules - modules/ does not expose internal plumbing files
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Only check entry points: apps/{branch}.py files
# APPLIES_TO: entry-point navigation and output quality.
APPLIES_TO = "production"
AUDIT_SCOPE = "entry_point"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if entry point follows the AIPass CLI UX house pattern.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip specific violations

    Returns:
        dict: {
            'passed': bool,           # Overall pass/fail
            'checks': [               # Individual check results
                {
                    'name': str,      # Check name
                    'passed': bool,   # Pass/fail
                    'message': str,   # Details
                }
            ],
            'score': int,             # 0-100 percentage
            'standard': str           # Standard name
        }
    """
    checks: List[Dict] = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "cli_ux", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "CLI_UX",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "CLI UX check", "passed": True, "message": "__init__.py skipped"}],
            "score": 100,
            "standard": "CLI_UX",
        }

    # Skip non-entry-point files (entry points live at apps/{name}.py)
    if not _is_entry_point(module_path, path):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "CLI UX check",
                    "passed": True,
                    "message": "Not an entry point file (not applicable)",
                }
            ],
            "score": 100,
            "standard": "CLI_UX",
        }

    # Read file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    # Empty file
    if not content.strip():
        return {
            "passed": True,
            "checks": [{"name": "CLI UX check", "passed": True, "message": "Empty file skipped"}],
            "score": 100,
            "standard": "CLI_UX",
        }

    # Parse AST
    try:
        tree = ast.parse(content, filename=module_path)
    except SyntaxError as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [{"name": "File parseable", "passed": False, "message": f"Syntax error: {e}"}],
            "score": 0,
            "standard": "CLI_UX",
        }

    # Find the two key functions via AST
    introspection_func = _find_function(tree, "print_introspection")
    help_func = _find_function(tree, "print_help")

    # --- Check 1: two_tier_help ---
    checks.append(_check_two_tier_help(tree, path.name))

    # --- Check 2: rich_console ---
    checks.append(_check_rich_console(introspection_func, help_func, path.name))

    # --- Check 3: title_markup ---
    checks.append(_check_title_markup(introspection_func, path.name))

    # --- Check 4: purpose_line ---
    checks.append(_check_purpose_line(introspection_func, path.name))

    # --- Check 5: help_pointer ---
    checks.append(_check_help_pointer(introspection_func, path.name))

    # --- Check 6: usage_section ---
    checks.append(_check_usage_section(help_func, path.name))

    # --- Check 7: examples_section ---
    checks.append(_check_examples_section(help_func, path.name))

    # --- Check 8: no_internal_modules ---
    checks.append(_check_no_internal_modules(module_path, path))

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass = ALL checks passed
    overall_passed = all(check["passed"] for check in checks)

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "cli_ux"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "CLI_UX"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_entry_point(module_path: str, path: Path) -> bool:
    """
    Detect if file is an entry point: apps/{name}.py (directly in apps/, not in subdirectory).

    Entry points live at apps/{name}.py -- their parent directory is 'apps'.
    Files in apps/modules/, apps/handlers/, apps/plugins/ etc. are NOT entry points.
    """
    if not path.name.endswith(".py"):
        return False
    posix_path = Path(module_path).as_posix()
    if "apps/" not in posix_path:
        return False
    return path.parent.name == "apps"


def _find_function(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    """Find a top-level function definition by name."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _collect_string_constants(func_node: ast.FunctionDef) -> List[str]:
    """Extract all string constants from a function body, including f-string parts."""
    return [
        node.value for node in ast.walk(func_node) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_two_tier_help(tree: ast.Module, filename: str) -> Dict:
    """Check 1: Entry point has BOTH print_introspection AND print_help."""
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ("print_introspection", "print_help"):
            found.add(node.name)

    missing = {"print_introspection", "print_help"} - found

    if not missing:
        return {
            "name": "two_tier_help",
            "passed": True,
            "message": f"Both print_introspection() and print_help() found in {filename}",
        }

    missing_str = ", ".join(sorted(missing))
    return {
        "name": "two_tier_help",
        "passed": False,
        "message": f"Entry point must define both print_introspection() and print_help() — {missing_str} not found",
    }


def _check_rich_console(
    introspection_func: Optional[ast.FunctionDef],
    help_func: Optional[ast.FunctionDef],
    filename: str,
) -> Dict:
    """Check 2: Help functions use console.print(), not bare print()."""
    funcs_to_check = []
    if introspection_func is not None:
        funcs_to_check.append(("print_introspection", introspection_func))
    if help_func is not None:
        funcs_to_check.append(("print_help", help_func))

    if not funcs_to_check:
        # Neither function exists -- auto-fail (two_tier_help already catches the root cause)
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    has_console_print = False
    has_bare_print = False

    for _func_name, func_node in funcs_to_check:
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            # console.print() — Attribute call where value.id == 'console' and attr == 'print'
            if isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "print"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "console"
                ):
                    has_console_print = True
            # bare print() — Name call where id == 'print'
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                has_bare_print = True

    if has_bare_print:
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    if not has_console_print:
        return {
            "name": "rich_console",
            "passed": False,
            "message": "Help functions must use console.print() from aipass.cli, not bare print()",
        }

    return {
        "name": "rich_console",
        "passed": True,
        "message": f"Help functions in {filename} use console.print() (no bare print())",
    }


def _check_title_markup(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 3: print_introspection contains a [bold styled title."""
    if introspection_func is None:
        return {
            "name": "title_markup",
            "passed": False,
            "message": (
                "print_introspection() must include a styled title line (e.g. [bold cyan]Branch Name[/bold cyan])"
            ),
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "[bold" in s:
            return {
                "name": "title_markup",
                "passed": True,
                "message": f"print_introspection() in {filename} has a styled title with [bold markup",
            }

    return {
        "name": "title_markup",
        "passed": False,
        "message": "print_introspection() must include a styled title line (e.g. [bold cyan]Branch Name[/bold cyan])",
    }


def _check_purpose_line(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 4: print_introspection contains a [dim] purpose/tagline line."""
    if introspection_func is None:
        return {
            "name": "purpose_line",
            "passed": False,
            "message": "print_introspection() must include a dim-styled purpose/tagline line",
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "[dim]" in s:
            return {
                "name": "purpose_line",
                "passed": True,
                "message": f"print_introspection() in {filename} has a [dim] purpose/tagline line",
            }

    return {
        "name": "purpose_line",
        "passed": False,
        "message": "print_introspection() must include a dim-styled purpose/tagline line",
    }


def _check_help_pointer(introspection_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 5: print_introspection contains a closing pointer to --help."""
    if introspection_func is None:
        return {
            "name": "help_pointer",
            "passed": False,
            "message": "print_introspection() must include a closing pointer to --help for more info",
        }

    strings = _collect_string_constants(introspection_func)
    for s in strings:
        if "--help" in s:
            return {
                "name": "help_pointer",
                "passed": True,
                "message": f"print_introspection() in {filename} includes a --help pointer",
            }

    return {
        "name": "help_pointer",
        "passed": False,
        "message": "print_introspection() must include a closing pointer to --help for more info",
    }


def _check_usage_section(help_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 6: print_help contains a Usage section."""
    if help_func is None:
        return {
            "name": "usage_section",
            "passed": False,
            "message": "print_help() must include a Usage section",
        }

    strings = _collect_string_constants(help_func)
    for s in strings:
        if "usage" in s.lower():
            return {
                "name": "usage_section",
                "passed": True,
                "message": f"print_help() in {filename} includes a Usage section",
            }

    return {
        "name": "usage_section",
        "passed": False,
        "message": "print_help() must include a Usage section",
    }


def _check_examples_section(help_func: Optional[ast.FunctionDef], filename: str) -> Dict:
    """Check 7: print_help contains an Examples section."""
    if help_func is None:
        return {
            "name": "examples_section",
            "passed": False,
            "message": "print_help() must include an Examples section",
        }

    strings = _collect_string_constants(help_func)
    for s in strings:
        if "example" in s.lower():
            return {
                "name": "examples_section",
                "passed": True,
                "message": f"print_help() in {filename} includes an Examples section",
            }

    return {
        "name": "examples_section",
        "passed": False,
        "message": "print_help() must include an Examples section",
    }


def _check_no_internal_modules(module_path: str, path: Path) -> Dict:
    """
    Check 8: modules/ directory does not expose internal plumbing files.

    Files whose stems end with _wire, _fix, _impl, or _internal should be
    underscore-prefixed to hide from discovery.
    """
    internal_suffixes = ("_wire", "_fix", "_impl", "_internal")

    # Derive the branch root from the entry point path:
    # entry point is at {branch_root}/apps/{name}.py -> parent.parent is branch_root
    branch_root = path.parent.parent
    modules_dir = branch_root / "apps" / "modules"

    if not modules_dir.is_dir():
        return {
            "name": "no_internal_modules",
            "passed": True,
            "message": "No modules/ directory found (nothing to check)",
        }

    exposed_internal: List[str] = []
    for py_file in modules_dir.glob("*.py"):
        stem = py_file.stem
        # Skip __init__.py and already-underscore-prefixed files
        if stem.startswith("_"):
            continue
        if any(stem.endswith(suffix) for suffix in internal_suffixes):
            exposed_internal.append(py_file.name)

    if exposed_internal:
        names = ", ".join(sorted(exposed_internal))
        return {
            "name": "no_internal_modules",
            "passed": False,
            "message": (
                f"modules/ directory exposes internal plumbing: {names} "
                f"— prefix with underscore or use COMMAND attribute"
            ),
        }

    return {
        "name": "no_internal_modules",
        "passed": True,
        "message": "No exposed internal plumbing files in modules/",
    }
