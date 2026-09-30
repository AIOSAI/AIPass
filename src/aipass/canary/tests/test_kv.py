# =================== AIPass ====================
# Name: test_kv.py
# Description: Tests for the key/value store - drone @canary kv, its JSON form, its file and its refusals
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Tests for `drone @canary kv`.

Driven through the entry point's main() with real module discovery, so the exit
codes asserted here are the ones drone hands back to a caller.

This is the first canary command that writes to a caller-named file, so three
things are pinned that the read-only commands never had to be:

* **The bytes on disk**, not just what comes back out. `set` then `get` would
  pass on a store that kept its pairs in JSON, in reverse, or in memory. The
  line format is read raw, with the tab counted.
* **What a refused call leaves behind.** A store that will not parse must come
  out of a refused `set` byte for byte unchanged - a command that repairs a file
  it cannot read has destroyed whatever was actually in it.
* **A single tab.** The shared console expands one to the next 8-column tab
  stop, so `list` writes to stdout directly; an assertion that only looked for
  the key and the value would pass on the padded version.

Every refusal is asserted as the pair: exit 2 AND nothing on stdout. A value is
about to be used by whatever called this, so a half-answer printed beside a
refusal would be read as the value.
"""

import json
import os
import sys

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.kv import store


def _run(monkeypatch, argv):
    """Invoke the entry point with a synthetic argv, real discovery."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


def _store(tmp_path, text=None, name="store.txt"):
    """Write a store file if text is given, and return its path as a string."""
    path = tmp_path / name
    if text is not None:
        path.write_text(text, encoding="utf-8", newline="")
    return str(path)


def _stderr(captured):
    """Stderr as one line, whitespace flattened.

    @cli renders a refusal through rich, which wraps it at the console width -
    80 when stdout is not a terminal - so a reason naming a long tmp_path
    arrives broken at whichever space falls near column 80. Flattening keeps
    these assertions about the reason. It cannot cure a wrapped long TOKEN,
    which is why no assertion here names a path.
    """
    return " ".join(captured.err.split())


def _refused(monkeypatch, capsys, argv):
    """Run a call that must refuse, and return its flattened stderr."""
    assert _run(monkeypatch, argv) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    return _stderr(captured)


# =============================================================================
# WHAT IT STORES
# =============================================================================


def test_a_pair_set_in_one_run_is_read_back_in_the_next(monkeypatch, capsys, tmp_path):
    """The whole point: two separate invocations, the value survives."""
    path = _store(tmp_path)

    assert _run(monkeypatch, ["kv", path, "set", "colour", "red"]) == 0
    capsys.readouterr()

    assert _run(monkeypatch, ["kv", path, "get", "colour"]) == 0
    assert capsys.readouterr().out == "red\n"


def test_set_prints_nothing_at_all(monkeypatch, capsys, tmp_path):
    """Not a confirmation line, not a summary - nothing, on either stream."""
    assert _run(monkeypatch, ["kv", _store(tmp_path), "set", "colour", "red"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_the_first_set_creates_the_file(monkeypatch, tmp_path):
    """The store does not have to exist for set; it does for every other verb."""
    path = tmp_path / "fresh.txt"
    assert not path.exists()

    assert _run(monkeypatch, ["kv", str(path), "set", "a", "1"]) == 0

    assert path.exists()


def test_the_store_line_is_a_key_a_single_tab_and_a_value(monkeypatch, tmp_path):
    """Read raw: one tab, not two, not a run of spaces, and one trailing newline."""
    path = tmp_path / "store.txt"

    assert _run(monkeypatch, ["kv", str(path), "set", "colour", "red"]) == 0

    assert path.read_bytes() == b"colour\tred\n"


def test_a_new_key_is_appended_after_the_ones_already_there(monkeypatch, tmp_path):
    """File order is insertion order; only list sorts."""
    path = tmp_path / "store.txt"

    for key, value in (("zed", "1"), ("ann", "2"), ("mid", "3")):
        assert _run(monkeypatch, ["kv", str(path), "set", key, value]) == 0

    assert path.read_text(encoding="utf-8") == "zed\t1\nann\t2\nmid\t3\n"


def test_setting_an_existing_key_replaces_the_value_without_moving_it(monkeypatch, tmp_path):
    """The contract's one clause about position: replaced in place, not re-appended."""
    path = _store(tmp_path, "a\t1\nb\t2\nc\t3\n")

    assert _run(monkeypatch, ["kv", path, "set", "a", "changed"]) == 0

    assert tmp_path.joinpath("store.txt").read_text(encoding="utf-8") == "a\tchanged\nb\t2\nc\t3\n"


def test_setting_a_key_twice_leaves_one_pair(monkeypatch, capsys, tmp_path):
    """A second set is a replacement, never a second line with the same key."""
    path = _store(tmp_path)

    for value in ("red", "blue"):
        assert _run(monkeypatch, ["kv", path, "set", "colour", value]) == 0

    capsys.readouterr()
    assert _run(monkeypatch, ["kv", path, "list"]) == 0
    assert capsys.readouterr().out == "colour\tblue\n"


def test_get_prints_the_value_alone_and_nothing_else(monkeypatch, capsys, tmp_path):
    """No key, no quotes, no label: the value and one newline."""
    path = _store(tmp_path, "colour\tred\nsize\tbig\n")

    assert _run(monkeypatch, ["kv", path, "get", "size"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "big\n"
    assert captured.err == ""


def test_delete_removes_that_pair_and_leaves_the_rest(monkeypatch, capsys, tmp_path):
    """Exit 0, nothing printed, and the other two lines untouched in order."""
    path = _store(tmp_path, "a\t1\nb\t2\nc\t3\n")

    assert _run(monkeypatch, ["kv", path, "delete", "b"]) == 0

    assert capsys.readouterr().out == ""
    assert tmp_path.joinpath("store.txt").read_text(encoding="utf-8") == "a\t1\nc\t3\n"


def test_deleting_the_last_pair_leaves_an_empty_file_not_a_missing_one(monkeypatch, tmp_path):
    """An empty store is a store; a deleted file would refuse the next list."""
    path = _store(tmp_path, "only\t1\n")

    assert _run(monkeypatch, ["kv", path, "delete", "only"]) == 0

    store_file = tmp_path / "store.txt"
    assert store_file.exists()
    assert store_file.read_bytes() == b""


def test_an_empty_value_is_stored_and_read_back(monkeypatch, capsys, tmp_path):
    """'k<tab>' is still a key, a tab and a value. The empty KEY stays refused."""
    path = _store(tmp_path)

    assert _run(monkeypatch, ["kv", path, "set", "blank", ""]) == 0
    assert tmp_path.joinpath("store.txt").read_bytes() == b"blank\t\n"

    capsys.readouterr()
    assert _run(monkeypatch, ["kv", path, "get", "blank"]) == 0
    assert capsys.readouterr().out == "\n"


def test_a_value_is_stored_verbatim(monkeypatch, capsys, tmp_path):
    """Markup, leading and trailing spaces, non-ASCII: caller data, not display text."""
    path = _store(tmp_path)
    value = "  [bold]zoë[/bold]  "

    assert _run(monkeypatch, ["kv", path, "set", "k", value]) == 0
    capsys.readouterr()

    assert _run(monkeypatch, ["kv", path, "get", "k"]) == 0
    assert capsys.readouterr().out == value + "\n"


# =============================================================================
# WHAT LIST PRINTS
# =============================================================================


def test_list_prints_key_tab_value_one_pair_per_line(monkeypatch, capsys, tmp_path):
    """The separator is one tab byte. The shared console would make it spaces."""
    path = _store(tmp_path, "colour\tred\nsize\tbig\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out == "colour\tred\nsize\tbig\n"


def test_list_sorts_by_key_in_ascending_code_point_order(monkeypatch, capsys, tmp_path):
    """'Z' before 'a' - a case-folding or locale sort would put them the other way."""
    path = _store(tmp_path, "a\t1\nZ\t2\nB\t3\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out.splitlines() == ["B\t3", "Z\t2", "a\t1"]


def test_list_does_not_print_the_file_order(monkeypatch, capsys, tmp_path):
    """Sorted, not as written: these two orders disagree on every line."""
    path = _store(tmp_path, "zed\t1\nann\t2\nmid\t3\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out.splitlines() == ["ann\t2", "mid\t3", "zed\t1"]


def test_list_of_an_empty_store_prints_nothing(monkeypatch, capsys, tmp_path):
    """The file is there and holds no pairs: a result, not a refusal."""
    path = _store(tmp_path, "")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_list_leaves_the_store_alone(monkeypatch, tmp_path):
    """A read verb rewrites nothing - the bytes are identical afterwards."""
    path = _store(tmp_path, "b\t2\na\t1\n")
    before = tmp_path.joinpath("store.txt").read_bytes()

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert tmp_path.joinpath("store.txt").read_bytes() == before


# =============================================================================
# THE JSON FORM
# =============================================================================


def test_json_list_prints_one_object_and_nothing_else(monkeypatch, capsys, tmp_path):
    """One line, parseable whole, with every pair in it."""
    path = _store(tmp_path, "colour\tred\nsize\tbig\n")

    assert _run(monkeypatch, ["kv", "--json", path, "list"]) == 0

    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out) == {"colour": "red", "size": "big"}


def test_json_list_keeps_the_sorted_key_order(monkeypatch, capsys, tmp_path):
    """Members in the same order list prints them, not the file's order."""
    path = _store(tmp_path, "zed\t1\nann\t2\nmid\t3\n")

    assert _run(monkeypatch, ["kv", "--json", path, "list"]) == 0

    assert list(json.loads(capsys.readouterr().out)) == ["ann", "mid", "zed"]


def test_json_list_of_an_empty_store_prints_an_empty_object(monkeypatch, capsys, tmp_path):
    """{} not nothing: a caller reading zero bytes cannot parse an empty answer."""
    path = _store(tmp_path, "")

    assert _run(monkeypatch, ["kv", "--json", path, "list"]) == 0

    assert capsys.readouterr().out == "{}\n"


def test_json_list_does_not_escape_non_ascii(monkeypatch, capsys, tmp_path):
    """ensure_ascii=False, like every other JSON form in this branch."""
    path = _store(tmp_path, "name\tzoë\n")

    assert _run(monkeypatch, ["kv", "--json", path, "list"]) == 0

    assert "zoë" in capsys.readouterr().out


def test_json_carries_a_value_a_tab_would_have_broken(monkeypatch, capsys, tmp_path):
    """The JSON form is the one a caller parses; a value with a space is intact."""
    path = _store(tmp_path, "note\ttwo words\n")

    assert _run(monkeypatch, ["kv", "--json", path, "list"]) == 0

    assert json.loads(capsys.readouterr().out) == {"note": "two words"}


# =============================================================================
# REFUSALS - THE ARGUMENTS
# =============================================================================


def test_no_file_is_refused(monkeypatch, capsys):
    """'kv --json' has a flag and no store to apply it to."""
    assert "no FILE given" in _refused(monkeypatch, capsys, ["kv", "--json"])


def test_no_verb_is_refused_as_its_own_reason(monkeypatch, capsys, tmp_path):
    """A missing verb is named as missing, not as 'not a kv verb'."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "a\t1\n")])

    assert "no verb given" in reason
    assert "set, get, delete, list" in reason


@pytest.mark.parametrize("verb", ["frobnicate", "SET", "put", "--version"])
def test_a_verb_that_is_not_one_of_the_four_is_refused(monkeypatch, capsys, tmp_path, verb):
    """Including the near misses: the wrong case, a synonym, another flag."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "a\t1\n"), verb])

    assert f"'{verb}' is not a kv verb" in reason


def test_set_with_no_value_is_refused(monkeypatch, capsys, tmp_path):
    """Named by the contract. The key is quoted back so the caller sees which."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path), "set", "colour"])

    assert "set with no VALUE" in reason
    assert "colour" in reason


def test_set_with_no_key_or_value_is_refused(monkeypatch, capsys, tmp_path):
    """Neither argument given is a different reason from a value missing."""
    assert "needs a KEY and a VALUE" in _refused(monkeypatch, capsys, ["kv", _store(tmp_path), "set"])


@pytest.mark.parametrize("verb", ["get", "delete"])
def test_get_and_delete_with_no_key_are_refused(monkeypatch, capsys, tmp_path, verb):
    """The contract names set's missing VALUE; the same hole on the other verbs."""
    assert "needs a KEY" in _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "a\t1\n"), verb])


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["list", "extra"],
        ["get", "a", "extra"],
        ["delete", "a", "extra"],
        ["set", "a", "1", "extra"],
    ],
)
def test_too_many_arguments_is_refused(monkeypatch, capsys, tmp_path, argv_tail):
    """Every verb has a fixed arity; a stray word is never silently dropped."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "a\t1\n"), *argv_tail])

    assert "too many arguments" in reason
    assert "extra" in reason


@pytest.mark.parametrize("verb", ["set", "get", "delete"])
def test_json_on_any_verb_but_list_is_refused(monkeypatch, capsys, tmp_path, verb):
    """The contract defines --json for list only; the others have no JSON shape."""
    path = _store(tmp_path, "a\t1\n")
    reason = _refused(monkeypatch, capsys, ["kv", "--json", path, verb, "a", "1"])

    assert "--json is only for list" in reason


def test_a_refused_call_writes_nothing_to_the_store(monkeypatch, capsys, tmp_path):
    """A bad set must not half-create the file it was pointed at."""
    path = tmp_path / "store.txt"

    assert _run(monkeypatch, ["kv", str(path), "set", "colour"]) == 2

    capsys.readouterr()
    assert not path.exists()


# =============================================================================
# REFUSALS - THE KEY AND THE VALUE
# =============================================================================


@pytest.mark.parametrize("verb", ["set", "get", "delete"])
def test_an_empty_key_is_refused_on_every_verb_that_takes_one(monkeypatch, capsys, tmp_path, verb):
    """Named by the contract, and checked before the store is even opened."""
    path = _store(tmp_path, "a\t1\n")

    argv = ["kv", path, verb, "", "1"] if verb == "set" else ["kv", path, verb, ""]

    assert "KEY is empty" in _refused(monkeypatch, capsys, argv)


@pytest.mark.parametrize(
    ("key", "named"),
    [("a\tb", "a tab"), ("a\nb", "a newline"), ("a\rb", "a carriage return")],
)
def test_a_key_carrying_a_separator_is_refused(monkeypatch, capsys, tmp_path, key, named):
    """The tab and the newline are the contract's; the carriage return is the ruling."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path), "set", key, "1"])

    assert f"KEY contains {named}" in reason


@pytest.mark.parametrize(
    ("value", "named"),
    [("a\tb", "a tab"), ("a\nb", "a newline"), ("a\rb", "a carriage return")],
)
def test_a_value_carrying_a_separator_is_refused(monkeypatch, capsys, tmp_path, value, named):
    """The ruling: never write a store this command would then refuse to read."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path), "set", "k", value])

    assert f"VALUE contains {named}" in reason


def test_a_bad_key_is_refused_before_the_store_is_read(monkeypatch, capsys, tmp_path):
    """An unreadable store and an unstorable key: the key is what gets named."""
    path = _store(tmp_path, "\xff not utf-8")
    tmp_path.joinpath("store.txt").write_bytes(b"\xff\xfe\x00")

    assert "KEY contains a tab" in _refused(monkeypatch, capsys, ["kv", path, "get", "a\tb"])


@pytest.mark.parametrize("verb", ["get", "delete"])
def test_a_key_the_store_does_not_hold_is_refused(monkeypatch, capsys, tmp_path, verb):
    """Named by the contract, for both verbs that look one up."""
    path = _store(tmp_path, "colour\tred\n")

    assert "no such key" in _refused(monkeypatch, capsys, ["kv", path, verb, "size"])


def test_a_failed_delete_leaves_the_store_untouched(monkeypatch, capsys, tmp_path):
    """The refusal comes before the rewrite, so nothing is lost to a typo."""
    path = _store(tmp_path, "colour\tred\n")
    before = tmp_path.joinpath("store.txt").read_bytes()

    assert _run(monkeypatch, ["kv", path, "delete", "size"]) == 2

    capsys.readouterr()
    assert tmp_path.joinpath("store.txt").read_bytes() == before


# =============================================================================
# REFUSALS - THE FILE
# =============================================================================


@pytest.mark.parametrize("verb_args", [["get", "a"], ["delete", "a"], ["list"]])
def test_a_store_that_is_not_there_is_refused(monkeypatch, capsys, tmp_path, verb_args):
    """The ruling: a missing store is not an empty one. Only set may create it."""
    missing = str(tmp_path / "nope.txt")

    assert "store not found" in _refused(monkeypatch, capsys, ["kv", missing, *verb_args])


def test_a_directory_named_as_the_store_is_refused(monkeypatch, capsys, tmp_path):
    """'Exists but cannot be read', in the form every platform can produce."""
    directory = tmp_path / "adir"
    directory.mkdir()

    assert "cannot read" in _refused(monkeypatch, capsys, ["kv", str(directory), "list"])


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="chmod cannot deny a windows owner or root")
def test_a_store_that_cannot_be_opened_is_refused(monkeypatch, capsys, tmp_path):
    """Skipped on the environment's marker, never on the file under test."""
    path = _store(tmp_path, "a\t1\n")
    os.chmod(path, 0o000)

    try:
        assert "cannot read" in _refused(monkeypatch, capsys, ["kv", path, "list"])
    finally:
        os.chmod(path, 0o600)


def test_a_store_that_is_not_utf8_is_refused(monkeypatch, capsys, tmp_path):
    """Named by the contract, with the byte offset the decoder gave."""
    path = tmp_path / "store.txt"
    path.write_bytes(b"a\t1\n\xff\xfe\n")

    assert "not valid UTF-8" in _refused(monkeypatch, capsys, ["kv", str(path), "list"])


@pytest.mark.parametrize(
    ("content", "found"),
    [("a1\n", "no tab"), ("a\t1\t2\n", "2 tabs"), ("a\t1\n\nb\t2\n", "no tab")],
)
def test_a_line_that_is_not_a_key_a_tab_and_a_value_is_refused(monkeypatch, capsys, tmp_path, content, found):
    """A line with no tab, one with two, and a blank line in the middle."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path, content), "list"])

    assert "is not a key, a tab and a value" in reason
    assert found in reason


def test_a_line_with_an_empty_key_is_refused(monkeypatch, capsys, tmp_path):
    """The store's only structure is in the first field; a line may not start with the tab."""
    assert "empty key" in _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "\tvalue\n"), "list"])


def test_a_repeated_key_is_refused_naming_both_lines(monkeypatch, capsys, tmp_path):
    """The ruling: last-wins would silently drop a pair somebody else wrote."""
    reason = _refused(monkeypatch, capsys, ["kv", _store(tmp_path, "a\t1\nb\t2\na\t3\n"), "list"])

    assert "line 3 repeats the key 'a'" in reason
    assert "first on line 1" in reason


def test_a_store_that_will_not_parse_is_not_overwritten_by_set(monkeypatch, capsys, tmp_path):
    """The load-bearing one: a command that repairs a file it cannot read destroys it."""
    path = _store(tmp_path, "a\t1\nbroken line\n")
    before = tmp_path.joinpath("store.txt").read_bytes()

    assert _run(monkeypatch, ["kv", path, "set", "new", "2"]) == 2

    capsys.readouterr()
    assert tmp_path.joinpath("store.txt").read_bytes() == before


def test_set_into_a_directory_that_is_not_there_is_refused(monkeypatch, capsys, tmp_path):
    """Creating the file is in the contract; building a directory tree is not."""
    missing = str(tmp_path / "nodir" / "store.txt")

    assert "the directory" in _refused(monkeypatch, capsys, ["kv", missing, "set", "a", "1"])


# =============================================================================
# THE FILE FORMAT AT ITS EDGES
# =============================================================================


def test_a_store_written_with_crlf_reads_the_same_as_one_with_lf(monkeypatch, capsys, tmp_path):
    """The ruling: one trailing carriage return per line is a line ending, not data."""
    path = _store(tmp_path, "colour\tred\r\nsize\tbig\r\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out == "colour\tred\nsize\tbig\n"


def test_a_value_holding_a_vertical_tab_is_one_pair_not_two_lines(monkeypatch, capsys, tmp_path):
    """Only \\n ends a line. splitlines() would break here and read a bogus second line."""
    path = _store(tmp_path, "note\tone\vtwo\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out == "note\tone\vtwo\n"


def test_a_line_separator_inside_a_value_does_not_split_the_store(monkeypatch, capsys, tmp_path):
    """\\u2028 is a line boundary to splitlines() and an ordinary character here."""
    path = _store(tmp_path, "note\tone two\n")

    assert _run(monkeypatch, ["kv", path, "get", "note"]) == 0

    assert capsys.readouterr().out == "one two\n"


def test_a_store_with_no_final_newline_is_read_whole(monkeypatch, capsys, tmp_path):
    """Somebody else's file: an unterminated last line is how half of them end."""
    path = _store(tmp_path, "a\t1\nb\t2")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out == "a\t1\nb\t2\n"


def test_the_terminator_is_restored_by_the_next_write(monkeypatch, tmp_path):
    """Reading an unterminated store is tolerated; writing one back is not."""
    path = _store(tmp_path, "a\t1")

    assert _run(monkeypatch, ["kv", path, "set", "b", "2"]) == 0

    assert tmp_path.joinpath("store.txt").read_bytes() == b"a\t1\nb\t2\n"


def test_keys_sort_by_code_point_not_by_locale(monkeypatch, capsys, tmp_path):
    """Non-ASCII keys: 'z' sorts before 'ä' because U+007A is below U+00E4."""
    path = _store(tmp_path, "ä\t1\nz\t2\n")

    assert _run(monkeypatch, ["kv", path, "list"]) == 0

    assert capsys.readouterr().out.splitlines() == ["z\t2", "ä\t1"]


# =============================================================================
# THE WRITE ITSELF
# =============================================================================


def test_a_write_leaves_no_temporary_file_behind(monkeypatch, tmp_path):
    """The store is swapped in from a sibling temp file; the sibling must not survive."""
    # Its own directory: the conftest seam puts a json sandbox in tmp_path, so
    # listing tmp_path itself would measure the fixture rather than the write.
    directory = tmp_path / "kvdir"
    directory.mkdir()
    path = directory / "store.txt"

    assert _run(monkeypatch, ["kv", str(path), "set", "a", "1"]) == 0

    assert [entry.name for entry in directory.iterdir()] == ["store.txt"]


@pytest.mark.skipif(os.name != "posix", reason="file modes are a posix idea")
def test_a_created_store_gets_the_mode_the_umask_would_give_it(monkeypatch, tmp_path):
    """Measured 2026-09-20: without the correction a new store landed 0600."""
    path = tmp_path / "store.txt"

    assert _run(monkeypatch, ["kv", str(path), "set", "a", "1"]) == 0

    umask = os.umask(0)
    os.umask(umask)
    assert path.stat().st_mode & 0o777 == 0o666 & ~umask


@pytest.mark.skipif(os.name != "posix", reason="file modes are a posix idea")
def test_an_existing_store_keeps_its_own_mode(monkeypatch, tmp_path):
    """A store the caller made group-readable does not go private on its next write."""
    path = tmp_path / "store.txt"
    path.write_text("a\t1\n", encoding="utf-8")
    os.chmod(path, 0o640)

    assert _run(monkeypatch, ["kv", str(path), "set", "b", "2"]) == 0

    assert path.stat().st_mode & 0o777 == 0o640


# =============================================================================
# THE FLAGS: --json IN FIRST POSITION, HELP ANYWHERE
# =============================================================================


def test_bare_kv_prints_the_usage_and_exits_zero(monkeypatch, capsys):
    """No arguments is a question, not a mistake."""
    assert _run(monkeypatch, ["kv"]) == 0

    out = capsys.readouterr().out
    assert "kv Module" in out
    assert "set KEY VALUE" in out


@pytest.mark.parametrize("form", ["--help", "-h", "help"])
def test_every_help_spelling_prints_the_page_and_touches_no_store(monkeypatch, capsys, tmp_path, form):
    """Help is a first-position flag, and it never creates the file."""
    # Not tmp_path itself: the conftest seam writes its json sandbox there.
    directory = tmp_path / "kvdir"
    directory.mkdir()
    monkeypatch.chdir(directory)

    assert _run(monkeypatch, ["kv", form]) == 0

    assert "Refusals (exit 2)" in capsys.readouterr().out
    assert list(directory.iterdir()) == []


def test_json_after_the_file_is_not_a_flag(monkeypatch, capsys, tmp_path):
    """The ruling: --json is read as a flag in first position only."""
    path = _store(tmp_path, "a\t1\n")

    assert "too many arguments" in _refused(monkeypatch, capsys, ["kv", path, "list", "--json"])


def test_a_key_spelled_like_a_flag_is_stored_not_obeyed(monkeypatch, capsys, tmp_path):
    """'set --json red' files a key named --json. Caller data is not a switch."""
    path = _store(tmp_path)

    assert _run(monkeypatch, ["kv", path, "set", "--json", "red"]) == 0

    assert tmp_path.joinpath("store.txt").read_bytes() == b"--json\tred\n"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["--help"],
        ["list", "-h"],
        ["get", "--help"],
        ["delete", "--help"],
        ["set", "--help", "red"],
        ["set", "colour", "--help"],
    ],
)
def test_a_help_flag_anywhere_explains_and_never_executes(monkeypatch, capsys, tmp_path, argv_tail):
    """A question must never execute, including in a position that would be data.

    The opposite ruling - a flag is only a flag in first position - was written
    first and then withdrawn: 'set --help colour' would have stored a pair in
    answer to a question, which is the harm @seedgo's help_flag_safety standard
    exists for. The cost is that a key spelled --help cannot be set from here.
    """
    path = _store(tmp_path, "colour\tred\n")
    before = tmp_path.joinpath("store.txt").read_bytes()

    assert _run(monkeypatch, ["kv", path, *argv_tail]) == 0

    assert "Refusals (exit 2)" in capsys.readouterr().out
    assert tmp_path.joinpath("store.txt").read_bytes() == before


def test_the_bare_word_help_is_only_read_in_first_position(monkeypatch, capsys, tmp_path):
    """'help' is a plausible VALUE, so only the two flag spellings travel."""
    path = _store(tmp_path)

    assert _run(monkeypatch, ["kv", path, "set", "greeting", "help"]) == 0

    assert tmp_path.joinpath("store.txt").read_bytes() == b"greeting\thelp\n"
    assert capsys.readouterr().out == ""


def test_a_value_spelled_like_a_flag_survives_the_round_trip(monkeypatch, capsys, tmp_path):
    """The other half of the same ruling: a value is not read as a switch either."""
    path = _store(tmp_path)

    assert _run(monkeypatch, ["kv", path, "set", "flag", "--json"]) == 0
    capsys.readouterr()

    assert _run(monkeypatch, ["kv", path, "get", "flag"]) == 0
    assert capsys.readouterr().out == "--json\n"


# =============================================================================
# THE HANDLER'S OWN SURFACE
# =============================================================================


def test_the_handler_refusal_carries_its_reason(tmp_path):
    """StoreInvalid is what the module catches; the reason is what it prints."""
    with pytest.raises(store.StoreInvalid) as raised:
        store.read_pairs(tmp_path / "nope.txt")

    assert raised.value.reason == f"store not found: {tmp_path / 'nope.txt'}"


def test_list_pairs_sorts_what_read_pairs_leaves_in_file_order(tmp_path):
    """Two functions, two orders - the sort belongs to list, not to the read."""
    path = tmp_path / "store.txt"
    path.write_text("zed\t1\nann\t2\n", encoding="utf-8")

    assert store.read_pairs(path) == [("zed", "1"), ("ann", "2")]
    assert store.list_pairs(path) == [("ann", "2"), ("zed", "1")]
