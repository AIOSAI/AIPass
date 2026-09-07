# =================== AIPass ====================
# Name: failure_path_test.py
# Description: teaching template - proving that code fails correctly, not merely that it fails
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""TEACHING TEMPLATE - THE FAILURE-PATH TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, branches stamped them, and five of those stamped families
now total 1,411 tests across the fleet. Measured, only 5 of the 48 test-function
names appearing in six or more branches still shared a shape: stamped once, then
every copy drifted somewhere different. The same standard scored a project by
searching its test files for 99 pattern substrings, so the cheapest way to score
well was to write the strings rather than the tests. This file teaches a SHAPE
and shows its reasoning, so that you write your own test against your own
subject. If you catch yourself renaming a variable at the top of a copy of this
file, stop - that is the stamping happening again.

WHAT A FAILURE-PATH TEST IS FOR
This is the API-key-missing species. The subject is asked to do something it
cannot legitimately do, and the test proves it refuses CORRECTLY. Correctly has
three parts, and a test that checks fewer than two of them is usually not worth
its line count:

  1. the TYPE of the error, because a caller writes `except` against a type;
  2. something checkable in the MESSAGE, because a human reads it at 3am and
     has to learn which knob to turn;
  3. the STATE left behind - the audit line written, the file not created, the
     connection closed, the counter not advanced.

Part 3 is the one that gets skipped, and it is the one that catches real bugs.
Anybody can raise. Raising without leaving a half-written file behind is the
hard part, and it is the part a caller actually depends on.

WHEN TO REACH FOR ONE
- The refusal is a documented behaviour: a caller catches it and does something.
- The refusal has to clean up, roll back, or leave a trace.
- The error message is the only user interface a failure has, and you want it
  to keep naming the thing the reader must fix.

WHEN NOT TO
- The failure is Python's own and you did not write it. Pinning that a function
  raises TypeError when handed an int pins the interpreter, not your code.
- You have already pinned the same refusal from another angle. One meaningful
  failure test per refusal path is the target, not per input that reaches it.
- Nothing catches it and nothing cleans up. Then the honest test is the happy
  path, and the crash is documentation.

WHAT IT COSTS
A failure-path test that asserts a message can go red when somebody improves the
wording. That is a real cost and it is paid on purpose: assert a SUBSTRING that
carries the information - the variable name, the path, the flag - and not the
whole sentence. Then rewording is free and dropping the useful part is not.

The larger cost is the one this file spends its second half on: failure tests
breed. They are easy to write, so they arrive twenty at a time, one per spelling
of an empty string, all walking the same three lines of code. This pack prefers
ONE meaningful failure over twenty input permutations. A row earns its place
when it reaches a DIFFERENT path, never when it merely looks different.

THE PARTNER RULE
A failure test cannot stand alone. A subject that raises unconditionally passes
every failure test ever written about it. Every refusal pinned here is paired
with one small success test, and the pairing is the point.

HOW THIS FILE IS ORGANISED
The subject is defined inline, so the file is self-contained - it imports pytest
and the standard library and nothing else. The `wrong_*` and `right_*` functions
are deliberately NOT named `test_*`, so neither pytest nor this pack's own
reader collects them; they are read, and they are executed by the collected
tests at the bottom against deliberately broken subjects, which is what proves
the wrong shapes stay green where the right shape goes red.
"""

from typing import Any, Callable

import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================


class MissingCredential(Exception):
    """Raised when a required credential is absent. Callers catch THIS, not Exception."""


class SloppyRefusal(Exception):
    """The error a deliberately broken subject raises instead of MissingCredential."""


def open_session(env: dict, audit: list) -> dict:
    """Open a session, or refuse by name and leave a trace of the refusal.

    Args:
        env: The environment mapping to read the credential from.
        audit: A list the call appends one line to, whichever way it goes.

    Returns:
        The opened session.

    Raises:
        MissingCredential: `SERVICE_API_KEY` is absent or blank. The audit line
            is written BEFORE the raise, which is the state half of the
            contract and the half a lazy test never sees.
    """
    key = env.get("SERVICE_API_KEY", "").strip()
    if not key:
        audit.append("refused: SERVICE_API_KEY missing")
        raise MissingCredential("SERVICE_API_KEY is not set - export it or pass --key")
    audit.append("opened")
    return {"key": key, "state": "open"}


def anonymous_open_session(env: dict, audit: list) -> dict:
    """A DELIBERATELY BROKEN subject: it refuses, but anonymously.

    Wrong exception type, a message naming nothing, and no audit line. A caller
    cannot catch it by type and a human cannot act on it.
    """
    if not env.get("SERVICE_API_KEY", "").strip():
        raise SloppyRefusal("error")
    return {"key": env["SERVICE_API_KEY"], "state": "open"}


def forgetful_open_session(env: dict, audit: list) -> dict:
    """A DELIBERATELY BROKEN subject: right type, right message, no audit line.

    This is the realistic regression - somebody moved the raise above the
    append during a refactor. Only an assertion about the state left behind
    can see it.
    """
    key = env.get("SERVICE_API_KEY", "").strip()
    if not key:
        raise MissingCredential("SERVICE_API_KEY is not set - export it or pass --key")
    audit.append("opened")
    return {"key": key, "state": "open"}


# =============================================================================
# THE WRONG SHAPES - read these first
# =============================================================================


def wrong_a_asserts_only_that_it_raised(open_fn: Callable[..., Any]) -> None:
    """WRONG. The weakest failure test that still looks like one: it raised something.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader.
    """
    # THE DEFECT. `Exception` is the base of everything the subject can throw,
    # including the ones that mean the code is broken rather than careful: an
    # AttributeError from a typo, a KeyError from a missing default, a
    # ValueError from a half-finished rewrite. All of them are green here. The
    # test reports that SOMETHING went wrong, which the traceback already said.
    with pytest.raises(Exception):
        open_fn({}, [])


def wrong_b_walks_an_input_matrix(open_fn: Callable[..., Any]) -> None:
    """WRONG for a different reason: seven inputs, one code path, one property.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE DEFECT. In a real file this arrives as a parametrize table with twenty
    # rows, and it looks like diligence. Every row here reaches the same
    # `if not key:` branch, so nineteen of them prove exactly what the first one
    # proved. What they buy: twenty ids in the report and twenty places to edit
    # the day the refusal grows a second property. What they miss is below -
    # breadth of input is not depth of oracle, and this table cannot see a
    # subject that stopped writing its audit line.
    for value in ("", " ", "\t", "\n", "  \t ", "\r\n", "      "):
        with pytest.raises(MissingCredential):
            open_fn({"SERVICE_API_KEY": value}, [])


# =============================================================================
# THE RIGHT SHAPE - and why it is different
# =============================================================================


def right_a_pins_type_message_and_state(open_fn: Callable[..., Any]) -> None:
    """RIGHT. One input, three claims: the error type, the useful part of the message, the state left behind.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    audit: list = []

    with pytest.raises(MissingCredential) as caught:
        open_fn({}, audit)

    # THE MESSAGE, BY THE PART THAT CARRIES INFORMATION. The variable name is
    # what the reader has to act on, so that is what is pinned. Pinning the
    # whole sentence would make every rewording a red suite for no gain.
    assert "SERVICE_API_KEY" in str(caught.value)

    # THE STATE LEFT BEHIND. This is the claim the two wrong shapes above never
    # make, and it is the one that catches a real refactor.
    assert audit == ["refused: SERVICE_API_KEY missing"]


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_open_session_refuses_a_missing_key_by_type_message_and_audit_line() -> None:
    """Pins open_session: MissingCredential, a message naming SERVICE_API_KEY, and the audit line it leaves."""
    audit: list = []

    with pytest.raises(MissingCredential) as caught:
        open_session({}, audit)

    assert "SERVICE_API_KEY" in str(caught.value)
    assert audit == ["refused: SERVICE_API_KEY missing"]


def test_open_session_opens_and_logs_when_the_key_is_present() -> None:
    """Pins open_session's success path - the partner without which a subject that always raises stays green."""
    audit: list = []

    assert open_session({"SERVICE_API_KEY": "sk-live-1"}, audit) == {"key": "sk-live-1", "state": "open"}
    assert audit == ["opened"]


def test_wrong_a_asserts_only_that_it_raised_accepts_an_anonymous_refusal() -> None:
    """Proof: wrong_a_asserts_only_that_it_raised accepts anonymous_open_session."""
    # The subject raises the wrong type with a message naming nothing. The
    # bare-Exception test is green against it.
    wrong_a_asserts_only_that_it_raised(anonymous_open_session)

    with pytest.raises(SloppyRefusal):
        # The right shape does not quietly pass here either. pytest.raises
        # re-raises the exception it did not expect, so the run names
        # SloppyRefusal and the reader learns WHAT went wrong rather than
        # only that something did.
        right_a_pins_type_message_and_state(anonymous_open_session)


def test_wrong_b_walks_an_input_matrix_and_misses_what_one_claim_catches() -> None:
    """Proof: wrong_b_walks_an_input_matrix stays green against forgetful_open_session,
    while right_a_pins_type_message_and_state goes red on the very same subject.
    """
    # Seven inputs, all green, against a subject whose audit line is gone.
    wrong_b_walks_an_input_matrix(forgetful_open_session)

    # One input and one more claim, and the regression is named.
    with pytest.raises(AssertionError):
        right_a_pins_type_message_and_state(forgetful_open_session)

    # And it still passes against the subject that is correct, which is what
    # stops it from being a test that simply always fails.
    right_a_pins_type_message_and_state(open_session)
