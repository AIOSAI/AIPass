# =================== AIPass ====================
# Name: constant_predicate_check.py
# Description: Constant Predicate Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""Constant Predicate Standards Checker Handler

Reference: constant_predicate.md
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

STANDARD = "CONSTANT_PREDICATE"
STANDARD_KEY = "constant_predicate"

CURE = "return an answer that depends on the argument, or assert the product called it"


_parse = partial(parse, tag="constant_predicate")


def _handed_over(tree: ast.Module) -> List[ast.Lambda]:
    """Every ``lambda`` that is an argument of some call.

    A lambda bound to a name and never handed anywhere is not yet a predicate
    the product will consult; the ARGUMENT position is what makes it one.
    """
    found: List[ast.Lambda] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for argument in list(node.args) + [keyword.value for keyword in node.keywords]:
            if isinstance(argument, ast.Lambda):
                found.append(argument)
    return found


def scan(source: str) -> Tuple[List[Tuple[int, str]], List[str]]:
    """((line, the constant) scored, the constants reported with a count)."""
    tree = _parse(source)
    if tree is None:
        return [], []

    scored: List[Tuple[int, str]] = []
    counted: List[str] = []
    for node in _handed_over(tree):
        if not isinstance(node.body, ast.Constant):
            continue
        value = node.body.value
        # bool BEFORE int: in Python `isinstance(True, int)` is True, and
        # reading a predicate as a numeric stand-in loses the whole rule.
        if isinstance(value, bool):
            scored.append((node.lineno, repr(value)))
        else:
            counted.append(repr(value))
    return sorted(scored), counted


_read = partial(read_text, tag="constant_predicate", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Constant predicate", "passed": passed, "message": message}]


def _clean_message(counted: List[str]) -> str:
    """The passing message, carrying the inert-callback count without a verdict."""
    if not counted:
        return "Every callable handed to the product here can discriminate"
    shape = "stub" if len(counted) == 1 else "stubs"
    return (
        f"Every callable handed to the product here can discriminate "
        f"({len(counted)} inert callback {shape} are counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for constant lambdas handed to the product."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    scored, counted = scan(source)
    if not scored:
        return _result(True, _one_check(True, _clean_message(counted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per lambda would hide the rest.
    detail = "\n".join(f"{path.name}:{line} lambda always returns {value} - {CURE}" for line, value in scored)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
