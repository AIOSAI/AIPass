# =================== AIPass ====================
# Name: assertion_shape_check.py
# Description: v5 - can this test's assertions actually fail
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Can this test's assertions actually fail?

THE SECOND V5 CHECK, PORTED FROM THE TAXONOMY NOMINATOR of the same name. Where
`no_oracle` asks whether a test verifies anything at all, this one asks the next
question down: the oracle is present - can it ever say no? An assertion that is
true of every possible program is worse than a missing one, because a reader
counts it as coverage and a mutant walks straight past it.

THREE SHAPES, AND THEY ARE NOT THE SAME KIND OF CLAIM.

TAUTOLOGY is per-assertion and it is the only one this file is confident about.
`assert True`, `len(x) >= 0`, `x in (True, False)`, `a == a` - each is true of
every program that reaches the line, so the assert is a comment with a keyword
in front of it. Nothing about the surrounding test can rescue these.

TYPE-ONLY is a property of the UNIT and never of a single line, and getting that
backwards is the failure mode that would sink the rule. A type assertion
standing BESIDE a value assertion is correct, common, and must never be flagged.
Only when a unit's ENTIRE oracle is `isinstance` does it say something weak: the
return shape is pinned and the value is not, so any implementation returning the
right shape of garbage passes.

OR-ESCAPE is the judgement call, and it is deliberately narrow. `assert result
== [] or isinstance(result, list)` has an exit - the second clause holds whenever
the first does. But `assert not hasattr(signal, "SIGKILL") or SIGKILL not in
handlers` is platform-divergent code, not an escape: the first clause asks about
the MACHINE, not about the result. So a capability probe anywhere in the `or`
acquits it. That acquittal is generous on purpose; a false flag on real
platform-divergent code is the kind of wrong that gets a standard switched off.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM. It does not claim to find every
assertion that cannot fail - a tautology assembled at runtime from a variable is
invisible to a static reader, and so is one hiding behind a helper the unit
calls, because nothing here follows a call. It does not claim a flagged unit is
a bad test; a tautology can sit beside four real assertions in the same body,
and the unit still scores as flagged because the shape is worth a reader's eye.
It does not claim to know whether an `or` was written as an escape or as honest
tolerance of two legal answers. It nominates. A human decides.

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, and the
pack's own corpus reader. That constraint is the reason the pack exists.
"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "assertion_shape"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Names that make a clause a MACHINE-capability probe, which acquits an `or`.
#: Both the dotted spelling and the bare tail are accepted, because a test that
#: did `from shutil import which` writes the same probe with a shorter name.
CAPABILITY_NAMES: frozenset = frozenset(
    {"hasattr", "sys.platform", "os.name", "platform.system", "sys.version_info", "shutil.which"}
)

#: Comparisons against `len(...)` that are true of every possible sequence.
#: `>= 0` always holds and `< 0` never does, so both are decided before the
#: program runs. `> 0`, `== 0` and `<= 0` are real claims and stay out.
VACUOUS_LEN_OPS: tuple = (ast.GtE, ast.Lt)

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


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


def unit_flags(unit: corpus.TestUnit) -> List[Dict]:
    """Every assertion-shape finding in one unit, with the evidence for each.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. Per-assertion findings
    come first in source order, then the unit-level TYPE-ONLY verdict, because
    a reader triaging a unit wants the concrete line before the summary.
    """
    asserts = corpus.asserts_in(unit)
    if not asserts:
        return []

    rows: List[Dict] = []
    for node in asserts:
        reason = _tautology_reason(node.test)
        if reason:
            rows.append(_finding("TAUTOLOGY", unit, node.lineno, reason))
            continue
        escape = _or_escape(node.test)
        if escape:
            rows.append(_finding("OR-ESCAPE", unit, node.lineno, escape))

    if all(_is_isinstance_only(node.test) for node in asserts):
        rows.append(
            _finding(
                "TYPE-ONLY",
                unit,
                asserts[0].lineno,
                f"every one of this unit's {len(asserts)} assertion(s) is an isinstance check - "
                f"the test pins the return TYPE and says nothing about the value",
            )
        )

    return rows


def _finding(species: str, unit: corpus.TestUnit, line: int, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "reason": reason}


def find_shaped_assertions(scanned: corpus.Corpus) -> List[Dict]:
    """Every assertion-shape finding in the corpus, unit order preserved."""
    rows: List[Dict] = []
    for unit in scanned.units():
        rows.extend(unit_flags(unit))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit holding four tautologies is
    one unit a reader has to go and look at; counting the findings would let a
    single sloppy test drive a project's score below zero, and a score that can
    go negative is one nobody believes twice.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its assertions can fail.

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
    # nothing else could catch it. The ordering here is the fix, inherited.
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
            "checks": [{"name": "Assertion shape", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_shaped_assertions(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Assertion shape",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units assert something that can fail"
                if not units
                else (
                    f"{len(units)}/{total} test units carry an assertion that cannot fail: "
                    + ", ".join(units[:MAX_REPORTED])
                    + (f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else "")
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
