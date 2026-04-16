# =================== AIPass ====================
# Name: modules_check.py
# Description: Modules Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-03-08
# =============================================

"""
Modules Standards Checker Handler

Validates module compliance with AIPass module standards.
Checks handle_command pattern, thin orchestration, file size guidelines.
"""

import re
import ast
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: all Python files
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
    Check if module follows module standards

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
    if is_bypassed(module_path, "modules", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "MODULES",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "MODULES",
        }

    # Read file
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

    # Only check files in modules/ directory
    is_module = "apps/modules/" in module_path
    if not is_module:
        return {
            "passed": True,
            "checks": [{"name": "Module check", "passed": True, "message": "Not a module file (skipped)"}],
            "score": 100,
            "standard": "MODULES",
        }

    # Check 1: handle_command pattern (for non-__init__ files)
    if not path.name == "__init__.py":
        handle_cmd_check = check_handle_command(content)
        if handle_cmd_check:
            checks.append(handle_cmd_check)

    # Check 2: File size guidelines
    size_check = check_file_size(lines, module_path)
    checks.append(size_check)

    # Check 3: No direct file operations (should use handlers)
    file_ops_check = check_no_direct_file_ops(content, lines)
    if file_ops_check:
        checks.append(file_ops_check)

    # Check 4: No business logic (hardcoded data)
    business_logic_check = check_no_business_logic(content, lines, module_path)
    if business_logic_check:
        checks.append(business_logic_check)

    # Check 5: Thin orchestration (no implementation functions)
    orchestration_check = check_thin_orchestration(content, module_path, bypass_rules)
    if orchestration_check:
        checks.append(orchestration_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "modules"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "MODULES"}


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
    """
    Check for handle_command pattern (drone routing standard)

    Modules should have: def handle_command(command: str, args: List[str]) -> bool
    """
    lines = content.split("\n")

    # Filter out comments and docstrings
    code_lines = []
    in_docstring = False

    for line in lines:
        stripped = line.strip()

        # Track docstrings - check for triple quotes anywhere in line
        skip_line, in_docstring = _track_docstring_state(stripped, in_docstring)
        if skip_line:
            continue

        # Skip docstrings and comments
        if in_docstring or stripped.startswith("#"):
            continue

        code_lines.append(line)

    # Search only actual code
    code_only = "\n".join(code_lines)

    # Check for handle_command function
    has_handle_command = bool(re.search(r"def\s+handle_command\s*\(", code_only))

    if not has_handle_command:
        return {
            "name": "handle_command pattern",
            "passed": False,
            "message": "Missing handle_command(command, args) -> bool for drone routing",
        }

    # Check return type annotation
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
    """
    Check file size against module guidelines

    Guidelines:
    - <150 lines: Simple (perfect)
    - 150-250: Standard (good)
    - 250-400: Complex (acceptable)
    - 400-600: Heavy (watch it)
    - 600+: Too large (split needed)
    """
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


def check_no_direct_file_ops(content: str, lines: List[str]) -> Optional[Dict]:
    """
    Check that module doesn't do direct file operations

    Modules should use handlers (like json_handler) not open(), Path.write_text(), etc.
    """
    file_operations = []

    in_docstring = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track docstrings (only if at start of line, not in strings)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring

        # Skip docstrings, comments and empty lines
        if in_docstring or not stripped or stripped.startswith("#"):
            continue

        # Check for direct file operations
        # Allow: from pathlib import Path (import is OK)
        # Allow: path = Path(...) (path creation is OK)
        # Forbidden: open(), .write_text(), .read_text(), .mkdir(), json.dump(), json.load()

        # Skip import lines
        if stripped.startswith("from ") or stripped.startswith("import "):
            continue

        # Check for forbidden operations
        # Match bare open() calls but NOT function names containing "open"
        # e.g. open(file) matches, but _handle_open(args) does NOT
        if re.search(r"(?<![.\w])open\s*\(", stripped) and "# open(" not in stripped:
            # Skip if in a string literal
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
        # Skip if line starts with whitespace (inside function/class)
        if line and line[0].isspace():
            continue

        # Check for list assignment
        match = list_pattern.match(line)
        if match:
            var_name = match.group(1)
            candidates[var_name] = line_num
            continue

        # Check for dict assignment
        match = dict_pattern.match(line)
        if match:
            var_name = match.group(1)
            candidates[var_name] = line_num

    return candidates


def check_no_business_logic(content: str, lines: List[str], module_path: str) -> Optional[Dict]:
    """
    Check that module doesn't contain hardcoded business logic data

    Detects hardcoded lists/dicts that should be in config files.
    Uses hybrid detection: line scan (fast) + AST verification (accurate).

    Only flags MODULE-LEVEL hardcoded data (function-local is OK for display/temp data).
    Skips: ALL_CAPS constants, empty structures, code references, function-local vars.
    """
    # Phase 1: Quick line scan for candidates (module-level only = no leading whitespace)
    # Only match assignments at column 0 (module level)
    list_pattern = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*\[")
    dict_pattern = re.compile(r"^([a-z][a-z0-9_]*)\s*=\s*\{")

    candidates = _scan_candidates(lines, list_pattern, dict_pattern)

    if not candidates:
        return {"name": "No business logic", "passed": True, "message": "No hardcoded data structures detected"}

    # Phase 2: AST verification (only module-level assignments)
    violations = []

    try:
        tree = ast.parse(content, filename=module_path)

        # Only check module-level assignments (tree.body), not function-local
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue

            # Get variable name
            if not isinstance(node.targets[0], ast.Name):
                continue

            var_name = node.targets[0].id

            # Only check candidates found in phase 1
            if var_name not in candidates:
                continue

            # Filter: Skip ALL_CAPS (constants)
            if var_name.isupper():
                continue

            # Check if it's a list or dict
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

            # Filter: Skip empty structures
            if element_count == 0:
                continue

            # Filter: Skip structures containing only code references (not data)
            if _is_code_reference_structure(value):
                continue

            # This is a confirmed violation
            violations.append({"line": node.lineno, "var": var_name, "type": var_type, "count": element_count})

    except SyntaxError:
        logger.info("Skipped business logic check: SyntaxError in %s", module_path)
        return None
    except Exception:
        logger.info("Skipped business logic check: parse error in %s", module_path)
        return None

    if violations:
        # Report first violation
        v = violations[0]
        msg = f"Line {v['line']}: '{v['var']}' has hardcoded {v['type']} with {v['count']} elements (move to config)"
        return {"name": "No business logic", "passed": False, "message": msg}

    return {"name": "No business logic", "passed": True, "message": "No hardcoded data structures detected"}


def check_thin_orchestration(content: str, module_path: str, bypass_rules: list | None = None) -> Optional[Dict]:
    """
    Check that module is a thin orchestrator (delegates to handlers).

    Modules should only have standard functions:
    - handle_command() - command routing
    - print_help() - help display
    - print_introspection() - module info display
    - main() - standalone entry point

    Also allowed:
    - handle_* — sub-command routing (same role as handle_command)
    - show_* — display/presentation orchestration
    - route_* — routing/dispatch functions
    - dispatch_* — dispatching functions
    - list_* — query/listing orchestration
    - get_* — data queries and getters
    - load_* — loading configs, registries, data
    - print_* — display wrappers
    - _* — private helpers

    Functions with <= 15 lines of code are considered thin wrappers
    and are allowed regardless of naming.

    Remaining public functions with >15 lines indicate implementation
    logic that belongs in handlers.
    """
    # Standard allowed functions in modules
    ALLOWED_FUNCTIONS = {
        "handle_command",
        "print_help",
        "print_introspection",
        "main",
    }

    # Prefixes that indicate orchestration patterns (not implementation)
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

    # Max lines for a function to be considered a thin wrapper
    # Under 40 lines = likely orchestration (parsing args, calling handlers, formatting)
    # Over 40 lines = likely implementation that belongs in handlers
    THIN_WRAPPER_MAX_LINES = 40

    # Check bypass
    if is_bypassed(module_path, "modules", bypass_rules=bypass_rules):
        return {"name": "Thin orchestration", "passed": True, "message": "Bypassed - thin orchestration check skipped"}

    try:
        tree = ast.parse(content, filename=module_path)
    except SyntaxError:
        logger.info("Skipped orchestration check: SyntaxError in %s", module_path)
        return None

    # Find all top-level function definitions
    non_standard_functions = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            func_name = node.name

            # Skip allowed functions
            if func_name in ALLOWED_FUNCTIONS:
                continue

            # Skip functions with orchestration prefixes
            if func_name.startswith(ORCHESTRATION_PREFIXES):
                continue

            # Skip thin wrappers (small functions are orchestration, not implementation)
            func_lines = (node.end_lineno - node.lineno + 1) if node.end_lineno is not None else 0
            if func_lines <= THIN_WRAPPER_MAX_LINES:
                continue

            # This is a non-standard function with substantial body - implementation logic
            non_standard_functions.append({"name": func_name, "line": node.lineno, "lines": func_lines})

    if non_standard_functions:
        # Report violation
        func_list = [f"{f['name']} (line {f['line']})" for f in non_standard_functions[:5]]
        extra = f" +{len(non_standard_functions) - 5} more" if len(non_standard_functions) > 5 else ""

        return {
            "name": "Thin orchestration",
            "passed": False,
            "message": f"Module has {len(non_standard_functions)} implementation function(s) that belong in handlers: {', '.join(func_list)}{extra}",
        }

    return {
        "name": "Thin orchestration",
        "passed": True,
        "message": "Module is thin orchestrator (standard functions only)",
    }
