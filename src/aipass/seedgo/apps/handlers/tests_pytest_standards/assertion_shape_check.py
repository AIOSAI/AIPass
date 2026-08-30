# =================== AIPass ====================
# Name: assertion_shape_check.py
# Description: nominator - assertion shape (TAUTOLOGY, TYPE-ONLY, OR-ESCAPE)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
TAXONOMY rule 5 — assertions that cannot fail, and assertions that let go.

Three shapes, all of them assertions a reader counts as coverage and a mutant
walks straight past:

  TAUTOLOGY   `assert True`, `len(x) >= 0`, `x in (True, False)`, `a == a`.
              The claim is true of every possible program. Measured: 16 in
              @daemon, 13 + 11 + 6 across three more branches.
  TYPE-ONLY   the unit's ONLY assertions are `isinstance` checks. The test
              pins the return TYPE and says nothing about the value, so any
              implementation returning the right shape of garbage passes.
  OR-ESCAPE   `assert result == [] or isinstance(result, list)` — the second
              clause is true whenever the first one is, so the assertion has
              an exit. One real example survived a probe that replaced the
              whole diff engine with an echo; all 19 tests in the file passed.

THE PAIRING RULE IS THE WHOLE DIFFICULTY, and getting it wrong in the other
direction is worse than missing a tautology. A type assertion standing BESIDE
a value assertion is correct, common, and must never be flagged — so TYPE-ONLY
is a property of the UNIT, never of a single line. TAXONOMY's known-good table
pins this: the same @api file holds both a MIRROR-EXPECT defect and a
spelled-out constant assertion that killed seven mutants, which is why the
rule has to be per-assertion for tautologies and per-unit for type-only.

A CAPABILITY CLAUSE ACQUITS AN `or`. `assert not hasattr(signal, "SIGKILL") or
SIGKILL not in [...]` is platform-divergent code, not an escape hatch: the
first clause is about the MACHINE, not about the result. In a real OR-ESCAPE
both clauses are about the result.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_assertion_shape"

#: Names that make a clause a MACHINE-capability probe, which acquits an `or`.
CAPABILITY_NAMES: frozenset = frozenset(
    {"hasattr", "sys.platform", "os.name", "platform.system", "sys.version_info", "shutil.which"}
)

#: Comparisons against `len(...)` that are true of every possible list.
VACUOUS_LEN_OPS: tuple = (ast.GtE, ast.Lt)

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 5 - assertion shape",
    "species": ["TAUTOLOGY", "TYPE-ONLY", "OR-ESCAPE"],
    "flags": [
        "assert on a bare literal - assert True, assert 1, assert 'text'",
        "len(x) >= 0 or len(x) < 0 - true of every possible sequence",
        "x in (True, False) - true of every bool",
        "self-comparison: the two sides of the compare are the same expression",
        "a unit whose ONLY assertions are isinstance checks (TYPE-ONLY)",
        "assert A or B where neither clause probes the machine (OR-ESCAPE)",
    ],
    "exempts": [
        "an isinstance assertion PAIRED with a value assertion in the same unit is correct",
        "an `or` whose first clause is a platform-capability probe (hasattr, sys.platform) is "
        "platform-divergent code, not an escape",
    ],
    "fix": "assert the VALUE. If the type matters too, assert both - the pairing is what makes it real.",
    "limits": [
        "a tautology assembled at runtime from a variable is invisible to a static reader",
        "a helper function that asserts on the unit's behalf is not followed across the call",
    ],
    "evidence": "16 in @daemon, 13 in @api half 1, 11 in @backup, 6 in @api half 2 (TAXONOMY section 5 rule 5)",
}


def _is_capability_clause(node: ast.AST) -> bool:
    """True when a clause asks the machine rather than the result."""
    for child in ast.walk(node):
        name = corpus.dotted_name(child)
        if name and (name in CAPABILITY_NAMES or name.rsplit(".", 1)[-1] in CAPABILITY_NAMES):
            return True
    return False


def _is_isinstance_only(node: ast.AST) -> bool:
    """True when an assert's whole test is a single isinstance() call."""
    return isinstance(node, ast.Call) and corpus.dotted_name(node.func) == "isinstance"


def _vacuous_len(test: ast.AST) -> str:
    """`len(x) >= 0` / `len(x) < 0`, or "" when the compare is real."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return ""
    if not isinstance(test.left, ast.Call) or corpus.dotted_name(test.left.func) != "len":
        return ""
    comparator = test.comparators[0]
    if not (isinstance(comparator, ast.Constant) and comparator.value == 0):
        return ""
    if isinstance(test.ops[0], VACUOUS_LEN_OPS):
        return "len(...) compared against 0 in a direction that is true of every sequence"
    return ""


def _bool_membership(test: ast.AST) -> str:
    """`x in (True, False)`, or "" when the membership is meaningful."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.In):
        return ""
    comparator = test.comparators[0]
    if not isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
        return ""
    values = [element.value for element in comparator.elts if isinstance(element, ast.Constant)]
    if len(values) == len(comparator.elts) and set(values) == {True, False}:
        return "membership in (True, False) is true of every bool"
    return ""


def _self_comparison(test: ast.AST) -> str:
    """`a == a`, or "" when the two sides differ."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return ""
    if not isinstance(test.ops[0], (ast.Eq, ast.Is)):
        return ""
    if ast.dump(test.left) == ast.dump(test.comparators[0]):
        return "both sides of the comparison are the same expression"
    return ""


def _literal_assert(test: ast.AST) -> str:
    """`assert True` and friends, or "" when the test is not a bare literal."""
    if isinstance(test, ast.Constant):
        return f"asserts the literal {test.value!r}, which is true of every program"
    return ""


def _tautology_reason(test: ast.AST) -> str:
    """The first tautology shape this assert matches, or "" for none."""
    for detector in (_literal_assert, _vacuous_len, _bool_membership, _self_comparison):
        reason = detector(test)
        if reason:
            return reason
    return ""


def _or_escape(test: ast.AST) -> str:
    """An OR-ESCAPE reason, or "" when the `or` is legitimate."""
    if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.Or):
        return ""
    if any(_is_capability_clause(value) for value in test.values):
        return ""
    return (
        f"{len(test.values)} clauses joined by `or` and none of them probes the machine - "
        f"the assertion passes whenever any single clause holds"
    )


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every tautological, type-only or escaping assertion in the corpus."""
    rows: List[dict] = []

    for unit in scanned.units():
        asserts = corpus.asserts_in(unit)
        if not asserts:
            continue

        rows.extend(_nominate_assertions(unit, asserts))

        if all(_is_isinstance_only(node.test) for node in asserts):
            rows.append(
                corpus.nomination(
                    "TYPE-ONLY",
                    unit,
                    f"every one of this unit's {len(asserts)} assertion(s) is an isinstance check - "
                    f"the test pins the return TYPE and says nothing about the value",
                    verdict=corpus.VERDICT_IMPROVE,
                    line=asserts[0].lineno,
                    evidence={"assertion_count": len(asserts)},
                )
            )

    return rows


def _nominate_assertions(unit: corpus.TestUnit, asserts: List[ast.Assert]) -> List[dict]:
    """Per-assertion nominations for one unit."""
    rows: List[dict] = []

    for node in asserts:
        reason = _tautology_reason(node.test)
        if reason:
            rows.append(corpus.nomination("TAUTOLOGY", unit, reason, line=node.lineno, evidence={"shape": "tautology"}))
            continue

        escape = _or_escape(node.test)
        if escape:
            rows.append(
                corpus.nomination(
                    "OR-ESCAPE",
                    unit,
                    escape,
                    verdict=corpus.VERDICT_IMPROVE,
                    line=node.lineno,
                    evidence={"shape": "or"},
                )
            )

    return rows
