# =================== AIPass ====================
# Name: coverage_slot_check.py
# Description: v5 - the test that says out loud why it exists
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Does this test admit, in writing, that it exists for the checker?

THE ONLY RULE IN THE PACK WHOSE DETECTOR IS A PHRASE MATCH, and it is the most
precise one for exactly that reason: every hit is a confession. A test whose
docstring says it is there "for coverage" or "to satisfy the checker" is telling
you what it is. Nobody writes that sentence about a test they believe in. The
original nominator's own note still holds - the same grep would have caught these
the day they were written.

THE FALSE POSITIVE IS REAL AND IT IS NAMED. A docstring that merely MENTIONS
coverage while asserting real behaviour is not a confession, and the naive grep -
the one that matches the bare word "coverage" anywhere - flags a suite about
checkers dozens of times over. So the phrases here are the PURPOSIVE ones: they
state the test's REASON, not its topic. "the coverage report lists every file" is
a subject. "added for coverage" is a confession. That narrowing is the whole
difference between a rule people read and a rule people switch off.

WHERE IT LOOKS. Docstrings and full-line comments inside the unit. Not arbitrary
string literals: a test whose DATA happens to contain "for coverage" is not
confessing anything, it is testing a string.

THE CLASS-NAME ARM OF THE ORIGINAL COULD NEVER FIRE, AND IT IS GONE RATHER THAN
CARRIED. The nominator ran the same phrase list over `unit.class_name`. Every one
of the ten patterns requires at least one whitespace character between its words -
`for\\s+coverage`, `placeholder\\s+test`, `boiler\\s?plate\\s+test` - and a Python
class name is an identifier, which cannot contain whitespace. The arm matched
nothing, in any corpus, ever. Reviving it by splitting CamelCase into words was
considered and REFUSED: `TestCoverageSlotDetection` would then read as a
confession, when it is a class ABOUT confessions, and the precision claim that
justifies phrase matching would be the first thing to die. So the arm is deleted,
the reason is written down, and a pin below holds the decision - a class name that
looks like a confession must not flag on its name alone.

THE COMMENT READER IS NOT THE ORIGINAL'S, AND THE DIFFERENCE IS A DEFECT IT HAD.
Comments are not in the AST at all, so the file is read a second time as text and
scanned for lines whose own content starts with `#`. The original stopped there,
which means every line inside a triple-quoted block starting with `#` - a fixture
holding a sample config, a snippet of another file - was read as a comment and
could confess on that test's behalf. Here the multi-line string spans are taken
from the parsed tree and those lines are excluded, so only real comments are read.
The pack's corpus keeps the tree and not the source, so the second read is the
price; a file that has moved or gone unreadable between the parse and the read
yields no comments rather than an exception, which biases this rule toward FEWER
flags, which is the safe direction for a rule that accuses.

WHAT IT DELIBERATELY DOES NOT CLAIM. It does not claim a flagged test is
worthless, and it never recommends deletion - a confessing test can still be the
last thing standing between a rename and a broken release. It does not claim to
find coverage slots: a slot written without confessing is invisible here by
construction, and that is not a gap to be closed with heuristics, it is the
boundary that keeps every hit meaning something. It cannot tell a test ABOUT
confessions from a confession, which is why it reads only test files and only the
prose a test writes about itself.

ITS OTHER LIMITS, all toward FEWER flags. Every phrase is anchored on both ends,
which is what keeps "the report groups coverage slots by file" out of the results -
and the same anchor means a confession written in the PLURAL ("these are coverage
slots") is missed. That is the trade the precision claim is bought with, and it is
named here rather than left for a reader to discover as a hole. A unit's comment
range ends at its last STATEMENT, so a comment sitting after the final line of the body is attributed to
nobody - and neither is a comment between two units, which is the point: a
module-level note is not a test's confession. A trailing comment on a line of code
is not read either, because the line does not start with `#`. One unit yields at
most one row however many phrases it matches: three confessions in one docstring
is one confessing test, and counting it three times would inflate the number the
rule exists to report.

STDLIB ONLY - `ast`, `pathlib`, `re`, `typing`, and the pack's own corpus reader.
That constraint is the reason the pack exists and can be lifted onto any project.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "coverage_slot"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Purposive phrases. Each states a REASON for the test's existence that is not
#: "this behaviour matters". Word-boundary anchored so "before coverage runs"
#: is prose and "for coverage" is a confession; case-insensitive because a
#: sentence that starts with one is still one.
CONFESSION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bfor\s+coverage\b", "says the test exists for coverage"),
    (r"\bcoverage\s+slot\b", "names itself a coverage slot"),
    # THE TEST MUST BE THE SUBJECT. A bare "to satisfy" is a verb phrase, not a
    # purposive claim, and it convicted five units fleet-wide on 2026-09-07 of
    # which NONE was a confession: "a test that fired real events to satisfy the
    # standard would pollute the bus" (a hypothetical about another test), "the
    # only way to satisfy the old form" (a rejected design), "started editing
    # the measurement to satisfy itself" (a guard that was not written),
    # "Cheap to satisfy" (@api), "editing text to satisfy a cap would be
    # authoring memories" (@memory). Requiring a self-referential verb acquits
    # all five and still reads every confession form the rule doc names.
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

#: What starts a comment line. Named so the reader's one contract - the `#` must
#: begin the line's own content - is spelled once.
COMMENT_MARKER: str = "#"

#: Every character that opens or closes a quotation in prose, straight and
#: typographic. A phrase between two of these is being NAMED, not said.
QUOTE_MARKS: str = "\"'\u201c\u201d\u2018\u2019"

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12

_COMPILED: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in CONFESSION_PATTERNS
)


# =============================================================================
# ANALYSIS
# =============================================================================


def _is_quoted(text: str, start: int, end: int) -> bool:
    """True when the span [start, end) sits inside quotation marks on its line.

    THE SAME EXCLUSION THE RULE ALREADY MAKES FOR DATA, one layer up. A test
    whose *data* contains "for coverage" is testing a string, and the rule has
    never flagged it. A docstring that writes the phrase IN QUOTES is doing the
    same thing in prose: it is naming the phrase, not confessing.

    Measured across the fleet on 2026-09-07 before this existed: 11 units
    matched a pattern, and exactly 5 of them had the match inside quotes - all
    five in seedgo's own `TestCoverageSlotDetection`, the tests OF this
    detector, whose docstrings necessarily quote the phrases it hunts. No other
    branch moved by a single unit. That is the whole population this narrowing
    touches, which is why it is a scope fix rather than the intent-guessing the
    rule doc refuses.

    The cost, stated rather than hidden: a genuine confession written inside
    quotation marks for emphasis is now missed. That is the same direction the
    data exclusion already errs in, and it is the safer one - a rule whose own
    test suite reads as a room full of confessions is a rule nobody trusts.

    Read on the match's OWN LINE only: an unbalanced quote earlier in a
    paragraph must not silence every phrase after it.

    Args:
        text: The prose the match was found in.
        start: Match start offset.
        end: Match end offset.

    Returns:
        True when a quotation opens before the span on its line and closes after it.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end == -1 else line_end
    opens = sum(text[line_start:start].count(mark) for mark in QUOTE_MARKS)
    closes = sum(text[end:line_end].count(mark) for mark in QUOTE_MARKS)
    return opens % 2 == 1 and closes >= 1


def confession_in(text: str) -> str:
    """The reason this text is a confession, or "" when it is not one.

    EVERY match is considered, not just the first: a phrase quoted early in a
    docstring must not acquit an unquoted confession later in the same one.

    Args:
        text: Any prose - a docstring, a comment.

    Returns:
        The reason for the first UNQUOTED match, or "".
    """
    for pattern, reason in _COMPILED:
        for match in pattern.finditer(text):
            if not _is_quoted(text, match.start(), match.end()):
                return reason
    return ""


def _multiline_string_lines(tree: ast.Module) -> Set[int]:
    """Every line covered by a string literal that spans more than one line.

    A `#` opening a line inside a triple-quoted block is CONTENT, not a comment.
    The raw-text reader cannot know that; the tree can, so it is asked.
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


def comments_in(root: Path, parsed: corpus.TestFile) -> Dict[int, str]:
    """Line number -> comment text for every full-line comment in one file.

    Args:
        root: The project root the corpus was built from.
        parsed: One parsed test file.

    Returns:
        A mapping, empty when the file could not be read a second time.
    """
    try:
        source = (root / parsed.relpath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
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

    A unit is reported ONCE however many phrases it matches, and the docstring is
    read before the comments because that is where a reader looks first.

    Args:
        unit: One test unit.
        comments: The whole file's comments, by line.

    Returns:
        A finding row, or an empty dict.
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


def find_confessions(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit that states a purpose other than the behaviour it tests."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        comments = comments_in(scanned.root, parsed)
        for unit in parsed.units:
            row = unit_confession(unit, comments)
            if row:
                rows.append(row)
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. `unit_confession` already returns at
    most one row per unit, so today this changes nothing - it is here because the
    day someone reports every matching phrase instead of the first, the score is
    the thing that breaks, and a score that can go negative is one nobody
    believes twice.
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
    """Score a project on whether its tests admit to existing for the checker.

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
            "checks": [{"name": "Coverage confessions", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_confessions(scanned)
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
