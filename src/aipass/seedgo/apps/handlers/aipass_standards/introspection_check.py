# =================== AIPass ====================
# Name: introspection_check.py
# Description: Introspection Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Introspection Standards Checker Handler

Validates that AIPass modules implement proper introspection support.

Checks:
1. Entry points (apps/{name}.py): print_introspection function exists
2. Entry points: Execution order — no-args check before --help check in main()
3. Modules (apps/modules/*.py): print_introspection function exists
4. Modules: handle_command() no-args gate — must gate on empty args and call print_introspection()
"""

import ast
from pathlib import Path
from typing import Dict, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Run on ALL .py files so modules (apps/modules/*.py) are checked, not just entry points
AUDIT_SCOPE = "all_files"


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed"""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        # Must match standard
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        # Must match file (check if rule file path is in the full path)
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        # Check line-specific bypass
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows introspection standards

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
    checks = []
    path = Path(module_path)

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "introspection", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "INTROSPECTION",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "INTROSPECTION",
        }

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Introspection check", "passed": True, "message": "__init__.py skipped"}],
            "score": 100,
            "standard": "INTROSPECTION",
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
            "standard": "INTROSPECTION",
        }

    # Empty file
    if not content.strip():
        return {
            "passed": True,
            "checks": [{"name": "Introspection check", "passed": True, "message": "Empty file skipped"}],
            "score": 100,
            "standard": "INTROSPECTION",
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
            "standard": "INTROSPECTION",
        }

    # Determine file type from path
    is_entry_point = _is_entry_point(module_path, path)
    is_module = "/modules/" in module_path and path.parent.name == "modules"

    # If neither entry point nor module, skip
    if not is_entry_point and not is_module:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Introspection check",
                    "passed": True,
                    "message": "Not an entry point or module file (not applicable)",
                }
            ],
            "score": 100,
            "standard": "INTROSPECTION",
        }

    # Check 1: print_introspection exists (applies to both entry points and modules)
    introspection_check = check_print_introspection_exists(tree, path.name)
    checks.append(introspection_check)

    # Check 2: Execution order (entry points only)
    if is_entry_point:
        order_check = check_execution_order(tree, content, path.name)
        if order_check:
            checks.append(order_check)

    # Check 3: Correct dispatch — no-args calls introspection, --help calls help (entry points only)
    if is_entry_point:
        dispatch_check = check_correct_dispatch(tree, path.name)
        if dispatch_check:
            checks.append(dispatch_check)

    # Check 4: handle_command() no-args gate (modules only)
    if is_module:
        gate_check = check_module_handle_command_gate(tree, path.name)
        if gate_check:
            checks.append(gate_check)

    # Check 5: Content references — help/introspection text should reference drone, not python3
    content_check = check_content_references(tree, path.name)
    if content_check:
        checks.append(content_check)

    # Check 6: Module help interception — handle_command() should intercept --help (modules only)
    if is_module:
        help_check = check_module_help_interception(tree, path.name)
        if help_check:
            checks.append(help_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "introspection"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "INTROSPECTION"}


def _is_entry_point(module_path: str, path: Path) -> bool:
    """
    Detect if file is an entry point: apps/{name}.py (directly in apps/, not in subdirectory)

    Entry points live at apps/{name}.py — their parent directory is 'apps'.
    Files in apps/modules/, apps/handlers/, apps/plugins/ etc. are NOT entry points.
    """
    if not path.name.endswith(".py"):
        return False
    if "apps/" not in module_path:
        return False
    return path.parent.name == "apps"


def check_print_introspection_exists(tree: ast.Module, filename: str) -> Dict:
    """
    Use AST to check if def print_introspection exists as a top-level function.
    """
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "print_introspection":
            return {
                "name": "print_introspection exists",
                "passed": True,
                "message": f"Found print_introspection() at line {node.lineno} in {filename}",
            }

    return {
        "name": "print_introspection exists",
        "passed": False,
        "message": f"Missing def print_introspection() in {filename}",
    }


def check_execution_order(tree: ast.Module, content: str, filename: str) -> Optional[Dict]:
    """
    In the main() function (or if __name__ block), verify that no-args check
    comes BEFORE --help check.

    The standard execution order is:
    1. No args → print introspection info
    2. --help → print help
    3. Route command

    Uses AST to find the main function, then inspects conditional order.
    """
    # Strategy: Find main() function, then look for the ordering of conditionals
    main_func = _find_main_function(tree)

    if main_func is None:
        # Also check if __name__ == '__main__' block
        main_func = _find_name_main_block(tree)

    if main_func is None:
        # No main function or __name__ block — can't check order
        return {
            "name": "Execution order",
            "passed": True,
            "message": f"No main() or __name__ block found in {filename} (skipped)",
        }

    # Walk the body of main to find conditionals
    no_args_line = None
    help_check_line = None

    for node in ast.walk(main_func):
        if isinstance(node, ast.If):
            # Check if this conditional is a no-args check
            if _is_no_args_check(node):
                if no_args_line is None:
                    no_args_line = node.lineno

            # Check if this conditional is a help flag check
            if _is_help_check(node):
                if help_check_line is None:
                    help_check_line = node.lineno

    # If both found, verify order
    if no_args_line is not None and help_check_line is not None:
        if no_args_line < help_check_line:
            return {
                "name": "Execution order",
                "passed": True,
                "message": f"No-args check (line {no_args_line}) before --help check (line {help_check_line})",
            }
        else:
            return {
                "name": "Execution order",
                "passed": False,
                "message": f"--help check (line {help_check_line}) before no-args check (line {no_args_line}) — no-args should come first",
            }

    # If only help check found (no no-args check)
    if help_check_line is not None and no_args_line is None:
        return {
            "name": "Execution order",
            "passed": False,
            "message": f"Found --help check but no no-args check in {filename} — add empty args handling before --help",
        }

    # If only no-args check found (no help check) — that's fine, help may be elsewhere
    if no_args_line is not None and help_check_line is None:
        return {
            "name": "Execution order",
            "passed": True,
            "message": f"No-args check found at line {no_args_line} (no --help conditional to compare against)",
        }

    # Neither found — can't determine order
    return {
        "name": "Execution order",
        "passed": True,
        "message": f"No args/help conditionals detected in main() of {filename} (skipped)",
    }


def _find_main_function(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """Find the top-level main() function definition."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    return None


def _find_handle_command_function(tree: ast.Module) -> Optional[ast.FunctionDef]:
    """Find the top-level handle_command() function definition."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "handle_command":
            return node
    return None


def check_module_handle_command_gate(tree: ast.Module, filename: str) -> Optional[Dict]:
    """
    For modules (apps/modules/*.py), verify that handle_command() contains a
    no-args gate that calls print_introspection().

    The standard pattern is::

        handle_command(command, args):
            ...
            if not args:
                print_introspection()  # or call a wrapper that shows introspection
                return True

    Without this gate, the module will immediately execute instead of showing
    introspection when called with no arguments.

    Uses AST to find handle_command(), then walks its body looking for a
    no-args conditional whose body calls print_introspection (or a known
    introspection wrapper).
    """
    handle_cmd = _find_handle_command_function(tree)

    if handle_cmd is None:
        # No handle_command — module may use a different pattern, skip
        return {
            "name": "handle_command no-args gate",
            "passed": True,
            "message": f"No handle_command() found in {filename} (skipped)",
        }

    # Walk handle_command body to find a no-args conditional that calls introspection
    # Known introspection-related function names (direct or wrapper)
    introspection_names = {
        "print_introspection",
        "_show_audit_introspection",
        "_show_pack_module_introspection",
    }

    for node in ast.walk(handle_cmd):
        if not isinstance(node, ast.If):
            continue

        if not _is_no_args_check(node):
            continue

        # Found a no-args gate — check if its body calls an introspection function
        calls = _get_function_calls_in_block(node.body)
        if calls & introspection_names:
            return {
                "name": "handle_command no-args gate",
                "passed": True,
                "message": f"handle_command() gates on no-args at line {node.lineno} → introspection",
            }

    # No no-args gate found that dispatches to introspection
    return {
        "name": "handle_command no-args gate",
        "passed": False,
        "message": f"handle_command() in {filename} has no no-args gate calling print_introspection() — module will not show introspection when called with no arguments",
    }


def _find_name_main_block(tree: ast.Module) -> Optional[ast.If]:
    """
    Find the if __name__ == '__main__': block at module level.
    Returns the If node so we can walk its body.
    """
    for node in tree.body:
        if isinstance(node, ast.If):
            # Check for: if __name__ == '__main__'
            test = node.test
            if isinstance(test, ast.Compare):
                # Left side: __name__
                if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                    # Right side: '__main__'
                    if (
                        test.comparators
                        and isinstance(test.comparators[0], ast.Constant)
                        and test.comparators[0].value == "__main__"
                    ):
                        return node
    return None


def _is_no_args_check(node: ast.If) -> bool:
    """
    Detect if an If node is checking for empty/no arguments.

    Patterns detected:
    - len(args) == 0
    - len(sys.argv) == 1
    - len(sys.argv) < 2
    - not args
    - not sys.argv[1:]
    - len(args) < 1
    """
    test = node.test

    # Pattern: not args / not sys.argv[1:]
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        operand = test.operand
        # not args
        if isinstance(operand, ast.Name) and operand.id == "args":
            return True
        # not sys.argv[1:]
        if isinstance(operand, ast.Subscript):
            return True

    # Pattern: len(...) == 0 or len(...) < 1
    if isinstance(test, ast.Compare):
        left = test.left

        # Check if left side is len(args) or len(sys.argv)
        if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len":
            if left.args:
                arg = left.args[0]
                # len(args) == 0
                if isinstance(arg, ast.Name) and arg.id == "args":
                    # Check comparator is 0 or 1
                    if test.comparators and isinstance(test.comparators[0], ast.Constant):
                        val = test.comparators[0].value
                        if val in (0, 1):
                            return True
                # len(sys.argv) == 1 or len(sys.argv) < 2
                if isinstance(arg, ast.Attribute):
                    if isinstance(arg.value, ast.Name) and arg.value.id == "sys" and arg.attr == "argv":
                        if test.comparators and isinstance(test.comparators[0], ast.Constant):
                            val = test.comparators[0].value
                            if val in (1, 2):
                                return True

    return False


def _is_help_check(node: ast.If) -> bool:
    """
    Detect if an If node is checking for --help or -h flags.

    Patterns detected:
    - '--help' in args
    - '-h' in args
    - args[0] == '--help'
    - args[0] in ('--help', '-h')
    - Comparisons involving the string '--help' or '-h'
    """
    return _ast_contains_help_string(node.test)


def _ast_contains_help_string(node: ast.AST) -> bool:
    """
    Recursively check if an AST node contains a reference to '--help' or '-h' strings.
    """
    # Direct string constant
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in ("--help", "-h"):
            return True

    # Walk all child nodes
    for child in ast.iter_child_nodes(node):
        if _ast_contains_help_string(child):
            return True

    return False


def check_correct_dispatch(tree: ast.Module, filename: str) -> Optional[Dict]:
    """
    Verify that no-args calls print_introspection() and --help calls print_help().

    These are two completely different things:
    - No args → introspection (what am I?)
    - --help → help (how do I use you?)

    Flags violations where they're swapped or mixed.
    """
    main_func = _find_main_function(tree)
    if main_func is None:
        main_func = _find_name_main_block(tree)
    if main_func is None:
        return None

    # Walk ALL conditionals in main (including nested ones in command routing)
    for node in ast.walk(main_func):
        if not isinstance(node, ast.If):
            continue

        # Check no-args block
        if _is_no_args_check(node):
            calls = _get_function_calls_in_block(node.body)
            if "print_help" in calls and "print_introspection" not in calls:
                return {
                    "name": "Correct dispatch",
                    "passed": False,
                    "message": f"No-args block calls print_help() in {filename} (line {node.lineno}) — should call print_introspection() (introspection != help)",
                }

        # Check --help block — look for help strings in the condition
        if _is_help_check(node):
            calls = _get_function_calls_in_block(node.body)
            # Calls introspection-related functions instead of print_help
            introspection_funcs = calls & {"print_introspection", "_show_pack_module_introspection"}
            if introspection_funcs and "print_help" not in calls:
                return {
                    "name": "Correct dispatch",
                    "passed": False,
                    "message": f"--help block calls {introspection_funcs.pop()}() in {filename} (line {node.lineno}) — should call print_help() (help != introspection)",
                }

        # Also check: condition contains --help string AND body calls introspection
        # This catches compound conditionals like: if not remaining or remaining[0] in ["--help"]
        if _ast_contains_help_string(node.test):
            calls = _get_function_calls_in_block(node.body)
            introspection_funcs = calls & {"print_introspection", "_show_pack_module_introspection"}
            if introspection_funcs and "print_help" not in calls:
                return {
                    "name": "Correct dispatch",
                    "passed": False,
                    "message": f"Block with --help condition calls {introspection_funcs.pop()}() in {filename} (line {node.lineno}) — --help should show help, not introspection",
                }

    return {
        "name": "Correct dispatch",
        "passed": True,
        "message": "No-args → introspection, --help → help (correct separation)",
    }


def _get_function_calls_in_block(body: list) -> set:
    """Extract all function call names from a block of AST statements."""
    calls = set()
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            # Direct call: print_introspection()
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            # Attribute call: self.print_introspection()
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls


def check_content_references(tree: ast.Module, filename: str) -> Optional[Dict]:
    """
    Check that print_introspection() and print_help() reference drone commands,
    not python3 standalone execution.

    Users and agents use `drone @branch command`, not `python3 module.py`.
    Help/introspection text that references python3 is misleading and causes
    agents to follow instructions that don't work.
    """
    target_funcs = {"print_introspection", "print_help"}
    python3_refs = []

    found_funcs = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            found_funcs.add(node.name)
            # Walk function body looking for string literals containing python3
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    val = child.value.lower()
                    if "python3 " in val or "python3\n" in val:
                        python3_refs.append((node.name, child.lineno))

    if not found_funcs:
        return None  # No relevant functions to check

    if python3_refs:
        refs_str = ", ".join(f"{fn}() line {ln}" for fn, ln in python3_refs[:3])
        return {
            "name": "Content references",
            "passed": False,
            "message": f'Help/introspection text references python3 instead of drone commands: {refs_str} in {filename} — use "drone @branch command" instead',
        }

    return {
        "name": "Content references",
        "passed": True,
        "message": "Help/introspection text uses correct command references",
    }


def check_module_help_interception(tree: ast.Module, filename: str) -> Optional[Dict]:
    """
    For modules, verify that handle_command() intercepts --help/-h before
    processing arguments as business logic.

    Without interception, --help gets treated as a regular argument
    (e.g., as a directory path or unknown filter).
    """
    handle_cmd = _find_handle_command_function(tree)
    if handle_cmd is None:
        return None  # No handle_command — skip

    # Look for --help check in handle_command()
    for node in ast.walk(handle_cmd):
        if isinstance(node, ast.If) and _is_help_check(node):
            return {
                "name": "Module help interception",
                "passed": True,
                "message": f"handle_command() intercepts --help at line {node.lineno}",
            }

    return {
        "name": "Module help interception",
        "passed": False,
        "message": f"handle_command() in {filename} does not intercept --help — flag may fall through to business logic",
    }
