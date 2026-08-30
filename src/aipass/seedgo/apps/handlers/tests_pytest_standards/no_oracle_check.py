# =================== AIPass ====================
# Name: no_oracle_check.py
# Description: nominator - the no-oracle pass (NO-ORACLE)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
TAXONOMY rule 7 — a test that checks nothing at all.

No `assert`. No `pytest.raises`. No `assert_*` on a mock. No `pytest.fail`.
The unit calls production code and then stops. It passes unless the call
raises, which makes it a smoke test wearing a test's name.

THIS RULE IS THE CLEAREST STATEMENT OF LAW M1 IN THE WHOLE CATALOG, and
TAXONOMY marks it explicitly: *MED as a verdict, LOW as a nomination — a bare
trailing call CAN be a working exception oracle; nominate only, let the probe
convict.* A test that calls `parse(bad_input)` with no assert really does fail
when `parse` starts accepting bad input. It is a weak oracle, not an absent
one, and static analysis cannot tell those apart from the outside.

So this file never says a test is worthless. It says: this unit has no
oracle a reader can see, and here is what it calls. The execution tier decides.

WHAT COUNTS AS AN ORACLE IS DELIBERATELY GENEROUS. `corpus.oracle_calls_in()`
accepts `pytest.raises`, `pytest.warns`, `pytest.fail`, `pytest.approx`, and
any method whose name starts with `assert_`. Being generous here is the right
direction to be wrong in: a false nomination costs a reader thirty seconds, a
missed one costs nothing visible at all, and the whole tier is advisory.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_no_oracle"

#: Helper-name prefixes that mean the unit delegates its checking. A unit
#: calling `_assert_document_is_lawful(...)` has an oracle behind one hop, and
#: nominating it would teach branches to inline their helpers.
DELEGATING_PREFIXES: tuple = ("assert", "_assert", "check", "_check", "verify", "_verify", "expect", "_expect")

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 7 - no-oracle pass",
    "species": ["NO-ORACLE"],
    "flags": [
        "a test unit with no assert statement, no pytest.raises/warns/fail, no assert_* mock "
        "call, and no call to a locally defined assertion helper",
    ],
    "exempts": [
        "a unit calling a helper whose name begins with assert/check/verify/expect - the "
        "oracle is one hop away, and flagging it would teach branches to inline helpers",
        "pytest.raises, pytest.warns, pytest.approx, pytest.fail and any assert_* method",
    ],
    "fix": (
        "if the call raising is the property under test, say so with pytest.raises or a "
        "comment; otherwise assert the result."
    ),
    "limits": [
        "a bare trailing call CAN be a working exception oracle - TAXONOMY rates this rule "
        "MED as a verdict and LOW as a nomination, which is why it only nominates (Law M1)",
        "a parametrised unit whose oracle lives in the parameter table is not followed",
    ],
    "evidence": "5 in @api half 2, 1 in @backup, 1 in @daemon, plus every IMPLICIT-ORACLE (TAXONOMY section 5)",
}


def _delegates(unit: corpus.TestUnit) -> str:
    """A checking-helper call this unit makes, or "" when it makes none."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        name = corpus.dotted_name(node.func)
        tail = name.rsplit(".", 1)[-1]
        if tail.startswith(DELEGATING_PREFIXES):
            return name
    return ""


def _production_calls(unit: corpus.TestUnit) -> List[str]:
    """Every call the unit makes, so a nomination can show its work."""
    names = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call):
            name = corpus.dotted_name(node.func)
            if name:
                names.append(name)
    return sorted(set(names))


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every unit with no visible oracle of any kind."""
    rows: List[dict] = []

    for unit in scanned.units():
        if corpus.asserts_in(unit) or corpus.oracle_calls_in(unit):
            continue

        delegate = _delegates(unit)
        if delegate:
            continue

        calls = _production_calls(unit)
        rows.append(
            corpus.nomination(
                "NO-ORACLE",
                unit,
                f"no assert, no pytest.raises, no assert_* call and no assertion helper - the "
                f"unit makes {len(calls)} call(s) and then stops, so it passes unless one of "
                f"them raises",
                verdict=corpus.VERDICT_IMPROVE,
                evidence={"calls": calls[:12], "call_count": len(calls)},
            )
        )

    return rows
