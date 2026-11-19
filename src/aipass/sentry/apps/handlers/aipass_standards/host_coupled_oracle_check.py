# =================== AIPass ====================
# Name: host_coupled_oracle_check.py
# Description: Host Coupled Oracle Standards Checker Handler
# Version: 1.1.0
# Created: 2026-10-26
# Modified: 2026-11-14
# =============================================

"""Host Coupled Oracle Standards Checker Handler.

Reference: host_coupled_oracle.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.sentry.apps.handlers.aipass_standards import calendar_bound_check as calendar
from aipass.sentry.apps.handlers.aipass_standards.check_support import tail_name
from aipass.sentry.apps.handlers.bypass.ignore_handler import load_ignore_entries
from aipass.sentry.apps.handlers.bypass.utils import is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

# APPLIES_TO: its corpus is tests/ already - the rule is about what a test's oracle depends on.
APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "HOST_COUPLED_ORACLE"
_BYPASS_KEY = "host_coupled_oracle"

#: tests/ is fingerprinted by the audit cache already; a skill's own tests/ under lib/ is not.
BRANCH_INPUTS = ("lib/*/tests/**/*.py",)

#: Below this the branch fails the standard, matching every other checker here.
PASS_THRESHOLD = 75

_OWN_PIDS = frozenset({"getpid", "getppid"})

#: A callee named for the command line it reads, matched on whole underscore-separated words.
_COMMAND_LINE = re.compile(r"(?:^|_)(?:args|argv|cmdline|command|title|proctitle)(?:_|$)")

_TITLE_FIX = (
    "pytest-xdist retitles every worker ('[pytest-xdist running] <test>'), so CI reads that title where a "
    "plain run reads python; start a child process and read the child's pid"
)


def _is_own_pid(node: ast.expr) -> bool:
    """``os.getpid()`` or ``os.getppid()``: this process, or the one that started it."""
    return isinstance(node, ast.Call) and tail_name(node.func) in _OWN_PIDS and not node.args


def _own_command_line_reads(unit: ast.AST) -> List[Tuple[int, str]]:
    """The unit hands its own pid to a reader named for the command line."""
    rows: List[Tuple[int, str]] = []
    for node in ast.walk(unit):
        if not isinstance(node, ast.Call):
            continue
        name = tail_name(node.func)
        if _COMMAND_LINE.search(name) and any(_is_own_pid(arg) for arg in node.args):
            rows.append((node.lineno, f"reads its own process's command line through {name}() - {_TITLE_FIX}"))
    return rows


def scan_file(file_path: str, package_root: str) -> List[Tuple[int, str]]:
    """Every test unit in one file. A file that cannot be read or parsed reports nothing."""
    test_module = calendar._module_at(Path(file_path), Path(package_root))
    if test_module is None:
        return []
    rows: List[Tuple[int, str]] = []
    for unit, _cls in calendar._test_units(test_module.tree):
        rows.extend((line, f"{unit.name} {detail}") for line, detail in _own_command_line_reads(unit))
    return sorted(rows)


def _result(score: int, checks: List[Dict], branch_path: str) -> Dict:
    """The pack's result shape, logged once."""
    json_handler.log_operation("check_completed", {"branch": branch_path, "score": score, "standard": _BYPASS_KEY})
    return {"passed": score >= PASS_THRESHOLD, "checks": checks, "score": score, "standard": STANDARD_NAME}


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch's tests for oracles that are only true on the host that wrote them."""
    branch_root = Path(branch_path)
    if is_bypassed(branch_path, _BYPASS_KEY, bypass_rules=bypass_rules):
        return _result(
            100,
            [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .sentry/bypass.json"}],
            branch_path,
        )

    files = calendar._corpus_files(branch_root, load_ignore_entries(branch_root))
    if not files:
        return _result(
            100,
            [{"name": "Host coupled oracle", "passed": True, "message": "No tests/ Python files to check"}],
            branch_path,
        )

    package_root = str(branch_root.resolve().parent)
    rows = [
        (rel, lineno, detail)
        for path in files
        for rel in [calendar._relative(path, branch_root)]
        for lineno, detail in scan_file(str(path), package_root)
        if not is_bypassed(rel, _BYPASS_KEY, lineno, bypass_rules)
    ]
    dirty_files = {rel for rel, _, _ in rows}
    score = int((len(files) - len(dirty_files)) / len(files) * 100)
    if not rows:
        message = f"No test reads its own process title in {len(files)} files"
        return _result(score, [{"name": "Host coupled oracle", "passed": True, "message": message}], branch_path)

    preview = "; ".join(f"{rel}:{lineno} {detail.split(' - ')[0]}" for rel, lineno, detail in rows[:3])
    suffix = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
    check = {
        "name": "Host coupled oracle",
        "passed": False,
        "message": f"{len(rows)} host-coupled oracle(s) in {len(dirty_files)}/{len(files)} files: {preview}{suffix}",
        "violations": [{"file": rel, "line": lineno, "name": detail} for rel, lineno, detail in rows],
    }
    return _result(score, [check], branch_path)
