# =================== AIPass ====================
# Name: os_walk_onerror_check.py
# Description: Os Walk Onerror Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-10-17
# =============================================

"""
Os Walk Onerror Standards Checker Handler

Reference: os_walk_onerror.md
"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "OS_WALK_ONERROR"
STANDARD_KEY = "os_walk_onerror"

#: ``os.walk(top, topdown, onerror, followlinks)`` -- onerror is the third slot.
ONERROR_POSITION = 2

CURE = "pass onerror= a callable that raises, or that records the error into what the function returns"
WHY = "an unreadable directory is skipped in silence"


def _bindings(node: ast.AST) -> Dict[str, str]:
    """Local name -> dotted name, for one import statement."""
    bound: Dict[str, str] = {}
    if isinstance(node, ast.Import):
        for alias in node.names:
            head = alias.name.split(".")[0]
            bound[alias.asname or head] = alias.name if alias.asname else head
    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        for alias in node.names:
            bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def aliases(tree: ast.AST) -> Dict[str, str]:
    """Local name -> dotted name, from every import in the file, local ones included."""
    bound: Dict[str, str] = {}
    for node in ast.walk(tree):
        bound.update(_bindings(node))
    return bound


def dotted(expr: ast.AST, bound: Dict[str, str]) -> str | None:
    """The canonical dotted name of a Name/Attribute chain, through the file's imports."""
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        head = dotted(expr.value, bound)
        return f"{head}.{expr.attr}" if head else None
    return None


def _names_onerror(call: ast.Call) -> bool:
    """Whether the call hands os.walk an error hook, or might (a splat)."""
    if len(call.args) > ONERROR_POSITION:
        return True
    for keyword in call.keywords:
        if keyword.arg is None:
            return True
        if keyword.arg == "onerror":
            return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
    return False


def scan(tree: ast.AST) -> List[int]:
    """The line of every os.walk call that names no onerror."""
    bound = aliases(tree)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and dotted(node.func, bound) == "os.walk" and not _names_onerror(node)
    )


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[os_walk_onerror] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "os.walk onerror", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for an os.walk call that names no onerror."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[os_walk_onerror] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)

    hits = [line for line in scan(tree) if not is_bypassed(module_path, STANDARD_KEY, line, bypass_rules)]
    if not hits:
        return _result(True, _one_check(True, "Every os.walk call names an onerror"), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(f"{path.name}:{line} os.walk without onerror - {WHY}; {CURE}" for line in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
