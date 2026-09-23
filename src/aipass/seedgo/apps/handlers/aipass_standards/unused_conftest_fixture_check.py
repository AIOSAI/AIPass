# =================== AIPass ====================
# Name: unused_conftest_fixture_check.py
# Description: Unused Conftest Fixture Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Unused Conftest Fixture Standards Checker Handler

Crack class G from the 2026-09-22 eyes-on review of @backup's tests: a fixture
defined in a branch's ``conftest.py``, not ``autouse``, that no test and no
other fixture in the branch ever requests. It is apparatus nothing uses --
dead weight that reads as shared infrastructure, so the next author extends it
instead of deleting it.

@backup's ``tests/conftest.py`` carries three: ``temp_dir`` (80),
``sample_data`` (92), ``mock_logger`` (176).

THREE WAYS TO REQUEST A FIXTURE, and all three count as use:

  * by PARAMETER NAME on a test or on another fixture -- the ordinary way;
  * by ``@pytest.mark.usefixtures("name")`` -- a string, which is why every
    string literal in the branch's tests is read as a possible request;
  * by ``request.getfixturevalue("name")`` -- also a string, same reading.

``autouse=True`` is never convicted. Nothing requests it by design; that is
what autouse means.

BUILT ALONE, NOT INSIDE ``conftest_fixtures``, and the dispatch asked me to say
which and why. ``conftest_fixtures`` is ``all_files`` and judges one
``conftest.py`` in isolation -- its two rules are about what that file itself
contains. This question cannot be answered from that file at all: whether a
fixture is requested is a fact about the WHOLE branch's ``tests/`` tree, so the
rule is ``branch_level`` and its entry point is ``check_branch``. Folding it
into a file-level checker would have meant a file-level rule secretly reading
its siblings, which is exactly the coupling the two scopes exist to keep apart.

CHECK FIRST, measured 2026-09-22 over the fleet:

  * 13 conftest files, 22 fixtures. @backup 3, @drone 3, then @commons,
    @daemon, @memory, @skills, @spawn at 2 each and six branches at 1.
  * The dispatch's first cut said 17 files and 51. The gap is the three
    request forms above: a rule that reads only parameter names convicts every
    fixture used through ``usefixtures`` or ``getfixturevalue``.
  * @backup's three land at 80, 92 and 176. The review said 79, 91 and 175 --
    the same fixtures; the review cites the ``@pytest.fixture`` decorator line
    and this rule cites the ``def``.

WHY IT CANNOT BE SATISFIED BY ACCIDENT: if no parameter, no ``usefixtures``
string and no ``getfixturevalue`` string in the entire branch names the
fixture, pytest can never construct it. Deleting it cannot turn the suite red.
There is no threshold and nothing to tune.
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "branch_level"

STANDARD = "UNUSED_CONFTEST_FIXTURE"
STANDARD_KEY = "unused_conftest_fixture"

#: The file whose fixtures this rule judges. A fixture in a test file is local
#: to it and its neighbours already see it or do not; conftest is the shared one.
CONFTEST = "conftest.py"

#: The decorator that makes a function a fixture.
FIXTURE = "fixture"

#: The keyword that means "nothing needs to request this".
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

    ``ruff`` already convicts a syntax error, and a verdict invented for a file
    Python cannot parse sends its author to the wrong place.
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

    Requests are parameter names plus EVERY string literal in the tree, because
    ``usefixtures`` and ``getfixturevalue`` both name a fixture with a string
    and reading only the two call shapes would miss a table of them.
    """
    fixtures: Dict[str, Tuple[Path, int]] = {}
    requested: Set[str] = set()
    for path in sorted(tests_dir.rglob("*.py")):
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


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Unused conftest fixture", "passed": passed, "message": message}]


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch for conftest fixtures no test ever requests.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo).
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(branch_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    branch_root = Path(branch_path)
    findings = scan(branch_root)
    if not findings:
        return _result(True, _one_check(True, "Every conftest fixture here is requested by something"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per fixture would show the
    # first and hide the rest behind a count.
    detail = "\n".join(
        f"{path.relative_to(branch_root)}:{line} {name} is defined and never requested - {CURE}"
        for path, line, name in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
