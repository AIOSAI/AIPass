# =================== AIPass ====================
# Name: test_bypass_anchors.py
# Description: A line-scoped standards waiver must still point at what it claims
# Version: 1.0.1
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for .seedgo/bypass.json: each line-scoped waiver still points at its anchor, e.g. apps/plugins/devpulse_ops/auth.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — whether seedgo honours a waiver at all, pinned by @seedgo in tests/test_bypass.py

import json
from pathlib import Path

import pytest

# A line-scoped waiver drifts silently on any edit above it; seedgo matches on ``lines`` alone,
# so this file is the only thing that enforces the ``anchor`` key.

# No module-level ``.resolve()``: it is an import-time cwd/symlink defect, and ``__file__`` is absolute.
BRANCH_ROOT = Path(__file__).parents[1]
BYPASS_FILE = BRANCH_ROOT / ".seedgo" / "bypass.json"


def _line_scoped_entries() -> list[dict]:
    data = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))
    return [entry for entry in data["bypass"] if entry.get("lines")]


class TestLineScopedBypassesAreOnTarget:
    def test_the_collector_finds_every_line_scoped_entry_the_file_holds(self):
        """The instrument's own arming probe: an empty collector would skip, not fail, every check below.

        The recount walks the raw JSON, independent of the collector it judges.
        Mutant: collector returns [] — the parametrized checks skip green; this test fails.
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
