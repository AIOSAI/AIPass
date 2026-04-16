# =================== AIPass ====================
# Name: naming_check.py
# Description: Naming Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Naming Standards Checker Handler

Validates module compliance with AIPass naming standards.
Checks file naming, function naming, variable naming, constant naming.
"""

import re
from pathlib import Path
from typing import Dict, Optional
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
    Check if module follows naming standards

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain violations

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
    if is_bypassed(module_path, "naming", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "NAMING",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "NAMING",
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
            "standard": "NAMING",
        }

    # Check 1: File naming (snake_case, no redundant prefixes)
    file_naming_check = check_file_naming(module_path, path)
    checks.append(file_naming_check)

    # Check 2: Function naming (snake_case)
    function_naming_check = check_function_naming(content)
    if function_naming_check:
        checks.append(function_naming_check)

    # Check 3: Constant naming (UPPER_CASE)
    constant_naming_check = check_constant_naming(content)
    if constant_naming_check:
        checks.append(constant_naming_check)

    # Check 4: Class naming (PascalCase) - if classes exist
    class_naming_check = check_class_naming(content)
    if class_naming_check:
        checks.append(class_naming_check)

    # Calculate score
    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    # Overall pass if score >= 75%
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "naming"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "NAMING"}


def check_file_naming(module_path: str, path: Path) -> Dict:
    """
    Check file naming conventions

    Rules:
    - snake_case filenames
    - No redundant prefixes (json/json_ops.py should be json/ops.py)
    - Exception: json_handler.py (documented exception)
    - Prefer standard verbs (create, ops, load, save, initialize, etc.)
    """
    filename = path.stem  # filename without extension

    # Python-reserved package marker — cannot be renamed
    if path.name == "__init__.py":
        return {"name": "File naming", "passed": True, "message": "__init__.py (Python-reserved package marker)"}

    # Check if it's the documented exception
    if filename == "json_handler" and "/handlers/json/" in module_path:
        return {
            "name": "File naming",
            "passed": True,
            "message": f"{filename}.py (documented exception - standardized handler)",
        }

    # Check for snake_case
    if not re.match(r"^[a-z][a-z0-9_]*$", filename):
        return {
            "name": "File naming",
            "passed": False,
            "message": f"{filename}.py uses invalid characters (use snake_case: lowercase + underscores)",
        }

    # Check for redundant prefixes
    # Extract parent directory name
    if len(path.parts) > 1:
        parent_dir = path.parts[-2]

        # Check if filename starts with parent directory name
        if filename.startswith(f"{parent_dir}_"):
            return {
                "name": "File naming",
                "passed": False,
                "message": f"{filename}.py has redundant prefix (in {parent_dir}/ dir, use {filename.replace(f'{parent_dir}_', '')}.py)",
            }

    # Check for standard verbs (informational)
    standard_verbs = [
        "create",
        "ops",
        "load",
        "save",
        "initialize",
        "formatters",
        "decorators",
        "logger",
        "prompts",
        "content",
        "check",
        "handler",
    ]
    uses_standard_verb = any(verb in filename for verb in standard_verbs)

    if uses_standard_verb:
        return {"name": "File naming", "passed": True, "message": f"{filename}.py (snake_case, uses standard verb)"}
    else:
        return {
            "name": "File naming",
            "passed": True,
            "message": f"{filename}.py (snake_case, custom name - consider standard verbs)",
        }


def check_function_naming(content: str) -> Optional[Dict]:
    """
    Check function naming conventions

    Rules:
    - snake_case function names
    - No single-letter names (except in list comprehensions/loops)
    """
    # Find all function definitions
    function_pattern = r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
    functions = re.findall(function_pattern, content, re.MULTILINE)

    if not functions:
        return None  # No functions to check

    # Check each function name
    bad_functions = []
    for func_name in functions:
        # Skip dunder methods
        if func_name.startswith("__") and func_name.endswith("__"):
            continue

        # Check for snake_case
        if not re.match(r"^[a-z_][a-z0-9_]*$", func_name):
            bad_functions.append(func_name)

    if bad_functions:
        return {
            "name": "Function naming",
            "passed": False,
            "message": f"Non-snake_case functions: {', '.join(bad_functions[:3])}{'...' if len(bad_functions) > 3 else ''}",
        }

    return {
        "name": "Function naming",
        "passed": True,
        "message": f"{len(functions)} functions checked - all snake_case",
    }


def check_constant_naming(content: str) -> Optional[Dict]:
    """
    Check constant naming conventions

    Rules:
    - UPPER_CASE for module-level constants
    - Assigned outside of functions/classes (column 0 only)
    - Excludes module imports (from X import Y as Z)
    - Excludes __dunder__ variables (PEP 8 convention: always lowercase)
    """
    # First pass: collect imported names to exclude from constant checking
    imported_names = set()
    for line in content.split("\n"):
        stripped = line.strip()
        # Match: from X import Y, Z
        if stripped.startswith("from ") and " import " in stripped:
            import_part = stripped.split(" import ", 1)[1]
            # Handle 'as' aliases: logger = system_logger
            for item in import_part.split(","):
                item = item.strip()
                if " as " in item:
                    # "system_logger as logger" -> get "logger"
                    imported_names.add(item.split(" as ")[1].strip())
                else:
                    # Direct import like "console"
                    imported_names.add(item.strip())

    # Second pass: find TRUE module-level assignments
    # Only check lines at column 0 (no indentation) — this eliminates local
    # variables inside functions/classes, which are always indented.
    # The old _iter_module_level_lines approach had a bug: multi-line function
    # signatures with closing ) at column 0 tricked it into thinking the
    # function body had ended.
    constants = []
    bad_constants = []
    in_multiline_string = False

    for line in content.split("\n"):
        stripped = line.strip()

        # Track multiline strings
        for delimiter in ('"""', "'''"):
            if delimiter in stripped:
                count = stripped.count(delimiter)
                if count % 2 == 1:
                    in_multiline_string = not in_multiline_string

        if in_multiline_string:
            continue

        # Only consider lines with zero indentation (true module-level)
        if line and (line[0] == " " or line[0] == "\t"):
            continue

        # Find assignments
        if "=" not in stripped or stripped.startswith("#"):
            continue

        # Extract variable name and assignment value
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$", stripped)
        if not match:
            continue

        const_name = match.group(1)
        assigned_value = match.group(2)

        # Skip __dunder__ variables (__all__, __version__, etc.)
        if const_name.startswith("__") and const_name.endswith("__"):
            continue

        # Skip if this is an imported name (like logger, console)
        if const_name in imported_names:
            continue

        # Skip if assignment is a function call or class instantiation (has parentheses)
        # Examples: logger = logging.getLogger(...), console = Console()
        if "(" in assigned_value:
            continue

        # Skip if assigning an imported value to a variable
        # Example: from prax import system_logger; logger = system_logger
        if assigned_value.strip() in imported_names:
            continue

        constants.append(const_name)

        # Constants should be UPPER_CASE
        if not const_name.isupper():
            bad_constants.append(const_name)

    if not constants:
        return None  # No constants found

    if bad_constants:
        return {
            "name": "Constant naming",
            "passed": False,
            "message": f"Non-UPPER_CASE constants: {', '.join(bad_constants[:3])}",
        }

    return {
        "name": "Constant naming",
        "passed": True,
        "message": f"{len(constants)} constants checked - all UPPER_CASE",
    }


def check_class_naming(content: str) -> Optional[Dict]:
    """
    Check class naming conventions

    Rules:
    - PascalCase class names
    """
    # Find all class definitions
    class_pattern = r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(:]"
    classes = re.findall(class_pattern, content, re.MULTILINE)

    if not classes:
        return None  # No classes to check

    # Check each class name
    bad_classes = []
    for class_name in classes:
        # Check for PascalCase
        if not re.match(r"^[A-Z][a-zA-Z0-9]*$", class_name):
            bad_classes.append(class_name)

    if bad_classes:
        return {
            "name": "Class naming",
            "passed": False,
            "message": f"Non-PascalCase classes: {', '.join(bad_classes[:3])}",
        }

    return {"name": "Class naming", "passed": True, "message": f"{len(classes)} classes checked - all PascalCase"}
