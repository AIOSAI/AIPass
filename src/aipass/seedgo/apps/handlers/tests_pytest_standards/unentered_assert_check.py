# =================== AIPass ====================
# Name: unentered_assert_check.py
# Description: nominator - assertions that may never execute (VACUOUS-GUARD, VACUOUS-LOOP)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
TAXONOMY rule 9 — the assertion that has never once run.

  VACUOUS-GUARD   the unit's only `assert` sits inside an `if` with no `else`.
                  When the guard is false the test passes having checked
                  nothing, and nothing in the run says so. @daemon's
                  `test_log_operation_empty_dict_not_attached` was traced: the
                  assertion **has never executed**.
  VACUOUS-LOOP    the only `assert` sits inside a `for` with no floor on the
                  iterable being non-empty. An empty `projects/` directory
                  makes @daemon's citizen-declaration test a silent pass, and
                  it was observed live as `478 passed, 3 skipped`.

THE KNOWN-GOOD IS THE HARD PART AND IT IS EXPLICIT: *an `if` that asserts on
BOTH branches is correct platform-divergent code and must pass.* TAXONOMY
pins three separate examples of it. So a guard is only vacuous when the `else`
is absent or asserts nothing — a two-sided guard is never nominated.

For loops, the floor is what makes the test honest: `assert items` before the
loop, `len(x) == 3`, a parametrised iterable, or a literal collection. Any of
them means an empty iterable would fail the test rather than pass it.

TAXONOMY rates this rule MED. It nominates.
"""

import ast
from typing import List, Optional

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_unentered_assert"

#: Calls that establish an emptiness floor when they appear before a loop.
FLOOR_CALLS: frozenset = frozenset({"len", "sorted", "list", "tuple", "set"})

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 9 - unentered-assertion pass",
    "species": ["VACUOUS-GUARD", "VACUOUS-LOOP"],
    "flags": [
        "the unit's only assert sits under an `if` whose `else` is absent or asserts nothing",
        "the unit's only assert sits inside a `for` with no floor proving the iterable is non-empty",
    ],
    "exempts": [
        "an `if` that asserts on BOTH branches is correct platform-divergent code and is never "
        "nominated (TAXONOMY known-good rows 2 and 3)",
        "a loop preceded by an emptiness floor - `assert items`, a len() comparison, or a "
        "literal collection - is never nominated",
        "a unit with any assertion at the top level of its body is never nominated: something in it always runs",
    ],
    "fix": "assert the floor as well as the contents: `assert items` before the loop, or an else branch.",
    "limits": [
        "a floor established inside a fixture is not followed across the call",
        "an `if` whose condition is statically always true still reads as a guard here",
    ],
    "evidence": (
        "4 in @api half 1, 3 in @daemon, 1 in @backup, including an assertion that has never "
        "once executed (TAXONOMY corpus row 14) and a loop observed passing over an empty "
        "directory (corpus row 17)"
    ),
}


def _asserts_directly_in(body: List[ast.stmt]) -> bool:
    """True when a statement list contains an `assert` at its own top level."""
    return any(isinstance(statement, ast.Assert) for statement in body)


def _top_level_assert(unit: corpus.TestUnit) -> bool:
    """True when the unit asserts somewhere that always runs.

    Walks only the statements that are unconditionally reached: the body
    itself, and the bodies of `with` blocks, which do not branch.
    """
    return _asserts_directly_in(_unconditional_statements(unit.node.body))


def _unconditional_statements(body: List[ast.stmt]) -> List[ast.stmt]:
    """Every statement reached without taking a branch or entering a loop."""
    reached: List[ast.stmt] = []
    for statement in body:
        reached.append(statement)
        if isinstance(statement, (ast.With, ast.AsyncWith, ast.Try)):
            reached.extend(_unconditional_statements(statement.body))
    return reached


def _guarding_if(unit: corpus.TestUnit) -> Optional[ast.If]:
    """The first one-sided `if` holding an assertion, or None."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(child, ast.Assert) for child in ast.walk(node)):
            continue
        if node.orelse and any(isinstance(child, ast.Assert) for child in ast.walk(ast.Module(node.orelse, []))):
            continue
        return node
    return None


def _has_floor(unit: corpus.TestUnit, loop: ast.For) -> bool:
    """True when something before the loop proves the iterable is non-empty."""
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


def _vacuous_loop(unit: corpus.TestUnit) -> Optional[ast.For]:
    """The first floorless `for` holding the unit's assertions, or None."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.For):
            continue
        if not any(isinstance(child, ast.Assert) for child in ast.walk(node)):
            continue
        if _has_floor(unit, node):
            continue
        return node
    return None


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every unit whose only assertions sit behind a branch that may not run."""
    rows: List[dict] = []

    for unit in scanned.units():
        if not corpus.asserts_in(unit) or _top_level_assert(unit):
            continue

        guard = _guarding_if(unit)
        if guard is not None:
            rows.append(
                corpus.nomination(
                    "VACUOUS-GUARD",
                    unit,
                    "every assertion in this unit sits under an `if` with no asserting `else` - "
                    "when the guard is false the test passes having checked nothing, and the run "
                    "says nothing about which happened",
                    verdict=corpus.VERDICT_IMPROVE,
                    line=guard.lineno,
                    evidence={"guard_line": guard.lineno},
                )
            )
            continue

        loop = _vacuous_loop(unit)
        if loop is not None:
            rows.append(
                corpus.nomination(
                    "VACUOUS-LOOP",
                    unit,
                    "every assertion in this unit sits inside a `for` with nothing proving the "
                    "iterable is non-empty - an empty iterable makes this a silent pass",
                    verdict=corpus.VERDICT_IMPROVE,
                    line=loop.lineno,
                    evidence={"loop_line": loop.lineno},
                )
            )

    return rows
