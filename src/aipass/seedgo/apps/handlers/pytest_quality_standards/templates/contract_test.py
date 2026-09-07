# =================== AIPass ====================
# Name: contract_test.py
# Description: teaching template - pinning a promise a caller depends on, not the implementation
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""TEACHING TEMPLATE - THE CONTRACT TEST. A worked example. Not a file to deploy.

DO NOT STAMP THIS FILE.
Copying it into a branch's test directory is the exact failure this pack was
built to correct. The standard v5 replaces - test_quality v4 - shipped six
reference templates, branches stamped them, and five of those stamped families
now total 1,411 tests across the fleet. Measured, only 5 of the 48 test-function
names appearing in six or more branches still shared a shape: stamped once, then
every copy drifted somewhere different, so the fleet holds over a thousand tests
that look like a standard and pin whatever each divergence left behind. The same
standard scored a project by searching its test files for 99 pattern substrings,
so the cheapest way to score well was to write the strings rather than the
tests. This file teaches a SHAPE and shows its reasoning, so that you write your
own test against your own subject. A contract test above all others cannot be
stamped: a promise belongs to one specific caller of one specific function, and
a copied promise is nobody's.

WHAT A CONTRACT TEST IS FOR
A contract is a promise some caller depends on. Not everything the code does -
only the part that, if it changed, would break somebody. The order of a returned
list, the fact that the input is not mutated, the key that is always present in
the result, the exception a caller catches by type. Those are promises. That the
function uses `sorted` with a lambda key is not a promise; it is this week's way
of keeping one.

The test for a promise has three properties, and the third is the one people
lose:

  1. the docstring NAMES the promise, so a reader learns the contract from the
     test without opening the implementation;
  2. the test goes red when the promise breaks;
  3. the test stays green through any refactor that keeps the promise.

Property 3 is what separates a contract test from an implementation test. A
suite that goes red on every honest refactor teaches its readers to distrust it,
and a distrusted suite gets its failures ignored - which is a worse outcome than
having no test at all, because it is invisible.

WHEN TO REACH FOR ONE
- Another module, another branch, or a user's script depends on the answer's
  SHAPE: an order, a key, a type, an absence of mutation.
- You are about to refactor, and you want a net under the promises rather than
  under the code.
- A promise was broken once already. That is the strongest possible reason and
  it makes the test a regression pin as well as a contract.

WHEN NOT TO
- Nobody depends on it. An internal helper's return order is not a contract
  just because it happens to be stable.
- You cannot state the promise in one sentence without describing the
  algorithm. If the sentence turns into pseudocode, you are pinning
  implementation and the docstring is telling you so.
- The promise is really a defect you have not fixed yet. Pin the defect as a
  failure-path test and fix it; do not promote it to a contract.

WHAT IT COSTS
The expectation has to be written BY HAND, and by hand is slower. Computing the
expected value with the implementation's own expression is faster to type and
worthless: it agrees with the code by construction, so a bug written into both
places at once is invisible, and the test can never disagree with the thing it
is checking. The first wrong shape below is exactly that, and it is run against
a subject that breaks a real promise to show it stays green.

The second cost is discipline about scope. A contract test that reaches for a
private helper because it is convenient turns into a tax on every future edit.
The second wrong shape below shows one, and then shows it dying on a refactor
that broke no promise at all.

HOW THIS FILE IS ORGANISED
The subject is defined inline, so the file is self-contained - it imports pytest
and the standard library and nothing else. The `wrong_*` and `right_*` functions
are deliberately NOT named `test_*`, so neither pytest nor this pack's own
reader collects them; they are read, and they are executed by the collected
tests at the bottom against alternative implementations, which is what proves
the claims above rather than asserting them in prose.
"""

from typing import Any, Callable

import pytest

# =============================================================================
# THE SUBJECT UNDER TEST - defined here so this file is self-contained
# =============================================================================


class Roster:
    """A roster of scored candidates.

    THE PROMISES, which are what the tests below pin:
      - `names()` answers in insertion order, always.
      - `top(count)` answers the highest scorers first, ties in insertion order.
      - `top(count)` does not reorder the roster it read.

    `_rank_key` is NOT one of the promises. It is how this version happens to
    keep the second one, and the second wrong shape below pins it anyway.
    """

    def __init__(self) -> None:
        """Start with an empty roster."""
        self._rows: list[tuple] = []

    def add(self, name: str, score: int) -> None:
        """Append one candidate to the end of the roster."""
        self._rows.append((name, score))

    def names(self) -> list:
        """Every name on the roster, in insertion order."""
        return [name for name, _ in self._rows]

    def top(self, count: int) -> list:
        """The `count` highest-scoring names, highest first, ties in insertion order."""
        return [name for name, _ in sorted(self._rows, key=self._rank_key)][:count]

    def _rank_key(self, row: tuple) -> int:
        """PRIVATE. How this version orders a row. No caller can see it."""
        return -row[1]


class RosterV2:
    """THE SAME PROMISES, a different implementation. `_rank_key` does not exist here.

    This is the honest refactor: every promise in `Roster`'s docstring is kept,
    and nothing outside the class can tell the two apart. A contract test must
    pass against this class unchanged; an implementation test cannot.
    """

    def __init__(self) -> None:
        """Start with an empty roster."""
        self._rows: list[tuple] = []

    def add(self, name: str, score: int) -> None:
        """Append one candidate to the end of the roster."""
        self._rows.append((name, score))

    def names(self) -> list:
        """Every name on the roster, in insertion order."""
        return [name for name, _ in self._rows]

    def top(self, count: int) -> list:
        """The `count` highest-scoring names, highest first, ties in insertion order."""
        ordered = sorted(self._rows, key=lambda row: -row[1])
        return [name for name, _ in ordered][:count]


class RosterThatSortsInPlace(Roster):
    """A DELIBERATELY BROKEN roster: `top` reorders the roster it read.

    It answers `top` correctly, so any test that looks only at the returned
    list is green. The promise it breaks - that reading the top leaves the
    roster in insertion order - is invisible from the return value alone.
    """

    def top(self, count: int) -> list:
        """The highest scorers, at the cost of the roster's own order."""
        self._rows.sort(key=self._rank_key)
        return [name for name, _ in self._rows][:count]


# =============================================================================
# THE WRONG SHAPES - read these first
# =============================================================================


def wrong_a_restates_the_implementation(roster_cls: Callable[..., Any]) -> None:
    """WRONG. Computes the expectation with the implementation's own expression.

    Not named `test_*` on purpose, so pytest walks past it and so does this
    pack's reader.
    """
    entries = [("ana", 3), ("bo", 9), ("cy", 3)]
    roster = roster_cls()
    for name, score in entries:
        roster.add(name, score)

    # THE DEFECT. `sorted(entries, key=lambda row: -row[1])` is the
    # implementation, retyped. It agrees with the code by construction: flip
    # the sort direction in both places and this stays green, which means the
    # assertion can never disagree with the thing it is checking. And because
    # it looks only at the returned list, it says nothing about the roster the
    # call read - so a subject that sorts its own storage in place walks past.
    expected = [name for name, _ in sorted(entries, key=lambda row: -row[1])][:2]
    assert roster.top(2) == expected


def wrong_b_pins_a_private_helper(roster: Any) -> None:
    """WRONG for a different reason: it pins `_rank_key`, which is not a promise.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    # THE DEFECT. Nothing outside the class may call `_rank_key`, so nothing
    # outside the class can be broken by changing it. This assertion is green
    # today and red the morning somebody inlines the helper without breaking a
    # single promise - a red suite bought with a refactor that harmed no
    # caller. Reds like that are how a team learns to skim past failures.
    assert roster._rank_key(("ana", 3)) == -3


# =============================================================================
# THE RIGHT SHAPE - and why it is different
# =============================================================================


def right_a_pins_the_top_contract(roster_cls: Callable[..., Any]) -> None:
    """RIGHT. Pins the promises by hand, including the one the return value cannot show.

    Not named `test_*` on purpose - see the note on the first wrong shape.
    """
    roster = roster_cls()
    for name, score in (("ana", 3), ("bo", 9), ("cy", 3)):
        roster.add(name, score)

    # HAND-WRITTEN, NOT COMPUTED. "bo" first because 9 beats 3, then "ana"
    # before "cy" because they tie and insertion order breaks ties. A reader
    # can check this line against the promise without opening `top`, and it
    # disagrees with the implementation the moment the implementation is wrong.
    assert roster.top(2) == ["bo", "ana"]

    # THE PROMISE THE RETURN VALUE CANNOT SHOW. A caller that lists the roster
    # after asking for the top depends on this, and nothing about the list
    # above reveals whether it holds.
    assert roster.names() == ["ana", "bo", "cy"]


# =============================================================================
# THE TESTS - the only functions in this file pytest collects
# =============================================================================


def test_roster_top_ranks_by_score_and_breaks_ties_by_insertion_order() -> None:
    """Pins the Roster.top contract: highest score first, and a tie is broken by which was added first."""
    roster = Roster()
    roster.add("ana", 3)
    roster.add("bo", 9)
    roster.add("cy", 3)

    assert roster.top(2) == ["bo", "ana"]
    assert roster.top(3) == ["bo", "ana", "cy"]


def test_roster_top_leaves_the_roster_in_insertion_order() -> None:
    """Pins the Roster.names contract: asking for the top does not reorder the roster it read."""
    roster = Roster()
    roster.add("ana", 3)
    roster.add("bo", 9)
    roster.add("cy", 3)
    roster.top(2)

    assert roster.names() == ["ana", "bo", "cy"]


def test_wrong_a_restates_the_implementation_accepts_a_roster_that_reorders_itself() -> None:
    """Proof: wrong_a_restates_the_implementation accepts RosterThatSortsInPlace."""
    # The broken subject returns the right list and wrecks its own order. The
    # implementation-restating shape is green against it.
    wrong_a_restates_the_implementation(RosterThatSortsInPlace)

    with pytest.raises(AssertionError):
        right_a_pins_the_top_contract(RosterThatSortsInPlace)

    # And the right shape still passes against the correct implementation,
    # which is what stops it from being a test that simply always fails.
    right_a_pins_the_top_contract(Roster)


def test_wrong_b_pins_a_private_helper_dies_on_a_refactor_the_contract_survives() -> None:
    """Proof: right_a_pins_the_top_contract accepts RosterV2 while wrong_b_pins_a_private_helper cannot run."""
    # Green today, against the version that happens to have the helper.
    wrong_b_pins_a_private_helper(Roster())

    # RosterV2 keeps every promise and dropped the helper. The contract shape
    # does not notice the refactor at all.
    right_a_pins_the_top_contract(RosterV2)

    # The implementation shape cannot even run against it - a red bought by a
    # change that broke no caller.
    with pytest.raises(AttributeError):
        wrong_b_pins_a_private_helper(RosterV2())
