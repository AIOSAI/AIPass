# =================== AIPass ====================
# Name: modules_check.py
# Description: Modules Standards Checker Handler
# Version: 1.4.1
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""
Modules Standards Checker Handler

Validates module compliance with AIPass module standards.
Checks handle_command pattern, thin orchestration, file size guidelines.
"""

import re
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

AUDIT_SCOPE = "all_files"
# Applies to production source only: the module contract describes apps/modules/
# orchestration code, which a test file is not.
APPLIES_TO = "production"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows module standards"""
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "modules", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "MODULES",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "MODULES",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "MODULES",
        }

    is_module = "apps/modules/" in module_path
    if not is_module:
        return {
            "passed": True,
            "checks": [
                {"name": "Module check", "passed": True, "message": "Not a module file (skipped)", "declined": True}
            ],
            "score": 100,
            "standard": "MODULES",
        }

    # A door is a re-export with no CLI: its own row replaces handle_command; the size and logic rows still stand
    if path.name.startswith("door_"):
        checks.append(check_door(content, module_path))
    elif not path.name == "__init__.py":
        handle_cmd_check = check_handle_command(content)
        if handle_cmd_check:
            checks.append(handle_cmd_check)

    size_check = check_file_size(lines, module_path)
    checks.append(size_check)

    file_ops_check = check_no_direct_file_ops(lines)
    if file_ops_check:
        checks.append(file_ops_check)

    business_logic_check = check_no_business_logic(content, lines, module_path)
    if business_logic_check:
        checks.append(business_logic_check)

    orchestration_check = check_thin_orchestration(content, module_path, bypass_rules)
    if orchestration_check:
        checks.append(orchestration_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    overall_passed = score >= 75

    # A door's verdict is its shape: a failing Door shape row fails the file even when the aggregate passes
    door_fault = [check for check in checks if check["name"] == "Door shape" and not check["passed"]]
    if door_fault:
        score, overall_passed = 0, False

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "modules"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "MODULES"}


def _own_branch(module_path: str) -> str:
    """The path segment before ``apps``: the branch a modules file belongs to."""
    parts = Path(module_path).parts
    for i, part in enumerate(parts):
        if part == "apps" and i > 0:
            return parts[i - 1]
    return ""


def _door_statement_problem(node: ast.stmt, own_handlers: "re.Pattern[str]", imported: set) -> Optional[str]:
    """What one top-level statement of a door does wrong, or None.

    Imports from the branch's own handlers add their names to ``imported``;
    a stdlib import is allowed and exports nothing.
    """
    if isinstance(node, ast.ImportFrom):
        module = ("." * node.level) + (node.module or "")
        if node.level == 0 and own_handlers.match(module):
            imported.update(alias.asname or alias.name for alias in node.names)
            return None
        if node.level == 0 and module.split(".")[0] in sys.stdlib_module_names:
            return None
        return f"line {node.lineno}: imports {module} (a door imports only its own handlers)"
    if isinstance(node, ast.Import):
        foreign = [a.name for a in node.names if a.name.split(".")[0] not in sys.stdlib_module_names]
        return f"line {node.lineno}: imports {foreign[0]} (a door imports only its own handlers)" if foreign else None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return f"line {node.lineno}: defines {node.name} (a door carries no logic)"
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return None  # the docstring
    if isinstance(node, ast.Assign) and [getattr(t, "id", "") for t in node.targets] == ["__all__"]:
        return None
    return f"line {node.lineno}: a statement beyond re-export (a door carries no logic)"


def check_door(content: str, module_path: str) -> Dict:
    """Check that ``apps/modules/door_<subject>.py`` is a door and nothing else.

    A door imports only from its OWN branch's ``apps.handlers`` (and the stdlib), defines no function or
    class, and carries an ``__all__`` of names it imported. Foreign handlers may import it: modules are the gateway.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.info("modules: door unparseable %s: %s", module_path, exc)
        return {"name": "Door shape", "passed": False, "message": f"Door does not parse: {exc}"}
    # A handlers package nested anywhere under the branch's tree is its own, as encapsulation reads it.
    own_handlers = re.compile(rf"aipass\.{re.escape(_own_branch(module_path))}\.(?:\w+\.)*?apps\.handlers(?:\.|$)")
    imported: set = set()
    problems = [p for node in tree.body if (p := _door_statement_problem(node, own_handlers, imported))]
    exported: Optional[List[str]] = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and [getattr(t, "id", "") for t in node.targets] == ["__all__"]:
            exported = list(ast.literal_eval(node.value)) if isinstance(node.value, (ast.List, ast.Tuple)) else None
    if exported is None:
        exported = []
        problems.append("carries no __all__ list of names")
    problems += [f"__all__ names {name!r}, which it does not import" for name in exported if name not in imported]
    if problems:
        return {"name": "Door shape", "passed": False, "message": "Door shape: " + "; ".join(problems)}
    return {
        "name": "Door shape",
        "passed": True,
        "message": f"Door re-exports only its own handlers ({len(exported)} names)",
    }


def _track_docstring_state(stripped: str, in_docstring: bool) -> tuple:
    """Returns (skip_line, new_in_docstring) for a stripped line."""
    if '"""' in stripped or "'''" in stripped:
        has_triple_double = '"""' in stripped
        has_triple_single = "'''" in stripped

        if has_triple_double:
            quote_count = stripped.count('"""')
            if quote_count % 2 == 1:
                in_docstring = not in_docstring
            return True, in_docstring
        elif has_triple_single:
            quote_count = stripped.count("'''")
            if quote_count % 2 == 1:
                in_docstring = not in_docstring
            return True, in_docstring

    return False, in_docstring


def check_handle_command(content: str) -> Optional[Dict]:
    """Check for handle_command pattern (drone routing standard)"""
    lines = content.split("\n")

    code_lines = []
    in_docstring = False

    for line in lines:
        stripped = line.strip()

        skip_line, in_docstring = _track_docstring_state(stripped, in_docstring)
        if skip_line:
            continue

        if in_docstring or stripped.startswith("#"):
            continue

        code_lines.append(line)

    code_only = "\n".join(code_lines)

    has_handle_command = bool(re.search(r"def\s+handle_command\s*\(", code_only))

    if not has_handle_command:
        return {
            "name": "handle_command pattern",
            "passed": False,
            "message": "Missing handle_command(command, args) -> bool for drone routing",
        }

    has_bool_return = bool(re.search(r"def\s+handle_command\([^)]*\)\s*->\s*bool", code_only))

    if not has_bool_return:
        return {
            "name": "handle_command pattern",
            "passed": False,
            "message": "handle_command exists but missing -> bool return type annotation",
        }

    return {
        "name": "handle_command pattern",
        "passed": True,
        "message": "handle_command(command, args) -> bool pattern implemented",
    }


def check_file_size(lines: List[str], module_path: str) -> Dict:
    """Check file size against module guidelines"""
    line_count = len(lines)

    if line_count < 150:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (simple - perfect size)"}
    elif line_count < 250:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (standard - good size)"}
    elif line_count < 400:
        return {"name": "File size", "passed": True, "message": f"{line_count} lines (complex - acceptable, watch it)"}
    elif line_count < 600:
        return {
            "name": "File size",
            "passed": True,
            "message": f"{line_count} lines (heavy - consider splitting into domains)",
        }
    else:
        return {
            "name": "File size",
            "passed": False,
            "message": f"{line_count} lines (too large - split required for AI comprehension)",
        }


def check_no_direct_file_ops(lines: List[str]) -> Optional[Dict]:
    """Check that module doesn't do direct file operations"""
    file_operations = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        skip_line, in_docstring = _track_docstring_state(stripped, in_docstring)
        if skip_line or in_docstring or not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("from ") or stripped.startswith("import "):
            continue

        # Bare open() only: the lookbehind keeps _handle_open(args) out.
        if re.search(r"(?<![.\w])open\s*\(", stripped) and "# open(" not in stripped:
            before_pattern = stripped.split("open(")[0]
            single_quotes = before_pattern.count("'")
            double_quotes = before_pattern.count('"')
            if single_quotes % 2 == 1 or double_quotes % 2 == 1:
                continue
            file_operations.append(f"line {i}: {stripped} (use handler instead)")

        if ".write_text(" in stripped or ".read_text(" in stripped:
            file_operations.append(f"line {i}: {stripped} (use json_handler instead)")

        if ".mkdir(" in stripped:
            file_operations.append(f"line {i}: {stripped} (use handler for file operations)")

        if "json.dump(" in stripped or "json.load(" in stripped:
            file_operations.append(f"line {i}: {stripped} (use json_handler instead)")

    if file_operations:
        return {
            "name": "No direct file operations",
            "passed": False,
            "message": f"Module has direct file operations: {file_operations[0]}",
        }

    return {
        "name": "No direct file operations",
        "passed": True,
        "message": "No direct file operations detected (uses handlers)",
    }


def _is_code_reference_structure(value) -> bool:
    code_ref_types = (ast.Name, ast.Call, ast.Attribute)
    if isinstance(value, ast.List):
        return all(isinstance(elt, code_ref_types) for elt in value.elts)
    if isinstance(value, ast.Dict):
        return all(isinstance(v, code_ref_types) for v in value.values)
    return False


def _scan_candidates(lines: List[str], list_pattern, dict_pattern) -> dict:
    """Scan for module-level list/dict assignment candidates."""
    candidates = {}
    for line_num, line in enumerate(lines, start=1):
        if line and line[0].isspace():
            continue

        match = list_pattern.match(line)
        if match:
            var_name = match.group(1)
            candidates[var_name] = line_num
            continue

        match = dict_pattern.match(line)
        if match:
            var_name = match.group(1)
            candidates[var_name] = line_num

    return candidates


def check_no_business_logic(content: str, lines: List[str], module_path: str) -> Optional[Dict]:
    """Check that module doesn't contain hardcoded business logic data"""
    list_pattern = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*\[")
    dict_pattern = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*\{")

    candidates = _scan_candidates(lines, list_pattern, dict_pattern)

    if not candidates:
        return {"name": "No business logic", "passed": True, "message": "No hardcoded data structures detected"}

    violations = []

    try:
        tree = ast.parse(content, filename=module_path)

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue

            if not isinstance(node.targets[0], ast.Name):
                continue

            var_name = node.targets[0].id

            if var_name not in candidates:
                continue

            if var_name.isupper():
                continue

            value = node.value
            var_type = None
            element_count = 0

            if isinstance(value, ast.List):
                var_type = "list"
                element_count = len(value.elts)
            elif isinstance(value, ast.Dict):
                var_type = "dict"
                element_count = len(value.keys)
            else:
                continue  # Not a list or dict

            if element_count == 0:
                continue

            if _is_code_reference_structure(value):
                continue

            violations.append({"line": node.lineno, "var": var_name, "type": var_type, "count": element_count})

    except SyntaxError:
        logger.info("Skipped business logic check: SyntaxError in %s", module_path)
        return None
    except Exception:
        logger.info("Skipped business logic check: parse error in %s", module_path)
        return None

    if violations:
        v = violations[0]
        msg = f"Line {v['line']}: '{v['var']}' has hardcoded {v['type']} with {v['count']} elements (move to config)"
        return {"name": "No business logic", "passed": False, "message": msg}

    return {"name": "No business logic", "passed": True, "message": "No hardcoded data structures detected"}


def check_thin_orchestration(content: str, module_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """Check that module is a thin orchestrator (delegates to handlers)."""
    ALLOWED_FUNCTIONS = {
        "handle_command",
        "print_help",
        "print_introspection",
        "main",
    }

    ORCHESTRATION_PREFIXES = (
        "_",  # Private helpers
        "print_",  # Display wrappers
        "handle_",  # Sub-command routing
        "show_",  # Display/presentation
        "route_",  # Routing/dispatch
        "dispatch_",  # Dispatching
        "list_",  # Query/listing
        "get_",  # Data queries/getters
        "load_",  # Loading configs/data
        "close_",  # Lifecycle orchestration (close plans, sessions)
        "restore_",  # Lifecycle orchestration (restore plans, state)
        "create_",  # Lifecycle orchestration (create plans, resources)
        "delete_",  # Lifecycle orchestration (delete plans, resources)
        "update_",  # Lifecycle orchestration (update state, records)
        "send_",  # Dispatch orchestration (send emails, events)
        "run_",  # Execution orchestration (run tasks, workflows)
    )

    # Under 40 lines is likely orchestration (parse args, call handlers, format); over is implementation.
    THIN_WRAPPER_MAX_LINES = 40

    if is_bypassed(module_path, "modules", bypass_rules=bypass_rules):
        return {
            "name": "Thin orchestration",
            "passed": True,
            "message": "Bypassed - thin orchestration check skipped",
            "declined": True,
        }

    try:
        tree = ast.parse(content, filename=module_path)
    except SyntaxError:
        logger.info("Skipped orchestration check: SyntaxError in %s", module_path)
        return None

    non_standard_functions = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            func_name = node.name

            if func_name in ALLOWED_FUNCTIONS:
                continue

            if func_name.startswith(ORCHESTRATION_PREFIXES):
                continue

            func_lines = (node.end_lineno - node.lineno + 1) if node.end_lineno is not None else 0
            if func_lines <= THIN_WRAPPER_MAX_LINES:
                continue

            non_standard_functions.append({"name": func_name, "line": node.lineno, "lines": func_lines})

    if non_standard_functions:
        func_list = [f"{f['name']} (line {f['line']})" for f in non_standard_functions[:5]]
        extra = f" +{len(non_standard_functions) - 5} more" if len(non_standard_functions) > 5 else ""

        return {
            "name": "Thin orchestration",
            "passed": False,
            "message": (
                f"Module has {len(non_standard_functions)} implementation function(s) "
                f"that belong in handlers: {', '.join(func_list)}{extra}"
            ),
        }

    return {
        "name": "Thin orchestration",
        "passed": True,
        "message": "Module is thin orchestrator (standard functions only)",
    }
