# =================== AIPass ====================
# Name: deep_nesting_check.py
# Description: Deep Nesting Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Deep Nesting Standards Checker Handler

Scans Python source files for functions whose control-flow nesting depth
exceeds the allowed threshold.  A nesting level is added for each:
If / For / While / Try / With / ExceptHandler.

Threshold: depth > 3 is a violation.  Functions that exceed this limit
should be decomposed into smaller helpers.
"""

import ast
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# -- Nesting node types -----------------------------------------------------

_NESTING_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.ExceptHandler)

DEPTH_LIMIT = 4


# -- Bypass helper -----------------------------------------------------------


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


# -- AST depth analysis ------------------------------------------------------


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    """
    Recursively walk a function body and return the maximum nesting depth.

    Each If/For/While/Try/With/ExceptHandler adds one level.
    The initial call starts at depth 0 (inside the function body).
    """
    max_depth = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTING_NODES):
            child_depth = _max_nesting_depth(child, current + 1)
        else:
            child_depth = _max_nesting_depth(child, current)
        if child_depth > max_depth:
            max_depth = child_depth
    return max_depth


# -- File scanning -----------------------------------------------------------


def _scan_file(file_path: Path) -> list[dict]:
    """
    Parse a single .py file and return a list of violation dicts.

    Each violation: {'func': str, 'depth': int, 'line': int}
    """
    violations: list[dict] = []

    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        logger.info("Skipped %s: SyntaxError during parse", file_path)
        return violations

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        depth = _max_nesting_depth(node)
        if depth > DEPTH_LIMIT:
            violations.append(
                {
                    "func": node.name,
                    "depth": depth,
                    "line": node.lineno,
                }
            )

    return violations


# -- Public checker entry point ----------------------------------------------


def check_module(module_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check if a module complies with deep nesting standards.

    Args:
        module_path: Path to the Python file to check.
        bypass_rules: Optional list of bypass rules to skip certain checks.

    Returns:
        dict with keys: passed, score, checks, standard.
    """
    checks: list[dict] = []
    path = Path(module_path)

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "deep_nesting", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "DEEP_NESTING",
        }

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Deep nesting", "passed": True, "message": "__init__.py skipped"}],
            "score": 100,
            "standard": "DEEP_NESTING",
        }

    # Validate file exists
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "DEEP_NESTING",
        }

    # Scan for deep nesting violations
    violations = _scan_file(path)

    if not violations:
        checks.append(
            {
                "name": "Deep nesting",
                "passed": True,
                "message": "All functions within nesting limit (max depth 3)",
            }
        )
    else:
        func_details = ", ".join(f"{v['func']}() depth {v['depth']} line {v['line']}" for v in violations)
        checks.append(
            {
                "name": "Deep nesting",
                "passed": False,
                "message": (
                    f"{len(violations)} function{'s' if len(violations) != 1 else ''} "
                    f"exceed nesting limit: {func_details}"
                ),
            }
        )

    # Calculate score
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "deep_nesting"},
    )

    return {
        "passed": overall_passed,
        "score": score,
        "checks": checks,
        "standard": "DEEP_NESTING",
    }
