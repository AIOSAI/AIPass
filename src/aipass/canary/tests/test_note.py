# =================== AIPass ====================
# Name: test_note.py
# Description: Tests for the note store - add, list, and refusing a store that will not parse
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-09-12
# =============================================

"""Tests for `drone @canary note`.

Driven through the entry point's main() with real module discovery, so the
exit codes asserted here are the ones drone hands back to a caller.

The load-bearing tests are the corrupt-store ones: a store that will not parse
must be refused by file name with a non-zero exit, and its bytes AND mtime must
be exactly what they were. Losing stored notes to one bad read is the failure
the contract exists to prevent, so "did not crash" is not the assertion.
"""

import json
import sys
from datetime import datetime

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.notes import store

VALID_LINE = b'{"text": "kept", "timestamp": "2026-09-12T15:00:00-07:00"}\n'

CORRUPT_STORES = {
    "not_json": b"this is not json\n",
    "torn_final_record": VALID_LINE + b'{"text": "b", "time',
    "record_without_terminator": VALID_LINE.rstrip(b"\n"),
    # The one unterminated store whose last line is still valid JSON: without
    # the terminator guard it lists clean and the next add glues two records
    # onto one line. The two cases above are refused even with the guard
    # deleted (chopping their final byte breaks the JSON), so only this case
    # measures the guard - mutant M5, 2026-09-12.
    "valid_record_then_space_no_terminator": VALID_LINE.rstrip(b"\n") + b" ",
    "json_but_not_a_record": VALID_LINE + b"[1, 2, 3]\n",
    "missing_timestamp": b'{"text": "a"}\n',
    "non_string_text": b'{"text": 7, "timestamp": "2026-09-12T15:00:00-07:00"}\n',
    "blank_line_inside": VALID_LINE + b"\n" + VALID_LINE,
    "not_utf8": b"\xff\xfe\xfd\n",
}


@pytest.fixture
def store_path(tmp_path, monkeypatch):
    """Point the store at a temp docs.local/ so no test touches the real one."""
    path = tmp_path / "docs.local" / "notes.jsonl"
    monkeypatch.setattr(store, "STORE_PATH", path)
    return path


def _run(monkeypatch, argv):
    """Invoke the entry point with a synthetic argv, real discovery."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


def _squash(text):
    """Remove all whitespace - Rich wraps long paths at the console width."""
    return "".join(text.split())


# =============================================================================
# WHERE THE STORE LIVES
# =============================================================================


def test_default_store_is_in_this_branch_under_docs_local():
    """The real store path sits inside canary, in docs.local/."""
    branch_root = canary_entry.MODULES_DIR.parent.parent

    assert store.BRANCH_ROOT == branch_root
    assert store.STORE_PATH.relative_to(branch_root).parts == ("docs.local", "notes.jsonl")


def test_docs_local_is_ignored_by_the_repo_gitignore():
    """docs.local/ is what keeps the store out of git - pin the rule itself."""
    gitignore = store.BRANCH_ROOT.parents[2] / ".gitignore"

    assert "docs.local/" in gitignore.read_text(encoding="utf-8").splitlines()


# =============================================================================
# ADD AND LIST
# =============================================================================


def test_add_then_list_prints_records_in_order_with_index_and_timestamp(monkeypatch, capsys, store_path):
    """Two adds, one list: both notes, in order, each with index and its own timestamp."""
    assert _run(monkeypatch, ["note", "add", "first note"]) == 0
    assert _run(monkeypatch, ["note", "add", "second note"]) == 0
    capsys.readouterr()

    assert _run(monkeypatch, ["note", "list"]) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    records = [json.loads(line) for line in store_path.read_text(encoding="utf-8").splitlines()]
    assert lines == [
        f"1. [{records[0]['timestamp']}] first note",
        f"2. [{records[1]['timestamp']}] second note",
    ]


def test_add_appends_exactly_one_record_and_keeps_prior_bytes(monkeypatch, capsys, store_path):
    """A second add leaves the first record's bytes as a prefix and adds one line."""
    assert _run(monkeypatch, ["note", "add", "one"]) == 0
    before = store_path.read_bytes()

    assert _run(monkeypatch, ["note", "add", "two"]) == 0
    after = store_path.read_bytes()
    capsys.readouterr()

    assert after.startswith(before)
    assert after.count(b"\n") == before.count(b"\n") + 1
    record = json.loads(after[len(before) :])
    assert sorted(record) == ["text", "timestamp"]
    assert record["text"] == "two"
    assert datetime.fromisoformat(record["timestamp"]).tzinfo is not None


def test_multi_word_and_multi_line_text_round_trip(monkeypatch, capsys, store_path):
    """Unquoted words join with a space; a newline inside a note stays inside one record."""
    assert _run(monkeypatch, ["note", "add", "hello", "world"]) == 0
    assert _run(monkeypatch, ["note", "add", "line one\nline two [bold]x[/bold]"]) == 0
    capsys.readouterr()

    assert store_path.read_bytes().count(b"\n") == 2
    assert [r["text"] for r in store.read_notes(store_path)] == ["hello world", "line one\nline two [bold]x[/bold]"]


def test_list_on_a_missing_store_answers_and_creates_nothing(monkeypatch, capsys, store_path):
    """No store yet is an empty list, exit 0 - and listing does not create the file."""
    assert _run(monkeypatch, ["note", "list"]) == 0

    assert "No notes yet" in capsys.readouterr().out
    assert not store_path.parent.exists()


# =============================================================================
# THE CONTRACT: A STORE THAT WILL NOT PARSE IS REFUSED, NEVER REWRITTEN
# =============================================================================


@pytest.mark.parametrize("subcommand", [["list"], ["add", "must not land"]])
@pytest.mark.parametrize("content", list(CORRUPT_STORES.values()), ids=list(CORRUPT_STORES))
def test_corrupt_store_is_refused_by_name_and_left_untouched(monkeypatch, capsys, store_path, subcommand, content):
    """Refused non-zero, the file named in the message, bytes and mtime unchanged."""
    store_path.parent.mkdir(parents=True)
    store_path.write_bytes(content)
    mtime_before = store_path.stat().st_mtime_ns

    result = _run(monkeypatch, ["note", *subcommand])

    err = capsys.readouterr().err
    assert result == 2
    assert _squash(str(store_path)) in _squash(err)
    assert "will not parse" in err
    assert store_path.read_bytes() == content
    assert store_path.stat().st_mtime_ns == mtime_before


def test_refusal_does_not_happen_for_a_valid_store(monkeypatch, capsys, store_path):
    """Control for the test above: the same seeding with a VALID line lists and adds."""
    store_path.parent.mkdir(parents=True)
    store_path.write_bytes(VALID_LINE)

    assert _run(monkeypatch, ["note", "list"]) == 0
    assert _run(monkeypatch, ["note", "add", "second"]) == 0

    assert "will not parse" not in capsys.readouterr().err
    assert [r["text"] for r in store.read_notes(store_path)] == ["kept", "second"]


def test_a_store_path_that_is_not_a_file_is_refused_nonzero(monkeypatch, capsys, store_path):
    """A directory where the store should be cannot be read - refused, left in place."""
    store_path.mkdir(parents=True)

    assert _run(monkeypatch, ["note", "list"]) == 2
    assert _run(monkeypatch, ["note", "add", "x"]) == 2

    assert _squash(str(store_path)) in _squash(capsys.readouterr().err)
    assert store_path.is_dir()


# =============================================================================
# ARGUMENT REFUSALS AND HELP
# =============================================================================


@pytest.mark.parametrize("words", [[], ["   "]], ids=["no_text", "blank_text"])
def test_add_without_text_is_refused_and_writes_nothing(monkeypatch, capsys, store_path, words):
    """An empty note is a refusal, not an empty record."""
    assert _run(monkeypatch, ["note", "add", *words]) == 2

    assert "needs text" in capsys.readouterr().err
    assert not store_path.exists()


@pytest.mark.parametrize(
    "argv",
    [["note", "bogus"], ["note", "list", "extra"]],
    ids=["unknown_subcommand", "list_with_arguments"],
)
def test_bad_note_arguments_exit_nonzero(monkeypatch, capsys, store_path, argv):
    """A routed command that refuses must not exit 0."""
    assert _run(monkeypatch, argv) == 2

    assert capsys.readouterr().err.strip()


@pytest.mark.parametrize(
    "argv",
    [["note", "--help"], ["note", "help"], ["note", "add", "--help"], ["note", "add", "text", "-h"]],
    ids=["note_help_flag", "note_help_word", "add_help_flag", "trailing_short_flag"],
)
def test_help_never_writes_a_note(monkeypatch, capsys, store_path, argv):
    """Help anywhere in the arguments explains the command and stores nothing."""
    assert _run(monkeypatch, argv) == 0

    assert "Usage:" in capsys.readouterr().out
    assert not store_path.exists()
