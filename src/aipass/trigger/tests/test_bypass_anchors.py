# ===================AIPASS====================
# META DATA HEADER
# Name: test_bypass_anchors.py - line-scoped waivers must still point at their reason
# Date: 2026-08-31
# Version: 1.1.0
# Category: trigger/tests
# =============================================

"""A line-scoped seedgo waiver fails OPEN and SILENT when its line moves.

MEASURED HERE 2026-08-31, round 5. The round-4 dead-cwd sweep added comment
lines to files that carried waivers keyed on line numbers. Every waived line
shifted - the log_watcher_service prints by +1, runaway_handler by -8 where a
dead _find_repo_root copy was deleted - and all four rules silently stopped
matching. The suppressed violations resurfaced and read as fresh breakage in
files nobody had touched semantically. Nothing warned: a rule matching no line
is indistinguishable from a rule doing its job.

Re-deriving fixed that day and left the next edit free to break it the same way,
so the waivers now carry an `anchor` - the literal text the waived line must
contain - and this file reds when a line moves out from under one. seedgo does
NOT read `anchor` (bypass_handler matches on `lines` alone); this test is the
only thing that does, which is why it lives here rather than in the standard.

The structural fix belongs in the checker - waivers anchored on CONTENT, not
line numbers - and is queued with @seedgo pending Patrick's GO. This is the
local reference, built the same way @drone built theirs.
"""

import json
from pathlib import Path

import pytest

BRANCH_ROOT = Path(__file__).resolve().parents[1]
BYPASS_FILE = BRANCH_ROOT / ".seedgo" / "bypass.json"

_ALL_RULES = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))["bypass"]
LINE_SCOPED = [rule for rule in _ALL_RULES if rule.get("lines")]


def _rule_id(rule: dict) -> str:
    return f"{rule['standard']}:{rule['file']}:{','.join(str(n) for n in rule['lines'])}"


def test_there_is_something_to_anchor():
    """Arming probe, and it must probe the list that is actually parametrized.

    pytest reports a parametrize over an EMPTY list as one skipped/deselected
    entry, so a collector that silently finds nothing produces a green summary
    for an instrument that checked nothing (@drone's surviving mutant, relayed
    2026-08-31). Asserting the RAW bypass list is non-empty is not enough - it
    stays full of file-scoped rules while the line-scoped subset goes to zero.
    """
    assert _ALL_RULES, f"no bypass rules parsed at all from {BYPASS_FILE}"

    # Recount from the RAW file rather than from the collector under judgement
    # (@drone's cure, relayed by @seedgo). Asserting LINE_SCOPED is non-empty
    # only catches a collector blinded ENTIRELY; a filter that quietly drops one
    # rule leaves a non-empty list and every remaining anchor still passing, so
    # the dropped waiver goes unwatched with a green board above it.
    raw = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))["bypass"]
    expected = sum(1 for rule in raw if rule.get("lines"))
    assert len(LINE_SCOPED) == expected, (
        f"the collector found {len(LINE_SCOPED)} line-scoped rules but the file "
        f"holds {expected} - some waiver is being skipped, and its anchor is "
        "not being checked by anything"
    )

    assert LINE_SCOPED, (
        "no line-scoped waivers found - if the last one was genuinely retired, "
        "delete this file; if the parse broke, every anchor check below is "
        "vacuously green and the drift this file exists to catch is unwatched"
    )


@pytest.mark.parametrize("rule", LINE_SCOPED, ids=_rule_id)
def test_every_line_scoped_waiver_declares_an_anchor(rule: dict):
    """A waiver with no anchor is a pointer nothing can validate."""
    assert rule.get("anchor"), (
        f"{_rule_id(rule)} is line-scoped with no `anchor` - add the literal text "
        "the waived line must contain, or the rule is unwatchable"
    )


@pytest.mark.parametrize("rule", LINE_SCOPED, ids=_rule_id)
def test_every_waived_line_still_contains_its_anchor(rule: dict):
    """The pin: an edit that moves a waived line reds HERE, not weeks later."""
    target = BRANCH_ROOT / rule["file"]
    assert target.exists(), f"{_rule_id(rule)} waives a file that no longer exists: {target}"

    lines = target.read_text(encoding="utf-8").splitlines()
    anchor = rule["anchor"]

    for number in rule["lines"]:
        assert 1 <= number <= len(lines), f"{_rule_id(rule)} points past the end of {rule['file']} ({len(lines)} lines)"
        actual = lines[number - 1]
        assert anchor in actual, (
            f"{_rule_id(rule)} has come unmoored. Line {number} of {rule['file']} "
            f"no longer contains {anchor!r} - it reads {actual.strip()!r}.\n"
            "The waiver is now suppressing the wrong line and NOT suppressing the "
            "right one, silently. Re-derive it by A/B (remove the rule, re-run the "
            "audit, match it to the one surviving violation) - never hand-adjust, "
            "and delete it outright if the checker has since learned the exemption."
        )


def test_an_anchor_that_moved_is_actually_caught():
    """The negative control: prove the check can fail, on a synthetic rule.

    Without this, a bug in the loop above (a `for` that never iterates, an
    anchor read off the wrong key) leaves every real rule passing for no reason.
    This rule is synthetic on purpose - it cannot be fixed by editing the tree.
    """
    drifted = {
        "file": "apps/log_watcher_service.py",
        "standard": "synthetic",
        "lines": [1],
        "anchor": "this text is not on line 1 of any file in this branch",
    }

    with pytest.raises(AssertionError, match="come unmoored"):
        test_every_waived_line_still_contains_its_anchor(drifted)
