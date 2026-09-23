# =================== AIPass ====================
# Name: sleep_in_test_check.py
# Description: Sleep In Test Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Sleep In Test Standards Checker Handler

Crack class N from the 2026-09-22 eyes-on review of @backup's tests, and test
template v1 item 23: a ``sleep`` inside a test. It is always one of two
mistakes, and both are curable without waiting.

  A SLEEP TO MOVE AN MTIME. On a filesystem with one-second timestamp
  granularity a 0.01s nudge does not move the mtime at all, so the test goes
  red for a reason that has nothing to do with the product; on a coarse or
  loaded host a 1.1s sleep is simply 1.1s of the suite's life, repeated.
  ``os.utime(path, (when, when))`` sets the time exactly, instantly, on every
  filesystem.

  A SLEEP TO WAIT FOR SOMETHING. A fixed sleep is a bet that the machine is
  fast enough today. It is flaky on a loaded CI box and slow on a fast one.
  A deadline poll on the REAL condition -- read the flag, join the thread with
  a timeout -- is both faster and honest about what it is waiting for.

MATCH THROUGH THE ALIAS, NOT THROUGH ``time.sleep``. This is the whole
implementation lesson. The rule is "a call whose name is ``sleep``", because
the fleet spells the module four different ways::

    time.sleep(0.01)          35 hits
    _time.sleep(0.05)          5     @prax's test_watcher
    time_module.sleep(0.01)    2     @hooks's test_engine
    time_mod.sleep(0.1)        1     @ai_mail's test_dispatch_monitor

Matching ``time.sleep`` and a bare ``sleep`` found 14 files and 35 hits and
silently missed eight. Matching the call's tail name found all of them.

CHECK FIRST, measured 2026-09-22 over the fleet's 565 test files:

  * 17 files, 43 hits -- which is the review's first cut exactly, once the
    aliases are counted.
  * Every hit is scored. There is no legitimate form: the dispatch's ruling is
    "score all", and both shapes above have a cure that is strictly better.

The evidence lines all land: ``test_versioned_engine.py`` 89, 110, 126, 240,
315, 441 -- @backup's baseline/diff suite, which is exactly the mtime shape.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: a sleep asserts nothing. It can only
make the suite slower, or make it pass on one machine and fail on another.
There is no threshold and nothing to tune.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "SLEEP_IN_TEST"
STANDARD_KEY = "sleep_in_test"

#: The call this rule is about, matched by its TAIL name so every spelling of
#: the module -- time, _time, time_module, time_mod -- is caught.
SLEEP = "sleep"

CURE = "os.utime for an mtime, a deadline poll on the real condition for an event"


def _tail_name(node: ast.AST) -> str:
    """The last name in a call target: ``a.b.c`` -> ``c``, ``f`` -> ``f``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _spelling(node: ast.Call) -> str:
    """How this call names the module, for the finding: ``time_mod.sleep``."""
    if isinstance(node.func, ast.Attribute):
        return f"{_tail_name(node.func.value)}.{SLEEP}"
    return SLEEP


def _parse(source: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[sleep_in_test] Unparseable, nothing scanned: %s", exc)
        return None


def scan(source: str) -> List[Tuple[int, str]]:
    """(line, how the call is spelled) for every sleep in this test file."""
    tree = _parse(source)
    if tree is None:
        return []
    return sorted(
        (node.lineno, _spelling(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _tail_name(node.func) == SLEEP
    )


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[sleep_in_test] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Sleep in test", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for sleeps standing in for a clock or a condition.

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

    findings = scan(source)
    if not findings:
        return _result(True, _one_check(True, "Nothing here waits on the clock"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per sleep would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.name}:{line} {spelling} waits instead of asserting - {CURE}" for line, spelling in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
