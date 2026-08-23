# =================== AIPass ====================
# Name: test_compass_command.py
# Description: Tests for the compass module command router (FPLAN P2)
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-06-16
# =============================================

"""Tests for the compass command router (FPLAN-0212 P2).

These exercise the thin command layer (``apps/modules/compass.py``) end to
end against a real temp SQLite store via the ``--db`` flag — the same path the
live ``drone @devpulse compass`` invocation takes. Everything goes through the
module entry point (``handle_command``): the round-trip (add -> query -> see
rating) is driven and asserted entirely via the command's own console output,
so the storage handler is never reached into directly.
"""

import re
from pathlib import Path

import pytest

from aipass.devpulse.apps.modules import compass as compass_cmd


@pytest.fixture
def db(tmp_path: Path) -> str:
    """A temp DB path string, passed through to the command via --db."""
    return str(tmp_path / "compass_cmd_test.db")


def _output(capsys) -> str:
    """Combined stdout+stderr (err_console / error() route to stderr)."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _add(capsys, db, context, decision, rating, *extra) -> int:
    """Drive an add through the command entry point; return the new id.

    The id is parsed from the command's own ``#<id>`` confirmation line — we
    never reach into the storage handler.
    """
    capsys.readouterr()  # isolate this add's output
    compass_cmd.handle_command("compass", ["add", context, decision, "--rating", rating, "--db", db, *extra])
    out = _output(capsys)
    match = re.search(r"#(\d+)", out)
    assert match, f"add did not report a new id; output was: {out!r}"
    return int(match.group(1))


def _query_out(capsys, db, query, *extra) -> str:
    """Run a query via the command and return its captured output (drained)."""
    capsys.readouterr()  # drop anything pending so we only see this query
    compass_cmd.handle_command("compass", ["query", query, "--db", db, *extra])
    return _output(capsys)


def _stats_out(capsys, db) -> str:
    """Run stats via the command and return its captured output (drained)."""
    capsys.readouterr()
    compass_cmd.handle_command("compass", ["stats", "--db", db])
    return _output(capsys)


# ---------------------------------------------------------------------------
# Routing basics
# ---------------------------------------------------------------------------


def test_rejects_unrelated_command():
    """Router returns False for commands that aren't 'compass'."""
    assert compass_cmd.handle_command("watchdog", []) is False


def test_no_args_shows_introspection(capsys):
    """Bare 'compass' shows introspection that mentions compass + subcommands."""
    assert compass_cmd.handle_command("compass", []) is True
    out = _output(capsys).lower()
    assert "compass" in out
    assert "add" in out and "query" in out


def test_help_flag_shows_usage(capsys):
    """--help prints usage covering every subcommand."""
    assert compass_cmd.handle_command("compass", ["--help"]) is True
    out = _output(capsys).lower()
    assert "usage" in out
    for sub in ("add", "query", "stats", "rate", "archive", "review"):
        assert sub in out


def test_unknown_subcommand_errors(capsys):
    """Unknown subcommand surfaces a clean error, still returns True."""
    assert compass_cmd.handle_command("compass", ["bogus"]) is True
    out = _output(capsys).lower()
    assert "bogus" in out or "unknown" in out


# ---------------------------------------------------------------------------
# add -> query round-trip (rating must be visible)
# ---------------------------------------------------------------------------


def test_add_then_query_shows_rating(capsys, db):
    """add stores a decision; query surfaces it with the [GOOD] rating tag."""
    assert (
        compass_cmd.handle_command(
            "compass",
            ["add", "auth fork", "chose JWT over sessions", "--rating", "good", "--note", "worked", "--db", db],
        )
        is True
    )
    add_out = _output(capsys)
    assert "GOOD" in add_out  # rating shown on add too

    assert compass_cmd.handle_command("compass", ["query", "JWT", "--db", db]) is True
    q_out = _output(capsys)
    assert "GOOD" in q_out  # the rating tag is the whole point
    assert "chose JWT over sessions" in q_out
    assert "auth fork" in q_out


def test_query_rating_filter(capsys, db):
    """--rating filters query results to the matching rating only."""
    compass_cmd.handle_command("compass", ["add", "ctx good", "good choice here", "--rating", "good", "--db", db])
    compass_cmd.handle_command("compass", ["add", "ctx bad", "bad choice here", "--rating", "bad", "--db", db])
    capsys.readouterr()  # drain add output

    assert compass_cmd.handle_command("compass", ["query", "choice", "--rating", "bad", "--db", db]) is True
    out = _output(capsys)
    assert "bad choice here" in out
    assert "good choice here" not in out


def test_add_persists_to_store(capsys, db):
    """add persists to the store; a later query surfaces it with its rating."""
    _add(capsys, db, "persist ctx", "persist decision", "interesting")

    out = _query_out(capsys, db, "persist")
    assert "INTERESTING" in out
    assert "persist decision" in out
    assert "1 result(s)" in out


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_reports_counts(capsys, db):
    """stats shows total plus by-rating / by-status breakdown."""
    compass_cmd.handle_command("compass", ["add", "c1", "d1", "--rating", "good", "--db", db])
    compass_cmd.handle_command("compass", ["add", "c2", "d2", "--rating", "bad", "--db", db])
    capsys.readouterr()

    assert compass_cmd.handle_command("compass", ["stats", "--db", db]) is True
    out = _output(capsys).lower()
    assert "total" in out
    assert "2" in out
    assert "good" in out and "bad" in out
    assert "active" in out


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------


def test_rate_changes_rating(capsys, db):
    """rate <id> <rating> re-rates an existing decision."""
    new_id = _add(capsys, db, "rate ctx", "rate decision", "good")

    assert compass_cmd.handle_command("compass", ["rate", str(new_id), "bad", "--db", db]) is True
    out = _output(capsys)
    assert "BAD" in out

    # Confirm the new rating sticks: querying the row now shows [BAD], not [GOOD].
    q_out = _query_out(capsys, db, "rate")
    assert "BAD" in q_out
    assert "GOOD" not in q_out


def test_rate_missing_id_warns(capsys, db):
    """rate on a non-existent id reports 'nothing changed', does not crash."""
    assert compass_cmd.handle_command("compass", ["rate", "999", "good", "--db", db]) is True
    out = _output(capsys).lower()
    assert "999" in out and ("nothing changed" in out or "no decision" in out)


def test_a_missing_id_flips_the_exit_code(capsys, db, monkeypatch):
    """'nothing changed' must not report success.

    It used ``warning``, which skips ``mark_command_failed``, so
    ``compass rate <id> good && <next step>`` ran the next step as if the
    rating had landed. Same defect @canary found in the owner gates on
    2026-08-22, in a verb nobody was looking at. Asserts the FAILURE MARK
    rather than the wording — the wording is for humans, the code is for
    everything else.
    """
    from aipass.cli.apps.modules import display as cli_display

    marks: list[int] = []
    monkeypatch.setattr(cli_display, "mark_command_failed", lambda: marks.append(1))

    for verb_args in (["rate", "999", "good"], ["archive", "999"], ["note", "999", "hello"]):
        marks.clear()
        assert compass_cmd.handle_command("compass", [*verb_args, "--db", db]) is True
        capsys.readouterr()
        assert marks, f"'{verb_args[0]}' on a missing id must mark the command failed"


def test_a_real_id_still_reports_success(capsys, db, monkeypatch):
    """The fix must not turn every rate into a failure."""
    from aipass.cli.apps.modules import display as cli_display

    did = _add(capsys, db, "ctx", "did the thing", "good")
    marks: list[int] = []
    monkeypatch.setattr(cli_display, "mark_command_failed", lambda: marks.append(1))

    assert compass_cmd.handle_command("compass", ["rate", str(did), "bad", "--db", db]) is True
    capsys.readouterr()
    assert marks == [], "a rating that landed must not mark the command failed"


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------


def test_archive_removes_from_query(capsys, db):
    """archive flips status; archived rows drop out of query, stats reflect it."""
    new_id = _add(capsys, db, "arch ctx", "arch decision", "good")

    assert compass_cmd.handle_command("compass", ["archive", str(new_id), "--db", db]) is True
    out = _output(capsys).lower()
    assert "archived" in out

    # Archived rows no longer surface in query...
    q_out = _query_out(capsys, db, "arch")
    assert "0 result(s)" in q_out
    assert "arch decision" not in q_out
    # ...but stats still count them under archived.
    s_out = _stats_out(capsys, db).lower()
    assert "archived" in s_out


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


def test_review_surfaces_a_decision(capsys, db):
    """review surfaces an active decision with its rating shown."""
    _add(capsys, db, "review ctx", "review decision", "impressive")

    capsys.readouterr()
    assert compass_cmd.handle_command("compass", ["review", "--db", db]) is True
    out = _output(capsys)
    assert "IMPRESSIVE" in out
    assert "review decision" in out


def test_review_empty_store(capsys, db):
    """review on an empty store reports nothing to review (no crash)."""
    assert compass_cmd.handle_command("compass", ["review", "--db", db]) is True
    out = _output(capsys).lower()
    assert "no active" in out or "nothing" in out


# ---------------------------------------------------------------------------
# Error surfacing — must fail loud, never silent
# ---------------------------------------------------------------------------


def test_bad_rating_error_surfaces(capsys, db):
    """add with an invalid rating surfaces the handler's ValueError message."""
    assert compass_cmd.handle_command("compass", ["add", "ctx", "decision", "--rating", "terrible", "--db", db]) is True
    out = _output(capsys).lower()
    assert "rating" in out and "terrible" in out
    # Nothing should have been stored — stats reports total 0.
    assert "total decisions: 0" in _stats_out(capsys, db).lower()


def test_add_requires_rating(capsys, db):
    """add without --rating fails loud."""
    assert compass_cmd.handle_command("compass", ["add", "ctx", "decision", "--db", db]) is True
    out = _output(capsys).lower()
    assert "rating" in out


def test_add_missing_positionals(capsys, db):
    """add with too few positional args shows usage, stores nothing."""
    assert compass_cmd.handle_command("compass", ["add", "only-context", "--rating", "good", "--db", db]) is True
    out = _output(capsys).lower()
    assert "usage" in out
    assert "total decisions: 0" in _stats_out(capsys, db).lower()


def test_query_bad_limit_errors(capsys, db):
    """query with a non-integer --limit fails loud."""
    assert compass_cmd.handle_command("compass", ["query", "anything", "--limit", "abc", "--db", db]) is True
    out = _output(capsys).lower()
    assert "limit" in out


def test_flag_without_value_errors(capsys, db):
    """A flag given without a following value fails loud (no silent swallow)."""
    assert compass_cmd.handle_command("compass", ["query", "x", "--rating"]) is True
    out = _output(capsys).lower()
    assert "rating" in out and "value" in out


# ---------------------------------------------------------------------------
# supersedes — atomic archive + link, both pointer directions
# ---------------------------------------------------------------------------


def test_add_supersedes_archives_and_links(capsys, db):
    """add --supersedes N archives #N, links the new row, shows 'supersedes #N'."""
    old = _add(capsys, db, "old ctx sessions", "use sessions", "good")
    capsys.readouterr()
    assert (
        compass_cmd.handle_command(
            "compass",
            [
                "add",
                "new ctx jwt",
                "switch to jwt",
                "--rating",
                "good",
                "--supersedes",
                str(old),
                "--db",
                db,
            ],
        )
        is True
    )
    out = _output(capsys)
    assert f"supersedes #{old}" in out

    # The archived row is gone from the default (active-only) query...
    q = _query_out(capsys, db, "sessions")
    assert "0 result(s)" in q

    # ...but --include-archived surfaces it WITH its status + forward pointer.
    q2 = _query_out(capsys, db, "sessions", "--include-archived")
    assert "ARCHIVED" in q2.upper()
    assert "superseded by #" in q2.lower()


def test_add_supersedes_bad_id_errors_no_write(capsys, db):
    """add --supersedes to a missing id errors and writes nothing."""
    capsys.readouterr()
    compass_cmd.handle_command(
        "compass",
        ["add", "ctx", "dec", "--rating", "good", "--supersedes", "9999", "--db", db],
    )
    out = _output(capsys).lower()
    assert "9999" in out
    assert "total decisions: 0" in _stats_out(capsys, db).lower()


def test_add_supersedes_non_integer_errors(capsys, db):
    """A non-integer --supersedes fails loud."""
    assert (
        compass_cmd.handle_command(
            "compass",
            ["add", "ctx", "dec", "--rating", "good", "--supersedes", "abc", "--db", db],
        )
        is True
    )
    out = _output(capsys).lower()
    assert "supersedes" in out and "integer" in out


# ---------------------------------------------------------------------------
# write-time conflict advisory — non-blocking
# ---------------------------------------------------------------------------


def test_add_conflict_advisory_prints_but_does_not_block(capsys, db):
    """An overlapping active row triggers an advisory; the add still succeeds."""
    _add(capsys, db, "caching layer strategy", "add redis caching", "good")
    capsys.readouterr()
    compass_cmd.handle_command(
        "compass",
        ["add", "caching approach again", "another caching layer", "--rating", "good", "--db", db],
    )
    out = _output(capsys)
    assert "possible conflict" in out.lower()
    assert "--supersedes" in out  # advisory hints the fix
    assert "Added decision" in out  # NON-BLOCKING: still added


def test_add_no_conflict_on_empty_store(capsys, db):
    """First add on an empty store prints no advisory."""
    capsys.readouterr()
    compass_cmd.handle_command("compass", ["add", "unique ctx", "unique dec", "--rating", "good", "--db", db])
    out = _output(capsys).lower()
    assert "possible conflict" not in out


# ---------------------------------------------------------------------------
# note — set a note, prove it is immediately searchable
# ---------------------------------------------------------------------------


def test_note_command_sets_and_is_searchable(capsys, db):
    """note <id> "text" sets the note; a later query finds the new note text."""
    did = _add(capsys, db, "note cmd ctx", "note cmd dec", "good")
    capsys.readouterr()
    assert compass_cmd.handle_command("compass", ["note", str(did), "findme pterodactyl", "--db", db]) is True
    out = _output(capsys).lower()
    assert "note set" in out

    q = _query_out(capsys, db, "pterodactyl")
    assert "1 result(s)" in q


def test_note_help(capsys):
    """compass note --help prints per-subcommand usage."""
    assert compass_cmd.handle_command("compass", ["note", "--help"]) is True
    out = _output(capsys).lower()
    assert "note" in out and "usage" in out


def test_note_missing_id_warns(capsys, db):
    """note on a non-existent id reports nothing changed, does not crash."""
    assert compass_cmd.handle_command("compass", ["note", "999", "text", "--db", db]) is True
    out = _output(capsys).lower()
    assert "999" in out and ("nothing changed" in out or "no decision" in out)


def test_note_missing_args_shows_usage(capsys, db):
    """note with too few args shows usage."""
    assert compass_cmd.handle_command("compass", ["note", "5", "--db", db]) is True
    out = _output(capsys).lower()
    assert "usage" in out


def test_help_and_introspection_list_note(capsys):
    """Both --help and bare introspection advertise the note subcommand."""
    compass_cmd.handle_command("compass", ["--help"])
    assert "note" in _output(capsys).lower()
    compass_cmd.handle_command("compass", [])
    assert "note" in _output(capsys).lower()


# ---------------------------------------------------------------------------
# --include-archived — archived hits must show status + supersession pointer
# ---------------------------------------------------------------------------


def test_include_archived_shows_archived_pointer(capsys, db):
    """--include-archived surfaces an archived row flagged with its successor."""
    old = _add(capsys, db, "archived-visible ctx", "the old choice", "bad")
    capsys.readouterr()
    compass_cmd.handle_command(
        "compass",
        [
            "add",
            "replacement ctx",
            "the new choice",
            "--rating",
            "good",
            "--supersedes",
            str(old),
            "--db",
            db,
        ],
    )
    capsys.readouterr()

    # Default query hides the archived row.
    q = _query_out(capsys, db, "old choice")
    assert "0 result(s)" in q

    # With the flag it appears, unmistakably marked archived + superseded.
    q2 = _query_out(capsys, db, "old choice", "--include-archived")
    assert "1 result(s)" in q2
    assert "archived" in q2.lower()
    assert "superseded by #" in q2.lower()
