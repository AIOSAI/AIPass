# =================== AIPass ====================
# Name: oversize_test_file_check.py
# Description: Oversize Test File Standards Checker Handler
# Version: 1.1.0
# Created: 2026-09-20
# Modified: 2026-10-17
# =============================================

"""
Oversize Test File Standards Checker Handler

Reference: oversize_test_file.md
"""

import ast
from pathlib import Path
from typing import Dict, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "OVERSIZE_TEST_FILE"
STANDARD_KEY = "oversize_test_file"

# Lines of code, payload already removed. Matches the product-side cap.
CODE_LINE_CAP = 1500

MESSAGE = (
    "split it along the unit under test, one file per subject - "
    "moving tests is not adding them, so ask @devpulse to open the gate for the split"
)


def _payload_lines(tree: ast.AST) -> int:
    """How many source lines sit inside a multi-line string literal.

    A SET of line numbers rather than a running sum: an f-string holds its own
    nested constants, and adding each span independently double-counts shared lines.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if node.end_lineno and node.end_lineno > node.lineno:
            lines.update(range(node.lineno, node.end_lineno + 1))
    return len(lines)


def measure(source: str) -> Tuple[int, int, int]:
    """(code_lines, total_lines, payload_lines) for one test file's source.

    An unparseable file is measured at full length: exempting it would make "delete one bracket" a way past the cap.
    """
    total = len(source.splitlines())
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[oversize_test_file] Unparseable, measured whole at %d lines: %s", total, exc)
        return total, total, 0
    payload = _payload_lines(tree)
    return total - payload, total, payload


def _measure_path(path: Path) -> Tuple[int, int, int]:
    """measure() for a file on disk, or zeroes if it cannot be read."""
    try:
        return measure(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError as exc:
        logger.info("[oversize_test_file] Cannot read %s: %s", path, exc)
        return 0, 0, 0


def _result(passed: bool, message: str, score: int) -> Dict:
    """The single-check result shape every checker in this pack returns."""
    return {
        "passed": passed,
        "checks": [{"name": "Test file size", "passed": passed, "message": message}],
        "score": score,
        "standard": STANDARD,
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file against the code-line cap."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, "Standard bypassed via .seedgo/bypass.json", 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, f"File not found: {module_path}", 0)

    code, total, payload = _measure_path(path)

    if code <= CODE_LINE_CAP:
        return _result(True, f"{code} code lines, cap {CODE_LINE_CAP}", 100)

    # Payload is named in the conviction: without the credit already given, the code-line count reads as unreachable.
    message = (
        f"{code} code lines, cap {CODE_LINE_CAP} "
        f"({total} total, {payload} of string payload already excluded) - {MESSAGE}"
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "code_lines": code},
    )
    return _result(False, message, 0)
