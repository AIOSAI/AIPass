# =================== AIPass ====================
# Name: sleep_in_test_check.py
# Description: Sleep In Test Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-22
# Modified: 2026-10-24
# =============================================

"""
Sleep In Test Standards Checker Handler

Reference: sleep_in_test.md
"""

from functools import partial
import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.check_support import parse, read_text, result, tail_name

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "SLEEP_IN_TEST"
STANDARD_KEY = "sleep_in_test"

#: Matched by TAIL name, so every spelling of the module (time, _time, time_module, time_mod) is caught.
SLEEP = "sleep"

CURE = "os.utime for an mtime, a deadline poll on the real condition for an event"


def _spelling(node: ast.Call) -> str:
    """How this call names the module, for the finding: ``time_mod.sleep``."""
    if isinstance(node.func, ast.Attribute):
        return f"{tail_name(node.func.value)}.{SLEEP}"
    return SLEEP


_parse = partial(parse, tag="sleep_in_test")


def scan(source: str) -> List[Tuple[int, str]]:
    """(line, how the call is spelled) for every sleep in this test file."""
    tree = _parse(source)
    if tree is None:
        return []
    return sorted(
        (node.lineno, _spelling(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and tail_name(node.func) == SLEEP
    )


_read = partial(read_text, tag="sleep_in_test", errors="ignore")
_result = partial(result, standard=STANDARD)


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Sleep in test", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file for sleeps standing in for a clock or a condition."""
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

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    detail = "\n".join(
        f"{path.name}:{line} {spelling} waits instead of asserting - {CURE}" for line, spelling in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
