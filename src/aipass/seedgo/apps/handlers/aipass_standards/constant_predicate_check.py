# =================== AIPass ====================
# Name: constant_predicate_check.py
# Description: Constant Predicate Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Constant Predicate Standards Checker Handler

Crack class C from the 2026-09-22 eyes-on review of @backup's tests: a
``lambda`` whose body is a constant, handed to product code as an argument. It
cannot discriminate a product that honours the callable from one that ignores
it entirely.

@backup's ``test_ignore_pathspec.py:491`` is the shape::

    mirror_tree(src, dst, should_ignore=lambda p: False)

``mirror.py:95`` never calls ``should_ignore``. The lambda answers False for
every path, and a product that dropped the parameter would pass the same test.

THE SPLIT IS THE JUDGEMENT THE DISPATCH ASKED FOR, and the numbers make the
case rather than an argument:

  SCORED -- the body is a ``bool``. ``lambda p: False`` is a PREDICATE, and a
  predicate that returns the same answer for every input cannot discriminate.
  There is no input for which it says anything, so no test using it can tell a
  product that consults it from one that does not. 163 hits.

  REPORTED WITH A COUNT, NEVER SCORED -- the body is anything else. 309 hits,
  and 236 of those return ``None``: ``lambda *a: None`` as an ``on_progress``
  or a logger. That is an inert CALLBACK, not a predicate, and a no-op stub
  for a callback that is not under test is a legitimate thing to write. The
  other 73 return a value the product then uses -- ``0``, ``'HEADER'``,
  ``'/usr/bin/python3'`` -- which is a stand-in answering a question, not a
  predicate refusing to.

  163 + 309 = 472, which is the review's own first cut to the hit. We are
  measuring the same population; this rule scores the third of it that cannot
  be right.

NOT RESTRICTED TO TEST BODIES, and this is the one place it reads wider than
the dispatch's wording. A constant predicate handed to the product from a
fixture or a module-level helper is the same defect reaching the same product
call, and the file it lives in is test code either way. Every hit is still
inside a ``tests/`` file.

CHECK FIRST, measured 2026-09-22 over the fleet's 565 test files:

  * SCORED: 38 files, 163 hits. REPORTED: 309 in the same files and others.
  * The evidence lines all land: ``test_ignore_pathspec.py:491`` and
    ``test_snapshot_fidelity.py`` 89, 107, 124, 149.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: a bool-constant lambda returns the
same answer for every argument it is ever given. Delete the product's call to
it and nothing about the test changes. There is no threshold and nothing to
tune.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "CONSTANT_PREDICATE"
STANDARD_KEY = "constant_predicate"

CURE = "return an answer that depends on the argument, or assert the product called it"


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[constant_predicate] Unparseable, nothing scanned: %s", exc)
        return None


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


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[constant_predicate] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Constant predicate", "passed": passed, "message": message}]


def _clean_message(counted: List[str]) -> str:
    """The passing message, carrying the inert-callback count without a verdict.

    The device ``weak_oracle`` uses for its soft oracles: a number the owner
    asked for rides along, and nobody is charged for it.
    """
    if not counted:
        return "Every callable handed to the product here can discriminate"
    shape = "stub" if len(counted) == 1 else "stubs"
    return (
        f"Every callable handed to the product here can discriminate "
        f"({len(counted)} inert callback {shape} are counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for constant lambdas handed to the product.

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

    scored, counted = scan(source)
    if not scored:
        return _result(True, _one_check(True, _clean_message(counted)), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per lambda would show the
    # first and hide the rest behind a count.
    detail = "\n".join(f"{path.name}:{line} lambda always returns {value} - {CURE}" for line, value in scored)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(scored)},
    )
    return _result(False, _one_check(False, detail), 0)
