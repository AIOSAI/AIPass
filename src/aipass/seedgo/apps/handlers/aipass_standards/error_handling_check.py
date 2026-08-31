# =================== AIPass ====================
# Name: error_handling_check.py
# Description: Error Handling Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Error Handling Standards Checker Handler

Validates error handling compliance — detects silent failures
(bare except: pass) in production code.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards import exception_handling
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows error handling standards"""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "error_handling", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "ERROR_HANDLING",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "ERROR_HANDLING",
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
            "standard": "ERROR_HANDLING",
        }

    # Only check: Error handling (for all files, not just non-test files)
    error_handling_check = check_error_handling(content, lines, module_path)
    if error_handling_check:
        checks.append(error_handling_check)

    # If no checks were added (no try/except blocks), pass
    if not checks:
        return {
            "passed": True,
            "checks": [
                {"name": "Error handling", "passed": True, "message": "No try/except blocks detected (not applicable)"}
            ],
            "score": 100,
            "standard": "ERROR_HANDLING",
        }

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "error_handling"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "ERROR_HANDLING"}


def _silent_except_lines(content: str, module_path: str = "") -> Optional[List[int]]:
    """Return the 1-indexed lines of every `except ...:` whose body is only `pass`.

    Returns None when the file cannot be parsed, so the caller can skip rather
    than guess.

    This replaced a line scanner that tracked an `in_except` flag and only cleared
    it on a line starting at column 0. Nothing inside a class body starts at column
    0, so once the flag was set it stayed set across method boundaries and the next
    bare `pass` anywhere downstream -- in a different method, inside no except at
    all -- was reported as a silent failure, against the earlier except's line.
    The AST knows where a handler actually ends, and handler.lineno is already
    1-indexed (the scanner reported a 0-based enumerate index, so every finding
    came back one line low).
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        logger.info("Skipping error-handling scan: SyntaxError during parse: %s", e)
        return None

    # Walked as Try nodes so the diagnostic-guard clause can read the BLOCK a
    # handler protects; an ExceptHandler has no link back to its own try.
    silent = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if not handler.body or not all(isinstance(s, ast.Pass) for s in handler.body):
                continue
            # A `pass` guarding a block that does nothing but REPORT is catching
            # the failure of the report, not the original error — the same
            # clause silent_catch uses, shared so the two cannot drift
            # (@canary and @daemon, 2026-08-31).
            if exception_handling.guards_a_diagnostic(node, module_path, handler.lineno):
                continue
            silent.append(handler.lineno)
    return sorted(silent)


def check_error_handling(content: str, lines: List[str], module_path: str = "") -> Optional[Dict]:
    """Check for proper error handling patterns"""
    try_count = content.count("try:")

    if try_count == 0:
        return None

    silent_lines = _silent_except_lines(content, module_path)
    if silent_lines is None:
        return None

    if silent_lines:
        where = ", ".join(f"line {n}" for n in silent_lines)
        name = Path(module_path).name if module_path else "file"
        return {
            "name": "Error handling",
            "passed": False,
            "message": f"Silent failure detected (except: pass) in {name} at {where} - errors should log/return",
        }

    return {
        "name": "Error handling",
        "passed": True,
        "message": f"Error handling present ({try_count} try/except blocks with proper handling)",
    }
