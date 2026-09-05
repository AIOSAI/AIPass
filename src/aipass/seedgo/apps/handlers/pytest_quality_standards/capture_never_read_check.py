# =================== AIPass ====================
# Name: capture_never_read_check.py
# Description: v5 - did the test read the output it arranged to capture
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Did this test look at the output it asked for?

PORTED FROM THE TAXONOMY NOMINATOR of the same name. Where `no_oracle` asks
whether a unit verifies anything and `assertion_shape` asks whether its
assertions can fail, this one asks a narrower and more embarrassing question:
the unit went to the trouble of arranging to SEE something, and then never
looked.

TWO SHAPES, ONE SPECIES.

CAPTURE-NEVER-READ is the exact static tell, and it is exact because requesting
the fixture is a declaration of intent that costs a line of source. A unit takes
`capsys` or `capfd` in its signature and never calls `readouterr()` anywhere in
its body. There is no reading of that shape which is correct: the fixture does
nothing at all unless it is read, so the parameter is either a leftover from a
deleted assertion or a test that was never finished. One live example survived a
probe that changed what the program prints.

RECEIPT-ONLY is the judgement call. A unit's SOLE assertion is `is True` or
`== 0` on a call to a function that names itself an output function -
`print_summary`, `show_status`, `report_totals`. The whole job of such a function
is what it emits; its return value is a receipt saying the call happened, not
evidence that anything was printed correctly.

SOLE IS THE SPECIES, and this is the direction in which getting it wrong would
do real damage. Nine `assert result is True` lines in one branch's suite are each
paired with a `mock.assert_called_once_with(...)`, and every one of them is
correct. Five `is_ssl_error(x) is True` assertions are correct because there the
boolean IS the behaviour - a predicate under test, not a router's receipt. So a
receipt standing beside ANY other assertion, or beside any oracle-shaped call,
is never flagged, and a callee that does not name itself an output function is
never flagged either.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM.

It does not follow calls. A unit that hands `capsys` to a helper which reads it
is flagged, and that flag is wrong. Following the call would mean resolving the
helper across modules, which is an interpreter, not a reader.

IT DOES NOT COVER `caplog`, DESPITE WHAT THE RULE'S NAME SUGGESTS. `capsys` has
a read method - a call site a reader can find. `caplog` is read by touching
`.records` or `.text`, which is ordinary attribute access and looks exactly like
every other attribute access in the body; the same mechanism cannot decide it.
Naming a fixture this rule cannot judge would turn a precise tell into a guess,
so the fixture set stops where the tell stops.

THE OUTPUT-PREFIX LIST IS A MEASURED UNDER-COUNT. A hand audit recorded 24
receipt-only units in one branch and this rule finds none of them, because that
branch's receipts sit on `handle_command`, a ROUTER. Widening the prefixes to
catch routers would also catch every predicate under test, which is the known-
good family above. The gap is published rather than closed by guessing.

THE RECEIPT CONSTANT SET IS WIDER THAN ITS NAME. `RECEIPT_CONSTANTS` is
`(True, 0)` and membership in Python is decided by equality, so `is False` and
`== 1` read as receipts too. That is stated here rather than discovered later:
the nominator this file ports named only two of the four in its docstring while
its code matched all four. All four are receipts by the same argument - a bare
boolean or exit code from a function whose work is what it prints - so the
behaviour is kept and the description is corrected.

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

STANDARD_NAME = "capture_never_read"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Fixtures that capture output. Requesting one is a declaration of intent -
#: the fixture does nothing whatever unless it is read.
CAPTURE_FIXTURES: frozenset = frozenset({"capsys", "capfd", "capsysbinary", "capfdbinary"})

#: The method that actually reads what was captured.
READ_METHOD: str = "readouterr"

#: Callee-name prefixes whose real work is what they EMIT, not what they return.
OUTPUT_PREFIXES: tuple = ("print_", "show_", "report_", "render_", "display_", "emit_")

#: Right-hand sides that make a comparison a receipt rather than a claim. See
#: the module docstring: `False` and `1` match these by equality, on purpose.
RECEIPT_CONSTANTS: tuple = (True, 0)

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def _requested_fixtures(unit: corpus.TestUnit) -> List[str]:
    """The capture fixtures this unit's signature asks pytest for.

    Positional parameters only, because that is how pytest injects a fixture
    into a function or a method. The pack's corpus keeps the function node
    rather than a pre-extracted parameter list, so the signature is read here
    rather than in the shared reader.

    NO `self` FILTER, AND THAT IS DELIBERATE. A method's first parameter is not
    a fixture, but the intersection below already excludes it - `self` is not a
    capture fixture and never can be. A filter that no input can make matter is
    the kind of careful-looking line that survives review and gets pinned by a
    test which can never go red.

    Args:
        unit: The test unit to read.

    Returns:
        The capture fixture names, sorted, or an empty list.
    """
    return sorted({arg.arg for arg in unit.node.args.args} & CAPTURE_FIXTURES)


def _reads_capture(unit: corpus.TestUnit) -> bool:
    """True when the unit reads its capture anywhere in its body.

    THE ATTRIBUTE ARM IS THE ONE THAT DECIDES, AND THE CALL ARM IS ALL BUT
    INERT. That is measured, not assumed: deleting the call arm leaves every
    behavioural pin in this rule green. `ast.walk` yields a Call before the
    Attribute in its own `func`, so the call arm answers first for the ordinary
    `capsys.readouterr()` - but the walk reaches that Attribute a moment later
    regardless, and the second arm gives the same answer. The call arm's only
    exclusive input is a call through a BARE NAME whose spelling ends in
    `readouterr`, which no pytest suite writes, so nothing here pins it.

    The attribute arm is not redundant in the other direction: it is the only
    thing that sees `read = capsys.readouterr` handed to a helper or passed as
    a callback, where the call site carries a name this reader cannot resolve.
    Without it, a unit that does read its capture is reported as one that never
    did - and that pin is real and red when the arm is blinded.

    The call arm is kept because it states the shape the rule is looking for,
    and deleting it would leave the rule resting entirely on an ordering
    property of `ast.walk` that nothing in this file controls.

    Args:
        unit: The test unit to read.

    Returns:
        True if a read of the capture is visible.
    """
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func).endswith(READ_METHOD):
            return True
        if isinstance(node, ast.Attribute) and node.attr == READ_METHOD:
            return True
    return False


def _receipt_callee(node: ast.Assert) -> str:
    """The output function this assert takes a receipt from, or "".

    Matches a single comparison of a call against one of RECEIPT_CONSTANTS
    with `is` or `==`, where the callee names itself an output function.
    Anything else returns "" - the rule refuses to guess which functions print.

    Args:
        node: One assert statement from the unit.

    Returns:
        The dotted callee name, or "" when this assert is not a receipt.
    """
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return ""
    if not isinstance(test.ops[0], (ast.Is, ast.Eq)):
        return ""

    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or comparator.value not in RECEIPT_CONSTANTS:
        return ""

    if not isinstance(test.left, ast.Call):
        return ""

    name = corpus.dotted_name(test.left.func)
    tail = name.rsplit(".", 1)[-1]
    return name if tail.startswith(OUTPUT_PREFIXES) else ""


def _receipt_finding(unit: corpus.TestUnit) -> Dict:
    """A RECEIPT-ONLY finding for this unit, or {} when the receipt has company.

    The pairing check is the whole correctness of this shape. A second
    assertion beside the receipt, or any oracle-shaped call such as a mock's
    `assert_called_once_with`, means the unit checks behaviour and the receipt
    is incidental.

    Args:
        unit: The test unit to judge.

    Returns:
        A finding row, or {} when nothing is flagged.
    """
    asserts = corpus.asserts_in(unit)
    if len(asserts) != 1:
        return {}
    if corpus.oracle_calls_in(unit):
        return {}

    callee = _receipt_callee(asserts[0])
    if not callee:
        return {}

    return _finding(
        "RECEIPT-ONLY",
        unit,
        asserts[0].lineno,
        f"the unit's only assertion takes a receipt from '{callee}', whose real work is what it emits - "
        f"the return value says the call happened, not that it printed anything right",
    )


def _finding(species: str, unit: corpus.TestUnit, line: int, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it.

    Args:
        species: Which of the two shapes was found.
        unit: The unit the finding belongs to.
        line: The line a reader should open.
        reason: What the reader will see when they get there.

    Returns:
        The finding row.
    """
    return {"nodeid": unit.nodeid, "line": line, "species": species, "reason": reason}


def unit_flags(unit: corpus.TestUnit) -> List[Dict]:
    """Every capture-never-read finding in one unit, with its evidence.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. A unit that captured
    without reading is not additionally judged for a receipt: it has already
    earned a reader's attention, and a second row for the same unit only makes
    a triage list longer.

    Args:
        unit: The test unit to judge.

    Returns:
        Zero or one finding rows.
    """
    requested = _requested_fixtures(unit)
    if requested and not _reads_capture(unit):
        return [
            _finding(
                "CAPTURE-NEVER-READ",
                unit,
                unit.line,
                f"requests {', '.join(requested)} and never calls {READ_METHOD}() - the unit arranged "
                f"to see the output and then did not look at it",
            )
        ]

    receipt = _receipt_finding(unit)
    return [receipt] if receipt else []


def find_unread_captures(scanned: corpus.Corpus) -> List[Dict]:
    """Every capture-never-read finding in the corpus, unit order preserved.

    Args:
        scanned: The parsed corpus.

    Returns:
        Finding rows across every unit.
    """
    rows: List[Dict] = []
    for unit in scanned.units():
        rows.extend(unit_flags(unit))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit can only produce one row
    today, but the scorer must not depend on that: the day a second shape is
    added, counting rows would let one unit be subtracted twice and push the
    flagged total past the unit total, which reports a NEGATIVE score that no
    caller checks for.

    Args:
        rows: Finding rows.

    Returns:
        Distinct nodeids in the order they were first seen.
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
    """Score a project on whether its tests read the output they capture.

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
            "checks": [{"name": "Capture read", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unread_captures(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Capture read",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units read the output they asked for"
                if not units
                else (
                    f"{len(units)}/{total} test units never look at the output they asked for: "
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
