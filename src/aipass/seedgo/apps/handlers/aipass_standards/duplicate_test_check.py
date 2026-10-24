# =================== AIPass ====================
# Name: duplicate_test_check.py
# Description: Duplicate Test Standards Checker Handler
# Version: 1.0.3
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""Duplicate Test Standards Checker Handler

Reference: duplicate_test.md
"""

from functools import partial
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "DUPLICATE_TEST"
STANDARD_KEY = "duplicate_test"

TEST_PREFIX = "test_"

DECORATOR = "@"

#: The pytest marks that change the case; any other mark only schedules the same case.
CASE_MARKS = {"parametrize", "usefixtures"}

CLONE = "is the same test as"
SUBSUMED = "asserts nothing that is not already asserted by"

CURE = "delete it, or widen it until it excludes a failure the other does not"


def _body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> List[ast.stmt]:
    """A function's statements with the docstring dropped."""
    statements = list(function.body)
    first = statements[0] if statements else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return statements[1:]
    return statements


def _shape(statement: ast.AST) -> str:
    """One statement as position-free text: formatting drops out, meaning does not.

    Constants are KEPT on purpose: ``*.log`` and ``*.txt`` are two different claims.
    """
    return ast.dump(statement)


def _harmless(statement: ast.AST) -> bool:
    """Whether a statement Y adds beyond X leaves the world exactly as it was."""
    if isinstance(statement, ast.Assert):
        return True
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        value = statement.value
        return value is not None and not any(isinstance(n, ast.Call) for n in ast.walk(value))
    return False


def _changes_the_case(decorator: ast.expr) -> bool:
    """Whether a decorator makes the test a different case (seedgo, fleet green leg 10).

    A ``pytest.mark.X`` outside CASE_MARKS does not change what runs: twins that differ
    only by a timeout or a skipif are one case run twice.
    """
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not isinstance(target, ast.Attribute):
        return True
    owner = target.value
    is_mark = (isinstance(owner, ast.Attribute) and owner.attr == "mark") or (
        isinstance(owner, ast.Name) and owner.id == "mark"
    )
    return not is_mark or target.attr in CASE_MARKS


def _tests(tree: ast.Module) -> List[Tuple[int, str, Dict[str, ast.AST]]]:
    """(line, name, statements by shape) for every test with a body in this file."""
    found: List[Tuple[int, str, Dict[str, ast.AST]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith(TEST_PREFIX):
            continue
        statements: Dict[str, ast.AST] = {_shape(s): s for s in _body(node)}
        if statements:
            # Decorators that change the case are part of the test: never shared away nor subsumed.
            statements.update({DECORATOR + _shape(d): d for d in node.decorator_list if _changes_the_case(d)})
            found.append((node.lineno, node.name, statements))
    return found


def _clones(tests: List[Tuple[int, str, Dict[str, ast.AST]]]) -> List[Tuple[int, str, str, str]]:
    """B1: tests whose statement sets are equal. The later copy is the finding."""
    groups: Dict[Tuple[str, ...], List[Tuple[int, str]]] = {}
    for line, name, statements in tests:
        groups.setdefault(tuple(sorted(statements)), []).append((line, name))
    findings: List[Tuple[int, str, str, str]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # The FIRST by line is the original: stable under an edit anywhere else in the file.
        original = min(members)[1]
        findings.extend((line, name, CLONE, original) for line, name in sorted(members)[1:])
    return findings


def _subsumed(tests: List[Tuple[int, str, Dict[str, ast.AST]]], claimed: Set[str]) -> List[Tuple[int, str, str, str]]:
    """B2: tests wholly contained in another whose extras change no world."""
    findings: List[Tuple[int, str, str, str]] = []
    for line, name, statements in tests:
        if name in claimed:
            continue
        for _other_line, other, bigger in tests:
            if other == name or not set(statements) < set(bigger):
                continue
            if all(_harmless(bigger[shape]) for shape in set(bigger) - set(statements)):
                findings.append((line, name, SUBSUMED, other))
                break
    return findings


_parse = partial(parse, tag="duplicate_test")


def scan(source: str) -> List[Tuple[int, str, str, str]]:
    """(line, test, relation, the other test) for each duplicate in this file."""
    tree = _parse(source)
    if tree is None:
        return []
    tests = _tests(tree)
    clones = _clones(tests)
    # A clone is already the strongest reading; charging it again as subsumed double-counts.
    subsumed = _subsumed(tests, {name for _line, name, _rel, _other in clones})
    return sorted(clones + subsumed)


_read = partial(read_text, tag="duplicate_test", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Duplicate test", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for tests another test in the same file already covers."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    findings = scan(source)
    if not findings:
        return _result(True, _one_check(True, "Every test here asserts something no other test does"), 100)

    # Every hit on ONE check: checklist._format_failure shows the first and "(+N more)".
    detail = "\n".join(
        f"{path.name}:{line} {name} {relation} {other} - {CURE}" for line, name, relation, other in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
