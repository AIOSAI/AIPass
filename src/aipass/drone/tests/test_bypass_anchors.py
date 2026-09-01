# =================== AIPass ====================
# Name: test_bypass_anchors.py
# Description: A line-scoped standards waiver must still point at what it claims
# Version: 1.0.0
# Created: 2026-08-31
# =============================================

"""A waiver that fails OPEN and SILENT is the one failure mode a waiver must not have.

THE SPECIES, @trigger's (round 5), measured fleet-wide by @seedgo (round 6). A
bypass entry scoped to LINE NUMBERS is a pointer into a file, and every edit above
those lines invalidates it silently. @trigger's round-4 sweep added comment lines
and shifted four of their waivers off target; the suppressed violations resurfaced
as unexplained findings in files nobody had touched semantically. Nothing reports
this — a waiver that stops matching simply stops working, and a waiver that starts
matching again suppresses whatever now occupies those lines.

DRONE'S EXPOSURE, measured by @seedgo and reproduced here line by line before
acting on it: nine numbers across two ``cli`` entries, every one adrift (+8 and
+13 in ``apps/drone.py``, +4 in ``apps/modules/router.py``). Those two entries
were DELETED rather than re-derived, because they had also become redundant —
``cli_check`` learned the relayed-stream exemption in round two, so both files
score 100 on their own merits. Verified by A/B here: removing both left ``cli`` at
100 and violations at 0. The fleet rule decides it — if the exemption is
structurally detectable, the checker learns it; a waiver is only for what cannot
be measured.

ONE LINE-SCOPED WAIVER SURVIVES, ``auth.py:27``, and it was on target. It stays
because it is a genuine cannot-be-measured case, and it now carries an ``anchor``:
the text that line must contain. This file is what makes the anchor mean anything.

NOTHING BUT THIS FILE WATCHES THE ANCHOR. @trigger read the two match sites in
seedgo before relying on theirs — ``bypass_handler.py:223`` and
``bypass/utils.py:34`` both match on ``lines`` alone, so the ``anchor`` key is
inert to the checker and this test is the only thing enforcing it. Said out loud
because verifying the audit still scores 100 with the key present (which is what
this branch did first) proves seedgo does not CHOKE on the field, not that it
reads it — an absence of evidence standing in for knowledge.

WHY AN ANCHOR RATHER THAN A RE-DERIVATION: re-deriving fixes today's numbers and
leaves tomorrow's edit free to break them the same way. @seedgo has the general
consequence queued for the checker pack — waivers should anchor to CONTENT, not to
line numbers — and this is that rule enforced locally in the one branch that still
has the exposure. If a future edit moves line 27, this file goes red naming the
entry, instead of the waiver going quiet.
"""

import json
from pathlib import Path

import pytest

# No ``.resolve()`` here, and that is the point rather than an omission. The first
# cut of this line was a bare module-level ``Path(__file__).resolve()`` — the exact
# import-time defect cured across apps/ this morning, written again hours later in
# a new file, and the AST ban only covers apps/ so nothing would have said so.
# Wrapping it in try/except was the second wrong answer (a silent catch seedgo
# caught). ``__file__`` is absolute, so the raw spelling already names the right
# directory; the resolve was only ever normalising symlinks nobody asked about.
BRANCH_ROOT = Path(__file__).parents[1]
BYPASS_FILE = BRANCH_ROOT / ".seedgo" / "bypass.json"


def _line_scoped_entries() -> list[dict]:
    data = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))
    return [entry for entry in data["bypass"] if entry.get("lines")]


class TestLineScopedBypassesAreOnTarget:
    def test_the_collector_finds_every_line_scoped_entry_the_file_holds(self):
        """The instrument's own arming probe, and its first cut was not enough.

        Every assertion below is PARAMETRIZED over ``_line_scoped_entries()``, and
        pytest reports a parametrized test with an empty list as SKIPPED. So a
        collector that returns nothing produces "1 passed, 2 skipped" — a green
        summary line for an instrument that checked nothing. Measured, not feared:
        M20 blinded the collector to ``return []`` and the first version of this
        probe SURVIVED it, because all it asserted was that the raw ``bypass``
        list was non-empty. That is the same species as drone's round-3 finding
        about narrow skips: a check that reports its own defeat as a pass.

        The recount is deliberately INDEPENDENT of the collector — it walks the
        raw JSON rather than calling the function it is judging. Asking the
        accused is how a guard deletes the failures it exists to expose.
        """
        data = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))
        assert data["bypass"], "no bypass entries at all — the file or its schema changed"

        expected = [entry for entry in data["bypass"] if "lines" in entry]
        assert expected, (
            "no line-scoped entries found in the raw file — if the last one was "
            "deleted, delete this file too rather than leaving it green over nothing"
        )
        assert len(_line_scoped_entries()) == len(expected), (
            f"the collector found {len(_line_scoped_entries())} line-scoped entries "
            f"where the file holds {len(expected)} — every parametrized check below "
            "is silently skipping the difference"
        )

    @pytest.mark.parametrize("entry", _line_scoped_entries(), ids=lambda e: f"{e['file']}:{e['standard']}")
    def test_every_line_scoped_entry_declares_an_anchor(self, entry):
        """A waiver that cannot say what it points at cannot be trusted to still point there."""
        assert entry.get("anchor"), (
            f"{entry['file']} [{entry['standard']}] is scoped to lines {entry['lines']} with no anchor — "
            "add the text those lines must contain, so drift is caught instead of silently fixing itself"
        )

    @pytest.mark.parametrize("entry", _line_scoped_entries(), ids=lambda e: f"{e['file']}:{e['standard']}")
    def test_every_line_scoped_entry_still_points_at_its_anchor(self, entry):
        """The pin itself: the numbered line must contain the text the entry claims."""
        source = BRANCH_ROOT / entry["file"]
        assert source.is_file(), f"{entry['file']} named by a bypass entry does not exist"

        lines = source.read_text(encoding="utf-8").splitlines()
        anchor = entry["anchor"]

        for number in entry["lines"]:
            assert 1 <= number <= len(lines), (
                f"{entry['file']} [{entry['standard']}] bypasses line {number}, but the file has {len(lines)} lines"
            )
            actual = lines[number - 1]
            assert anchor in actual, (
                f"{entry['file']}:{number} [{entry['standard']}] has DRIFTED.\n"
                f"  expected to contain: {anchor}\n"
                f"  actual line:         {actual.strip()!r}\n"
                "A line-scoped waiver whose number moves fails open and silent — re-derive it, "
                "or delete it if the checker has since learned the exemption."
            )
