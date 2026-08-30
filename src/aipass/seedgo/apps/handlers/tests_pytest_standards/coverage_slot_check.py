# =================== AIPass ====================
# Name: coverage_slot_check.py
# Description: nominator - the confession grep (COVERAGE-SLOT)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
TAXONOMY rule 6 — the test that says out loud why it exists.

COVERAGE-SLOT is the only species in the catalog whose detector is a phrase
match, and it is the most precise rule in the set for exactly that reason:
*every hit is a confession*. A test whose docstring says it exists "to satisfy
the checker" or "for coverage" is telling you what it is. Nobody writes that
sentence about a test they believe in.

TAXONOMY's own note: the same grep would have caught them the day they were
written.

THE FALSE POSITIVE IS REAL AND IT IS NAMED. A docstring that merely MENTIONS
coverage while asserting real behaviour is not a confession, and the naive
grep — the one that matches the bare word "coverage" anywhere — flags this
branch's own test suite dozens of times over, because seedgo is a tool whose
subject matter is checkers and standards. So the phrases here are the
*purposive* ones: the ones that state the test's REASON, not its topic. That
narrowing is why this file greps phrases rather than words, and it is the same
correction this campaign has already had to make twice for token matching.

The scan is over DOCSTRINGS, COMMENTS and CLASS NAMES, not over arbitrary
string literals. A test whose data happens to contain "for coverage" is not
confessing anything.
"""

import ast
import re
from typing import List, Tuple

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_coverage_slot"

#: Purposive phrases. Each states a REASON for the test's existence that is
#: not "this behaviour matters". Word-boundary anchored, case-insensitive.
CONFESSION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bfor\s+coverage\b", "says the test exists for coverage"),
    (r"\bcoverage\s+slot\b", "names itself a coverage slot"),
    (r"\bto\s+satisf(?:y|ies)\b", "says the test exists to satisfy something"),
    (r"\bsatisfies\s+the\s+(?:checker|standard|audit|linter)\b", "says it satisfies a checker"),
    (r"\bthe\s+standard\s+requires\b", "cites a standard as the reason it exists"),
    (r"\bseedgo\s+requires\b", "cites the auditor as the reason it exists"),
    (r"\bkeeps?\s+\w+\s+honest\b", "describes itself as keeping something honest rather than testing it"),
    (r"\bplaceholder\s+test\b", "calls itself a placeholder"),
    (r"\bboiler\s?plate\s+test\b", "calls itself boilerplate"),
    (r"\bexists?\s+(?:only\s+)?(?:so|because)\s+the\s+(?:checker|audit|standard)\b", "exists for the auditor"),
)

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 6 - confession grep",
    "species": ["COVERAGE-SLOT"],
    "flags": [
        "a test docstring, comment or class name stating a PURPOSE that is not the behaviour: "
        "'for coverage', 'to satisfy the checker', 'the standard requires', 'keeps X honest'",
    ],
    "exempts": [
        "a docstring that merely MENTIONS coverage while asserting real behaviour - the "
        "patterns are purposive phrases, never bare topic words",
        "string literals in test DATA are not scanned; only docstrings, comments and class names",
    ],
    "fix": (
        "if the behaviour matters, say what it is and assert it. If it does not, the test is "
        "a nomination for review - never for deletion (Law M11)."
    ),
    "limits": [
        "a coverage slot written without confessing is invisible to this rule, by construction",
        "phrase matching cannot tell a test ABOUT confessions from a confession - this file's "
        "own docstring is why the scan excludes non-test modules",
    ],
    "evidence": "small but exact - TAXONOMY records 'every hit is a confession' (section 5 rule 6)",
}

_COMPILED = tuple((re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in CONFESSION_PATTERNS)


def _comments_for(parsed: corpus.TestFile) -> dict:
    """Line number -> comment text, for every `#` comment in the file.

    Read from the raw source because comments are not in the AST at all. A
    string is only treated as a comment when the `#` starts the line's own
    content, so a URL fragment inside a literal is not mistaken for one.
    """
    comments = {}
    for index, line in enumerate(parsed.source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            comments[index] = stripped.lstrip("#").strip()
    return comments


def _confession_in(text: str) -> str:
    """The reason this text is a confession, or "" when it is not one."""
    for pattern, reason in _COMPILED:
        if pattern.search(text):
            return reason
    return ""


def _unit_comments(unit: corpus.TestUnit, comments: dict) -> List[Tuple[int, str]]:
    """Comments lying inside a unit's source range."""
    linenos = [getattr(node, "lineno", 0) for node in ast.walk(unit.node)]
    last = max(linenos or [unit.lineno])
    return [(line, text) for line, text in comments.items() if unit.lineno <= line <= last]


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every test that states a purpose other than the behaviour it tests."""
    rows: List[dict] = []

    for parsed in scanned.files:
        comments = _comments_for(parsed)
        for unit in parsed.units:
            row = _nominate_unit(unit, comments)
            if row:
                rows.append(row)

    return rows


def _nominate_unit(unit: corpus.TestUnit, comments: dict) -> dict:
    """One nomination for a unit, or an empty dict when it confesses nothing.

    A unit is nominated ONCE however many phrases it matches. Three
    confessions in one docstring is one confessing test, and counting it three
    times would inflate the group's own number.
    """
    reason = _confession_in(unit.docstring)
    if reason:
        return corpus.nomination(
            "COVERAGE-SLOT",
            unit,
            f"the docstring {reason}",
            verdict=corpus.VERDICT_IMPROVE,
            evidence={"where": "docstring"},
        )

    reason = _confession_in(unit.class_name)
    if reason:
        return corpus.nomination(
            "COVERAGE-SLOT",
            unit,
            f"the enclosing class name {reason}",
            verdict=corpus.VERDICT_IMPROVE,
            evidence={"where": "class_name", "class": unit.class_name},
        )

    for line, text in sorted(_unit_comments(unit, comments)):
        reason = _confession_in(text)
        if reason:
            return corpus.nomination(
                "COVERAGE-SLOT",
                unit,
                f"a comment inside the test {reason}",
                verdict=corpus.VERDICT_IMPROVE,
                line=line,
                evidence={"where": "comment"},
            )

    return {}
