# =================== AIPass ====================
# Name: router_assert_check.py
# Description: Router Assert Standards Checker Handler
# Version: 1.1.2
# Created: 2026-09-20
# Modified: 2026-10-24
# =============================================

"""
Router Assert Standards Checker Handler

Reference: router_assert.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "ROUTER_ASSERT"
STANDARD_KEY = "router_assert"
NOT_JUDGED = "Not judged: the file cannot be read or does not parse (ruff convicts that)"

# A short closed list: each is the "did any module claim this command" protocol and answers True even when it
# handled the command by printing an error. A wider list would convict real predicates, whose True IS the behaviour.
ROUTER_NAMES: frozenset[str] = frozenset({"handle_command", "route_command", "main", "handle"})

# A call to any of these asserts an effect without an `assert` statement (mock's assert_*, pytest.raises/warns).
# Leading underscores are stripped first: a module-local ``_assert_nothing_happened`` helper is an oracle too.
_EFFECT_CALL_PREFIX = "assert"
_EFFECT_CALL_NAMES: frozenset[str] = frozenset({"raises", "warns", "deprecated_call"})

MESSAGE = (
    "the router returned True and the test asserts nothing it did - "
    "assert the effect (what was printed, what was called, what was not)"
)


def _callee_name(node: ast.AST) -> str | None:
    """The bare name of a call's callee, through one level of attribute access."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_router_call(node: ast.AST) -> bool:
    """Whether this node is a call to one of the routing protocol names."""
    return _callee_name(node) in ROUTER_NAMES


def _router_bound_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Local names bound to a router call anywhere in the unit.

    ``result = handle_command(...)`` then ``assert result is True`` is the same test as the one-liner.
    """
    bound: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and _is_router_call(node.value):
            bound.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _is_router_call(node.value):
            if isinstance(node.target, ast.Name):
                bound.add(node.target.id)
        elif isinstance(node, ast.NamedExpr) and _is_router_call(node.value):
            bound.add(node.target.id)
    return bound


def _is_sole_router_true(test: ast.expr, bound: set[str]) -> bool:
    """Whether an assert's expression is exactly ``<router result> is True``.

    ``is False`` fails this deliberately, and so does ``==``: ``== True`` is a weaker claim, another rule's job.
    """
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Is):
        return False
    right = test.comparators[0]
    if not (isinstance(right, ast.Constant) and right.value is True):
        return False
    left = test.left
    if isinstance(left, ast.Name):
        return left.id in bound
    return _is_router_call(left)


def _asserts_an_effect(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the unit carries an oracle that is not an ``assert`` statement.

    A test that only calls ``console.print.assert_called_once_with(...)`` asserts the effect; never convict it.
    """
    for node in ast.walk(func):
        name = _callee_name(node)
        if name is None:
            continue
        if name.lstrip("_").startswith(_EFFECT_CALL_PREFIX) or name in _EFFECT_CALL_NAMES:
            return True
    return False


def _test_functions(tree: ast.AST) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every ``test_*`` function in the module, including methods on Test classes."""
    found: List[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found.append(node)
    return found


def find_violations(source: str) -> Optional[List[Tuple[int, str]]]:
    """Every convicted unit in this source, as (line of the unit, its name).

    Convicted when it HAS assertions and every one is a router's ``is True``; one other assertion acquits it.

    None when the source does not parse: nothing was judged, which is not the [] of a clean file.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        logger.info("[router_assert] Unparseable source: %s", exc)
        return None

    violations: List[Tuple[int, str]] = []
    for func in _test_functions(tree):
        asserts = [n for n in ast.walk(func) if isinstance(n, ast.Assert)]
        if not asserts:
            continue
        if _asserts_an_effect(func):
            continue
        bound = _router_bound_names(func)
        if all(_is_sole_router_true(a.test, bound) for a in asserts):
            violations.append((func.lineno, func.name))
    return violations


def _scan_path(path: Path) -> Optional[List[Tuple[int, str]]]:
    """Violations in one file, or None if it cannot be read or parsed."""
    try:
        return find_violations(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        logger.info("[router_assert] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, message: str, score: int) -> Dict:
    """The single-check result shape every checker in this pack returns."""
    return {
        "passed": passed,
        "checks": [{"name": "Router-only assertions", "passed": passed, "message": message}],
        "score": score,
        "standard": STANDARD,
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for units whose only oracle is a router's True."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, "Standard bypassed via .seedgo/bypass.json", 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, f"File not found: {module_path}", 0)

    scanned = _scan_path(path)
    if scanned is None:
        return _result(True, NOT_JUDGED, 100)
    hits = [(ln, name) for ln, name in scanned if not is_bypassed(module_path, STANDARD_KEY, ln, bypass_rules)]

    if not hits:
        return _result(True, "No test asserts only a router's True", 100)

    sample = ", ".join(f"{name}:{ln}" for ln, name in hits[:3])
    suffix = f" (and {len(hits) - 3} more)" if len(hits) > 3 else ""
    message = f"{len(hits)} test(s) assert only a router's True - {sample}{suffix}: {MESSAGE}"

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY},
    )
    return _result(False, message, 0)
