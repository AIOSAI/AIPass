# =================== AIPass ====================
# Name: test_search.py
# Description: Unit tests for search handler, search queries, and log export
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/search/search_ops.py, search_queries.py, and log_export.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that search_ops.py, search_queries.py, and log_export.py parse and import

import sqlite3

from unittest.mock import patch, MagicMock


from aipass.commons.apps.handlers.search.search_ops import run_search

from aipass.commons.apps.handlers.search.search_queries import (
    search_posts,
    sync_post_to_fts,
)

from aipass.commons.apps.handlers.search.log_export import export_room_log

_OPS = "aipass.commons.apps.handlers.search.search_ops"


def _run_parsed(args: list) -> dict:
    """Run run_search with every query function recorded; return the result and the recorders."""
    with (
        patch(f"{_OPS}.json_handler", autospec=True),
        patch(f"{_OPS}.get_db") as mock_get_db,
        patch(f"{_OPS}.close_db"),
        patch(f"{_OPS}.search_all", return_value={"posts": [], "comments": []}) as mock_all,
        patch(f"{_OPS}.search_posts", return_value=[]) as mock_posts,
        patch(f"{_OPS}.search_comments", return_value=[]) as mock_comments,
    ):
        result = run_search(args)
    return {
        "result": result,
        "conn": mock_get_db.return_value,
        "get_db": mock_get_db,
        "all": mock_all,
        "posts": mock_posts,
        "comments": mock_comments,
    }


def test_run_search_refuses_an_empty_query():
    """An empty query is refused before any database round-trip."""
    seen = _run_parsed([""])
    assert seen["result"] == {"success": False, "error": "Search query cannot be empty"}
    seen["get_db"].assert_not_called()
    seen["all"].assert_not_called()
    seen["posts"].assert_not_called()
    seen["comments"].assert_not_called()


def test_parse_search_args_query_only():
    """First positional arg (not the last) is the search query; no filters, all types searched."""
    seen = _run_parsed(["hello world", "--type"])
    seen["all"].assert_called_once_with(seen["conn"], "hello world", room=None, author=None)
    assert seen["result"]["query"] == "hello world"


def test_parse_search_args_room_flag():
    """The --room flag should set the room filter and lowercase it."""
    seen = _run_parsed(["test", "--room", "General"])
    seen["all"].assert_called_once_with(seen["conn"], "test", room="general", author=None)


def test_parse_search_args_author_flag():
    """The --author flag should set the author filter and lowercase it."""
    seen = _run_parsed(["test", "--author", "DRONE"])
    seen["all"].assert_called_once_with(seen["conn"], "test", room=None, author="drone")


def test_parse_search_args_type_flag_valid():
    """The --type flag accepts 'posts' and 'comments', and each runs only its own query."""
    seen = _run_parsed(["test", "--type", "posts"])
    seen["posts"].assert_called_once_with(seen["conn"], "test", room=None, author=None)
    seen["all"].assert_not_called()
    seen["comments"].assert_not_called()

    seen = _run_parsed(["test", "--type", "comments"])
    seen["comments"].assert_called_once_with(seen["conn"], "test", author=None)
    seen["all"].assert_not_called()
    seen["posts"].assert_not_called()


def test_parse_search_args_type_flag_invalid():
    """A bogus --type searches posts and comments together, never one of them alone."""
    seen = _run_parsed(["test", "--type", "bogus"])
    seen["all"].assert_called_once_with(seen["conn"], "test", room=None, author=None)
    seen["posts"].assert_not_called()
    seen["comments"].assert_not_called()


def test_parse_search_args_all_flags():
    """All flags combined should be parsed; --type survives after --room and --author."""
    seen = _run_parsed(["registry", "--room", "Dev", "--author", "flow", "--type", "posts"])
    seen["posts"].assert_called_once_with(seen["conn"], "registry", room="dev", author="flow")
    assert seen["result"]["success"] is True


def test_parse_search_args_flag_without_value():
    """A flag at the end without a value should be skipped, not raise IndexError."""
    seen = _run_parsed(["test", "--room"])
    seen["all"].assert_called_once_with(seen["conn"], "test", room=None, author=None)


@patch("aipass.commons.apps.handlers.search.search_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.search.search_ops.close_db")
@patch("aipass.commons.apps.handlers.search.search_ops.get_db")
@patch("aipass.commons.apps.handlers.search.search_ops.search_all")
def test_run_search_no_args(
    mock_search_all: MagicMock,
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_json: MagicMock,
) -> None:
    """run_search with no args should return error with usage message."""
    result = run_search([])
    assert result["success"] is False
    assert result["error"].startswith("Usage")
    mock_get_db.assert_not_called()
    mock_search_all.assert_not_called()
    mock_close_db.assert_not_called()


@patch("aipass.commons.apps.handlers.search.search_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.search.search_ops.close_db")
@patch("aipass.commons.apps.handlers.search.search_ops.get_db")
@patch("aipass.commons.apps.handlers.search.search_ops.search_all")
def test_run_search_returns_results(
    mock_search_all: MagicMock,
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_json: MagicMock,
) -> None:
    """run_search with a valid query should delegate to search_all and return results."""
    mock_conn = MagicMock()
    mock_get_db.return_value = mock_conn
    mock_search_all.return_value = {
        "posts": [{"id": 1, "title": "Found"}],
        "comments": [],
    }

    result = run_search(["registry"])

    assert result["success"] is True
    assert result["query"] == "registry"
    assert len(result["posts"]) == 1
    assert result["posts"][0]["title"] == "Found"
    assert result["comments"] == []
    mock_close_db.assert_called_once_with(mock_conn)


def _log_comment_lines(conn: sqlite3.Connection, comments: list) -> list:
    """Seed one post in r/general with the given comments; return the exported log's comment lines.

    Each comment is (key, parent_key, author, content, vote_score); parent_key names an earlier key or None.
    """
    for agent in {c[2] for c in comments} | {"LOG_AUTHOR"}:
        conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)", (agent, agent))
    post_id = conn.execute(
        "INSERT INTO posts (title, content, room_name, author) VALUES (?, ?, ?, ?)",
        ("Log post", "body", "general", "LOG_AUTHOR"),
    ).lastrowid
    ids: dict = {}
    for key, parent_key, author, content, score in comments:
        ids[key] = conn.execute(
            "INSERT INTO comments (post_id, parent_id, author, content, vote_score) VALUES (?, ?, ?, ?, ?)",
            (post_id, ids.get(parent_key), author, content, score),
        ).lastrowid
    conn.commit()
    return [line for line in export_room_log(conn, "general").splitlines() if "> " in line]


def test_format_comment_tree_flat(initialized_db: sqlite3.Connection):
    """Top-level comments render without indentation, and a zero score keeps its plus sign."""
    lines = _log_comment_lines(
        initialized_db,
        [("c1", None, "DRONE", "First", 3), ("c2", None, "FLOW", "Second", 0)],
    )
    assert lines == ["  > DRONE: First [+3]", "  > FLOW: Second [+0]"]


def test_format_comment_tree_nested(initialized_db: sqlite3.Connection):
    """Child comments should be indented deeper than their parent."""
    lines = _log_comment_lines(
        initialized_db,
        [("c1", None, "A", "Root", 1), ("c2", "c1", "B", "Reply", -1)],
    )
    assert len(lines) == 2
    root_indent = len(lines[0]) - len(lines[0].lstrip())
    reply_indent = len(lines[1]) - len(lines[1].lstrip())
    assert reply_indent > root_indent


def test_format_comment_tree_empty(initialized_db: sqlite3.Connection):
    """A post with no comments should produce no comment lines, and no comment block."""
    lines = _log_comment_lines(initialized_db, [])
    assert lines == []
    assert export_room_log(initialized_db, "general").endswith("\nbody\n")


def test_format_comment_tree_negative_score(initialized_db: sqlite3.Connection):
    """Negative vote scores should show the minus sign, not a plus."""
    lines = _log_comment_lines(initialized_db, [("c1", None, "X", "Bad take", -5)])
    assert lines == ["  > X: Bad take [-5]"]


# FTS5 reads MATCH input as its own query language: unquoted, "FPLAN-0593" is a NOT-clause and raises.


def test_quote_fts5_query_hyphenated_term(initialized_db: sqlite3.Connection):
    """A hyphenated identifier in a title must not be parsed as an FTS5 NOT operator."""
    post_id = _seed_agent_and_post(initialized_db, "FPLAN-0593 kickoff", "notes")

    assert [r["id"] for r in search_posts(initialized_db, "FPLAN-0593")] == [post_id]


def test_quote_fts5_query_plain_single_word(initialized_db: sqlite3.Connection):
    """A single ordinary word is wrapped as one terminated literal phrase token."""
    post_id = _seed_agent_and_post(initialized_db, "Greeting", "hello from the commons")

    assert [r["id"] for r in search_posts(initialized_db, "hello")] == [post_id]


def test_quote_fts5_query_multi_word(initialized_db: sqlite3.Connection):
    """Each word becomes its own quoted phrase joined by implicit AND: one word alone is not a match."""
    both = _seed_agent_and_post(initialized_db, "Both", "world news, then hello again")
    _seed_agent_and_post(initialized_db, "One", "hello only")

    assert [r["id"] for r in search_posts(initialized_db, "hello world")] == [both]


def test_quote_fts5_query_embedded_double_quote(initialized_db: sqlite3.Connection):
    """An embedded double-quote must be doubled per the FTS5 escaping rule, not left bare."""
    post_id = _seed_agent_and_post(initialized_db, "Quoted", 'she wrote a"b in the log')

    assert [r["id"] for r in search_posts(initialized_db, 'a"b')] == [post_id]


def _seed_agent_and_post(conn: sqlite3.Connection, title: str, content: str) -> int:
    """Insert a test agent and a post, syncing it into the FTS index, return the post id."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("SEARCH_FIX_BRANCH", "Search Fix Branch"),
    )
    cursor = conn.execute(
        "INSERT INTO posts (title, content, room_name, author) VALUES (?, ?, ?, ?)",
        (title, content, "general", "SEARCH_FIX_BRANCH"),
    )
    conn.commit()
    post_id = cursor.lastrowid
    assert post_id is not None
    sync_post_to_fts(conn, post_id, title, content, "SEARCH_FIX_BRANCH", "general")
    conn.commit()
    return post_id


def test_search_posts_hyphenated_query_end_to_end(initialized_db: sqlite3.Connection) -> None:
    """Searching a real DB for a hyphenated plan ID must find the post, not raise fts5 syntax error."""
    post_id = _seed_agent_and_post(
        initialized_db,
        "Plan update",
        "Status notes for FPLAN-0593 landed tonight.",
    )

    results = search_posts(initialized_db, "FPLAN-0593")

    assert len(results) == 1
    assert results[0]["id"] == post_id
