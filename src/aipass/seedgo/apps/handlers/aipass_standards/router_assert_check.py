# =================== AIPass ====================
# Name: router_assert_check.py
# Description: Router Assert Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""
Router Assert Standards Checker Handler

Convicts a test whose ONLY oracle is a command router returning ``is True``.

Every router in this fleet returns ``True`` on the path it took and on the
path it refused to take, so ``assert handle_command(...) is True`` passes
whether the command ran, printed an error, or did nothing at all. The test
named "unknown subcommand -- error displayed to user" asserts that a function
returned the same constant it returns for success.

``is False`` is NEVER convicted. A decline is a whole contract: the router
recognising that a command is not its own is the entire behaviour under test,
and there is no effect to assert beyond the return value.

This is a PROHIBITION, not a requirement. Nothing here says a test must
contain a particular string -- the v4 ``test_quality_check.py`` scored the
literal ``"is True"`` as a positive and agents duly supplied 224 of them,
which is how this defect was manufactured in the first place.

Two lanes, by design:

  * ``check_module`` -- APPLIES_TO tests, so only the per-file checklist lane
    runs it, and only on a test file. That lane fires from the PostToolUse
    hook, so the rule meets an agent on the write that creates the shape.
  * ``check_branch_info`` -- the standing backlog, reported UNSCORED through
    the audit's info channel. Test files are not in the audit's corpus
    (``_collect_py_files`` walks ``apps/`` only), so no branch's number moves
    on the day this lands. The backlog is a list to work through, not a debt
    charged to whoever happens to run the audit next.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "ROUTER_ASSERT"
STANDARD_KEY = "router_assert"

# The callees whose return value is a routing verdict rather than a result.
# Deliberately a short closed list: every one of these is the "did any module
# claim this command" protocol in apps/<branch>.py and apps/modules/*.py, and
# all of them answer True for "I handled it", including "I handled it by
# printing an error". A wider list (any function returning a bool) would
# convict real predicates, whose True IS the behaviour.
ROUTER_NAMES: frozenset[str] = frozenset({"handle_command", "route_command", "main", "handle"})

# A call to any of these means the unit DOES assert an effect, without using
# an `assert` statement to do it. mock's assert_* family raises on its own,
# and pytest.raises/warns are oracles in a context manager.
#
# Leading underscores are stripped before the prefix test, which is not
# cosmetic: aipass's test_help_flag.py:174 asserts the whole effect through
# a module-local helper named ``_assert_nothing_happened``, and matching only
# "assert_" convicted it. That was the one false positive in the first
# precision sample, and it is the shape a shared oracle helper takes.
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

    ``result = handle_command(...)`` followed by ``assert result is True`` is
    the same test as the one-liner, and it is the more common shape: 130 of
    this branch's own hits assign first.
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

    ``is False`` fails this deliberately, and so does ``==``: a test written
    with ``== True`` is a different (weaker) claim and not the shape the owner
    ruled on. Widening this is a separate rule with its own evidence.
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

    A test that only calls ``console.print.assert_called_once_with(...)`` has
    no ``assert`` statement at all and must never be convicted for it -- it is
    asserting precisely the effect this rule asks for.
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


def find_violations(source: str) -> List[Tuple[int, str]]:
    """Every convicted unit in this source, as (line of the unit, its name).

    A unit is convicted when it HAS assertions and every one of them is a
    router's ``is True`` -- one honest assertion anywhere else acquits the
    whole unit, because the test then proves something the router's return
    value does not.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

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


def _scan_path(path: Path) -> List[Tuple[int, str]]:
    """Violations in one file, or none if it cannot be read."""
    try:
        return find_violations(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        logger.info("[router_assert] Cannot read %s: %s", path, exc)
        return []


def _result(passed: bool, message: str, score: int) -> Dict:
    """The single-check result shape every checker in this pack returns."""
    return {
        "passed": passed,
        "checks": [{"name": "Router-only assertions", "passed": passed, "message": message}],
        "score": score,
        "standard": STANDARD,
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for units whose only oracle is a router's True.

    Args:
        module_path: Path to the test file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, "Standard bypassed via .seedgo/bypass.json", 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, f"File not found: {module_path}", 0)

    hits = [(ln, name) for ln, name in _scan_path(path) if not is_bypassed(module_path, STANDARD_KEY, ln, bypass_rules)]

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


def check_branch_info(branch_path: str) -> List[str]:
    """The standing backlog, reported with no score attached.

    The audit's corpus is ``apps/``, so nothing under ``tests/`` can move a
    branch's number through the scoring lane. This line is the whole of what
    the audit says about the rule: how many units are already in the shape,
    so the work is visible without being charged.
    """
    tests_dir = Path(branch_path) / "tests"
    if not tests_dir.is_dir():
        return []
    units, files = 0, 0
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        hits = _scan_path(test_file)
        if hits:
            units += len(hits)
            files += 1
    if not units:
        return []
    return [
        f"router_assert backlog: {units} test(s) in {files} file(s) assert only a router's True "
        f"(unscored - convicted on the next write of the file)"
    ]
