# =================== AIPass ====================
# Name: capture_never_read_check.py
# Description: nominator - capture-never-read and receipt-only asserts (RETURN-ONLY)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""TAXONOMY rule 8 — the test asked for the output and never looked at it.

Reference: capture_never_read.md
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_capture_never_read"

#: Fixtures that capture output. Requesting one is a declaration of intent.
CAPTURE_FIXTURES: frozenset = frozenset({"capsys", "capfd", "capsysbinary", "capfdbinary"})

READ_METHOD = "readouterr"

#: Callee-name prefixes whose real work is what they EMIT, not what they return.
OUTPUT_PREFIXES: tuple = ("print_", "show_", "report_", "render_", "display_", "emit_")

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 8 - capture-never-read",
    "species": ["RETURN-ONLY"],
    "flags": [
        "a unit requesting capsys/capfd that never calls readouterr()",
        "a unit whose SOLE assertion is `is True` or `== 0` on a print_*/show_*/report_* call",
    ],
    "exempts": [
        "`is True` paired with any other assertion or any assert_* mock call is KEEP - the "
        "species is the SOLE assertion (TAXONOMY known-good rows 9 and 10)",
        "a predicate under test, where the boolean IS the behaviour, is KEEP",
        "a callee whose name does not declare it an output function is never nominated",
    ],
    "fix": "read what you captured: assert on readouterr().out, or assert the emitted text directly.",
    "limits": [
        "a unit that reads the capture inside a helper is not followed across the call",
        "an output function not named with an output prefix is invisible to the second shape",
        "MEASURED UNDER-COUNT: TAXONOMY records 24 RETURN-ONLY units in @backup and this rule "
        "finds 0 there. The difference is real and deliberate - backup's are sole `is True` "
        "assertions on `handle_command`, a ROUTER receipt, and rule 8 as written names only "
        "print_*/show_*/report_* callees. Widening the prefix list to catch routers would also "
        "catch every predicate under test, which TAXONOMY's known-good rows 9 and 10 forbid. "
        "The gap is published rather than closed by guessing",
    ],
    "evidence": (
        "18 in @daemon, 24 in @backup, 4 + 4 across @api; @daemon test_timer_install.py:39 "
        "requests capsys, never reads it, and survived probe P20 (TAXONOMY corpus row 16)"
    ),
}


def _reads_capture(unit: corpus.TestUnit) -> bool:
    """True when the unit calls `readouterr()` anywhere in its body."""
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func).endswith(READ_METHOD):
            return True
        if isinstance(node, ast.Attribute) and node.attr == READ_METHOD:
            return True
    return False


def _receipt_assert(node: ast.Assert) -> str:
    """The output callee this assert takes a receipt from, or "".

    Only callees that name themselves output functions: the rule refuses to guess which print.
    """
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return ""
    if not isinstance(test.ops[0], (ast.Is, ast.Eq)):
        return ""

    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or comparator.value not in (True, 0):
        return ""

    if not isinstance(test.left, ast.Call):
        return ""

    name = corpus.dotted_name(test.left.func)
    tail = name.rsplit(".", 1)[-1]
    return name if tail.startswith(OUTPUT_PREFIXES) else ""


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every unit that captured output it never read, or took a bare receipt."""
    rows: List[dict] = []

    for unit in scanned.units():
        requested = sorted(set(unit.params) & CAPTURE_FIXTURES)
        if requested and not _reads_capture(unit):
            rows.append(
                corpus.nomination(
                    "RETURN-ONLY",
                    unit,
                    f"requests {', '.join(requested)} and never calls {READ_METHOD}() - the unit "
                    f"arranged to see the output and then did not look at it",
                    verdict=corpus.VERDICT_IMPROVE,
                    evidence={"fixtures": requested},
                )
            )
            continue

        row = _receipt_nomination(unit)
        if row:
            rows.append(row)

    return rows


def _receipt_nomination(unit: corpus.TestUnit) -> dict:
    """A receipt-only nomination for a unit, or {} when the assertion is paired.

    Any other assertion or `assert_*` mock call beside the receipt acquits the unit.
    """
    asserts = corpus.asserts_in(unit)
    if len(asserts) != 1:
        return {}
    if corpus.oracle_calls_in(unit):
        return {}

    callee = _receipt_assert(asserts[0])
    if not callee:
        return {}

    return corpus.nomination(
        "RETURN-ONLY",
        unit,
        f"the unit's only assertion takes a receipt from '{callee}', whose real work is what it "
        f"emits - the return value says the call happened, not that it printed anything right",
        verdict=corpus.VERDICT_IMPROVE,
        line=asserts[0].lineno,
        evidence={"callee": callee},
    )
