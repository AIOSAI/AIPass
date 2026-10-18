# =================== AIPass ====================
# Name: test_bypass_anchors.py
# Description: Line-scoped seedgo waivers must still point at their reason
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests that .seedgo/bypass.json line waivers still hit their anchor in apps/log_watcher_service.py and kin."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — what a waived line does, in tests/test_runaway_handler.py

import json
from pathlib import Path

import pytest

# A line-scoped waiver fails open and silent when its line moves. seedgo matches on `lines`
# alone and never reads `anchor`, so this test is the only check that does.

BRANCH_ROOT = Path(__file__).resolve().parents[1]
BYPASS_FILE = BRANCH_ROOT / ".seedgo" / "bypass.json"

_ALL_RULES = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))["bypass"]
LINE_SCOPED = [rule for rule in _ALL_RULES if rule.get("lines")]


def _rule_id(rule: dict) -> str:
    return f"{rule['standard']}:{rule['file']}:{','.join(str(n) for n in rule['lines'])}"


def test_there_is_something_to_anchor():
    """Arming probe, and it must probe the list that is actually parametrized."""
    assert len(_ALL_RULES) >= 1, f"no bypass rules parsed at all from {BYPASS_FILE}"

    # Recount from the raw file: an empty parametrize reads green, and a filter that drops
    # one rule leaves a non-empty list with every remaining anchor passing.
    raw = json.loads(BYPASS_FILE.read_text(encoding="utf-8"))["bypass"]
    expected = sum(1 for rule in raw if rule.get("lines"))
    assert len(LINE_SCOPED) == expected, (
        f"the collector found {len(LINE_SCOPED)} line-scoped rules but the file "
        f"holds {expected} - some waiver is being skipped, and its anchor is "
        "not being checked by anything"
    )

    assert len(LINE_SCOPED) >= 1, (
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
    """The negative control: prove the check can fail, on a synthetic rule."""
    drifted = {
        "file": "apps/log_watcher_service.py",
        "standard": "synthetic",
        "lines": [1],
        "anchor": "this text is not on line 1 of any file in this branch",
    }

    with pytest.raises(AssertionError, match="come unmoored"):
        test_every_waived_line_still_contains_its_anchor(drifted)
