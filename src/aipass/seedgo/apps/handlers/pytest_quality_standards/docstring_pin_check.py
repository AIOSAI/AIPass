# =================== AIPass ====================
# Name: docstring_pin_check.py
# Description: v5 - does a test's docstring name a symbol the test actually calls
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Does this test's docstring name anything the test actually touches?

THE RULE "EVERY TEST'S DOCSTRING MUST NAME THE DEFECT IT PINS" WAS ACCEPTED ONLY
IN A STRUCTURAL FORM, AND THE REASON IS THE WHOLE CAMPAIGN. The standard this
pack replaces scored tests by searching for pattern substrings in raw source, and
branches complied by writing the patterns into comments - a file of strings with
no code scored 94 percent. A prose version of this rule would be that same defect
one level up: "Pins the contract that the parser rejects malformed input" would
pass a prose matcher while naming nothing, proving nothing, and costing the author
eight seconds. So this file never reads the docstring for MEANING.

WHAT IT ACTUALLY ASKS. Collect the names the unit CALLS. Pull every identifier
and dotted path out of the docstring with a regex. The unit is anchored if any
docstring token matches any called name, on the full dotted string or on the
final segment either way round - a docstring saying `parse` anchors a call to
`mod.parse`, and a docstring saying `mod.parse` anchors a call to `parse`. That
is the entire test. It is satisfiable ONLY by naming a real symbol the unit
really calls, and it is unsatisfiable by any amount of well-formed English.

WHAT IT IS FORBIDDEN TO DO, WRITTEN DOWN SO A LATER EDIT HAS TO ARGUE WITH IT.
It never scores on docstring length, word count, sentence count, or the presence
of words like "pins", "contract", "defect", "regression", "invariant". If a
future maintainer finds themselves matching prose here, they have rebuilt the
thing this pack exists to delete.

TWO SPECIES. NO_DOCSTRING is a unit with no docstring node at all - there is
nothing to anchor. UNANCHORED_DOCSTRING is a unit whose docstring names nothing
it calls; an empty docstring lands here rather than in NO_DOCSTRING, because a
present-but-empty string is a docstring that names nothing, which is exactly what
this species is.

THE FALSE-FLAG FAMILY, NAMED RATHER THAN HIDDEN, AND IT IS WHY `SCORED` IS FALSE.
A unit that makes no call at all can never be anchored: a test whose subject is a
constant (`assert mod.LIMIT == 10`), an operator, an attribute read, or a bare
`with pytest.raises(...)` around a subscript has no `ast.Call` for this rule to
find, so its docstring is unanchorable no matter how well written. Every such
unit is flagged, and that is a known family of false flags, not a discovery. The
row carries `call_count` so a reader can filter them in one pass. The reverse
error exists too: a docstring word that HAPPENS to equal a called name - "raises",
"open", "list", "format", "next" - anchors a unit by accident, so this rule is a
floor and never a ceiling. Those two facts together are why the accepted ruling
was "structural, with an unscored report-line fallback", and why `SCORED` ships
False: the check reports its full finding list and reports 100, so the fleet can
be measured before anything is gated on the measurement.

STDLIB ONLY, like the rest of the pack: `ast`, `re`, `pathlib`, `typing`, and the
pack's own corpus reader. That constraint is the reason the pack exists.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "docstring_pin"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: WHETHER THE MEASURED NUMBER IS THE REPORTED NUMBER. False ships the ruling as
#: accepted: the check still reports every violation and every check line, and
#: reports 100, so the fleet is measured before anything is gated on it. The
#: measured number never disappears - it travels in `measured_score` and in the
#: report line - because a fallback that silently discards its own measurement
#: is how a standard gets adopted without anyone seeing what it would have said.
SCORED: bool = False

#: A Python identifier or dotted path, as it appears in prose. Deliberately the
#: whole vocabulary of the docstring: ordinary English words match this pattern
#: too, and they are harmless precisely because no unit calls them.
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def called_names(unit: corpus.TestUnit) -> Set[str]:
    """Every name the unit calls, as the full dotted string AND its tail.

    BOTH SPELLINGS GO IN THE SET, so the match downstream is a plain membership
    test in one direction. A docstring that says `parse` is talking about the
    same symbol as a call to `mod.parse`; requiring the author to reproduce the
    import path would be scoring on typing, not on knowledge.
    """
    names: Set[str] = set()
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        name = corpus.dotted_name(node.func)
        if name:
            names.add(name)
            names.add(name.rsplit(".", 1)[-1])
    return names


def docstring_tokens(text: str) -> List[str]:
    """Every identifier-shaped token in a docstring, source order preserved.

    Order is kept so the evidence on a row is the FIRST anchoring token a
    reader would find scanning the docstring themselves, not an arbitrary one
    pulled out of a set.
    """
    return IDENTIFIER_PATTERN.findall(text)


def anchoring_token(unit: corpus.TestUnit, text: str) -> str:
    """The first docstring token naming something the unit calls, or "".

    Matched on the full dotted string and on the final segment, from both
    sides: `mod.parse` in prose anchors a call to `parse`, and `parse` in prose
    anchors a call to `mod.parse`.
    """
    names = called_names(unit)
    for token in docstring_tokens(text):
        if token in names or token.rsplit(".", 1)[-1] in names:
            return token
    return ""


def unit_flag(unit: corpus.TestUnit) -> Dict:
    """The docstring finding for one unit, or {} when the unit is anchored.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. AT MOST ONE ROW PER UNIT
    by construction, so the score is per-unit without a dedup pass: a unit
    cannot be both undocumented and unanchored, and a second finding on the
    same unit could push the flagged total past the unit total and drive the
    score negative.
    """
    text = ast.get_docstring(unit.node)

    # `is None`, NOT falsiness. An empty docstring is a docstring node that
    # names nothing, which is UNANCHORED_DOCSTRING - the species that exists
    # for exactly that. Collapsing the two loses the distinction between an
    # author who wrote nothing and an author who wrote something that says
    # nothing, and those are different conversations.
    if text is None:
        return _finding(
            "NO_DOCSTRING",
            unit,
            "the unit has no docstring, so it names no symbol and pins no defect a reader can check",
        )

    token = anchoring_token(unit, text)
    if token:
        return {}

    return _finding(
        "UNANCHORED_DOCSTRING",
        unit,
        "the docstring names no symbol this unit calls - it may describe the defect in prose, but "
        "nothing in it can be checked against the code",
    )


def _finding(species: str, unit: corpus.TestUnit, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it.

    `call_count` rides along because a unit that calls NOTHING is unanchorable
    by construction - the named false-flag family - and a reader triaging a
    list needs to separate those out without reopening every file.
    """
    calls = sorted(corpus.dotted_name(node.func) for node in ast.walk(unit.node) if isinstance(node, ast.Call))
    calls = [name for name in calls if name]
    return {
        "nodeid": unit.nodeid,
        "line": unit.line,
        "species": species,
        "reason": reason,
        "calls": calls[:MAX_REPORTED],
        "call_count": len(calls),
    }


def find_unanchored_docstrings(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose docstring anchors nothing, unit order preserved."""
    return [row for row in (unit_flag(unit) for unit in scanned.units()) if row]


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its test docstrings name what they test.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory, violations, and measured_score. While `SCORED` is False the
        reported score is 100 and the measured number travels in
        `measured_score` and in a check line naming the fallback. A project with
        no tests reports not_applicable rather than a number, because zero tests
        measured is not zero quality found.
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
            "checks": [{"name": "Docstring anchor", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unanchored_docstrings(scanned)
    measured_score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Docstring anchor",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units have a docstring naming a symbol they call"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units have a docstring that names nothing they call: "
                    + ", ".join(row["nodeid"] for row in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]

    # THE FALLBACK REPORTS, IT DOES NOT SCORE - AND IT SAYS SO IN THE OUTPUT.
    # The ruling accepted this rule structurally with an unscored report line,
    # because the false-flag family named in the module docstring has not been
    # measured against the fleet yet. Reporting 100 with the findings still
    # attached is what lets that measurement happen; reporting 100 and dropping
    # the measured number would make the fallback indistinguishable from a rule
    # that found nothing.
    if not SCORED:
        checks.append(
            {
                "name": "Docstring anchor scoring",
                "passed": True,
                "message": (
                    f"REPORTING, NOT SCORING - this rule is structural and unscored while SCORED is "
                    f"False, so the reported score is 100. The measured score is {measured_score} "
                    f"({len(flagged)}/{total} units flagged); the findings above are complete"
                ),
            }
        )

    checks.extend(unreadable)

    return {
        "passed": True,
        "score": measured_score if SCORED else 100,
        "measured_score": measured_score,
        "scored": SCORED,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }
