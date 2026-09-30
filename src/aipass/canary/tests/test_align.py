# =================== AIPass ====================
# Name: test_align.py
# Description: Tests for the column aligner - drone @canary align, its JSON form and its refusals
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Tests for `drone @canary align`.

Driven through the entry point's main() with real module discovery, so the exit
codes asserted here are the ones drone hands back to a caller.

The load-bearing assertion is the pair: a refusal exits 2 AND writes nothing to
stdout. A table is the kind of output that gets piped, so a half-aligned one
printed beside a refusal would be read as the answer. Every refusal is run
twice, plain and --json, because the JSON form is the one a caller parses
without looking - and because an empty result prints as nothing in the plain
form, where it hides (canary key learning 31).

Alignment is asserted as exact lines, never as "contains". Padding IS the
output: a test that only checked for the fields would pass on a formatter that
never padded anything at all.
"""

import json
import sys

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.table import aligner


def _run(monkeypatch, argv):
    """Invoke the entry point with a synthetic argv, real discovery."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


def _table(tmp_path, text, name="table.txt"):
    """Write a table file and return its path as a string."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _stderr(captured):
    """Stderr as one line, whitespace flattened.

    @cli renders a refusal through rich, which wraps it at the console width -
    80 when stdout is not a terminal. A refusal that names a long path is
    therefore broken across lines at whichever space happens to fall near
    column 80, so 'has no non-blank lines' arrived here as 'has\nno non-blank
    lines' and only for the parametrised cases whose tmp_path was long enough.
    The wrapping is the shared console's, not this branch's; flattening it
    keeps these assertions about the reason rather than about path length.
    """
    return " ".join(captured.err.split())


def _json_payload(monkeypatch, capsys, tmp_path, text):
    """Run the JSON form over one table and return the parsed payload."""
    assert _run(monkeypatch, ["align", "--json", _table(tmp_path, text)]) == 0
    return json.loads(capsys.readouterr().out)


# =============================================================================
# WHAT IT ALIGNS
# =============================================================================


def test_every_column_is_padded_to_its_widest_value(monkeypatch, capsys, tmp_path):
    """The exact lines, two spaces between columns, exit 0."""
    table = _table(tmp_path, "alice 12 red\nbo 3 blue\ncarolina 7 g\n")

    assert _run(monkeypatch, ["align", table]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "alice     12  red",
        "bo        3   blue",
        "carolina  7   g",
    ]
    assert captured.err == ""


def test_columns_are_exactly_two_spaces_apart(monkeypatch, capsys, tmp_path):
    """One space would still look like a table; the contract says two."""
    table = _table(tmp_path, "a bb\ncc d\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["a   bb", "cc  d"]


def test_no_line_ends_in_whitespace(monkeypatch, capsys, tmp_path):
    """The last column is never padded, so the short last value ends the line."""
    table = _table(tmp_path, "alice longest\nbob x\n")

    assert _run(monkeypatch, ["align", table]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == ["alice  longest", "bob    x"]
    assert all(line == line.rstrip() for line in lines)


def test_rows_keep_the_order_they_were_written(monkeypatch, capsys, tmp_path):
    """This lines columns up; it does not sort. Sorted output would reverse these."""
    table = _table(tmp_path, "zed 1\nann 2\nmid 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["zed  1", "ann  2", "mid  3"]


def test_blank_and_whitespace_only_lines_are_skipped(monkeypatch, capsys, tmp_path):
    """They produce no row and no blank line in the output."""
    table = _table(tmp_path, "\nalice 12\n   \n\t\nbob 3\n\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_leading_and_trailing_whitespace_on_a_line_is_ignored(monkeypatch, capsys, tmp_path):
    """Indentation does not become a wider first column, and trailing spaces vanish."""
    table = _table(tmp_path, "    alice 12   \n\tbob 3\t\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_a_run_of_spaces_is_one_separator(monkeypatch, capsys, tmp_path):
    """An already-aligned file re-aligns to the same thing rather than growing empty fields."""
    table = _table(tmp_path, "alice     12\nbob       3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_a_tab_separates_a_column_like_a_space(monkeypatch, capsys, tmp_path):
    """The ruling: a table is written with either, and a tab inside a field would misalign it."""
    table = _table(tmp_path, "alice\t12\nbob 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_the_widest_value_may_be_the_last_row(monkeypatch, capsys, tmp_path):
    """The width is the whole column's, not the first row's."""
    table = _table(tmp_path, "a 1\nbb 2\nccc 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["a    1", "bb   2", "ccc  3"]


def test_a_single_row_aligns_to_itself(monkeypatch, capsys, tmp_path):
    """One row is a table; its own widths are the column widths."""
    table = _table(tmp_path, "alice 12 red\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12  red"]


def test_a_file_with_many_columns_aligns_all_of_them(monkeypatch, capsys, tmp_path):
    """Nothing about two columns is special; five behave the same way."""
    table = _table(tmp_path, "a bb ccc dddd e\nfffff g hh iii j\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "a      bb  ccc  dddd  e",
        "fffff  g   hh   iii   j",
    ]


def test_width_counts_code_points_not_terminal_cells(monkeypatch, capsys, tmp_path):
    """The ruling: a double-width character counts as one, so the padding is measurable."""
    table = _table(tmp_path, "日本 12\nab 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["日本  12", "ab  3"]


def test_a_composed_accent_counts_as_one_character(monkeypatch, capsys, tmp_path):
    """'zoë' in composed form is three code points, so it pads to three."""
    table = _table(tmp_path, "zoë 1\nabcd 2\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["zoë   1", "abcd  2"]


def test_a_no_break_space_stays_inside_a_field(monkeypatch, capsys, tmp_path):
    """The ruling: str.split() would break this row in two; only a space or tab separates."""
    table = _table(tmp_path, "a b c\nxx yy\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["a b  c", "xx   yy"]


def test_a_no_break_space_at_the_edge_of_a_line_is_still_stripped(monkeypatch, capsys, tmp_path):
    """The honest half of that ruling: strip() takes any whitespace, this one included."""
    table = _table(tmp_path, " alice 12 \nbob 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_a_file_with_no_final_newline_still_reads_its_last_row(monkeypatch, capsys, tmp_path):
    """This file is somebody else's - a missing terminator is not a torn write."""
    table = _table(tmp_path, "alice 12\nbob 3")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_crlf_line_endings_read_the_same(monkeypatch, capsys, tmp_path):
    """A file written on Windows is not a one-row table with a stray carriage return.

    This one is a behaviour pin, not a discriminator: strip() removes the
    trailing \\r on its own, so it passes whether the file is cut by
    splitlines() or by split("\\n"). The two tests below are what separate them.
    """
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"alice 12\r\nbob 3\r\n")

    assert _run(monkeypatch, ["align", str(path)]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_carriage_return_alone_ends_a_line(monkeypatch, capsys, tmp_path):
    """A file with old-Mac endings is two rows, not one row holding a \\r."""
    path = tmp_path / "cr.txt"
    path.write_bytes(b"alice 12\rbob 3\r")

    assert _run(monkeypatch, ["align", str(path)]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_a_vertical_tab_ends_a_line_like_a_newline(monkeypatch, capsys, tmp_path):
    """The other half of the separator ruling, measured rather than asserted in prose.

    A vertical tab never reaches the question of what separates two fields:
    str.splitlines() treats it as a line boundary, so it cuts the FILE before
    anything cuts a row. Reading the file with split("\\n") instead would make
    this one row of four fields.
    """
    table = _table(tmp_path, "alice 12\x0bbob 3\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["alice  12", "bob    3"]


def test_markup_in_a_field_prints_as_typed(monkeypatch, capsys, tmp_path):
    """A field is caller data: '[bold]' is four to eight characters, not a style."""
    table = _table(tmp_path, "[bold]x[/bold] 1\nab 2\n")

    assert _run(monkeypatch, ["align", table]) == 0

    assert capsys.readouterr().out.splitlines() == ["[bold]x[/bold]  1", "ab              2"]


# =============================================================================
# THE JSON FORM
# =============================================================================


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda table: ["align", "--json", table],
        lambda table: ["align", table, "--json"],
    ],
    ids=["flag_first", "flag_last"],
)
def test_json_form_prints_one_array_of_arrays_and_nothing_else(monkeypatch, capsys, tmp_path, argv_builder):
    """stdout is a single JSON array in file order, no prose around it."""
    table = _table(tmp_path, "alice 12 red\nbo 3 blue\n")

    assert _run(monkeypatch, argv_builder(table)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == [["alice", "12", "red"], ["bo", "3", "blue"]]


def test_every_field_in_the_json_form_is_a_string(monkeypatch, capsys, tmp_path):
    """A count-looking field stays '12': this reads a table, it does not type it."""
    payload = _json_payload(monkeypatch, capsys, tmp_path, "alice 12\nbob 3\n")

    assert all(isinstance(field, str) for row in payload for field in row)


def test_the_json_form_carries_no_padding(monkeypatch, capsys, tmp_path):
    """The padding belongs to the printed form; a parser gets the fields as written."""
    payload = _json_payload(monkeypatch, capsys, tmp_path, "alice 12\nbo 3\n")

    assert payload == [["alice", "12"], ["bo", "3"]]


def test_a_non_ascii_field_survives_the_json_form(monkeypatch, capsys, tmp_path):
    """ensure_ascii is off, so the field reaches stdout as typed rather than escaped."""
    payload = _json_payload(monkeypatch, capsys, tmp_path, "zoë 4\n")

    assert payload == [["zoë", "4"]]


# =============================================================================
# THE CONTRACT: A REFUSAL EXITS 2 AND WRITES NOTHING TO STDOUT
# =============================================================================


def test_the_json_flag_alone_is_refused_rather_than_answered(monkeypatch, capsys):
    """Bare 'align' is a question and exits 0; 'align --json' asked for output with no FILE.

    The flag is what separates them, and it is the only way to reach the
    no-FILE refusal at all: with no arguments whatsoever the module prints its
    usage instead. An empty array here would answer a question nobody finished
    asking.
    """
    assert _run(monkeypatch, ["align", "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no FILE given" in _stderr(captured)


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
def test_more_than_one_file_is_refused(monkeypatch, capsys, tmp_path, flags):
    """One FILE is the whole argument list; a second is a request nobody defined."""
    table = _table(tmp_path, "alice 12\n")
    other = _table(tmp_path, "bob 3\n", name="other.txt")

    assert _run(monkeypatch, ["align", *flags, table, other]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "too many arguments" in _stderr(captured)
    assert other in _stderr(captured)


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
def test_a_file_that_is_not_there_is_refused_rather_than_read_as_empty(monkeypatch, capsys, tmp_path, flags):
    """A missing file and an empty one are different answers, and neither is a table."""
    missing = str(tmp_path / "nowhere.txt")

    assert _run(monkeypatch, ["align", *flags, missing]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "file not found" in _stderr(captured)
    assert missing in _stderr(captured)


def test_a_path_that_cannot_be_read_as_a_file_is_refused(monkeypatch, capsys, tmp_path):
    """A directory exists and still cannot be read - the refusal names that, not absence."""
    directory = tmp_path / "table_dir"
    directory.mkdir()

    assert _run(monkeypatch, ["align", str(directory)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read" in _stderr(captured)


def test_a_file_that_is_not_valid_utf8_is_refused(monkeypatch, capsys, tmp_path):
    """Refused by encoding, with the byte offset - never silently replaced."""
    path = tmp_path / "latin1.txt"
    path.write_bytes(b"alice 12\nbo\xffb 3\n")

    assert _run(monkeypatch, ["align", str(path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not valid UTF-8" in _stderr(captured)


BAD_FILES = {
    "one_field_first_row": ("alice\nbob 3\n", "fewer than two fields"),
    "one_field_later_row": ("alice 12\nbob\n", "fewer than two fields"),
    "more_fields_than_the_first_row": ("alice 12\nbob 3 extra\n", "has 3 fields, the first row set 2"),
    "fewer_fields_than_the_first_row": ("alice 12 red\nbob 3\n", "has 2 fields, the first row set 3"),
    "empty_file": ("", "has no non-blank lines"),
    "only_blank_lines": ("\n   \n\t\n", "has no non-blank lines"),
}


@pytest.mark.parametrize("flags", [[], ["--json"]], ids=["plain", "json"])
@pytest.mark.parametrize(("text", "reason"), list(BAD_FILES.values()), ids=list(BAD_FILES))
def test_a_file_that_is_not_a_table_is_refused_with_an_empty_stdout(monkeypatch, capsys, tmp_path, flags, text, reason):
    """Exit 2, the reason on stderr, and not one byte on stdout to mistake for a table."""
    assert _run(monkeypatch, ["align", *flags, _table(tmp_path, text)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert reason in _stderr(captured)


def test_a_bad_row_is_named_by_its_line_number(monkeypatch, capsys, tmp_path):
    """Blank lines still count toward the number, so it points at the line an editor shows."""
    table = _table(tmp_path, "alice 12\n\nbob\n")

    assert _run(monkeypatch, ["align", table]) == 2

    assert "line 3" in _stderr(capsys.readouterr())


def test_a_one_field_row_is_named_as_that_and_not_as_a_count_mismatch(monkeypatch, capsys, tmp_path):
    """Both checks apply to this row; the more specific one has to run first.

    A refusal that fires first hides every check behind it (canary key learning
    23), so which one speaks is the contract, not an implementation detail.
    """
    table = _table(tmp_path, "alice 12 red\nbob\n")

    assert _run(monkeypatch, ["align", table]) == 2

    captured = capsys.readouterr()
    assert "fewer than two fields" in _stderr(captured)
    assert "the first row set" not in _stderr(captured)


def test_the_rows_before_a_bad_one_are_not_printed(monkeypatch, capsys, tmp_path):
    """One bad row refuses the whole file: a table missing its last row is not that table.

    The two good rows are read and held before line 3 is reached, so this is
    the case where a partial table would escape if anything printed as it went.
    """
    table = _table(tmp_path, "alice 12\nbob 3\ncarol\n")

    assert _run(monkeypatch, ["align", table]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fewer than two fields" in _stderr(captured)


def test_the_argument_count_is_checked_before_a_file_is_opened(monkeypatch, capsys, tmp_path):
    """Two FILEs where neither exists names the argument count, not the absent file."""
    missing = str(tmp_path / "nowhere.txt")

    assert _run(monkeypatch, ["align", missing, missing]) == 2

    captured = capsys.readouterr()
    assert "too many arguments" in _stderr(captured)
    assert "file not found" not in _stderr(captured)


# =============================================================================
# USAGE AND HELP NEVER ALIGN
# =============================================================================


def test_bare_align_prints_the_usage_and_exits_zero(monkeypatch, capsys):
    """No arguments at all is a question, not a refusal."""
    assert _run(monkeypatch, ["align"]) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "align --json FILE" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda table: ["align", "--help"],
        lambda table: ["align", "-h"],
        lambda table: ["align", "help"],
        lambda table: ["align", "--help", table],
        lambda table: ["align", table, "--help"],
    ],
    ids=["help_flag", "short_flag", "help_word", "flag_before_args", "flag_after_args"],
)
def test_help_anywhere_explains_and_aligns_nothing(monkeypatch, capsys, tmp_path, argv_builder):
    """Help prints the page, exits 0, and never reads the file.

    An aligned row is a line of fields and nothing else, so that is what must be
    absent: the help page quotes 'alice  12  red' inside an example line, and a
    substring check would pass for the wrong reason.
    """
    table = _table(tmp_path, "alice 12 red\nbo 3 blue\n")

    assert _run(monkeypatch, argv_builder(table)) == 0

    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert not any(line.strip() in ("alice  12  red", "bo     3   blue") for line in captured.out.splitlines())
    assert captured.err == ""


# =============================================================================
# THE HANDLER ITSELF
# =============================================================================


def test_read_rows_returns_the_fields_in_file_order(tmp_path):
    """The handler's own surface, without the entry point in the way."""
    path = tmp_path / "table.txt"
    path.write_text("alice 12 red\nbo 3 blue\n", encoding="utf-8")

    assert aligner.read_rows(path) == [["alice", "12", "red"], ["bo", "3", "blue"]]


def test_widths_measure_each_column_against_its_widest_value():
    """Per column, not one width for the whole table."""
    rows = [["a", "bbbb"], ["ccc", "d"]]

    assert aligner.widths(rows) == [3, 4]


def test_render_pads_every_column_but_the_last():
    """The rendering contract in one assertion: two spaces, left-aligned, nothing trailing."""
    rows = [["a", "bbbb", "c"], ["ccc", "d", "eeee"]]

    assert aligner.render(rows) == ["a    bbbb  c", "ccc  d     eeee"]


def test_handler_refusals_carry_a_readable_reason(tmp_path):
    """TableInvalid names the part that is wrong, not just that something is."""
    path = tmp_path / "table.txt"
    path.write_text("alice 12\nbob\n", encoding="utf-8")

    with pytest.raises(aligner.TableInvalid) as caught:
        aligner.read_rows(path)
    assert caught.value.reason == f"{path}: line 2 has fewer than two fields ('bob')"

    with pytest.raises(aligner.TableInvalid) as missing:
        aligner.read_rows(tmp_path / "nowhere.txt")
    assert missing.value.reason == f"file not found: {tmp_path / 'nowhere.txt'}"
