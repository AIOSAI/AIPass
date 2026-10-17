# =================== AIPass ====================
# Name: coverage_slot_check.py
# Description: v5 - the test that says out loud why it exists
# Version: 1.0.1
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Does this test admit, in writing, that it exists for the checker?

Reference: coverage_slot.md
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "coverage_slot"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Purposive phrases (a reason to exist, not a topic), word-boundary anchored.
CONFESSION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bfor\s+coverage\b", "says the test exists for coverage"),
    (r"\bcoverage\s+slot\b", "names itself a coverage slot"),
    # The test must be the subject: a bare "to satisfy" convicts prose about other tests and designs.
    (
        r"\b(?:exists?|added|written|kept|included)\s+(?:only\s+)?to\s+satisf(?:y|ies)\b",
        "says the test exists to satisfy something",
    ),
    (r"\bsatisfies\s+the\s+(?:checker|standard|audit|linter)\b", "says it satisfies a checker"),
    (r"\bthe\s+standard\s+requires\b", "cites a standard as the reason it exists"),
    (r"\bseedgo\s+requires\b", "cites the auditor as the reason it exists"),
    (r"\bkeeps?\s+\w+\s+honest\b", "describes itself as keeping something honest rather than testing it"),
    (r"\bplaceholder\s+test\b", "calls itself a placeholder"),
    (r"\bboiler\s?plate\s+test\b", "calls itself boilerplate"),
    (r"\bexists?\s+(?:only\s+)?(?:so|because)\s+the\s+(?:checker|audit|standard)\b", "exists for the auditor"),
)

#: The `#` must begin the line's own content; trailing comments are not read.
COMMENT_MARKER: str = "#"

#: A phrase between two of these is being named, not said.
QUOTE_MARKS: str = "\"'\u201c\u201d\u2018\u2019"

#: The full list lives in the report artifact; the check message stays readable.
MAX_REPORTED: int = 12

_COMPILED: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in CONFESSION_PATTERNS
)


def _is_quoted(text: str, start: int, end: int) -> bool:
    """True when the span [start, end) sits inside quotation marks on its line.

    Read on the match's own line only: an unbalanced quote earlier must not silence later phrases.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    opens = sum(text[line_start:start].count(mark) for mark in QUOTE_MARKS)
    closes = sum(text[end:line_end].count(mark) for mark in QUOTE_MARKS)
    return opens % 2 == 1 and closes >= 1


def confession_in(text: str) -> str:
    """The reason this text is a confession, or "" when it is not one.

    Every match is considered: an early quoted phrase must not acquit a later unquoted one.
    """
    for pattern, reason in _COMPILED:
        for match in pattern.finditer(text):
            if not _is_quoted(text, match.start(), match.end()):
                return reason
    return ""


def _multiline_string_lines(tree: ast.Module) -> Set[int]:
    """Every line covered by a string literal that spans more than one line.

    A `#` opening a line inside a triple-quoted block is content, not a comment.
    """
    covered: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", 0) or start
        if start and end > start:
            covered.update(range(start, end + 1))
    return covered


def comments_in(root: Path, parsed: corpus.TestFile) -> Optional[Dict[int, str]]:
    """Line number -> comment text for every full-line comment in one file.

    None when the file cannot be re-read: unread comments are not no comments.
    """
    try:
        source = (root / parsed.relpath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    inside_string = _multiline_string_lines(parsed.tree)
    comments: Dict[int, str] = {}
    for index, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(COMMENT_MARKER) and index not in inside_string:
            comments[index] = stripped.lstrip(COMMENT_MARKER).strip()
    return comments


def _unit_span(unit: corpus.TestUnit) -> Tuple[int, int]:
    """The first and last source line a unit's own statements occupy."""
    lines = [unit.line]
    for node in ast.walk(unit.node):
        lines.append(getattr(node, "end_lineno", 0) or getattr(node, "lineno", 0))
    return unit.line, max(lines)


def _unit_comments(unit: corpus.TestUnit, comments: Dict[int, str]) -> List[Tuple[int, str]]:
    """The comments lying inside a unit's source range, in line order."""
    first, last = _unit_span(unit)
    return sorted((line, text) for line, text in comments.items() if first <= line <= last)


def unit_confession(unit: corpus.TestUnit, comments: Dict[int, str]) -> Dict:
    """One confession row for a unit, or {} when it confesses nothing.

    Reported once however many phrases match; the docstring is read before comments.
    """
    reason = confession_in(ast.get_docstring(unit.node) or "")
    if reason:
        return _finding(unit, unit.line, "docstring", f"the docstring {reason}")

    for line, text in _unit_comments(unit, comments):
        reason = confession_in(text)
        if reason:
            return _finding(unit, line, "comment", f"a comment inside the test {reason}")

    return {}


def _finding(unit: corpus.TestUnit, line: int, where: str, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {"nodeid": unit.nodeid, "line": line, "species": "COVERAGE-SLOT", "where": where, "reason": reason}


def find_confessions(scanned: corpus.Corpus, unread: Optional[List[str]] = None) -> List[Dict]:
    """Every unit that states a purpose other than the behaviour it tests."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        comments = comments_in(scanned.root, parsed)
        if comments is None:
            if unread is not None:
                unread.append(parsed.relpath)
            comments = {}
        for unit in parsed.units:
            row = unit_confession(unit, comments)
            if row:
                rows.append(row)
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order."""
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests admit to existing for the checker.

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
            "checks": [{"name": "Coverage confessions", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    unread: List[str] = []
    flagged = find_confessions(scanned, unread)
    if unread:
        unreadable.append(
            {
                "name": "Comments readable",
                "passed": True,
                "message": (
                    f"{len(unread)} test file(s) were judged without their comments: {', '.join(unread[:MAX_REPORTED])}"
                ),
            }
        )
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Coverage confessions",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units state a behaviour rather than a reason to exist"
                if not units
                else (
                    f"{len(units)}/{total} test units say in writing that they exist for the checker: "
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
