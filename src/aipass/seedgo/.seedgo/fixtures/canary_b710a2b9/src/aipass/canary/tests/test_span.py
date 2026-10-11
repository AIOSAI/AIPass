# =================== AIPass ====================
# Name: test_span.py
# Description: Tests for the duration parser - drone @canary span, its JSON form and its refusals
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Tests for `drone @canary span`.

Driven through the entry point's main() with real module discovery, so the exit
codes asserted here are the ones drone hands back to a caller.

The load-bearing assertion is the pair: a refusal exits 2 AND writes nothing to
stdout. A refusal that printed a number would be read as an answer by whatever
consumes the output, so "it exited non-zero" alone is not the contract. Every
refusal case is run twice, plain and --json, because the JSON form is the one a
caller parses without looking.
"""

import json
import sys

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.duration import parser

VALID = {
    "days_and_hours": ("2d 4h", 187200),
    "minutes_only": ("90m", 5400),
    "no_whitespace": ("1h30m", 5400),
    "seconds_only": ("45s", 45),
    "every_unit": ("1d 2h 3m 4s", 93784),
    "order_is_free": ("30m 1h", 5400),
    "whitespace_is_insignificant": ("  2d \t 4h  ", 187200),
    "leading_zeros": ("007h", 25200),
    "zero": ("0s", 0),
    "one_day": ("1d", 86400),
    "one_hour": ("1h", 3600),
    "one_minute": ("1m", 60),
    "one_second": ("1s", 1),
    "the_limit_exactly": ("366d", 31622400),
}

REFUSED = {
    "empty": ("", "no duration text"),
    "whitespace_only": ("   ", "no duration text"),
    "unit_twice_apart": ("1h 1h", "more than once"),
    "unit_twice_among_others": ("2d 4h 2d", "more than once"),
    "unknown_unit": ("2x", "unknown unit 'x'"),
    # Uppercase is refused, not folded: a parser that accepts a spelling it was
    # never given cannot be measured from outside.
    "uppercase_unit": ("2H", "unknown unit 'H'"),
    "unit_with_no_number": ("d", "has no number"),
    "decimal": ("1.5h", "not a plain non-negative integer"),
    "negative": ("-3h", "not a plain non-negative integer"),
    "signed": ("+3h", "not a plain non-negative integer"),
    # int("٣") is 3, so only an ASCII-only check refuses this one.
    "non_ascii_digit": ("٣h", "not a plain non-negative integer"),
    "bare_number": ("90", "bare number with no unit"),
    "bare_number_after_a_part": ("1h 30", "bare number with no unit"),
    "one_day_over": ("367d", "over the 366-day limit"),
    "one_second_over": ("366d 1s", "over the 366-day limit"),
}


def _run(monkeypatch, argv):
    """Invoke the entry point with a synthetic argv, real discovery."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


# =============================================================================
# WHAT IT PARSES
# =============================================================================


@pytest.mark.parametrize(("text", "seconds"), list(VALID.values()), ids=list(VALID))
def test_a_written_duration_prints_its_total_in_seconds(monkeypatch, capsys, text, seconds):
    """One line, the number and nothing else, exit 0."""
    assert _run(monkeypatch, ["span", text]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [str(seconds)]
    assert captured.err == ""


def test_unquoted_words_are_one_duration(monkeypatch, capsys):
    """A shell that split '2d 4h' into two arguments means the same duration."""
    assert _run(monkeypatch, ["span", "2d", "4h"]) == 0

    assert capsys.readouterr().out.splitlines() == ["187200"]


# =============================================================================
# THE JSON FORM
# =============================================================================


@pytest.mark.parametrize(
    "argv",
    [["span", "--json", "1h30m"], ["span", "1h30m", "--json"]],
    ids=["flag_first", "flag_last"],
)
def test_json_form_prints_one_object_with_one_key_and_nothing_else(monkeypatch, capsys, argv):
    """stdout is a single JSON object: exactly {"seconds": N}, no prose around it."""
    assert _run(monkeypatch, argv) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {"seconds": 5400}
    assert list(payload) == ["seconds"]


# =============================================================================
# THE CONTRACT: A REFUSAL EXITS 2 AND WRITES NOTHING TO STDOUT
# =============================================================================


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
@pytest.mark.parametrize(("text", "reason"), list(REFUSED.values()), ids=list(REFUSED))
def test_a_text_that_is_not_a_duration_is_refused_with_an_empty_stdout(monkeypatch, capsys, flags, text, reason):
    """Exit 2, the reason on stderr, and not one byte on stdout to mistake for an answer."""
    assert _run(monkeypatch, ["span", *flags, text]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert reason in captured.err


def test_the_366_day_limit_is_measured_on_both_sides(monkeypatch, capsys):
    """The control for the over-limit cases: the boundary itself still answers."""
    assert _run(monkeypatch, ["span", "366d"]) == 0
    assert capsys.readouterr().out.splitlines() == ["31622400"]

    assert _run(monkeypatch, ["span", "366d 1s"]) == 2
    assert capsys.readouterr().out == ""


def test_json_flag_with_no_text_is_refused_rather_than_answered(monkeypatch, capsys):
    """--json alone carries no duration, and an empty object is not an answer."""
    assert _run(monkeypatch, ["span", "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no duration text" in captured.err


# =============================================================================
# USAGE AND HELP NEVER PARSE
# =============================================================================


def test_bare_span_prints_the_usage_and_exits_zero(monkeypatch, capsys):
    """No text at all is a question, not a refusal."""
    assert _run(monkeypatch, ["span"]) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "span --json TEXT" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["span", "--help"],
        ["span", "-h"],
        ["span", "help"],
        ["span", "--help", "2d 4h"],
        ["span", "2d 4h", "--help"],
    ],
    ids=["help_flag", "short_flag", "help_word", "flag_before_text", "flag_after_text"],
)
def test_help_anywhere_explains_and_parses_nothing(monkeypatch, capsys, argv):
    """Help prints the page, exits 0, and never turns the text into a number.

    An answer is a line that is nothing but the number, so that is what must be
    absent: the help page itself quotes 187200 inside an example line, and a
    substring check would pass for the wrong reason.
    """
    assert _run(monkeypatch, argv) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert not any(line.strip().isdigit() for line in captured.out.splitlines())
    assert captured.err == ""


# =============================================================================
# THE PARSER ITSELF
# =============================================================================


def test_parse_duration_returns_an_int_and_refusals_carry_their_reason():
    """The handler's own surface: a number out, or DurationInvalid with a readable reason."""
    assert parser.parse_duration("1h30m") == 5400

    with pytest.raises(parser.DurationInvalid) as caught:
        parser.parse_duration("2x")

    assert caught.value.reason == "unknown unit 'x' (units are d, h, m, s, lowercase)"
