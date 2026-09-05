# =================== AIPass ====================
# Name: seam_test.py
# Description: teaching template - what a seam test proves and how it is written here
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""TEACHING TEMPLATE - THE SEAM TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, and branches stamped them into their trees. Five of those
stamped families now total 1,411 tests across the fleet. When those tests were
measured, only 5 of the 48 test-function names that appear in six or more
branches still shared a shape: they were stamped once, and then every copy
drifted somewhere different. So the fleet carries over a thousand tests that
LOOK like a standard and pin whatever each divergence happened to leave behind.
The same standard scored a project by searching its test files for 99 pattern
substrings, which meant the cheapest way to score well was to write the strings
rather than the tests. This file teaches a SHAPE and shows its reasoning so that
you write your own test, against your own subject, in your own words. If you
catch yourself renaming a variable at the top of a copy of this file, stop -
that is the stamping happening again.

WHAT A SEAM TEST IS FOR
A seam is the join between two units: a caller, and the thing it calls. The
contract at that join is a promise with two halves - the caller promises to
call the collaborator a particular way, and the collaborator promises to answer
a particular way. Almost every integration bug in a system this size lives at a
seam and not inside either unit: the caller formats the entry one way, the
collaborator was changed to expect another, and both units' own tests stay
green because neither one is wrong on its own.

A seam test puts a stand-in on the far side of the join and then asserts the
interaction: what crossed, how often, and what came back. It is the cheapest
test that can catch a two-unit disagreement, because it needs neither unit's
real dependencies.

WHEN TO REACH FOR ONE
- The caller's whole job IS the call: it formats, routes, retries, or fans out.
- The real collaborator is slow, remote, destructive, or nondeterministic.
- You want to pin a refusal path where the seam must NOT be crossed at all.
  "It did not write" is a real property and a mock is the only cheap way to see it.

WHEN NOT TO
- The collaborator is a pure local function that is fast and total. Call it. A
  stand-in buys you nothing and costs you the truth.
- You do not own the seam. Mocking somebody else's internal call shape pins
  THEIR implementation, and it goes red the day they refactor without breaking
  a single promise of yours. Own the seam or do not test it here.
- The thing you want to know is the ANSWER, not the interaction. Then you want
  a contract test - see contract_test.py in this directory.

WHAT IT COSTS
A stand-in agrees with you. That is the whole danger: a Mock has every attribute
you ask it for, so a seam test keeps passing after the real collaborator's
method is renamed or deleted. That is not a hypothetical - the pack's mock_drift
rule exists because deleting one real function left 46 of 46 tests green. Two
habits pay that cost down, and both appear below: inject the collaborator as a
PARAMETER rather than patching a dotted string, and pair the stand-in test with
one small test against the real collaborator so the stand-in's shape cannot
drift away from the thing it stands in for.

THE ONE RULE THIS FILE EXISTS TO TEACH
Never assert the mock's own configuration back at itself. A stand-in you
configured two lines ago is not evidence about your code; it is evidence about
your typing. That shape is shown first, below, and then it is RUN against a
caller that never crosses the seam, to prove it stays green.

HOW THIS FILE IS ORGANISED
The subject under test is defined inline, so the file is self-contained and
honest - it imports pytest and the standard library and nothing else. The
`wrong_*` and `right_*` functions are deliberately NOT named `test_*`, so
neither pytest nor this pack's own reader collects them; they are read, and
they are executed by the collected tests at the bottom, which prove that the
wrong shape passes where the right shape fails.
"""

from unittest.mock import Mock

from typing import Any, Callable, Protocol


class SupportsAppend(Protocol):
    """The far side of the seam, named as a type.

    Typing the collaborator as `object` compiles but says nothing, and a reader
    then cannot tell WHICH method the seam is. A Protocol is the seam written
    down: it names the one call that crosses, so the boundary this file is
    teaching about is visible in the signature rather than only in the mock.
    """

    def append(self, entry: str) -> int:  # pragma: no cover - a shape, not code
        """Write one entry and return whatever the far side gives back."""
        ...


import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================


class Ledger:
    """The far side of the seam: a collaborator with real behaviour."""

    def __init__(self) -> None:
        """Start with an empty entry list."""
        self.entries: list[str] = []

    def append(self, entry: str) -> int:
        """Store one entry and return the new entry count."""
        self.entries.append(entry)
        return len(self.entries)


def record_failure(ledger: SupportsAppend, job_id: str, reason: str) -> int:
    """Write one formatted failure line through the ledger and return its count.

    The ledger arrives as an argument. That is the seam, and passing it in is
    what makes the seam OWNED: a test supplies its own far side without
    reaching into any module by name.

    Args:
        ledger: Anything with an `append(entry) -> int` method.
        job_id: The job the failure belongs to.
        reason: Why the job failed. Blank is refused.

    Returns:
        Whatever the ledger returned for the write.

    Raises:
        ValueError: The reason is blank, so nothing is written.
    """
    if not reason.strip():
        raise ValueError("reason is required")
    return ledger.append(f"{job_id}: {reason}")


def broken_record_failure(ledger: SupportsAppend, job_id: str, reason: str) -> int:
    """A DELIBERATELY BROKEN caller: it never crosses the seam.

    It answers with a plausible number and writes nothing at all. Every seam
    test below is judged by whether it can see this.
    """
    if not reason.strip():
        raise ValueError("reason is required")
    return 1


# =============================================================================
# THE WRONG SHAPE - read this first
# =============================================================================


def wrong_a_asserts_the_mock_back_at_itself(record: Callable[..., Any]) -> None:
    """WRONG. A tautological seam test: it configures a stand-in, then asserts the configuration.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader. It is here to be read, and to be run by a collected test
    below against a caller that never writes anything.
    """
    ledger = Mock()
    ledger.append.return_value = 7
    record(ledger, "job-9", "disk full")

    # THE DEFECT. `ledger.append.return_value` is a value this function set two
    # lines ago. The assertion is `7 == 7` with a stand-in in the middle. It
    # holds when the caller formats the entry wrongly. It holds when the caller
    # calls `append` four times. It holds when the caller never calls `append`
    # at all - which is exactly what `broken_record_failure` does. The stand-in
    # is not the subject; the caller is, and nothing here looks at the caller.
    assert ledger.append.return_value == 7


# =============================================================================
# THE RIGHT SHAPE - and why it is different
# =============================================================================


def right_a_asserts_the_interaction(record: Callable[..., Any]) -> None:
    """RIGHT. Asserts what crossed the seam and what came back through it.

    Not named `test_*` on purpose - see the note on the wrong shape above.
    """
    ledger = Mock()
    ledger.append.return_value = 7
    returned = record(ledger, "job-9", "disk full")

    # ASSERT THE INTERACTION THAT MATTERS. This one line fails three different
    # ways, and every one of them is a defect a caller would feel: never
    # called, called more than once, or called with an entry the far side was
    # not promised. That is the caller's half of the contract, stated once.
    ledger.append.assert_called_once_with("job-9: disk full")

    # AND THE ANSWER CROSSES BACK. Without this line the caller could drop
    # whatever the collaborator handed it and invent its own number, and the
    # interaction assertion above would still be green.
    assert returned == 7


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_record_failure_crosses_the_seam_once_with_the_formatted_entry() -> None:
    """Pins record_failure: one ledger.append call carrying the formatted entry, and its answer returned."""
    ledger = Mock()
    ledger.append.return_value = 3

    assert record_failure(ledger, "job-9", "disk full") == 3
    ledger.append.assert_called_once_with("job-9: disk full")


def test_record_failure_never_writes_when_the_reason_is_blank() -> None:
    """Pins record_failure: a blank reason raises ValueError and the seam is not crossed at all."""
    ledger = Mock()

    with pytest.raises(ValueError):
        record_failure(ledger, "job-9", "   ")

    # THE PROPERTY IS AN ABSENCE. A real ledger would let you look at its rows
    # afterwards, but on a refusal path there is often nothing to look at. The
    # stand-in is what makes "it did not write" observable.
    ledger.append.assert_not_called()


def test_record_failure_writes_through_a_real_ledger_and_returns_its_count() -> None:
    """Pins record_failure against the real Ledger, so the stand-in above cannot drift from the real one."""
    # THIS IS THE PARTNER TEST, AND IT IS NOT OPTIONAL. A stand-in answers
    # every attribute it is asked for, so the two tests above stay green if
    # `Ledger.append` is renamed or deleted. One small run against the real
    # collaborator is what makes that rename go red.
    ledger = Ledger()

    assert record_failure(ledger, "job-9", "disk full") == 1
    assert ledger.entries == ["job-9: disk full"]


def test_wrong_a_asserts_the_mock_back_at_itself_survives_a_caller_that_never_writes() -> None:
    """Proof: wrong_a_asserts_the_mock_back_at_itself stays green against broken_record_failure,
    while right_a_asserts_the_interaction goes red on the very same caller.
    """
    # THE PROOF, RATHER THAN THE CLAIM. `broken_record_failure` never calls the
    # ledger. The tautological seam test is green against it, so it was never
    # evidence about the caller.
    wrong_a_asserts_the_mock_back_at_itself(broken_record_failure)

    # The interaction assertion sees it immediately.
    with pytest.raises(AssertionError):
        right_a_asserts_the_interaction(broken_record_failure)

    # And the right shape still passes against the caller that is correct,
    # which is what stops it from being a test that simply always fails.
    right_a_asserts_the_interaction(record_failure)
