# =================== AIPass ====================
# Name: unconsumed_side_effect_check.py
# Description: Unconsumed Side Effect Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Unconsumed Side Effect Standards Checker Handler

Crack class F from the 2026-09-22 eyes-on review of @backup's tests. A test
queues several answers for a mock and never checks that they were all taken::

    drive_api.side_effect = [
        {"files": []},
        {"id": "new_folder_456"},
        {"id": "new_folder_456", "name": "AIPass Backups"},
    ]

A ``side_effect`` list of three says the product will call this mock three
times. Nothing in the test says so. If the product calls it twice, the third
answer is never consumed, the test still passes, and whatever branch that third
answer was written to feed is unpinned -- deletable, with the suite green.

THE CURE IS ONE LINE: ``assert mock.call_count == 3``, or
``assert_has_calls([...])`` when the arguments matter. Either one turns the
list's length from a hope into a claim.

WHAT ACQUITS, WHAT IS SCORED, WHAT IS COUNTED:

  * ACQUITTED: the test asserts the mock's calls -- ``call_count``,
    ``assert_called``/``assert_called_once``/``assert_called_with`` and their
    kin, ``assert_has_calls``, ``mock_calls``, ``call_args``,
    ``assert_not_called``, and the ``await_`` forms. 9 of the fleet's 26.
  * SCORED: the mock is never mentioned in any assertion in the test. 17.
  * COUNTED, not charged: the mock is asserted some OTHER way -- its return
    value reaches an assert, say -- so the test is watching it, just not
    counting it. Zero in this fleet today; the bucket is here because the
    shape is legitimate and the count should be ready when it appears.

A list of ONE is never judged: a single queued answer is a return value spelled
differently, and there is no unconsumed tail to lose.

CHECK FIRST, measured 2026-09-23 over the fleet's 572 test files:

  * 5 files, 17 scored, 0 counted, 9 acquitted.
  * Lengths among the judged: 2 eleven times, 3 five times, 4 once.
  * @backup carries 4, @backup's share suite 7, @hooks 4, @api and @drone 1
    each.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: the list's length is an assertion the
test declines to make. The fix is additive -- one more assert -- and no
threshold exists to tune.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "UNCONSUMED_SIDE_EFFECT"
STANDARD_KEY = "unconsumed_side_effect"

#: The attribute that queues several answers for one mock.
SIDE_EFFECT = "side_effect"

#: Every way a test can claim how many times, or with what, the mock was called.
CONSUMERS: frozenset[str] = frozenset(
    {
        "call_count",
        "call_args",
        "call_args_list",
        "mock_calls",
        "assert_called",
        "assert_called_once",
        "assert_called_with",
        "assert_called_once_with",
        "assert_any_call",
        "assert_has_calls",
        "assert_not_called",
        "await_count",
        "await_args_list",
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_with",
    }
)

CURE = "assert mock.call_count, or assert_has_calls when the arguments matter"


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[unconsumed_side_effect] Unparseable, nothing scanned: %s", exc)
        return None


def _dotted(node: ast.AST) -> str:
    """A mock written out: ``client._api_call`` from its Attribute chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _tests(tree: ast.Module) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every test function in the file."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]


def queued(function: ast.AST) -> Dict[str, Tuple[int, int]]:
    """Every mock handed a list of more than one answer: mock -> (line, count)."""
    found: Dict[str, Tuple[int, int]] = {}
    for node in ast.walk(function):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Attribute) and target.attr == SIDE_EFFECT):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)) and len(node.value.elts) > 1:
            found[_dotted(target.value)] = (node.lineno, len(node.value.elts))
    return found


def counted_calls(function: ast.AST) -> Set[str]:
    """Every mock whose calls this test actually claims something about."""
    return {
        _dotted(node.value) for node in ast.walk(function) if isinstance(node, ast.Attribute) and node.attr in CONSUMERS
    }


def watched(function: ast.AST) -> Set[str]:
    """Every name or path that reaches an assertion in this test."""
    found: Set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Assert):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                found.add(inner.id)
            elif isinstance(inner, ast.Attribute):
                found.add(_dotted(inner))
                found.add(_dotted(inner.value))
    return found


def scan(source: str) -> Tuple[List[Tuple[int, str, int]], int]:
    """((line, mock, how many answers) scored, how many were counted not charged)."""
    tree = _parse(source)
    if tree is None:
        return [], 0

    scored: List[Tuple[int, str, int]] = []
    reported = 0
    for function in _tests(tree):
        answers = queued(function)
        if not answers:
            continue
        claimed = counted_calls(function)
        seen = watched(function)
        for mock, (line, count) in answers.items():
            if mock in claimed:
                continue
            if mock in seen:
                reported += 1
            else:
                scored.append((line, mock, count))
    return sorted(scored), reported


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[unconsumed_side_effect] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Unconsumed side effect", "passed": passed, "message": message}]


def _clean_message(reported: int) -> str:
    """The passing message, carrying the watched-but-uncounted number."""
    if not reported:
        return "Every queued side effect here is claimed by an assertion"
    shape = "queue is" if reported == 1 else "queues are"
    return (
        f"Every queued side effect here is claimed by an assertion "
        f"({reported} {shape} watched some other way but never counted)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for queued mock answers nothing counts.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

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

    findings, reported = scan(source)
    if not findings:
        return _result(True, _one_check(True, _clean_message(reported)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per mock would show the first
    # and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {mock} is queued {count} answers and nothing counts them - {CURE}"
        for line, mock, count in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
