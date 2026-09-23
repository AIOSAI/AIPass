# =================== AIPass ====================
# Name: self_set_assert_check.py
# Description: Self Set Assert Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Self Set Assert Standards Checker Handler

Crack class E from the 2026-09-22 eyes-on review of @backup's tests. A test
writes a value and then asserts that the value is there::

    r = BackupResult(mode="snapshot")
    r.files_deleted = 5
    assert r.files_deleted == 5

Nothing about the product decided that. Python's attribute assignment did, and
it would pass against an empty class. The test reads as coverage of
``BackupResult`` and covers only ``setattr``.

The shapes, all three the same defect:

  * ``target.attr = X`` then ``assert target.attr == X``
  * ``d[key] = X`` then ``assert d[key] == X``
  * a CONSTRUCTOR KWARG, ``obj = C(attr=X)`` then ``assert obj.attr == X``,
    which is 14 of the fleet's 15 and the shape nobody sees while writing it.

THE JUDGEMENT THIS RULE MAKES: score only when NOTHING RAN in between. If a
call sits between the assignment and the assertion, the assert is a durability
oracle -- "the product did not clobber this" -- and that is a real claim about
the product. ``test_drive_pipeline.py`` sets ``client.file_tracker``, calls
``get_or_create_backup_folder()``, and then asserts the tracker is unchanged:
that is the test's whole point, and convicting it would be wrong. Those ride in
the passing message as a count.

The other line this rule holds: the comparison must be ``==`` against the SAME
literal. ``client._drive_service = service`` followed by ``assert
client.drive_service is service`` sets the backing field and asserts the
PROPERTY -- different name, and ``is`` not ``==``. The product's getter is
under test there, so the rule declines it.

``weak_oracle`` reads a self-set assert as STRONG, because it is a real value
comparison. This rule is the other half of that verdict: the comparison is
strong, the value is the test's own.

CHECK FIRST, measured 2026-09-23 over the fleet's 572 test files:

  * 5 files scored, 15 hits; 8 more reported across 5 other files. Shapes:
    constructor kwarg 14, attribute assign 1.
  * The largest single cluster is one ``Event`` built with eight keyword
    arguments and all eight read straight back.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: with no call in between there is no
product between the write and the read. The assertion is a statement about
Python, and it passes with the product deleted.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "SELF_SET_ASSERT"
STANDARD_KEY = "self_set_assert"

#: The three ways a test hands itself the value it is about to assert.
ATTRIBUTE = "attribute assign"
ITEM = "item assign"
KWARG = "constructor kwarg"

CURE = "assert what the product computed, not what this test just wrote"


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[self_set_assert] Unparseable, nothing scanned: %s", exc)
        return None


def _dotted(node: ast.AST) -> str:
    """A target written out: ``client.file_tracker``, ``inbox['unread']``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        base = _dotted(node.value)
        return f"{base}[{node.slice.value!r}]" if base else ""
    return ""


def _literal(node: ast.AST) -> str | None:
    """The node's value as a stable repr, or None when it is not a literal."""
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, SyntaxError, TypeError):
        return None


def _tests(tree: ast.Module) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every test function in the file."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]


def _from_kwargs(node: ast.Assign, written: Dict[str, Tuple[str, str, int]]) -> None:
    """Record ``obj = C(attr=X)`` as a write of ``obj.attr``."""
    if not isinstance(node.value, ast.Call):
        return
    for target in node.targets:
        base = _dotted(target)
        if not base:
            continue
        for keyword in node.value.keywords:
            value = _literal(keyword.value)
            if keyword.arg and value is not None:
                written[f"{base}.{keyword.arg}"] = (value, KWARG, node.lineno)


def written_here(function: ast.AST) -> Dict[str, Tuple[str, str, int]]:
    """Every path this test writes a literal to: path -> (value, shape, line)."""
    written: Dict[str, Tuple[str, str, int]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        value = _literal(node.value)
        if value is None:
            _from_kwargs(node, written)
            continue
        for target in node.targets:
            path = _dotted(target)
            if not path:
                continue
            if "." in path:
                written[path] = (value, ATTRIBUTE, node.lineno)
            elif "[" in path:
                written[path] = (value, ITEM, node.lineno)
    return written


def _equality(node: ast.Assert) -> Tuple[str, str | None]:
    """(what this assert compares, the literal it compares against)."""
    test = node.test
    if not isinstance(test, ast.Compare) or not test.ops or not isinstance(test.ops[0], ast.Eq):
        return "", None
    return _dotted(test.left), _literal(test.comparators[0])


def scan(source: str) -> Tuple[List[Tuple[int, str, str]], int]:
    """((line, path, shape) scored, how many were reported not judged)."""
    tree = _parse(source)
    if tree is None:
        return [], 0

    scored: List[Tuple[int, str, str]] = []
    reported = 0
    for function in _tests(tree):
        written = written_here(function)
        if not written:
            continue
        calls = sorted(node.lineno for node in ast.walk(function) if isinstance(node, ast.Call))
        for node in ast.walk(function):
            if not isinstance(node, ast.Assert):
                continue
            path, value = _equality(node)
            if path not in written or value is None or written[path][0] != value:
                continue
            _value, shape, set_line = written[path]
            # A call in between makes this a durability oracle, not a tautology.
            if any(set_line < line < node.lineno for line in calls):
                reported += 1
            else:
                scored.append((node.lineno, path, shape))
    return sorted(scored), reported


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[self_set_assert] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Self set assert", "passed": passed, "message": message}]


def _clean_message(reported: int) -> str:
    """The passing message, carrying the durability count without a verdict."""
    if not reported:
        return "Every assertion here compares a value the product produced"
    shape = "assertion re-reads" if reported == 1 else "assertions re-read"
    return (
        f"Every assertion here compares a value the product produced "
        f"({reported} {shape} a value after a call ran, which is a durability check)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for assertions that only read back what the test wrote.

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
    # check and appends "(+N more)", so one check per assertion would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {path_} was set by this test ({shape}) - {CURE}" for line, path_, shape in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
