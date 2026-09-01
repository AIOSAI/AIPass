# =================== AIPass ====================
# Name: documentation_check.py
# Description: Documentation Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Documentation Standards Checker Handler

Validates documentation compliance: module docstrings and function docstrings.
META block validation is handled separately by meta_check.py.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"
# Applies to production source only: a test documents itself by its name and its
# assertions. 163 of 456 fleet test files failed docstring coverage (36%, 15 branches).
APPLIES_TO = "production"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module follows documentation standards.

    Checks module-level docstrings and public function docstrings.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional bypass rules

    Returns:
        dict with passed, checks, score, standard keys
    """
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

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Documentation check", "passed": True, "message": "__init__.py file (skipped)"}],
            "score": 100,
            "standard": "DOCUMENTATION",
        }

    # Check 1: Module-level docstring
    docstring_check = check_module_docstring(lines)
    checks.append(docstring_check)

    # Check 2: Function docstrings (for public functions)
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


def check_module_docstring(lines: List[str]) -> Dict:
    """
    Check for module-level docstring.

    Looks for a triple-quoted string near the top of the file,
    allowing for META block, comments, or blank lines before it.
    """
    for line in lines[:30]:
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            return {"name": "Module docstring", "passed": True, "message": "Module-level docstring present"}

    return {
        "name": "Module docstring",
        "passed": False,
        "message": "Missing module-level docstring (expected within first 30 lines)",
    }


def _public_functions_by_ast(content: str):
    """Public functions and whether each has a docstring, read as Python reads.

    THE LINE SCAN BELOW READ STRINGS AS SOURCE. ``stripped.startswith("def ")``
    over the raw file matches a ``def`` inside a docstring's code example or
    inside a module built as a string literal and fed to a subprocess — the
    shape every branch wrote this week for the dead-cwd worlds. @api, @canary,
    @skills and two seedgo files were all flagged for functions that do not
    exist. Caught by dogfooding: this checker flagged a three-line example in a
    new nominator's own docstring.

    It had the mirror defect too. ``async def`` never matched at all, so an
    undocumented async function was invisible — ``find_import_section_end`` in
    the imports pack has handled ``async def`` since it was written.

    Scope is UNCHANGED: nested functions still count, exactly as the line scan
    counted them. Narrowing to module and class level would clear 40 more files
    and that is a different decision, not this fix.

    Args:
        content: Module source.

    Returns:
        A list of ``(name, line, has_docstring)`` triples, or None when the
        source will not parse.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
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
    """Turn the parsed function list into this check's verdict.

    Args:
        found: ``(name, line, has_docstring)`` triples.

    Returns:
        The check result dict.
    """
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


def check_function_docstrings(content: str, lines: List[str]) -> Dict:  # noqa: ARG001
    """
    Check that public functions have docstrings.

    Public functions (not starting with _) should have docstrings.
    """
    parsed = _public_functions_by_ast(content)
    if parsed is not None:
        return _judge(parsed)

    # AST unavailable (the file will not parse). Fall back to the line scan
    # rather than reporting clean: a file we could not read has not been proven
    # to document anything, and an exemption bought with a SyntaxError is an
    # exemption granted on ignorance.
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
        # Scan past the full function signature (may span many lines for
        # functions with lots of parameters) up to 30 lines ahead.
        for check_line in range(line_num, min(line_num + 30, len(lines) + 1)):
            if check_line - 1 < len(lines):
                check_stripped = lines[check_line - 1].strip()
                if check_stripped.startswith('"""') or check_stripped.startswith("'''"):
                    has_docstring = True
                    break
                # Stop scanning if we hit another def or class -- no docstring found
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
