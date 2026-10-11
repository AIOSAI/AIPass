# =================== AIPass ====================
# Name: os_walk_onerror_check.py
# Description: Os Walk Onerror Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Os Walk Onerror Standards Checker Handler

``os.walk`` swallows every ``OSError`` its ``scandir`` raises unless it is
handed ``onerror=``. An unreadable subtree is not walked, nothing is raised,
nothing is returned, and the run reports success over a tree it never saw.

  ``backup/apps/handlers/scan/walk.py:34``: the backup scan walks the project
  with ``os.walk(root_path, followlinks=False)``; a directory it cannot list
  drops out of the backup in silence.

THE SHAPE. A call that resolves to ``os.walk`` with no ``onerror=`` keyword,
or ``onerror=None``, which is the default again. Names resolve through the
file's own imports: ``import os as o`` and ``from os import walk`` are
followed. The hit is reported on the call's line.

NOT CONVICTED, each for its reason:
  * ``onerror=`` given with any value but the literal None. Whether the
    callable raises, records, or only logs cannot be read from the call; the
    page says which of those is a cure.
  * A third positional argument: that slot IS ``onerror``.
  * A ``**kwargs`` splat: it can carry ``onerror``.
  * ``Path.rglob`` / ``Path.glob``: no error hook exists to pass, so there is
    nothing to name. Counted in the check-first, never judged.
  * The words ``os.walk`` in a string or comment: not a call.
  * Test files: a fixture walking its own ``tmp_path`` is not the hazard
    (``APPLIES_TO = "production"``).

CHECK FIRST (2026-09-25, before the rule landed). ``src/aipass/*/apps``,
1,214 product files: 13 ``os.walk`` calls, 8 without ``onerror`` in 8
files across 6 branches -- seedgo 2 (readme_check, audit_tests/m10), drone 2
(deletion_log, broker/daemon), ai_mail 1 (central_writer), aipass 1
(init/git_auth), backup 1 (scan/walk, the specimen), devpulse 1
(watchdog/agent). 5 pass ``onerror``: drone rm_handler x2, flow
heal_registry and monitor_ops, devpulse release_notify/managers. Devpulse's
grep said 9 without; the ninth is prose in a docstring. ``rglob`` counted, not
judged: 62 calls, 43 of them seedgo's. The model file scores 100 (a test file,
not in this rule's corpus).
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
    """Check a product file for an os.walk call that names no onerror.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
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

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(f"{path.name}:{line} os.walk without onerror - {WHY}; {CURE}" for line in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
