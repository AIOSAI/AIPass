# =================== AIPass ====================
# Name: unread_redirect_check.py
# Description: nominator - an autouse fixture that redirects a seam nothing reads back
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-10-17
# =============================================

"""An autouse redirect nobody reads makes every write through that seam invisible.

Reference: unread_redirect.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: Both spellings can be autouse and redirect, so every walk takes the union.
FIXTURE_NODE = Union[ast.FunctionDef, ast.AsyncFunctionDef]

GROUP = "static_unread_redirect"

#: Calls that redirect something: monkeypatch's environment and attribute
#: doors, plus the two that move the process itself.
REDIRECT_CALLS: frozenset = frozenset({"setenv", "setattr", "chdir", "syspath_prepend", "delenv"})

#: Without it a fixture nobody requests never runs: dead code, a different finding.
AUTOUSE = "autouse"

FIXTURE_NAMES: frozenset = frozenset({"fixture", "yield_fixture"})

CONFTEST = "conftest.py"

#: Replacing a writer and asserting on the record is the second door onto a seam.
#: Declared, never inferred: a forgotten writer over-reports, which gets noticed.
SEAM_WRITERS: frozenset = frozenset({"log_operation"})

SPECIFICATION = {
    "rule": "DPLAN-0352 round 3 ask 2 - an autouse redirect whose target no test reads",
    "species": ["UNREAD-REDIRECT"],
    "flags": [
        "an autouse fixture that redirects a seam (monkeypatch setenv/setattr/chdir) and returns or "
        "yields the redirect target, where no test in the suite requests it",
    ],
    "exempts": [
        "a fixture that returns and yields nothing: it is an isolation fence, there is no target to "
        "read, and nothing reading it is the design",
        "a fixture any test requests by parameter or through usefixtures",
        "a suite that SUBSTITUTES the seam writer (monkeypatch.setattr(..., 'log_operation', ...)) "
        "and asserts on what it recorded - that is the second door onto the same seam",
        "a fixture that is not autouse: one nobody requests simply never runs",
    ],
    "fix": (
        "either assert against the redirect target in at least one test, so writes through the seam "
        "are observable, or stop handing the target back and let the fixture be the fence it is"
    ),
    "limits": [
        "PROXY, AND A FLOOR. 'Requested' is read as 'a test takes it as a parameter or names it in "
        "usefixtures', which is weaker than 'a test asserts against the redirect target'. A suite "
        "that requests the fixture for its tmp_path and never looks at the seam reads as clean here.",
        "Conftest only. A redirect declared inside one test module applies to that module, and this "
        "rule does not read it.",
        "It nominates a MECHANISM, not a defect. Whether any write through the seam deserved to be "
        "observed is the execution tier's question - statement_deletion is what answers it.",
        "The writer-substitution acquittal is BRANCH-WIDE and blunt: one test file that names a seam "
        "writer clears the whole suite. A branch that watches the seam in one place and is blind "
        "everywhere else reads as clean, which is the under-reporting direction a nominator should "
        "err in, but it is not free.",
    ],
}


def _is_fixture_decorator(node: ast.expr) -> bool:
    """True for `@pytest.fixture(...)`, `@fixture(...)` and the yield spelling."""
    call = node.func if isinstance(node, ast.Call) else node
    if isinstance(call, ast.Attribute):
        return call.attr in FIXTURE_NAMES
    return isinstance(call, ast.Name) and call.id in FIXTURE_NAMES


def _is_autouse(node: ast.expr) -> bool:
    """True when this decorator carries `autouse=True` literally."""
    if not isinstance(node, ast.Call):
        return False
    for keyword in node.keywords:
        if keyword.arg == AUTOUSE and isinstance(keyword.value, ast.Constant):
            return bool(keyword.value.value)
    return False


def _redirects(fixture: FIXTURE_NODE) -> Set[str]:
    """Which redirect doors this fixture body goes through."""
    return {
        node.func.attr
        for node in ast.walk(fixture)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in REDIRECT_CALLS
    }


def _hands_back(fixture: FIXTURE_NODE) -> bool:
    """True when the fixture returns or yields a value a test could read.

    A bare `yield` hands back None: the fence shape.
    """
    for node in ast.walk(fixture):
        if isinstance(node, (ast.Return, ast.Yield)) and node.value is not None:
            return True
    return False


def autouse_redirects(tree: ast.Module) -> List[FIXTURE_NODE]:
    """Every autouse fixture in this module that redirects something."""
    found: List[FIXTURE_NODE] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [d for d in node.decorator_list if _is_fixture_decorator(d)]
        if not decorators or not any(_is_autouse(d) for d in decorators):
            continue
        if _redirects(node):
            found.append(node)
    return found


def _usefixtures_names(unit: corpus.TestUnit) -> Set[str]:
    """Fixture names this unit names through `@pytest.mark.usefixtures(...)`."""
    names: Set[str] = set()
    for decorator in unit.decorators:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not (isinstance(target, ast.Attribute) and target.attr == "usefixtures"):
            continue
        for argument in decorator.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                names.add(argument.value)
    return names


def requested_fixtures(scanned: corpus.Corpus) -> Set[str]:
    """Every fixture name any test in the corpus asks for, by either door."""
    asked: Set[str] = set()
    for unit in scanned.units():
        asked.update(unit.params)
        asked.update(_usefixtures_names(unit))
    return asked


def substitutes_the_writer(scanned: corpus.Corpus) -> bool:
    """True when any test in the suite replaces a seam writer with its own.

    Reads whole modules: the substitution usually lives in a fixture the tests request.
    """
    for parsed in scanned.files:
        for node in ast.walk(parsed.tree):
            if isinstance(node, ast.Attribute) and node.attr in SEAM_WRITERS:
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # The dotted tail: patch() names its target as one dotted path.
                if node.value.rsplit(".", 1)[-1] in SEAM_WRITERS:
                    return True
    return False


def _conftests(root: Path) -> Dict[str, ast.Module]:
    """Every conftest under the corpus root, parsed. Unreadable ones are skipped."""
    parsed: Dict[str, ast.Module] = {}
    for path in sorted(root.rglob(CONFTEST)):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts[:-1]):
            continue
        try:
            parsed[relative.as_posix()] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            # Logged: silently skipping is how a rule reports clean on a tree it never opened.
            logger.warning(f"[AUDIT-TESTS] {GROUP} could not read {path}: {type(exc).__name__}: {exc}")
            continue
    return parsed


def _file_unit(relpath: str, lineno: int, name: str) -> corpus.TestUnit:
    """A synthetic unit standing for a fixture, so a conftest finding has a row.

    Carries the fixture's own name and line rather than a nodeid pytest would never produce.
    """
    return corpus.TestUnit(
        name=name,
        node=ast.FunctionDef(name=name, lineno=lineno, body=[], decorator_list=[]),  # type: ignore[call-arg]
        lineno=lineno,
        docstring="",
        params=[],
        decorators=[],
        class_name="",
        relpath=relpath,
    )


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every autouse redirect that hands back a target no test ever asks for."""
    asked = requested_fixtures(scanned)
    if substitutes_the_writer(scanned):
        # Watched at the writer instead of the target: nominating would be a false positive.
        return []

    rows: List[dict] = []

    for relpath, tree in _conftests(scanned.root).items():
        for fixture in autouse_redirects(tree):
            if fixture.name in asked:
                continue
            if not _hands_back(fixture):
                continue
            doors = sorted(_redirects(fixture))
            rows.append(
                corpus.nomination(
                    "UNREAD-REDIRECT",
                    _file_unit(relpath, fixture.lineno, fixture.name),
                    (
                        f"{fixture.name}() is autouse, redirects through {', '.join(doors)}, and hands "
                        f"the target back - but no test in this suite requests it, so every write "
                        f"through that seam is unobservable for the whole run"
                    ),
                    verdict=corpus.VERDICT_IMPROVE,
                    line=fixture.lineno,
                    evidence={
                        "fixture": fixture.name,
                        "redirect_calls": doors,
                        "hands_target_back": True,
                        "requested_by_any_test": False,
                        "proxy": "requested = a test parameter or a usefixtures name; a floor, not a count",
                    },
                )
            )

    return rows


def _why_not(fixture: FIXTURE_NODE, asked: Set[str], substituted: bool) -> Optional[str]:
    """The reason this redirect was cleared, or None when it was nominated."""
    if fixture.name in asked:
        return "a test requests it, so the seam is reachable from the suite"
    if substituted:
        return "the suite substitutes the seam writer and asserts on what it recorded"
    if not _hands_back(fixture):
        return "it hands nothing back - an isolation fence, with no target to read"
    return None


def acquitted(scanned: corpus.Corpus) -> List[dict]:
    """Every autouse redirect this rule deliberately did NOT nominate, and why.

    Published because the must_not_fire side is the precision argument.
    """
    asked = requested_fixtures(scanned)
    substituted = substitutes_the_writer(scanned)
    cleared: List[dict] = []

    for relpath, tree in _conftests(scanned.root).items():
        for fixture in autouse_redirects(tree):
            reason = _why_not(fixture, asked, substituted)
            if reason is not None:
                cleared.append({"file": relpath, "fixture": fixture.name, "why_not": reason})

    return cleared
