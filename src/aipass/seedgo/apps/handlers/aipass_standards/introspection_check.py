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
import re
from pathlib import Path
from typing import Dict, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Run on ALL .py files so modules (apps/modules/*.py) are checked, not just entry points
AUDIT_SCOPE = "all_files"


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

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

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

    # Check 1b: print_introspection produces output (not just returns data)
    if introspection_check["passed"]:
        behavior_check = check_introspection_output_behavior(tree, path.name)
        if behavior_check:
            checks.append(behavior_check)

    # Check 1c: print_introspection uses dynamic discovery (no hardcoded module lists)
    if introspection_check["passed"]:
        discovery_check = check_introspection_dynamic_discovery(tree, path.name)
        if discovery_check:
            checks.append(discovery_check)

    # Check 1d: print_introspection uses Rich formatting (not flat plain strings)
    if introspection_check["passed"]:
        richness_check = check_introspection_rich_formatting(tree, path.name)
        if richness_check:
            checks.append(richness_check)

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
    # Normalize to forward slashes for cross-platform string matching
    posix_path = Path(module_path).as_posix()
    if "apps/" not in posix_path:
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


def _find_print_introspection(tree: ast.Module) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "print_introspection":
            return node
    return None


def _has_output_calls(func_node: ast.FunctionDef) -> bool:
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "print":
                return True
            # Delegation to helper functions counts as output production
            if name.startswith("_"):
                return True
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in ("print", "write"):
                return True
    return False


def _returns_data(func_node: ast.FunctionDef) -> Optional[int]:
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value is not None:
            if not isinstance(node.value, ast.Constant) or node.value.value is not None:
                return node.lineno
    return None


def check_introspection_output_behavior(tree: ast.Module, filename: str) -> Optional[Dict]:
    """Verify print_introspection() produces output via print/console.print, not just returns data."""
    func = _find_print_introspection(tree)
    if func is None:
        return None

    has_output = _has_output_calls(func)
    return_line = _returns_data(func)

    if return_line is not None and not has_output:
        return {
            "name": "Introspection output",
            "passed": False,
            "message": (
                f"print_introspection() in {filename} returns data (line {return_line}) "
                f"but does not print — should use console.print() to display structure"
            ),
        }

    if not has_output and return_line is None:
        return {
            "name": "Introspection output",
            "passed": False,
            "message": (
                f"print_introspection() in {filename} produces no output — "
                f"should use console.print() to display branch structure"
            ),
        }

    return {
        "name": "Introspection output",
        "passed": True,
        "message": "print_introspection() produces output",
    }


def check_introspection_dynamic_discovery(tree: ast.Module, filename: str) -> Optional[Dict]:
    """Verify print_introspection() uses dynamic module discovery, not hardcoded lists."""
    func = _find_print_introspection(tree)
    if func is None:
        return None

    hardcoded_lists = []
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            _collect_hardcoded_string_lists(node.value, hardcoded_lists)
        if isinstance(node, ast.Assign):
            _collect_hardcoded_string_lists(node.value, hardcoded_lists)

    if hardcoded_lists:
        items_preview = ", ".join(hardcoded_lists[:4])
        extra = f" +{len(hardcoded_lists) - 4} more" if len(hardcoded_lists) > 4 else ""
        return {
            "name": "Introspection discovery",
            "passed": False,
            "message": (
                f"print_introspection() in {filename} has hardcoded lists "
                f"[{items_preview}{extra}] — should auto-discover modules via Path.glob or similar"
            ),
        }

    return {
        "name": "Introspection discovery",
        "passed": True,
        "message": "print_introspection() has no hardcoded module/handler lists",
    }


def _collect_hardcoded_string_lists(node: ast.AST, result: list) -> None:
    if isinstance(node, ast.List):
        string_vals = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        if string_vals:
            result.extend(string_vals)
    elif isinstance(node, ast.Dict):
        for value in node.values:
            if value is not None:
                _collect_hardcoded_string_lists(value, result)
    elif isinstance(node, ast.Tuple):
        string_vals = [elt.value for elt in node.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
        if string_vals:
            result.extend(string_vals)


def check_introspection_rich_formatting(tree: ast.Module, filename: str) -> Optional[Dict]:
    """Verify print_introspection() uses Rich markup tags, not flat plain strings.

    AIPass design pattern requires consistent Rich formatting in introspection output.
    Checks for square-bracket tags like [bold cyan], [dim], [yellow], [green], [/...].

    Delegation: if print_introspection delegates to _-prefixed helpers in the same file,
    walks into those helpers to find markup (treats delegation as valid if helper is styled).
    """
    func = _find_print_introspection(tree)
    if func is None:
        return None

    if not _has_output_calls(func):
        return None

    if _has_rich_markup(func):
        return {
            "name": "Rich formatting",
            "passed": True,
            "message": "print_introspection() uses Rich markup tags",
        }

    delegated_helpers = _get_delegated_helpers(func)
    if delegated_helpers:
        helpers_map = _build_helpers_map(tree)
        for helper_name in delegated_helpers:
            helper_func = helpers_map.get(helper_name)
            if helper_func and _has_rich_markup(helper_func):
                return {
                    "name": "Rich formatting",
                    "passed": True,
                    "message": f"print_introspection() delegates to {helper_name}() which uses Rich markup",
                }
        return {
            "name": "Rich formatting",
            "passed": False,
            "message": (
                f"print_introspection() in {filename} delegates to "
                f"{', '.join(delegated_helpers)} but no Rich markup found — "
                f"introspection output must use Rich formatting tags "
                f"(e.g. [bold cyan], [dim], [yellow])"
            ),
        }

    return {
        "name": "Rich formatting",
        "passed": False,
        "message": (
            f"print_introspection() in {filename} produces output but has no Rich "
            f"markup tags — introspection must use Rich formatting "
            f"(e.g. [bold cyan], [dim], [yellow]) for consistent design"
        ),
    }


_RICH_TAG_RE = re.compile(r"\[/?(?:bold|dim|italic|cyan|yellow|green|red|blue|magenta|white|underline)[^\]]*\]")


def _has_rich_markup(func_node: ast.FunctionDef) -> bool:
    for node in ast.walk(func_node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _RICH_TAG_RE.search(node.value):
                return True
    return False


def _get_delegated_helpers(func_node: ast.FunctionDef) -> list:
    helpers = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id.startswith("_"):
                helpers.append(node.func.id)
    return helpers


def _build_helpers_map(tree: ast.Module) -> dict:
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            result[node.name] = node
    return result


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
    known_names = collect_help_predicate_names(tree)

    for node in ast.walk(main_func):
        if isinstance(node, ast.If):
            # Check if this conditional is a no-args check
            if _is_no_args_check(node):
                if no_args_line is None:
                    no_args_line = node.lineno

            # Check if this conditional is a help flag check
            if _is_help_check(node, known_names):
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
                "message": (
                    f"--help check (line {help_check_line}) before no-args check "
                    f"(line {no_args_line}) — no-args should come first"
                ),
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
        "message": (
            f"handle_command() in {filename} has no no-args gate calling "
            f"print_introspection() — module will not show introspection "
            f"when called with no arguments"
        ),
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


# Names that stand for the caller's argument list. A delegated help predicate
# must be asked about the arguments — `wants_help(args)` guards a command,
# `_contains_help_string(node)` inspects a syntax tree and guards nothing.
_ARGUMENT_NAMES = frozenset(
    {
        "arg",
        "args",
        "argument",
        "arguments",
        "argv",
        "cmd",
        "command",
        "flags",
        "extra",
        "opts",
        "options",
        "params",
        "remaining",
        "rest",
        "tokens",
    }
)


def _has_help_token(name: str) -> bool:
    """
    Report whether a snake_case name carries `help` as a whole word.

    Accepts: wants_help, is_help, is_help_flag, should_show_help, _help_requested.
    Rejects: helper, _has_credential_helper, unhelpful — `help` is only a
    substring there, and a substring match would read unrelated predicates
    as help guards.
    """
    return "help" in name.lower().split("_")


def collect_help_predicate_names(tree: ast.Module) -> frozenset:
    """
    Collect every function name this module defines or imports.

    A delegated help predicate only counts when the module actually owns the
    name — locally defined or explicitly imported. This keeps an arbitrary
    attribute chain (`ctx.cli.wants_help(args)`) from passing as a guard.
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return frozenset(names)


def _call_targets_arguments(call: ast.Call) -> bool:
    """
    Report whether a call is asked about the caller's argument list.

    A predicate taking no arguments reads argv itself, so there is nothing to
    inspect and it is accepted. A predicate that IS handed something must be
    handed the arguments (`wants_help(args)`, `wants_help(args[1:])`), not an
    unrelated object.
    """
    supplied = list(call.args) + [kw.value for kw in call.keywords]
    if not supplied:
        return True

    for value in supplied:
        for sub in ast.walk(value):
            if isinstance(sub, ast.Name) and sub.id.lower() in _ARGUMENT_NAMES:
                return True
            if isinstance(sub, ast.Attribute) and sub.attr == "argv":
                return True
    return False


def _is_help_predicate_call(call: ast.Call, known_names: frozenset) -> bool:
    """Report whether a call delegates the help decision to a help predicate."""
    func = call.func
    if isinstance(func, ast.Name):
        name = root = func.id
    elif isinstance(func, ast.Attribute):
        # module-qualified call: help_flags.wants_help(args)
        if not isinstance(func.value, ast.Name):
            return False
        name, root = func.attr, func.value.id
    else:
        return False

    if not _has_help_token(name):
        return False
    if root not in known_names:
        return False
    return _call_targets_arguments(call)


def _is_help_check(node: ast.If, known_names: frozenset | None = None) -> bool:
    """
    Detect if an If node is checking for --help or -h flags.

    Literal patterns detected:
    - '--help' in args
    - '-h' in args
    - args[0] == '--help'
    - args[0] in ('--help', '-h')
    - Comparisons involving the string '--help' or '-h'

    Delegated patterns detected (when known_names is supplied):
    - wants_help(args)
    - wants_help(args, allow_bare_word=True)
    - help_flags.wants_help(args)

    A module that routes help through a shared predicate holds no '--help'
    literal of its own, so literal-only detection reports the modules that
    guard correctly and stays silent on the ones that do not.
    """
    if _ast_contains_help_string(node.test):
        return True

    if known_names:
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call) and _is_help_predicate_call(sub, known_names):
                return True

    return False


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

    known_names = collect_help_predicate_names(tree)

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
                    "message": (
                        f"No-args block calls print_help() in {filename} "
                        f"(line {node.lineno}) — should call "
                        f"print_introspection() (introspection != help)"
                    ),
                }

        # Check --help block — look for help strings in the condition
        if _is_help_check(node, known_names):
            calls = _get_function_calls_in_block(node.body)
            # Calls introspection-related functions instead of print_help
            introspection_funcs = calls & {"print_introspection", "_show_pack_module_introspection"}
            if introspection_funcs and "print_help" not in calls:
                return {
                    "name": "Correct dispatch",
                    "passed": False,
                    "message": (
                        f"--help block calls {introspection_funcs.pop()}() in "
                        f"{filename} (line {node.lineno}) — should call "
                        f"print_help() (help != introspection)"
                    ),
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
                    "message": (
                        f"Block with --help condition calls "
                        f"{introspection_funcs.pop()}() in {filename} "
                        f"(line {node.lineno}) — --help should show help, "
                        f"not introspection"
                    ),
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
            "message": (
                f"Help/introspection text references python3 instead of "
                f"drone commands: {refs_str} in {filename} — "
                f'use "drone @branch command" instead'
            ),
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

    # Look for --help check in handle_command() — a literal flag comparison or
    # a delegated predicate this module defines or imports
    known_names = collect_help_predicate_names(tree)
    for node in ast.walk(handle_cmd):
        if isinstance(node, ast.If) and _is_help_check(node, known_names):
            return {
                "name": "Module help interception",
                "passed": True,
                "message": f"handle_command() intercepts --help at line {node.lineno}",
            }

    return {
        "name": "Module help interception",
        "passed": False,
        "message": (
            f"handle_command() in {filename} does not intercept --help — flag may fall through to business logic"
        ),
    }
