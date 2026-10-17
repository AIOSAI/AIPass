# =================== AIPass ====================
# Name: introspection_check.py
# Description: Introspection Standards Checker Handler
# Version: 1.0.3
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Introspection Standards Checker Handler

Reference: introspection.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: the no-args gate is a module behaviour.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows introspection standards"""
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "introspection", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "INTROSPECTION",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "INTROSPECTION",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {"name": "Introspection check", "passed": True, "message": "__init__.py skipped", "declined": True}
            ],
            "score": 100,
            "standard": "INTROSPECTION",
        }

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

    if not content.strip():
        return {
            "passed": True,
            "checks": [
                {"name": "Introspection check", "passed": True, "message": "Empty file skipped", "declined": True}
            ],
            "score": 100,
            "standard": "INTROSPECTION",
        }

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

    is_entry_point = _is_entry_point(module_path, path)
    # A door is a re-export with no CLI: the modules standard reads its shape, there is nothing to introspect
    is_module = "/modules/" in module_path and path.parent.name == "modules" and not path.name.startswith("door_")

    if not is_entry_point and not is_module:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Introspection check",
                    "passed": True,
                    "message": "Not an entry point or module file (not applicable)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "INTROSPECTION",
        }

    introspection_check = check_print_introspection_exists(tree, path.name)
    checks.append(introspection_check)

    if introspection_check["passed"]:
        behavior_check = check_introspection_output_behavior(tree, path.name)
        if behavior_check:
            checks.append(behavior_check)

    if introspection_check["passed"]:
        discovery_check = check_introspection_dynamic_discovery(tree, path.name)
        if discovery_check:
            checks.append(discovery_check)

    if introspection_check["passed"]:
        richness_check = check_introspection_rich_formatting(tree, path.name)
        if richness_check:
            checks.append(richness_check)

    if is_entry_point:
        order_check = check_execution_order(tree, path.name)
        if order_check:
            checks.append(order_check)

    if is_entry_point:
        dispatch_check = check_correct_dispatch(tree, path.name)
        if dispatch_check:
            checks.append(dispatch_check)

    if is_module:
        gate_check = check_module_handle_command_gate(tree, path.name)
        if gate_check:
            checks.append(gate_check)

    content_check = check_content_references(tree, path.name)
    if content_check:
        checks.append(content_check)

    if is_module:
        help_check = check_module_help_interception(tree, path.name)
        if help_check:
            checks.append(help_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "introspection"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "INTROSPECTION"}


def _is_entry_point(module_path: str, path: Path) -> bool:
    """Detect if file is an entry point: apps/{name}.py (directly in apps/, not in subdirectory)"""
    if not path.name.endswith(".py"):
        return False
    posix_path = Path(module_path).as_posix()
    if "apps/" not in posix_path:
        return False
    return path.parent.name == "apps"


def check_print_introspection_exists(tree: ast.Module, filename: str) -> Dict:
    """Use AST to check if def print_introspection exists as a top-level function."""
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

    Walks into ``_``-prefixed helpers it delegates to: a styled helper counts.
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


def check_execution_order(tree: ast.Module, filename: str) -> Optional[Dict]:
    """In the main() function (or if __name__ block), verify that no-args check comes BEFORE --help check."""
    main_func = _find_main_function(tree)

    if main_func is None:
        main_func = _find_name_main_block(tree)

    if main_func is None:
        return {
            "name": "Execution order",
            "passed": True,
            "message": f"No main() or __name__ block found in {filename} (skipped)",
            "declined": True,
        }

    no_args_line = None
    help_check_line = None
    known_names = collect_help_predicate_names(tree)

    for node in ast.walk(main_func):
        if isinstance(node, ast.If):
            if _is_no_args_check(node):
                if no_args_line is None:
                    no_args_line = node.lineno

            if _is_help_check(node, known_names):
                if help_check_line is None:
                    help_check_line = node.lineno

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

    if help_check_line is not None and no_args_line is None:
        return {
            "name": "Execution order",
            "passed": False,
            "message": f"Found --help check but no no-args check in {filename} — add empty args handling before --help",
        }

    if no_args_line is not None and help_check_line is None:
        return {
            "name": "Execution order",
            "passed": True,
            "message": f"No-args check found at line {no_args_line} (no --help conditional to compare against)",
        }

    return {
        "name": "Execution order",
        "passed": True,
        "message": f"No args/help conditionals detected in main() of {filename} (skipped)",
        "declined": True,
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
    """Verify that a module's handle_command() has a no-args gate that calls print_introspection()."""
    handle_cmd = _find_handle_command_function(tree)

    if handle_cmd is None:
        # No handle_command — module may use a different pattern, skip
        return {
            "name": "handle_command no-args gate",
            "passed": True,
            "message": f"No handle_command() found in {filename} (skipped)",
            "declined": True,
        }

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

        calls = _get_function_calls_in_block(node.body)
        if calls & introspection_names:
            return {
                "name": "handle_command no-args gate",
                "passed": True,
                "message": f"handle_command() gates on no-args at line {node.lineno} → introspection",
            }

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
    """Find the if __name__ == '__main__': block at module level. Returns the If node so we can walk its body."""
    for node in tree.body:
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare):
                if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                    if (
                        test.comparators
                        and isinstance(test.comparators[0], ast.Constant)
                        and test.comparators[0].value == "__main__"
                    ):
                        return node
    return None


def _is_no_args_check(node: ast.If) -> bool:
    """Detect if an If node is checking for empty/no arguments."""
    test = node.test

    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        operand = test.operand
        if isinstance(operand, ast.Name) and operand.id == "args":
            return True
        if isinstance(operand, ast.Subscript):
            return True

    if isinstance(test, ast.Compare):
        left = test.left

        if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len":
            if left.args:
                arg = left.args[0]
                if isinstance(arg, ast.Name) and arg.id == "args":
                    if test.comparators and isinstance(test.comparators[0], ast.Constant):
                        val = test.comparators[0].value
                        if val in (0, 1):
                            return True
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

    ``help`` must be a whole word: a substring match would read ``helper`` or ``unhelpful`` as help guards.
    """
    return "help" in name.lower().split("_")


def collect_help_predicate_names(tree: ast.Module) -> frozenset:
    """
    Collect every function name this module defines or imports.

    Only names the module defines or imports count, so ``ctx.cli.wants_help(args)`` is not a guard.
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

    A predicate taking no arguments reads argv itself and is accepted; one that IS handed something must be
    handed the arguments (``wants_help(args)``), not an unrelated object.
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
    """Recursively check if an AST node contains a reference to '--help' or '-h' strings."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value in ("--help", "-h"):
            return True

    for child in ast.iter_child_nodes(node):
        if _ast_contains_help_string(child):
            return True

    return False


def check_correct_dispatch(tree: ast.Module, filename: str) -> Optional[Dict]:
    """Verify that no-args calls print_introspection() and --help calls print_help()."""
    main_func = _find_main_function(tree)
    if main_func is None:
        main_func = _find_name_main_block(tree)
    if main_func is None:
        return None

    known_names = collect_help_predicate_names(tree)

    for node in ast.walk(main_func):
        if not isinstance(node, ast.If):
            continue

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

        if _is_help_check(node, known_names):
            calls = _get_function_calls_in_block(node.body)
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

        # A compound conditional (`if not remaining or remaining[0] in ["--help"]`) is caught here too.
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
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls


def check_content_references(tree: ast.Module, filename: str) -> Optional[Dict]:
    """Check that print_introspection() and print_help() reference drone commands, not python3 standalone execution."""
    target_funcs = {"print_introspection", "print_help"}
    python3_refs = []

    found_funcs = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in target_funcs:
            found_funcs.add(node.name)
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
    """For modules, verify that handle_command() intercepts --help/-h before processing arguments as business logic."""
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
