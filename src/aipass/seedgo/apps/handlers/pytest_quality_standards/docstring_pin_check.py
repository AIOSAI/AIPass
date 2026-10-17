# =================== AIPass ====================
# Name: docstring_pin_check.py
# Description: v5 - does a test's docstring name a symbol the test actually calls
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Does this test's docstring name anything the test actually touches?

Reference: docstring_pin.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "docstring_pin"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: False reports 100; the measured number still travels in `measured_score` and the report line.
SCORED: bool = False

#: English words match too, harmlessly: no unit calls them.
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

#: The full list lives in the report artifact; the check message stays readable.
MAX_REPORTED: int = 12


def called_names(unit: corpus.TestUnit) -> Set[str]:
    """Every name the unit calls, as the full dotted string AND its tail."""
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
    """Every identifier-shaped token in a docstring, source order preserved."""
    return IDENTIFIER_PATTERN.findall(text)


def anchoring_token(unit: corpus.TestUnit, text: str) -> str:
    """The first docstring token naming something the unit calls, or ""."""
    names = called_names(unit)
    for token in docstring_tokens(text):
        if token in names or token.rsplit(".", 1)[-1] in names:
            return token
    return ""


def unit_flag(unit: corpus.TestUnit) -> Dict:
    """The docstring finding for one unit, or {} when the unit is anchored.

    At most one row per unit by construction, so the score needs no dedup pass.
    """
    text = ast.get_docstring(unit.node)

    # `is None`, not falsiness: an empty docstring is UNANCHORED_DOCSTRING, not NO_DOCSTRING.
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

    `call_count` lets a reader filter the call-less units, unanchorable by construction.
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


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its test docstrings name what they test.

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

    # Dropping the measured number would make the fallback look like a rule that found nothing.
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
