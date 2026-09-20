# =================== AIPass ====================
# Name: fixture_check.py
# Description: the lane's two-sided release check against a banked fixture
# Version: 1.0.0
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

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: The answer key, beside the tree it describes.
EXPECTATIONS_FILE = "expectations.json"

#: The frozen subject, relative to the fixture directory.
TREE_DIR = "tree"

#: The three lists an answer key must carry. A key missing one of them is
#: refused rather than read as an empty list: a fixture with no `must_not_fire`
#: half silently becomes a one-sided check, which is the exact degradation this
#: file was written to prevent.
REQUIRED_LISTS: tuple = ("must_fire", "must_not_fire", "out_of_reach")

#: Verdicts this check reports.
SHIPS = "ships"
BLOCKED = "blocked"
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


def fixture_tree(fixture_dir: Path) -> Path:
    """The frozen subject tree inside a fixture directory.

    Args:
        fixture_dir: Directory holding `tree/` and `expectations.json`.

    Returns:
        The path to the frozen tree.

    Raises:
        FixtureError: The tree is absent.
    """
    tree = Path(fixture_dir) / TREE_DIR
    if not tree.is_dir():
        raise FixtureError(f"{tree}: the fixture has no frozen tree to measure")
    return tree


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
    return (group, str(row.get("file", "")), str(row.get("nodeid", "")))


def _expected_key(entry: dict) -> Tuple[str, str, str]:
    """The identity an answer-key entry expects.

    Args:
        entry: One `must_fire` or `must_not_fire` entry.

    Returns:
        The tuple this entry is matched on.
    """
    return (str(entry.get("group", "")), str(entry.get("file", "")), str(entry.get("nodeid", "")))


def _nominated_rows(documents: Dict[str, dict]) -> Dict[Tuple[str, str, str], dict]:
    """Every nomination the lane produced, keyed for matching.

    Args:
        documents: Group name to group document, as the adapter publishes them.

    Returns:
        Row identity to the row itself.
    """
    rows: Dict[Tuple[str, str, str], dict] = {}
    for group, document in documents.items():
        for row in document.get("nominations") or []:
            rows[_row_key(group, row)] = row
    return rows


def compare(documents: Dict[str, dict], expectations: dict) -> dict:
    """Judge one lane run against one answer key.

    Args:
        documents: Group name to group document, as the adapter publishes them.
        expectations: The parsed answer key.

    Returns:
        The comparison, with a verdict and a per-row account of both halves.
    """
    nominated = _nominated_rows(documents)

    fired, missed, drifted = _judge_must_fire(nominated, expectations["must_fire"])
    silent, leaked = _judge_must_not_fire(nominated, expectations["must_not_fire"])

    verdict = SHIPS if not missed and not leaked else BLOCKED
    return {
        "verdict": verdict,
        "must_fire": {"expected": len(expectations["must_fire"]), "fired": fired, "missed": missed},
        "must_not_fire": {"expected": len(expectations["must_not_fire"]), "silent": silent, "leaked": leaked},
        "out_of_reach": _reach_summary(expectations["out_of_reach"]),
        "line_drift": drifted,
        "why": _verdict_sentence(verdict, missed, leaked),
    }


def _judge_must_fire(
    nominated: Dict[Tuple[str, str, str], dict],
    entries: List[dict],
) -> Tuple[List[str], List[dict], List[dict]]:
    """Which required nominations arrived, which did not, and which moved.

    Args:
        nominated: Row identity to the row the lane produced.
        entries: The `must_fire` list.

    Returns:
        (ids that fired, entries that did not, rows whose line moved).
    """
    fired: List[str] = []
    missed: List[dict] = []
    drifted: List[dict] = []

    for entry in entries:
        row = nominated.get(_expected_key(entry))
        if row is None:
            missed.append({"id": entry.get("id", ""), "group": entry.get("group", ""), "why": entry.get("why", "")})
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

    return fired, missed, drifted


def _judge_must_not_fire(
    nominated: Dict[Tuple[str, str, str], dict],
    entries: List[dict],
) -> Tuple[List[str], List[dict]]:
    """Which known-false rows stayed silent, and which came back.

    Args:
        nominated: Row identity to the row the lane produced.
        entries: The `must_not_fire` list.

    Returns:
        (ids that stayed silent, entries that fired anyway).
    """
    silent: List[str] = []
    leaked: List[dict] = []

    for entry in entries:
        if _expected_key(entry) in nominated:
            leaked.append(
                {
                    "id": entry.get("id", ""),
                    "group": entry.get("group", ""),
                    "why_false": entry.get("why_false", ""),
                }
            )
            continue
        silent.append(str(entry.get("id", "")))

    return silent, leaked


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


def _verdict_sentence(verdict: str, missed: List[dict], leaked: List[dict]) -> str:
    """The verdict in words, naming what blocked it.

    Args:
        verdict: The verdict reached.
        missed: Required nominations that did not arrive.
        leaked: Known-false rows that fired anyway.

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
        tree = fixture_tree(fixture_dir)
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
