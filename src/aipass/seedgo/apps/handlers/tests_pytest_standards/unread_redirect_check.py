# =================== AIPass ====================
# Name: unread_redirect_check.py
# Description: nominator - an autouse fixture that redirects a seam nothing reads back
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""An autouse redirect nobody reads makes every write through that seam invisible.

THE MECHANISM, NOT THE INSTANCE. Round 2's statement-deletion campaign found
9 of 9 `log_operation` calls in canary surviving deletion, and 7 of 9 logger
calls. That is not nine defects; it is one, and this rule is it. Canary's
conftest declares `mock_infrastructure(tmp_path, monkeypatch)` autouse, points
the json seam at a throwaway directory, and HANDS THAT DIRECTORY BACK. Not one
of its six test files ever asks for it. Every write through the seam therefore
lands somewhere no assertion can reach, by construction, for the whole suite.

The contrast inside the same branch is what makes it a mechanism: canary's
`mock_logger` fixture IS requested, by `test_canary_cli.py`, and the two
logger calls it watches are exactly the two of nine whose deletion the suite
noticed.

THE ROUND-2 SWEEP THAT MOTIVATED THIS RULE WAS WRONG BY 14x, and the record
says so rather than being quietly restated. That sweep used a substring proxy
- "does any test file mention the fixture name" - and reported 33 redirecting
autouse fixtures, 25 unrequested, 14 of them in branches whose production
writes through the seam. Three separate errors in that number, each found by
dogfooding this rule against the fleet:

  substring        seedgo's "43 mentions" of `mock_infrastructure` are 43
                   declarations of `_mock_infrastructure`, a DIFFERENT,
                   module-local fixture. The underscore made it a different
                   word and the substring made it the same one.
  one door         seedgo observes its trail by REPLACING the writer -
                   `monkeypatch.setattr(..., "log_operation", recorder)` then
                   an assertion on what it recorded - and never reads the
                   redirect target at all. A rule that knows only the target
                   reports every suite using the writer door as blind.
  dotted targets   `patch("aipass.devpulse...json_handler.log_operation")`
                   names the writer inside one dotted string. Comparing the
                   whole literal missed it, and devpulse and hooks were both
                   false positives until the comparison took the dotted tail.

Measured after all three cures, 2026-09-20: 30 redirecting autouse fixtures
across 18 branches, 29 acquitted, **1 nomination - canary**. That is the same
branch the execution tier independently convicted, where deleting 9 of 9
`log_operation` calls left the suite green. Static nominated, execution
convicted, and they agree on a population of one.

WHAT ACQUITS, AND WHY THE ACQUITTALS MATTER MORE THAN THE HIT:

  hands nothing back   A fixture that returns and yields nothing is a FENCE,
                       not a seam. There is no target to read, so "nothing
                       reads it" is its design rather than a defect. This one
                       clause acquits every isolation guard in the fleet -
                       `isolated_cadence_state`, `_redirect_bot_config_dir`,
                       `isolate_escalation_state` and the rest.
  requested by a test  flow's `mock_logger` and spawn's `_isolate_spawn_json`
                       are named in their own suites.
  writer substituted   sixteen branches watch the seam at the writer instead
                       of at the target. That is observation, by a door this
                       rule had to be taught.

NOMINATION, NEVER CONVICTION (Law M1). A redirect whose target is legitimately
never read is a pure sandbox and is not a defect, so this rule says only that
nothing in the suite can see through the seam. Whether anything SHOULD is the
execution tier's question, and `statement_deletion` is the instrument that
answers it.

THE PROXY IS STATED AND IT IS STILL A FLOOR. "Requested" means a test takes
the fixture as a parameter or names it in `usefixtures`; "substituted" means
the suite names a seam writer anywhere. Both are weaker than "a test asserts
that a particular write happened", so this rule UNDER-reports in both
directions and its count is a floor, not a measurement.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: Either spelling of a fixture function. Both can be autouse and both can
#: redirect, so every walk here takes the union rather than the sync half.
FIXTURE_NODE = Union[ast.FunctionDef, ast.AsyncFunctionDef]

GROUP = "static_unread_redirect"

#: Calls that redirect something: monkeypatch's environment and attribute
#: doors, plus the two that move the process itself.
REDIRECT_CALLS: frozenset = frozenset({"setenv", "setattr", "chdir", "syspath_prepend", "delenv"})

#: The decorator keyword that makes a fixture run whether or not it is asked
#: for. Without it a fixture nobody requests simply never runs, which is dead
#: code and a different finding.
AUTOUSE = "autouse"

#: Fixture declarations, however the module spells its pytest import.
FIXTURE_NAMES: frozenset = frozenset({"fixture", "yield_fixture"})

#: Where fixtures that apply to a whole suite live.
CONFTEST = "conftest.py"

#: The fleet's canonical trail writer. A suite that REPLACES this symbol and
#: asserts on what the replacement recorded is observing every write through
#: the seam, without ever reading the redirect target.
#:
#: FOUND BY DOGFOODING, and it is why this list exists. The first cut of this
#: rule fired on seedgo, and seedgo turned out to observe its own trail the
#: other way round: `monkeypatch.setattr(m10.json_handler, "log_operation",
#: lambda name, payload: recorded.append(name))`, then an assertion on
#: `recorded`. There are two doors onto a seam and a rule that knows one of
#: them reports the branches using the other as blind.
#:
#: DECLARED, NEVER INFERRED: a writer added to the fleet and forgotten here
#: makes this rule over-report, which is the direction that gets noticed.
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

    A bare `yield` hands back None, which is the fence shape: there is nothing
    to assert against, so nothing reading it cannot be a defect.
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

    Reads the whole test module rather than only test functions: the
    substitution usually lives in a fixture the tests then request, and a walk
    limited to `test_*` bodies would miss every suite that factored it out.
    """
    for parsed in scanned.files:
        for node in ast.walk(parsed.tree):
            if isinstance(node, ast.Attribute) and node.attr in SEAM_WRITERS:
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # THE DOTTED TAIL, not the whole string. `unittest.mock.patch`
                # names its target as one dotted path -
                # "aipass.devpulse.apps.handlers.json.json_handler.log_operation"
                # - and the first cut of this compared the whole literal, so
                # every suite using patch() read as blind. devpulse and hooks
                # were both false positives until this line existed.
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
            # A conftest nobody can parse is a conftest this rule cleared
            # nothing in, and the corpus already publishes what it could not
            # read. Biasing toward FEWER nominations is the safe direction -
            # but silently is how a rule starts reporting clean on a tree it
            # never opened, so it is logged.
            logger.warning(f"[AUDIT-TESTS] {GROUP} could not read {path}: {type(exc).__name__}: {exc}")
            continue
    return parsed


def _file_unit(relpath: str, lineno: int, name: str) -> corpus.TestUnit:
    """A synthetic unit standing for a fixture, so a conftest finding has a row.

    The subject here is a FIXTURE, not a test, and every other nominator in
    this pack addresses a test. Rather than invent a nodeid that pytest would
    never produce, the unit carries the fixture's own name and line so a
    reader lands on the declaration.
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
        # The suite watches the seam at the writer instead of at the target.
        # Nominating here would report a branch that observes its trail as one
        # that cannot - the exact false positive this rule was measured into.
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

    Published because the must_not_fire side is the whole precision argument:
    a rule that fired on all 33 of the fleet's redirecting fixtures would be
    useless, and a reader can only check that by seeing which it let go.
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
