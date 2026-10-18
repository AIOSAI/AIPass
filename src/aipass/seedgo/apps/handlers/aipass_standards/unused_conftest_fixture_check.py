# =================== AIPass ====================
# Name: unused_conftest_fixture_check.py
# Description: Unused Conftest Fixture Standards Checker Handler
# Version: 1.2.0
# Created: 2026-09-22
# Modified: 2026-10-17
# =============================================

"""
Unused Conftest Fixture Standards Checker Handler

Reference: unused_conftest_fixture.md
"""

import ast
from pathlib import Path, PurePath
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import in_skipped_dir
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD = "UNUSED_CONFTEST_FIXTURE"
STANDARD_KEY = "unused_conftest_fixture"

CONFTEST = "conftest.py"

FIXTURE = "fixture"

AUTOUSE = "autouse"

CURE = "request it in a test, or delete it"


def _tail_name(node: ast.AST) -> str:
    """The last name in a decorator or call target: ``a.b`` -> ``b``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _tail_name(node.func)
    return ""


def _parse(path: Path) -> ast.Module | None:
    """A file's tree, or None when Python cannot read it.

    ``ruff`` already convicts a syntax error; a second verdict misdirects the author.
    """
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError) as exc:
        logger.info("[unused_conftest_fixture] Unparseable, nothing scanned: %s", exc)
        return None


def _is_autouse(function: ast.AST) -> bool:
    """Whether any ``@pytest.fixture`` on this function sets ``autouse``."""
    decorators = getattr(function, "decorator_list", [])
    return any(
        isinstance(d, ast.Call) and _tail_name(d) == FIXTURE and any(k.arg == AUTOUSE for k in d.keywords)
        for d in decorators
    )


def _is_fixture(function: ast.AST) -> bool:
    """Whether this function carries a ``@pytest.fixture`` in either spelling."""
    return any(_tail_name(d) == FIXTURE for d in getattr(function, "decorator_list", []))


def _read_branch(tests_dir: Path) -> Tuple[Dict[str, Tuple[Path, int]], Set[str]]:
    """(conftest fixtures that are not autouse, every name the branch requests).

    Every string literal counts as a request: ``usefixtures`` and ``getfixturevalue``
    name fixtures by string, and reading only those two call shapes misses a table of them.
    """
    fixtures: Dict[str, Tuple[Path, int]] = {}
    requested: Set[str] = set()
    for path in sorted(tests_dir.rglob("*.py")):
        if in_skipped_dir(path, tests_dir):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        is_conftest = path.name == CONFTEST
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                requested |= {a.arg for a in node.args.args if a.arg not in ("self", "cls")}
                if is_conftest and _is_fixture(node) and not _is_autouse(node):
                    fixtures[node.name] = (path, node.lineno)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                requested.add(node.value)
    return fixtures, requested


def scan(branch_root: Path) -> List[Tuple[Path, int, str]]:
    """(conftest, line, name) for every fixture the branch never requests."""
    tests_dir = branch_root / "tests"
    if not tests_dir.is_dir():
        return []
    fixtures, requested = _read_branch(tests_dir)
    return sorted((path, line, name) for name, (path, line) in fixtures.items() if name not in requested)


def reported_path(path: PurePath, root: PurePath) -> str:
    """The path from root as the finding prints it: ``tests/conftest.py``, forward slashes on every host."""
    return path.relative_to(root).as_posix()


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Unused conftest fixture", "passed": passed, "message": message}]


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for conftest fixtures no test ever requests."""
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    findings = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, "Every conftest fixture here is requested by something"), 100)

    # Every hit on ONE check: checklist._format_failure prints only the first
    # failed check plus "(+N more)", so one check per fixture would hide the rest.
    detail = "\n".join(
        f"{reported_path(path, branch_root)}:{line} {name} is defined and never requested - {CURE}"
        for path, line, name in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
