# =================== AIPass ====================
# Name: self_set_assert_check.py
# Description: Self Set Assert Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-23
# Modified: 2026-10-24
# =============================================

"""
Self Set Assert Standards Checker Handler

Reference: self_set_assert.md
"""

from functools import partial
import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "SELF_SET_ASSERT"
STANDARD_KEY = "self_set_assert"

#: The three ways a test hands itself the value it is about to assert.
ATTRIBUTE = "attribute assign"
ITEM = "item assign"
KWARG = "constructor kwarg"

CURE = "assert what the product computed, not what this test just wrote"


_parse = partial(parse, tag="self_set_assert")


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


_read = partial(read_text, tag="self_set_assert", errors="ignore")
_result = partial(result, standard=STANDARD)


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
    """Check a test file for assertions that only read back what the test wrote."""
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

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(
        f"{path.name}:{line} {path_} was set by this test ({shape}) - {CURE}" for line, path_, shape in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
