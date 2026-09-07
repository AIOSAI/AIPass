# =================== AIPass ====================
# Name: unentered_assert_check.py
# Description: v5 - assertions that may never execute (VACUOUS-GUARD, VACUOUS-LOOP)
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Does this test's assertion ever actually run?

A test can hold a perfectly good assertion and still prove nothing, because the
assertion sits behind something that may never be entered. Two shapes account
for almost every instance:

  VACUOUS-GUARD  the unit's assertions all sit inside an `if` with no asserting
                 `else`. When the guard is false the test passes having checked
                 nothing at all, and the run says nothing about which happened -
                 a green line either way. One instance in the triage corpus was
                 traced to an assertion that had never once executed.

  VACUOUS-LOOP   the unit's assertions all sit inside a `for` with nothing
                 proving the iterable is non-empty. An empty directory, an empty
                 query result, an empty fixture list - the loop body never runs
                 and the test reports green. One was observed live: a citizen
                 declaration test passing over an empty `projects/` directory.

THE KNOWN-GOOD IS THE HARD PART, AND IT IS EXPLICIT. An `if` that asserts on
BOTH branches is correct platform-divergent code and must pass. Whichever way
the condition falls, something is checked. So a guard is only vacuous when the
`else` is absent or asserts nothing - a two-sided guard is never flagged. Get
this wrong and the checker teaches projects to delete the branch they cannot
run on the box they are sitting at, which is worse code than it started with.

Likewise a unit that asserts anywhere on a path that always runs is never
flagged, however many conditional assertions it also carries. Something in it
ran. This rule is about assertions that may never execute, not about assertions
that are merely conditional.

WHAT THIS DELIBERATELY DOES NOT CLAIM. It does not claim the flagged assertion
IS dead - only that nothing in the file proves it is alive. A guard whose
condition is a constant `True`, or a loop over an iterable that a fixture has
already filled, reads here exactly like one that never fires: the floor lives
one call away and a static reader does not follow it. That is a false flag, it
costs a reader thirty seconds, and the tier is advisory either way. Nor does it
rank the two species - a vacuous loop and a vacuous guard are the same finding
wearing different syntax, and both are reported as one flag per unit.

ONE MORE LIMIT, STATED RATHER THAN HIDDEN. `has_floor` accepts an assert-shaped
floor (`assert items` or `assert len(items) == 3` before the loop) as well as a
literal iterable. From `check_branch` that arm is subsumed: an assert standing
at the top level of the body already exempts the unit one step earlier, so the
literal-iterable arm is the one that fires there. The assert arm is kept because
`has_floor` answers a question about ONE loop for a caller that reads loops
directly, and because the exemption above it is the likelier of the two to be
narrowed later. It is documented here so nobody re-discovers it as a surprise.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "unentered_assert"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Calls that establish an emptiness floor when they appear in an assertion
#: before a loop. `assert len(rows) == 3` proves the loop body runs; without a
#: floor of some kind, an empty iterable turns the whole unit into a silent pass.
FLOOR_CALLS: frozenset = frozenset({"len", "sorted", "list", "tuple", "set"})

#: How many flagged units to name in the result. The full list rides in
#: `violations`; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def _asserts_anywhere_in(statements: List[ast.stmt]) -> bool:
    """True when any statement in the list holds an assert at any depth."""
    return any(isinstance(child, ast.Assert) for statement in statements for child in ast.walk(statement))


def _unconditional_statements(body: List[ast.stmt]) -> List[ast.stmt]:
    """Every statement reached without taking a branch or entering a loop.

    `with` and `try` bodies are included because neither of them decides
    anything: entering a `with` is unconditional, and the happy path of a `try`
    runs until something raises. An `if` body or a `for` body is not, which is
    the entire subject of this rule.
    """
    reached: List[ast.stmt] = []
    for statement in body:
        reached.append(statement)
        if isinstance(statement, (ast.With, ast.AsyncWith, ast.Try)):
            reached.extend(_unconditional_statements(statement.body))
    return reached


def asserts_on_a_path_that_always_runs(unit: corpus.TestUnit) -> bool:
    """True when the unit asserts somewhere that cannot be skipped.

    The public entry point for the exemption - the report lane and the tests
    both ask the question here rather than re-deriving it. A unit answering
    True is never flagged, no matter what else it guards.
    """
    return any(isinstance(statement, ast.Assert) for statement in _unconditional_statements(unit.node.body))


def guarding_if(unit: corpus.TestUnit) -> Optional[ast.If]:
    """The first one-sided `if` holding an assertion, or None.

    One-sided is the whole test: an `if` whose `else` is absent, or whose `else`
    asserts nothing. An `if/else` that checks something on both arms is correct
    divergent code and is skipped here rather than excused later, so no caller
    can accidentally drop the exemption.
    """
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.If):
            continue
        if not _asserts_anywhere_in([node]):
            continue
        if node.orelse and _asserts_anywhere_in(node.orelse):
            continue
        return node
    return None


def has_floor(unit: corpus.TestUnit, loop: ast.For) -> bool:
    """True when something proves this loop's iterable is non-empty.

    A literal collection is a floor by construction. So is an assertion before
    the loop that reads the iterable's size or truth - `assert rows`,
    `assert len(rows) == 3`. Any of them means an empty iterable fails the test
    rather than passing it silently.
    """
    if isinstance(loop.iter, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return True

    for statement in _unconditional_statements(unit.node.body):
        if not isinstance(statement, ast.Assert) or statement.lineno >= loop.lineno:
            continue
        for node in ast.walk(statement.test):
            if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in FLOOR_CALLS:
                return True
        if isinstance(statement.test, (ast.Name, ast.Attribute, ast.Compare)):
            return True

    return False


def vacuous_loop(unit: corpus.TestUnit) -> Optional[ast.For]:
    """The first floorless `for` holding an assertion, or None."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.For):
            continue
        if not _asserts_anywhere_in([node]):
            continue
        if has_floor(unit, node):
            continue
        return node
    return None


def find_unentered(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose assertions all sit behind something that may not run.

    ONE ROW PER UNIT, ALWAYS. A unit carrying both shapes is one finding with
    two symptoms, and counting it twice would push the flagged total past the
    unit total and drive the score below zero on a real branch.
    """
    rows: List[Dict] = []

    for unit in scanned.units():
        if not corpus.asserts_in(unit) or asserts_on_a_path_that_always_runs(unit):
            continue

        guard = guarding_if(unit)
        if guard is not None:
            rows.append(
                {
                    "nodeid": unit.nodeid,
                    "line": unit.line,
                    "species": "VACUOUS-GUARD",
                    "branch_line": guard.lineno,
                    "assert_count": len(corpus.asserts_in(unit)),
                    "detail": (
                        "every assertion in this unit sits under an `if` with no asserting `else` - "
                        "when the guard is false the test passes having checked nothing, and the run "
                        "says nothing about which happened"
                    ),
                }
            )
            continue

        loop = vacuous_loop(unit)
        if loop is not None:
            rows.append(
                {
                    "nodeid": unit.nodeid,
                    "line": unit.line,
                    "species": "VACUOUS-LOOP",
                    "branch_line": loop.lineno,
                    "assert_count": len(corpus.asserts_in(unit)),
                    "detail": (
                        "every assertion in this unit sits inside a `for` with nothing proving the "
                        "iterable is non-empty - an empty iterable makes this a silent pass"
                    ),
                }
            )

    return rows


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its assertions can be reached.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. A project with no tests reports not_applicable rather than a
        number, because zero tests measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering below is the fix; keep it.
    unreadable: List[Dict] = []
    if scanned.unparseable:
        unreadable.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Assertion reachability", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unentered(scanned)
    score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Assertion reachability",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units assert on a path that always runs"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units assert only behind a branch that may never be "
                    "entered: "
                    + ", ".join(f"{r['nodeid']} ({r['species']})" for r in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }
