# =================== AIPass ====================
# Name: deep_nesting_check.py
# Description: Deep Nesting Standards Checker Handler
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""
Deep Nesting Standards Checker Handler

Reference: deep_nesting.md
"""

import ast
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: four levels is as unreadable in a test as in a module.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_NESTING_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.ExceptHandler)

DEPTH_LIMIT = 4


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    """Recursively walk a function body and return the maximum nesting depth."""
    max_depth = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTING_NODES):
            child_depth = _max_nesting_depth(child, current + 1)
        else:
            child_depth = _max_nesting_depth(child, current)
        if child_depth > max_depth:
            max_depth = child_depth
    return max_depth


def _scan_file(file_path: Path) -> list[dict]:
    """Parse a single .py file and return a list of violation dicts.
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


def check_module(module_path: str, bypass_rules: list | None = None) -> dict:
    """Check if a module complies with deep nesting standards."""
    checks: list[dict] = []
    path = Path(module_path)

    if is_bypassed(module_path, "deep_nesting", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "DEEP_NESTING",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Deep nesting", "passed": True, "message": "__init__.py skipped", "declined": True}],
            "score": 100,
            "standard": "DEEP_NESTING",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "DEEP_NESTING",
        }

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
