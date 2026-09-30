# =================== AIPass ====================
# Name: fixture_check.py
# Description: the lane's two-sided release check against a banked fixture
# Version: 1.1.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
The lane's own regression, run against a frozen tree with a known answer key.

WHY A LANE THAT JUDGES SUITES NEEDS ONE. Round 1 of the test-quality rounds
graded @canary and the owner's ruling was that it had graded the CHECKER: the
lane reported two nominations on canary and both were false, while six real
defects - including a test that asserts silent data loss as correct behaviour -
went unnamed. A lane with no answer key cannot tell "this suite is clean" from
"this instrument is blind", and those are different documents.

TWO-SIDED, AFTER SEMGREP'S RULE TESTS. Semgrep annotates a rule's own fixture
with `ruleid:` (this line MUST be reported) and `ok:` (this line must NOT be),
and runs the pair as the rule's regression. Both halves are load-bearing and
the second half is the one people skip: a rule tuned only against must-fire
rows reaches 100% by nominating everything. The banked fixture's two false
positives are the reason that half exists here - they were the lane's entire
output on its first real target.

THE THIRD LIST IS A FINDING, NOT AN EXCUSE. `out_of_reach` names every known
defect in the fixture that no mechanism of this lane can currently see, each
with one line saying why, split by `reach`:

  none                        no mechanism of this lane's class can convict it.
                              The headline case: canary's code, its test and
                              its docs all AGREE that a note containing `-h` is
                              discarded, so nothing in the tree disagrees with
                              anything else and there is no contradiction to
                              find. A mutant that makes the code CORRECT is
                              reported as killed, because the blessing test
                              fails against correct code.
  mechanism_not_built         a named, declared mechanism would see it. These
                              are the funded backlog, not the blind spot.
  static_reachable_not_built  a static rule would see it and nobody wrote one.

A ROW MOVING FROM `out_of_reach` TO `must_fire` IS THE LANE IMPROVING, and it
is the only number in these rounds worth reporting as progress. A shrinking
`out_of_reach` list that shrank because somebody deleted rows is the failure
mode this file exists to make visible, which is why the check reports the
three list sizes every run rather than only the verdict.

THIS FILE READS FIXTURES, IT DOES NOT SHIP ONE. The fixture tree and its answer
key are data under `.seedgo/fixtures/<name>/`, outside `apps/` and outside any
`tests/` directory, and the check takes the directory as an argument. A second
ecosystem banks its own fixture beside the first and this code does not move.
"""

import fnmatch
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: The answer key, beside the tree it describes.
EXPECTATIONS_FILE = "expectations.json"

#: Where the frozen subject sits, relative to the fixture directory, when the
#: answer key does not say. The default is the aipass branch layout, and that
#: is not cosmetic: `envcopy.detect_layout()` only returns a repo root for a
#: target at `<root>/src/aipass/<branch>`, and for anything else the copy is
#: NOT importable under the target's own package name. A fixture banked as a
#: bare `tree/` therefore has its suite resolve `aipass.canary` through the
#: venv to the LIVE branch - measured, and it is round 0's own C2 finding
#: ("the probes grade the INSTALLED tree, not the collected one") reproduced
#: inside the instrument that reported it.
DEFAULT_SUBJECT_PATH = "src/aipass/canary"

#: The key an answer key uses to name its subject path itself, so a fixture
#: for a differently-named branch does not need a code change here.
SUBJECT_PATH_KEY = "subject_path"

#: The three lists an answer key must carry. A key missing one of them is
#: refused rather than read as an empty list: a fixture with no `must_not_fire`
#: half silently becomes a one-sided check, which is the exact degradation this
#: file was written to prevent.
REQUIRED_LISTS: tuple = ("must_fire", "must_not_fire", "out_of_reach")

#: Verdicts this check reports.
#:
#: INCOMPLETE is the one that took a second fixture to discover, and it is the
#: reason the vocabulary is four words rather than three. Fixture two's answer
#: key names rows in `pytest.width_coupling`, an EXECUTION group, while
#: `collect()` runs the static tier only. Judged with three words those rows
#: read as `missed` and the check reports BLOCKED - a lane failure that never
#: happened, indistinguishable in the artifact from a rule that really did go
#: blind. The opposite shortcut is worse: dropping unmeasured rows makes the
#: check SHIP on a fraction of its own key and never say which fraction.
#: INCOMPLETE is Law S1 applied to the checker itself - a row that was not
#: measured is `not_measured` with a reason, never a pass and never a fail.
SHIPS = "ships"
BLOCKED = "blocked"
INCOMPLETE = "incomplete"
REFUSED = "refused"


class FixtureError(Exception):
    """A fixture that cannot be read, and therefore cannot judge anything."""


# =============================================================================
# READING THE ANSWER KEY
# =============================================================================


def load_expectations(fixture_dir: Path) -> dict:
    """Read and validate one fixture's answer key.

    Args:
        fixture_dir: Directory holding `tree/` and `expectations.json`.

    Returns:
        The parsed answer key.

    Raises:
        FixtureError: The key is absent, unreadable, or missing a list.
    """
    path = Path(fixture_dir) / EXPECTATIONS_FILE
    try:
        expectations = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureError(f"{path}: the answer key could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"{path}: the answer key is not valid JSON: {exc}") from exc

    missing = [name for name in REQUIRED_LISTS if not isinstance(expectations.get(name), list)]
    if missing:
        raise FixtureError(
            f"{path}: the answer key is missing {', '.join(missing)} - a fixture without all three "
            f"lists is a one-sided check, and a rule tuned against must_fire alone reaches 100% by "
            f"nominating everything"
        )
    return expectations


def fixture_tree(fixture_dir: Path, expectations: Optional[dict] = None) -> Path:
    """The frozen subject tree inside a fixture directory.

    The answer key may name its own subject path, because the path carries
    meaning the checker should not hardcode: a subject at
    `<fixture>/src/aipass/<branch>` is importable under its own package name
    and one at `<fixture>/tree` is not, and that difference decides whether an
    execution group measures the frozen tree or the live branch.

    Args:
        fixture_dir: Directory holding the subject and `expectations.json`.
        expectations: The parsed answer key, when one has been read.

    Returns:
        The path to the frozen subject.

    Raises:
        FixtureError: The subject is absent.
    """
    fixture_dir = Path(fixture_dir)
    declared = str((expectations or {}).get(SUBJECT_PATH_KEY) or DEFAULT_SUBJECT_PATH)
    tree = fixture_dir / declared
    if tree.is_dir():
        return tree

    raise FixtureError(
        f"{tree}: the fixture has no frozen subject to measure - the answer key's "
        f"'{SUBJECT_PATH_KEY}' names '{declared}' and nothing is there"
    )


# =============================================================================
# MATCHING NOMINATIONS AGAINST THE KEY
# =============================================================================


def _row_key(group: str, row: dict) -> Tuple[str, str, str]:
    """The identity a nomination is matched on: group, file and nodeid.

    The LINE is deliberately not part of the identity. A fixture is frozen, so
    a line number would in principle be stable - but a rule that legitimately
    moves its anchor within the same test (from the assert to the decorator,
    say) would then read as a miss, and the answer key would be corrected to
    match the rule rather than the other way round. Line is compared
    separately and reported as drift, never as failure.

    Args:
        group: The published group name the row came from.
        row: One nomination row.

    Returns:
        The tuple this row is matched on.
    """
    return (group, _file_of(row), str(row.get("nodeid", "")))


def _expected_key(entry: dict) -> Tuple[str, str, str]:
    """The identity an answer-key entry expects.

    Args:
        entry: One `must_fire` or `must_not_fire` entry.

    Returns:
        The tuple this entry is matched on.
    """
    return (str(entry.get("group", "")), str(entry.get("file", "")), str(entry.get("nodeid", "")))


#: The list key each kind of group publishes its rows under.
#:
#: `nominations` is what a NOMINATOR emits. `diverged` is what a `measure_only`
#: group emits, and the difference is not cosmetic: `width_coupling` nominates
#: nothing, it subtracts two verdict sets, so calling its output a nomination
#: would misdeclare the group's own kind (Law M1 - static nominates, never
#: convicts - cuts the other way too: a measurement must not be dressed as a
#: nomination). The check reads both and refuses a third.
ROW_KEYS: tuple = ("nominations", "diverged")


def _rows_of(document: dict) -> Optional[List[dict]]:
    """One group's rows, whichever key its kind publishes them under.

    Returns None - not an empty list - for a document carrying neither key
    while claiming to have measured something. That distinction is the whole
    point: `[]` means "this group looked and found nothing" and None means
    "this check cannot read this group's shape", and collapsing the second
    into the first is how an answer key silently stops being asked.

    Args:
        document: One group document.

    Returns:
        The rows, or None if the shape is unrecognised.
    """
    for key in ROW_KEYS:
        rows = document.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if document.get("status") in ("not_applicable", "refused"):
        # A group that says it did not run is readable and simply has no rows.
        return []
    return None


def _file_of(row: dict) -> str:
    """The file a row names, derived from its nodeid when it carries none.

    A `measure_only` row is keyed by nodeid alone, because a verdict diff is a
    property of a NODE rather than of a line in a file. The path in front of
    `::` is that node's file, and deriving it here keeps the answer key written
    the one way for every group.

    Args:
        row: One published row.

    Returns:
        The file path, or "" if the row names neither.
    """
    stated = row.get("file")
    if stated:
        return str(stated)
    nodeid = str(row.get("nodeid", ""))
    return nodeid.split("::", 1)[0] if "::" in nodeid else ""


def _nominated_rows(documents: Dict[str, dict]) -> Dict[Tuple[str, str, str], dict]:
    """Every row the lane produced, keyed for matching.

    Args:
        documents: Group name to group document, as the adapter publishes them.

    Returns:
        Row identity to the row itself.
    """
    rows: Dict[Tuple[str, str, str], dict] = {}
    for group, document in documents.items():
        for row in _rows_of(document) or []:
            rows[_row_key(group, row)] = row
    return rows


def _rows_by_group(documents: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Rows grouped by the group that produced them.

    The keyed form above is enough for an entry naming one nodeid. A FAMILY
    entry - "this test's 30 cases diverge, 20 of them" - is a count over a
    group, and a count cannot be read off a dict keyed by exact identity.

    Args:
        documents: Group name to group document, as the adapter publishes them.

    Returns:
        Group name to its rows, in the order the group reported them.
    """
    return {group: _rows_of(document) or [] for group, document in documents.items()}


def _measured_groups(documents: Dict[str, dict]) -> set:
    """The groups this run actually produced a document for.

    A group absent from the run is not a group that found nothing. `collect()`
    runs the static tier only, so every execution group is absent from a
    default release check, and an answer-key row bound to one was NOT judged.
    Telling those two states apart is the whole of INCOMPLETE.

    Args:
        documents: Group name to group document, as the adapter publishes them.

    Returns:
        The set of group names present in this run AND readable.
    """
    return {group for group, document in documents.items() if _rows_of(document) is not None}


def _entry_scope(entry: dict) -> Optional[str]:
    """The group pattern an entry judges in bulk, or None if it names one row.

    An entry carrying `group_glob` is a SCOPE row: it makes a claim about a
    whole family rather than one nodeid. Fixture two needs it for the shape the
    brief stated as "the 56 cases themselves" - 56 must_not_fire rows written
    out one per nodeid would be an answer key that has to be edited every time
    canary adds a parametrize case, and an answer key edited to match the
    subject is the failure mode this file exists to prevent.

    Args:
        entry: One `must_fire` or `must_not_fire` entry.

    Returns:
        The glob, or None.
    """
    glob = entry.get("group_glob")
    return str(glob) if glob else None


def _matching_groups(glob: str, groups) -> List[str]:
    """Every present group name matching a scope entry's pattern.

    Args:
        glob: An fnmatch pattern such as `pytest.static_*`.
        groups: The group names available to match against.

    Returns:
        The matching names, sorted for a stable report.
    """
    return sorted(name for name in groups if fnmatch.fnmatchcase(name, glob))


def compare(documents: Dict[str, dict], expectations: dict) -> dict:
    """Judge one lane run against one answer key.

    Args:
        documents: Group name to group document, as the adapter publishes them.
        expectations: The parsed answer key.

    Returns:
        The comparison, with a verdict and a per-row account of both halves.
    """
    nominated = _nominated_rows(documents)
    by_group = _rows_by_group(documents)
    measured = _measured_groups(documents)

    fired, missed, unmeasured_fire, drifted = _judge_must_fire(
        nominated, by_group, measured, expectations["must_fire"], documents
    )
    silent, leaked, unmeasured_silent = _judge_must_not_fire(
        nominated, by_group, measured, expectations["must_not_fire"]
    )
    not_measured = unmeasured_fire + unmeasured_silent

    if missed or leaked:
        verdict = BLOCKED
    elif not_measured:
        verdict = INCOMPLETE
    else:
        verdict = SHIPS

    return {
        "verdict": verdict,
        "must_fire": {
            "expected": len(expectations["must_fire"]),
            "fired": fired,
            "missed": missed,
            "not_measured": unmeasured_fire,
        },
        "must_not_fire": {
            "expected": len(expectations["must_not_fire"]),
            "silent": silent,
            "leaked": leaked,
            "not_measured": unmeasured_silent,
        },
        "out_of_reach": _reach_summary(expectations["out_of_reach"]),
        "groups_measured": sorted(measured),
        "line_drift": drifted,
        "why": _verdict_sentence(verdict, missed, leaked, not_measured),
    }


def _truncated(documents: Dict[str, dict], group: str) -> bool:
    """Whether a group published fewer rows than it counted.

    A family entry counts the PUBLISHED rows, and a group that caps its list
    can publish fewer than it found. Counting against a capped list would read
    a cap as a miss and send a reader looking for a regression in a rule that
    worked - so a short count under a cap is `not_measured`, never `missed`.

    Args:
        documents: Group name to group document.
        group: The group to ask.

    Returns:
        True if the group says its published list was cut.
    """
    return bool((documents.get(group) or {}).get("diverged_truncated"))


def _judge_must_fire(
    nominated: Dict[Tuple[str, str, str], dict],
    by_group: Dict[str, List[dict]],
    measured: set,
    entries: List[dict],
    documents: Optional[Dict[str, dict]] = None,
) -> Tuple[List[str], List[dict], List[dict], List[dict]]:
    """Which required nominations arrived, which did not, and which moved.

    Three entry shapes, and the shape is read off the entry rather than
    declared, so an answer key never carries a mode field that can disagree
    with the row beside it:

      * `nodeid`        one named test. Matched exactly.
      * `nodeid_prefix` a FAMILY - "this test's parametrize cases". Counted,
                        and satisfied at `expected_count` OR MORE. A ceiling
                        would be wrong here: fixture two's own width counts are
                        20 at one sample and 5 at another, so pinning equality
                        would pin the sample rather than the defect.
      * neither         the group must produce at least one row for the file.

    Args:
        nominated: Row identity to the row the lane produced.
        by_group: Group name to every row that group produced.
        measured: The groups this run produced a document for.
        entries: The `must_fire` list.

    Returns:
        (ids that fired, entries that did not, entries never judged, line drift).
    """
    fired: List[str] = []
    missed: List[dict] = []
    not_measured: List[dict] = []
    drifted: List[dict] = []

    for entry in entries:
        group = str(entry.get("group", ""))
        if group not in measured:
            not_measured.append(_unjudged(entry, "must_fire"))
            continue

        prefix = entry.get("nodeid_prefix")
        if prefix:
            observed = [row for row in by_group.get(group, []) if str(row.get("nodeid", "")).startswith(str(prefix))]
            wanted = int(entry.get("expected_count") or 1)
            if len(observed) < wanted and _truncated(documents or {}, group):
                row = _unjudged(entry, "must_fire")
                row["reason"] = (
                    f"'{group}' published a truncated row list ({len(observed)} of at least {wanted} "
                    f"wanted matched the family prefix) - a cap is not a miss"
                )
                not_measured.append(row)
                continue
            if len(observed) < wanted:
                missed.append(
                    {
                        "id": entry.get("id", ""),
                        "group": group,
                        "why": entry.get("why", ""),
                        "expected_count": wanted,
                        "observed_count": len(observed),
                    }
                )
                continue
            fired.append(str(entry.get("id", "")))
            continue

        row = nominated.get(_expected_key(entry))
        if row is None:
            missed.append({"id": entry.get("id", ""), "group": group, "why": entry.get("why", "")})
            continue
        fired.append(str(entry.get("id", "")))
        expected_line = entry.get("line")
        if expected_line is not None and row.get("line") != expected_line:
            drifted.append(
                {
                    "id": entry.get("id", ""),
                    "expected_line": expected_line,
                    "reported_line": row.get("line"),
                }
            )

    return fired, missed, not_measured, drifted


def _unjudged(entry: dict, half: str) -> dict:
    """The record for an answer-key row this run never put a question to.

    Args:
        entry: The answer-key entry.
        half: Which half of the key it came from.

    Returns:
        The row, naming the group that was absent so a reader can run it.
    """
    group = _entry_scope(entry) or str(entry.get("group", ""))
    return {
        "id": entry.get("id", ""),
        "group": group,
        "half": half,
        "reason": f"'{group}' produced no document in this run - the row was not judged, in either direction",
    }


def _judge_must_not_fire(
    nominated: Dict[Tuple[str, str, str], dict],
    by_group: Dict[str, List[dict]],
    measured: set,
    entries: List[dict],
) -> Tuple[List[str], List[dict], List[dict]]:
    """Which known-false rows stayed silent, and which came back.

    A SCOPE entry (`group_glob` plus `file`) is the shape fixture two needed:
    "no static group may nominate anything in test_span.py", covering 56 cases
    and every group that exists now or later. Its leak report names the rows
    that broke it, because an id alone would send a reader hunting for which
    of 56 fired.

    A scope entry whose glob matches NO present group is not silent - it is
    unjudged, and it says so. A pattern that matches nothing would otherwise be
    the quietest possible pass, and a typo in the glob would read as a clean
    half of the key forever.

    Args:
        nominated: Row identity to the row the lane produced.
        by_group: Group name to every row that group produced.
        measured: The groups this run produced a document for.
        entries: The `must_not_fire` list.

    Returns:
        (ids that stayed silent, entries that fired anyway, entries never judged).
    """
    silent: List[str] = []
    leaked: List[dict] = []
    not_measured: List[dict] = []

    for entry in entries:
        glob = _entry_scope(entry)
        if glob:
            matched = _matching_groups(glob, measured)
            if not matched:
                not_measured.append(_unjudged(entry, "must_not_fire"))
                continue
            wanted_file = str(entry.get("file", ""))
            offenders = [
                {"group": group, "file": _file_of(row), "nodeid": row.get("nodeid"), "line": row.get("line")}
                for group in matched
                for row in by_group.get(group, [])
                if not wanted_file or _file_of(row) == wanted_file
            ]
            if offenders:
                leaked.append(
                    {
                        "id": entry.get("id", ""),
                        "group": glob,
                        "why_false": entry.get("why_false", ""),
                        "groups_matched": matched,
                        "offenders": offenders,
                    }
                )
                continue
            silent.append(str(entry.get("id", "")))
            continue

        group = str(entry.get("group", ""))
        if group not in measured:
            not_measured.append(_unjudged(entry, "must_not_fire"))
            continue
        if _expected_key(entry) in nominated:
            leaked.append(
                {
                    "id": entry.get("id", ""),
                    "group": group,
                    "why_false": entry.get("why_false", ""),
                }
            )
            continue
        silent.append(str(entry.get("id", "")))

    return silent, leaked, not_measured


def _reach_summary(entries: List[dict]) -> dict:
    """How many known defects the lane cannot see, split by why.

    Published every run so that a SHRINKING list is visible as either progress
    (a row moved to must_fire) or as rows having been quietly dropped.

    Args:
        entries: The `out_of_reach` list.

    Returns:
        The total and the per-reach counts.
    """
    by_reach: Dict[str, int] = {}
    for entry in entries:
        reach = str(entry.get("reach", "unstated"))
        by_reach[reach] = by_reach.get(reach, 0) + 1
    return {"total": len(entries), "by_reach": by_reach, "ids": [str(e.get("id", "")) for e in entries]}


def _verdict_sentence(verdict: str, missed: List[dict], leaked: List[dict], not_measured: List[dict]) -> str:
    """The verdict in words, naming what blocked it.

    Args:
        verdict: The verdict reached.
        missed: Required nominations that did not arrive.
        leaked: Known-false rows that fired anyway.
        not_measured: Rows bound to a group this run never produced.

    Returns:
        One sentence a reader can act on.
    """
    if verdict == SHIPS:
        return "every must_fire row was nominated and every must_not_fire row stayed silent"

    parts = []
    if missed:
        parts.append(f"{len(missed)} must_fire row(s) not nominated: {', '.join(m['id'] for m in missed)}")
    if leaked:
        parts.append(f"{len(leaked)} known-false row(s) nominated: {', '.join(leak['id'] for leak in leaked)}")
    if not_measured:
        absent = sorted({str(row["group"]) for row in not_measured})
        parts.append(
            f"{len(not_measured)} row(s) not judged - this run produced no document for {', '.join(absent)}; "
            f"the check cannot certify a key it only partly asked"
        )
    return "; ".join(parts)


# =============================================================================
# THE CHECK
# =============================================================================


def verify(fixture_dir: Path, documents: Optional[Dict[str, dict]] = None) -> dict:
    """Run the release check for one banked fixture.

    Args:
        fixture_dir: Directory holding `tree/` and `expectations.json`.
        documents: Group documents from a lane run. Collected from the
            fixture's own tree when not supplied.

    Returns:
        The comparison, or a refusal naming what could not be read.
    """
    fixture_dir = Path(fixture_dir)
    try:
        expectations = load_expectations(fixture_dir)
        tree = fixture_tree(fixture_dir, expectations)
    except FixtureError as exc:
        # Not swallowed and not a zero: a fixture that cannot be read has
        # judged nothing, and reporting that as "ships" is the failure this
        # whole lane exists to refuse.
        logger.error(f"[AUDIT-TESTS] fixture check refused: {exc}")
        json_handler.log_operation("fixture_check_refused", {"fixture": str(fixture_dir), "reason": str(exc)})
        return {"verdict": REFUSED, "why": str(exc), "fixture": str(fixture_dir)}

    if documents is None:
        documents = collect(tree)

    result = compare(documents, expectations)
    result["fixture"] = str(fixture_dir)
    result["commit"] = (expectations.get("fixture") or {}).get("commit", "")
    json_handler.log_operation(
        "fixture_check_completed",
        {
            "fixture": fixture_dir.name,
            "verdict": result["verdict"],
            "missed": len(result["must_fire"]["missed"]),
            "leaked": len(result["must_not_fire"]["leaked"]),
            "out_of_reach": result["out_of_reach"]["total"],
        },
    )
    return result


def collect(tree: Path) -> Dict[str, dict]:
    """Run the static tier over a frozen tree and return its group documents.

    The STATIC tier only, and deliberately: the two-sided property is about
    which nominations a rule set produces, and the static nominators only read.
    An execution tier would need an isolated env built around the tree, which
    is the adapter's job rather than this check's - and a release check that
    executed a foreign suite could not be run as cheaply as it needs to be.

    Args:
        tree: The frozen subject tree.

    Returns:
        Group name to group document, namespaced as the adapter publishes them.
    """
    from aipass.seedgo.apps.handlers.tests_pytest_standards import adapter, nominators

    documents = nominators.run(Path(tree))
    return {f"{adapter.ECOSYSTEM}.{name}": document for name, document in documents.items()}
