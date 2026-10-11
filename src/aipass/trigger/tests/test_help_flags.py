# =================== AIPass ====================
# Name: test_help_flags.py
# Description: Unit tests for the whole-sequence help-flag predicate
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/cli/help_flags.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the routing in apps/trigger.py that calls the predicate; the entry point tests cover it

import pytest

from aipass.trigger.apps.handlers.cli.help_flags import (
    HELP_BARE_WORD,
    HELP_FLAGS_DASHED,
    wants_help,
)


@pytest.mark.parametrize("token", ["helper", "--helpful", "-help", "h", "HELP"])
def test_near_misses_are_not_flags(token):
    """Matching is exact, never prefix or fuzzy, in either token class."""
    assert wants_help([token]) is False
    assert wants_help(["mute", token]) is False


# ---------------------------------------------------------------------------
# wants_help — dashed forms scan the whole sequence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["-h"],
        ["mute", "--help"],
        ["mute", "@trigger", "--help"],
        ["list", "--branch", "api", "-h"],
        ["fire", "error_detected", "branch=api", "count=2", "--help"],
    ],
)
def test_dashed_flag_counts_at_any_position(args):
    """The position of a dashed flag is irrelevant — it always means explain."""
    assert wants_help(args) is True


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["mute", "@trigger"],
        ["fire", "error_detected", "message=--help-me"],
        ["suppress", "abc123", "--helpful-context"],
    ],
)
def test_no_flag_means_run_the_command(args):
    """Matching is exact, so a flag-shaped substring inside a value is safe.

    The same list with a real flag appended does ask, so the refusal is about
    the tokens, not the command. Mutant run: the dashed-flag check removed reddens this.
    """
    assert wants_help(args) is False
    assert wants_help([*args, "--help"]) is True


def test_dashed_flag_inside_a_key_value_pair_is_a_payload():
    """`message=--help` is event data, not a request for the manual.

    Exact matching is what protects this: the token is `message=--help`,
    which is not `--help`.
    """
    assert wants_help(["error_detected", "message=--help"]) is False


# ---------------------------------------------------------------------------
# wants_help — the bare word is positional
# ---------------------------------------------------------------------------


def test_bare_word_help_counts_in_the_subcommand_slot():
    """`help` at position 0 is the subcommand, so it asks for the manual."""
    assert wants_help(["help"]) is True
    assert wants_help(["help", "mute"]) is True


@pytest.mark.parametrize(
    "args",
    [
        ["suppress", "abc123", "help"],
        ["fire", "error_detected", "message=help"],
        ["list", "help"],
    ],
)
def test_bare_word_help_past_position_zero_is_an_operand(args):
    """Later `help` is a reason, a payload or a filter — never a flag.

    This is the whole reason the bare word is treated differently from the
    dashed forms: it is a legitimate value in this branch's own commands.
    The same list led by the bare word asks for the manual, so position is
    the whole difference. Mutant run: the bare-word branch returning False reddens this.
    """
    assert wants_help(args) is False
    assert wants_help([HELP_BARE_WORD, *args]) is True


def test_bare_word_can_be_switched_off_entirely():
    """allow_bare_word=False leaves only the unambiguous dashed forms."""
    assert wants_help(["help"], allow_bare_word=False) is False
    assert wants_help(["help", "--help"], allow_bare_word=False) is True


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_dashed_constant_excludes_the_bare_word():
    """The two token classes stay separate — the whole design rests on it."""
    assert HELP_FLAGS_DASHED == ("--help", "-h")
    assert HELP_BARE_WORD == "help"
    assert HELP_BARE_WORD not in HELP_FLAGS_DASHED
