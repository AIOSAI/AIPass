# =================== AIPass ====================
# Name: test_top.py
# Description: Tests for the leaderboard reader - drone @canary top, its JSON form and its refusals
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Tests for `drone @canary top`.

Driven through the entry point's main() with real module discovery, so the exit
codes asserted here are the ones drone hands back to a caller.

The load-bearing assertion is the pair: a refusal exits 2 AND writes nothing to
stdout. A partial ranking printed beside a refusal would be read as an answer by
whatever consumes the output, so "it exited non-zero" alone is not the contract.
Every argument refusal is run twice, plain and --json, because the JSON form is
the one a caller parses without looking.

The tie-break has its own control. Sorting by count alone would leave dictionary
insertion order deciding equal counts - stable within one run, and therefore a
result that passes a single-run assertion while being a property of how the file
happened to be written. The tie tests write the same rows in two different orders
and demand the same output.
"""

import json
import sys

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.leaderboard import reader


def _run(monkeypatch, argv):
    """Invoke the entry point with a synthetic argv, real discovery."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


def _board(tmp_path, text, name="scores.txt"):
    """Write a leaderboard file and return its path as a string."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


# =============================================================================
# WHAT IT RANKS
# =============================================================================


def test_the_highest_counts_print_one_per_line(monkeypatch, capsys, tmp_path):
    """Name, one space, count - in count-descending order, exit 0."""
    board = _board(tmp_path, "alice 12\nbob 30\ncarol 7\n")

    assert _run(monkeypatch, ["top", "2", board]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["bob 30", "alice 12"]
    assert captured.err == ""


def test_counts_for_one_name_are_added_before_ranking(monkeypatch, capsys, tmp_path):
    """The file is a tally, not a table: alice's two rows beat bob's single 30."""
    board = _board(tmp_path, "alice 12\nbob 30\nalice 25\n")

    assert _run(monkeypatch, ["top", "2", board]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice 37", "bob 30"]


@pytest.mark.parametrize(
    "text",
    ["ann 5\nbea 5\ncal 5\n", "cal 5\nbea 5\nann 5\n", "bea 5\ncal 5\nann 5\n"],
    ids=["already_sorted", "reversed", "shuffled"],
)
def test_an_equal_count_is_broken_by_name_ascending(monkeypatch, capsys, tmp_path, text):
    """The control for the tie-break: three write orders, one ranking."""
    assert _run(monkeypatch, ["top", "3", _board(tmp_path, text)]) == 0

    assert capsys.readouterr().out.splitlines() == ["ann 5", "bea 5", "cal 5"]


def test_a_tie_made_by_summing_is_broken_the_same_way(monkeypatch, capsys, tmp_path):
    """The tie exists only after the counts are added, and still orders by name."""
    board = _board(tmp_path, "zed 4\nabe 3\nzed 2\nabe 3\n")

    assert _run(monkeypatch, ["top", "2", board]) == 0

    assert capsys.readouterr().out.splitlines() == ["abe 6", "zed 6"]


def test_fewer_rows_than_n_prints_what_there_is(monkeypatch, capsys, tmp_path):
    """Short is an answer, not a refusal."""
    board = _board(tmp_path, "alice 12\nbob 30\n")

    assert _run(monkeypatch, ["top", "10", board]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["bob 30", "alice 12"]
    assert captured.err == ""


def test_a_file_with_no_rows_prints_nothing_and_exits_zero(monkeypatch, capsys, tmp_path):
    """An empty tally is an empty ranking - not one byte, and not a refusal."""
    board = _board(tmp_path, "\n   \n\n")

    assert _run(monkeypatch, ["top", "3", board]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_blank_lines_and_stray_whitespace_are_ignored(monkeypatch, capsys, tmp_path):
    """Indentation, trailing spaces, tabs between the fields and blank lines all read the same."""
    board = _board(tmp_path, "\n   alice\t12   \n\n\tbob 30\n   \n")

    assert _run(monkeypatch, ["top", "2", board]) == 0

    assert capsys.readouterr().out.splitlines() == ["bob 30", "alice 12"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [("alice 0", "alice 0"), ("alice -0", "alice 0"), ("alice 007", "alice 7")],
    ids=["zero", "negative_zero", "leading_zeros"],
)
def test_a_plain_integer_is_read_as_written(monkeypatch, capsys, tmp_path, row, expected):
    """Zero is a count, -0 equals zero rather than being negative, and 007 is seven."""
    assert _run(monkeypatch, ["top", "1", _board(tmp_path, row + "\n")]) == 0

    assert capsys.readouterr().out.splitlines() == [expected]


def test_a_file_with_no_final_newline_still_reads_its_last_row(monkeypatch, capsys, tmp_path):
    """Unlike the note store, this file is somebody else's - a missing terminator is not a tear."""
    board = _board(tmp_path, "alice 12\nbob 30")

    assert _run(monkeypatch, ["top", "2", board]) == 0

    assert capsys.readouterr().out.splitlines() == ["bob 30", "alice 12"]


def test_n_may_be_written_with_leading_zeros(monkeypatch, capsys, tmp_path):
    """007 is a plain positive integer, so it asks for seven rows."""
    board = _board(tmp_path, "alice 12\nbob 30\ncarol 7\n")

    assert _run(monkeypatch, ["top", "007", board]) == 0

    assert len(capsys.readouterr().out.splitlines()) == 3


# =============================================================================
# THE JSON FORM
# =============================================================================


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda board: ["top", "--json", "2", board],
        lambda board: ["top", "2", board, "--json"],
    ],
    ids=["flag_first", "flag_last"],
)
def test_json_form_prints_one_array_of_two_key_objects_and_nothing_else(monkeypatch, capsys, tmp_path, argv_builder):
    """stdout is a single JSON array in ranked order, no prose around it."""
    board = _board(tmp_path, "alice 12\nbob 30\n")

    assert _run(monkeypatch, argv_builder(board)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == [{"name": "bob", "count": 30}, {"name": "alice", "count": 12}]
    assert [list(row) for row in payload] == [["name", "count"], ["name", "count"]]


def test_json_form_of_an_empty_tally_is_an_empty_array(monkeypatch, capsys, tmp_path):
    """A caller that parses stdout gets [] rather than nothing to parse."""
    assert _run(monkeypatch, ["top", "--json", "3", _board(tmp_path, "\n")]) == 0

    assert json.loads(capsys.readouterr().out) == []


def test_a_non_ascii_name_survives_the_json_form(monkeypatch, capsys, tmp_path):
    """The name is caller data and reaches stdout as typed."""
    assert _run(monkeypatch, ["top", "--json", "1", _board(tmp_path, "zoë 4\n")]) == 0

    assert json.loads(capsys.readouterr().out) == [{"name": "zoë", "count": 4}]


# =============================================================================
# THE CONTRACT: A REFUSAL EXITS 2 AND WRITES NOTHING TO STDOUT
# =============================================================================

BAD_ARGUMENTS = {
    "n_but_no_file": (["3"], "no FILE given"),
    "zero": (["0", "BOARD"], "N must be a positive integer"),
    "negative_n": (["-1", "BOARD"], "N must be a positive integer"),
    "decimal_n": (["1.5", "BOARD"], "N must be a positive integer"),
    "word_n": (["three", "BOARD"], "N must be a positive integer"),
    # int("٣") is 3, so only an ASCII-only check refuses this one.
    "non_ascii_digit_n": (["٣", "BOARD"], "N must be a positive integer"),
    "empty_n": (["", "BOARD"], "N must be a positive integer"),
    "too_many_arguments": (["2", "BOARD", "extra.txt"], "too many arguments"),
}


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
@pytest.mark.parametrize(("argv", "reason"), list(BAD_ARGUMENTS.values()), ids=list(BAD_ARGUMENTS))
def test_bad_arguments_are_refused_with_an_empty_stdout(monkeypatch, capsys, tmp_path, flags, argv, reason):
    """Exit 2, the reason on stderr, and not one byte on stdout to mistake for a ranking."""
    board = _board(tmp_path, "alice 12\n")
    filled = [board if arg == "BOARD" else arg for arg in argv]

    assert _run(monkeypatch, ["top", *flags, *filled]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert reason in captured.err


def test_the_json_flag_alone_is_refused_rather_than_answered(monkeypatch, capsys):
    """Bare 'top' is a question and exits 0; 'top --json' asked for output and has no N.

    The flag is what separates them. An empty array here would be a caller's
    answer to a question it never finished asking.
    """
    assert _run(monkeypatch, ["top", "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no N given" in captured.err


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
def test_a_file_that_is_not_there_is_refused_rather_than_read_as_empty(monkeypatch, capsys, tmp_path, flags):
    """A missing file and an empty one are different answers; only one of them is a result."""
    missing = str(tmp_path / "nowhere.txt")

    assert _run(monkeypatch, ["top", *flags, "3", missing]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "file not found" in captured.err
    assert missing in captured.err


def test_a_path_that_cannot_be_read_as_a_file_is_refused(monkeypatch, capsys, tmp_path):
    """A directory exists and still cannot be read - the refusal names that, not absence."""
    directory = tmp_path / "scores_dir"
    directory.mkdir()

    assert _run(monkeypatch, ["top", "3", str(directory)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read" in captured.err


def test_a_file_that_is_not_valid_utf8_is_refused(monkeypatch, capsys, tmp_path):
    """Refused by encoding, with the byte offset - never silently replaced."""
    path = tmp_path / "latin1.txt"
    path.write_bytes(b"alice 12\nbo\xffb 3\n")

    assert _run(monkeypatch, ["top", "2", str(path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not valid UTF-8" in captured.err


BAD_ROWS = {
    "name_with_no_count": ("alice\n", "not exactly a name and an integer count"),
    "count_with_no_name": ("12\n", "not exactly a name and an integer count"),
    "three_fields": ("alice 12 extra\n", "not exactly a name and an integer count"),
    "decimal_count": ("alice 1.5\n", "count that is not an integer"),
    "signed_count": ("alice +3\n", "count that is not an integer"),
    "word_count": ("alice twelve\n", "count that is not an integer"),
    "non_ascii_digit_count": ("alice ٣\n", "count that is not an integer"),
    "lone_minus": ("alice -\n", "count that is not an integer"),
    "negative_count": ("alice -3\n", "negative count"),
}


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
@pytest.mark.parametrize(("row", "reason"), list(BAD_ROWS.values()), ids=list(BAD_ROWS))
def test_a_row_that_is_not_a_name_and_an_integer_count_is_refused(monkeypatch, capsys, tmp_path, flags, row, reason):
    """One bad row refuses the whole file: a ranking missing a row is not a ranking."""
    board = _board(tmp_path, "bob 30\n" + row)

    assert _run(monkeypatch, ["top", *flags, "2", board]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert reason in captured.err


def test_a_bad_row_is_named_by_its_line_number(monkeypatch, capsys, tmp_path):
    """Blank lines still count toward the number, so the reader points at the line an editor shows."""
    board = _board(tmp_path, "alice 12\n\nbob thirty\n")

    assert _run(monkeypatch, ["top", "2", board]) == 2

    assert "line 3" in capsys.readouterr().err


def test_the_negative_count_refusal_is_its_own_reason(monkeypatch, capsys, tmp_path):
    """-3 IS an integer, so folding it into "not an integer" would point at the wrong thing."""
    board = _board(tmp_path, "alice -3\n")

    assert _run(monkeypatch, ["top", "1", board]) == 2

    captured = capsys.readouterr()
    assert "negative count" in captured.err
    assert "not an integer" not in captured.err


def test_n_is_refused_before_the_file_is_opened(monkeypatch, capsys, tmp_path):
    """Both halves are wrong; the refusal names N, so the argument check runs first."""
    missing = str(tmp_path / "nowhere.txt")

    assert _run(monkeypatch, ["top", "0", missing]) == 2

    captured = capsys.readouterr()
    assert "N must be a positive integer" in captured.err
    assert "file not found" not in captured.err


# =============================================================================
# USAGE AND HELP NEVER RANK
# =============================================================================


def test_bare_top_prints_the_usage_and_exits_zero(monkeypatch, capsys):
    """No arguments at all is a question, not a refusal."""
    assert _run(monkeypatch, ["top"]) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "top --json N FILE" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda board: ["top", "--help"],
        lambda board: ["top", "-h"],
        lambda board: ["top", "help"],
        lambda board: ["top", "--help", "2", board],
        lambda board: ["top", "2", board, "--help"],
    ],
    ids=["help_flag", "short_flag", "help_word", "flag_before_args", "flag_after_args"],
)
def test_help_anywhere_explains_and_ranks_nothing(monkeypatch, capsys, tmp_path, argv_builder):
    """Help prints the page, exits 0, and never reads the file.

    A ranking is a line of a name and a bare count, so that is what must be
    absent: the help page quotes 'alice 12' inside an example line, and a
    substring check would pass for the wrong reason.
    """
    board = _board(tmp_path, "alice 12\nbob 30\n")

    assert _run(monkeypatch, argv_builder(board)) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert not any(line.strip() in ("alice 12", "bob 30") for line in captured.out.splitlines())
    assert captured.err == ""


# =============================================================================
# THE READER ITSELF
# =============================================================================


def test_read_totals_sums_and_rank_orders(tmp_path):
    """The handler's own surface, without the entry point in the way."""
    path = tmp_path / "scores.txt"
    path.write_text("alice 12\nbob 5\nalice 3\ncarl 5\n", encoding="utf-8")

    totals = reader.read_totals(path)
    assert totals == {"alice": 15, "bob": 5, "carl": 5}
    assert reader.rank(totals, 2) == [("alice", 15), ("bob", 5)]
    assert reader.rank(totals, 99) == [("alice", 15), ("bob", 5), ("carl", 5)]


def test_reader_refusals_carry_a_readable_reason(tmp_path):
    """LeaderboardInvalid names the part that is wrong, not just that something is."""
    with pytest.raises(reader.LeaderboardInvalid) as caught:
        reader.parse_n("0")
    assert caught.value.reason == "N must be a positive integer, got '0'"

    path = tmp_path / "scores.txt"
    path.write_text("alice -3\n", encoding="utf-8")

    with pytest.raises(reader.LeaderboardInvalid) as caught:
        reader.read_totals(path)
    assert caught.value.reason.endswith("line 1 has a negative count (-3)")
