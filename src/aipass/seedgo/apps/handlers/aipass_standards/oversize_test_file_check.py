# =================== AIPass ====================
# Name: oversize_test_file_check.py
# Description: Oversize Test File Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""
Oversize Test File Standards Checker Handler

Convicts a test file carrying more than ``CODE_LINE_CAP`` lines of CODE.

Fixture payload does not count. A test file that holds 1,500 lines of sample
JSON, a rendered README or a captured log is doing exactly what a test file
should — the payload is data the assertions read, and charging for it would
push authors to move fixtures out of sight rather than to split anything. So
every line inside a multi-line string literal is subtracted before the cap is
applied, docstrings included: the gold standard asks for a docstring naming
the bug a test pins, and a size rule must never be a reason to delete one.

The cap is not tuned to land a number. Measured across the fleet 2026-09-20:
538 test files, median 378 code lines, 90th percentile 1,161. A cap of 1,500
therefore sits above nine files in ten and convicts 34 — the tail, not the
body — and it is the same figure the product side already uses.

Two lanes, exactly as ``router_assert``:

  * ``check_module`` -- APPLIES_TO tests, so only the per-file checklist lane
    runs it, on the write that grows the file.
  * ``check_branch_info`` -- the standing backlog, UNSCORED. Test files are
    not in the audit's corpus (``_collect_py_files`` walks ``apps/``), so no
    branch's number moves.

One honest limit, stated because it is the whole reason this rule is a
prohibition and not a requirement: the cure for an oversize file is a split,
and a split needs new test files, which the hooks test-write gate refuses by
policy. The message therefore tells an author what the split looks like and
never implies they can perform it unasked.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import applicability
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
    nested constants, and adding each span independently double-counts the
    lines they share. Measured 2026-09-20 that gap was 26 lines on this
    branch's largest file — small, but it makes the number irreproducible,
    which is worse than wrong for a threshold nobody can re-derive.
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

    A file that does not parse is measured at its full length rather than
    skipped: ruff already convicts the syntax error, and silently exempting
    an unparseable file would make "delete one bracket" a way past the cap.
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
    """Check one test file against the code-line cap.

    Args:
        module_path: Path to the test file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, "Standard bypassed via .seedgo/bypass.json", 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, f"File not found: {module_path}", 0)

    code, total, payload = _measure_path(path)

    if code <= CODE_LINE_CAP:
        return _result(True, f"{code} code lines, cap {CODE_LINE_CAP}", 100)

    # Payload is named in the conviction on purpose: an author looking at a
    # 10,524-line file needs to know the rule already gave them credit for
    # 5,933 of those lines, or the number reads as unreachable.
    message = (
        f"{code} code lines, cap {CODE_LINE_CAP} "
        f"({total} total, {payload} of string payload already excluded) - {MESSAGE}"
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "code_lines": code},
    )
    return _result(False, message, 0)


def check_branch_info(branch_path: str) -> List[str]:
    """The standing backlog, reported with no score attached.

    Names the largest offender rather than only counting them: "3 files over
    the cap" gives an owner nothing to start on, and the biggest file is
    almost always where the split is worth doing first.
    """
    tests_dir = Path(branch_path) / "tests"
    if not tests_dir.is_dir():
        return []
    over: List[Tuple[int, str]] = []
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        if applicability.is_retired_path(str(test_file)):
            continue
        code, _total, _payload = _measure_path(test_file)
        if code > CODE_LINE_CAP:
            over.append((code, test_file.name))
    if not over:
        return []
    worst_code, worst_name = max(over)
    return [
        f"oversize_test_file backlog: {len(over)} test file(s) over {CODE_LINE_CAP} code lines, "
        f"largest {worst_name} at {worst_code} (unscored - convicted on the next write of the file)"
    ]
