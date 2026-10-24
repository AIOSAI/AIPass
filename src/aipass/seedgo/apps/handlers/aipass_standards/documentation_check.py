# =================== AIPass ====================
# Name: documentation_check.py
# Description: Documentation Standards Checker Handler
# Version: 1.0.2
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""Documentation Standards Checker Handler

Validates documentation compliance: module docstrings and function docstrings.
META block validation is handled separately by meta_check.py. Reference: documentation.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

AUDIT_SCOPE = "all_files"
# Applies to production source only: a test documents itself by its name and assertions.
APPLIES_TO = "production"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows documentation standards."""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "documentation", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "DOCUMENTATION",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "DOCUMENTATION",
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
            "standard": "DOCUMENTATION",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Documentation check",
                    "passed": True,
                    "message": "__init__.py file (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "DOCUMENTATION",
        }

    docstring_check = check_module_docstring(lines)
    checks.append(docstring_check)

    function_docs_check = check_function_docstrings(content, lines)
    checks.append(function_docs_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "documentation"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "DOCUMENTATION"}


#: The two triple-quote spellings, named because the fallback below is a
#: LINE SCAN and a literal quote in this file's own source is exactly the
#: construct that makes such a scan hard to read.
TRIPLE_DOUBLE: str = chr(34) * 3
TRIPLE_SINGLE: str = chr(39) * 3


def _module_docstring_by_line_scan(lines: List[str]) -> Dict:
    """The pre-AST scan, kept for files that will not parse.

    Says so in the message: a fallback must not read like a verdict from the real arm.
    """
    for line in lines[:30]:
        stripped = line.strip()
        if stripped.startswith(TRIPLE_DOUBLE) or stripped.startswith(TRIPLE_SINGLE):
            return {
                "name": "Module docstring",
                "passed": True,
                "message": "Module-level docstring present (file does not parse - line scan)",
            }
    return {
        "name": "Module docstring",
        "passed": False,
        "message": "Missing module-level docstring (file does not parse - line scan)",
    }


def check_module_docstring(lines: List[str]) -> Dict:
    r"""Check for module-level docstring, read as Python reads it."""
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError) as exc:
        # Logged rather than swallowed: silent_catch would accept a bare `return None` here
        # and flag a return that names its fallback.
        logger.info("Module docstring check fell back to a line scan: %s", exc)
        return _module_docstring_by_line_scan(lines)

    if ast.get_docstring(tree) is not None:
        return {"name": "Module docstring", "passed": True, "message": "Module-level docstring present"}

    return {
        "name": "Module docstring",
        "passed": False,
        "message": "Missing module-level docstring (no string literal opens the module body)",
    }


def _public_functions_by_ast(content: str):
    """Public functions and whether each has a docstring, read as Python reads."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        found.append((node.name, node.lineno, bool(ast.get_docstring(node))))
    return found


def _judge(found: list) -> Dict:
    """Turn the parsed function list into this check's verdict."""
    if not found:
        return {"name": "Function docstrings", "passed": True, "message": "No public functions to check"}

    undocumented = [f"{name} (line {line})" for name, line, documented in found if not documented]
    if undocumented:
        return {
            "name": "Function docstrings",
            "passed": False,
            "message": f"{len(undocumented)} public functions missing docstrings: {undocumented[0]}",
        }
    return {
        "name": "Function docstrings",
        "passed": True,
        "message": f"All {len(found)} public functions have docstrings",
    }


def check_function_docstrings(content: str, lines: List[str]) -> Dict:
    """Check that public functions have docstrings."""
    parsed = _public_functions_by_ast(content)
    if parsed is not None:
        return _judge(parsed)

    # AST unavailable: fall back to the line scan rather than reporting clean, since a
    # file we could not read has not been proven to document anything.
    public_functions = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("def ") and not stripped.startswith("def _"):
            match = re.match(r"def\s+(\w+)\s*\(", stripped)
            if match:
                func_name = match.group(1)
                public_functions.append((func_name, i))

    if not public_functions:
        return {"name": "Function docstrings", "passed": True, "message": "No public functions to check"}

    undocumented = []
    for func_name, line_num in public_functions:
        has_docstring = False
        for check_line in range(line_num, min(line_num + 30, len(lines) + 1)):
            if check_line - 1 < len(lines):
                check_stripped = lines[check_line - 1].strip()
                if check_stripped.startswith('"""') or check_stripped.startswith("'''"):
                    has_docstring = True
                    break
                if check_line > line_num and (check_stripped.startswith("def ") or check_stripped.startswith("class ")):
                    break
        if not has_docstring:
            undocumented.append(f"{func_name} (line {line_num})")

    if undocumented:
        return {
            "name": "Function docstrings",
            "passed": False,
            "message": f"{len(undocumented)} public functions missing docstrings: {undocumented[0]}",
        }

    return {
        "name": "Function docstrings",
        "passed": True,
        "message": f"All {len(public_functions)} public functions have docstrings",
    }
