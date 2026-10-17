# =================== AIPass ====================
# Name: assertion_shape_check.py
# Description: v5 - can this test's assertions actually fail
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Can this test's assertions actually fail?

Reference: assertion_shape.md
"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "assertion_shape"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Capability probes that acquit an `or`; the bare tail also matches (`from shutil import which`).
CAPABILITY_NAMES: frozenset = frozenset(
    {"hasattr", "sys.platform", "os.name", "platform.system", "sys.version_info", "shutil.which"}
)

#: `len(x) >= 0` always holds and `< 0` never does; `> 0`, `== 0`, `<= 0` are real claims.
VACUOUS_LEN_OPS: tuple = (ast.GtE, ast.Lt)

#: The full list lives in the report artifact; the check message stays readable.
MAX_REPORTED: int = 12


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


def _has_oracle_company(unit: corpus.TestUnit) -> bool:
    """True when the unit holds an oracle that is not an assert statement."""
    for node in ast.walk(unit.node):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                context = item.context_expr
                if isinstance(context, ast.Call) and corpus.dotted_name(context.func) in ("pytest.raises", "raises"):
                    return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert_"):
            return True
    return False


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

    Per-assertion findings come first, then the unit-level TYPE-ONLY verdict.
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

    if all(_is_isinstance_only(node.test) for node in asserts) and not _has_oracle_company(unit):
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

    The score is per unit, not per finding, so it can never go below zero.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its assertions can fail.

    bypass_rules is accepted for the scoring-API contract and unread: shadow mode gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the empty-corpus return: an unparseable-only project must not read as one without tests.
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
