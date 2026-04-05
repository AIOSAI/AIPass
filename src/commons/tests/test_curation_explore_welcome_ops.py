# ===================AIPASS====================
# META DATA HEADER
# Name: test_curation_explore_welcome_ops.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-04-03): Initial creation — ops-layer tests for curation, explore, welcome
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks get_db, close_db, get_caller_branch, json_handler targeting SOURCE modules
# =============================================

"""
Unit tests for the *ops* layer of curation, explore, and welcome handlers.

These tests exercise the public functions that parse CLI args, acquire a DB
connection, call into the query layer, and return result dicts.  The existing
test_curation.py, test_explore_leaderboard.py, and test_welcome_engagement.py
cover the lower-level query functions and module routing; this file focuses on
the ops orchestration that sits above them.

Covered modules:
- commons.apps.handlers.curation.curation_ops
    add_react, remove_react, show_reactions, pin_post_cmd, unpin_post_cmd,
    show_pinned, show_trending
- commons.apps.handlers.rooms.explore_ops
    explore_rooms, list_secrets
- commons.apps.handlers.welcome.welcome_ops
    run_welcome (--dry-run and normal), _welcome_scan, _welcome_specific
"""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest


# =============================================================================
# HELPERS
# =============================================================================


def _seed_agent(conn: sqlite3.Connection, name: str, display: str = "Test") -> None:
    """Insert a single agent."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (name, display),
    )
    conn.commit()


def _seed_post(
    conn: sqlite3.Connection,
    title: str,
    room: str,
    author: str,
    *,
    pinned: int = 0,
) -> int:
    """Insert a post and return its ID."""
    conn.execute(
        "INSERT INTO posts (title, content, room_name, author, pinned) "
        "VALUES (?, ?, ?, ?, ?)",
        (title, "body", room, author, pinned),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


def _seed_comment(conn: sqlite3.Connection, post_id: int, author: str) -> int:
    """Insert a comment and return its ID."""
    conn.execute(
        "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
        (post_id, author, "A comment"),
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return row[0]


def _seed_room(
    conn: sqlite3.Connection,
    name: str,
    display_name: str,
    created_by: str,
    *,
    hidden: int = 0,
    discovery_hint: str = "",
) -> None:
    """Insert a room."""
    conn.execute(
        "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by, hidden, discovery_hint) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, display_name, "desc", created_by, hidden, discovery_hint),
    )
    conn.commit()


# =============================================================================
# curation_ops -- add_react
# =============================================================================


@patch("commons.apps.handlers.curation.curation_ops.json_handler")
@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_add_react_success_post(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_rq_json: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """add_react with valid post target returns success with reaction info."""
    from commons.apps.handlers.curation.curation_ops import add_react

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Hello", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = add_react(["post", str(post_id), "thumbsup"])

    assert result["success"] is True
    assert result["is_new"] is True
    assert result["reaction"] == "thumbsup"
    assert result["target_type"] == "post"
    assert result["target_id"] == post_id
    assert result["agent"] == "TEST_BRANCH"


@patch("commons.apps.handlers.curation.curation_ops.json_handler")
@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_add_react_success_comment(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_rq_json: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """add_react targeting a comment returns success."""
    from commons.apps.handlers.curation.curation_ops import add_react

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Hello", "general", "TEST_BRANCH")
    comment_id = _seed_comment(initialized_db, post_id, "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = add_react(["comment", str(comment_id), "agree"])

    assert result["success"] is True
    assert result["target_type"] == "comment"
    assert result["target_id"] == comment_id


def test_add_react_too_few_args() -> None:
    """add_react with fewer than 3 args returns usage error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    result = add_react(["post", "1"])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_add_react_invalid_target_type() -> None:
    """add_react with invalid target type returns error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    result = add_react(["thread", "1", "thumbsup"])
    assert result["success"] is False
    assert "post" in result["error"] or "comment" in result["error"]


def test_add_react_non_numeric_id() -> None:
    """add_react with non-numeric ID returns error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    result = add_react(["post", "abc", "thumbsup"])
    assert result["success"] is False
    assert "number" in result["error"]


def test_add_react_invalid_reaction() -> None:
    """add_react with invalid reaction name returns error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    result = add_react(["post", "1", "love"])
    assert result["success"] is False
    assert "Invalid reaction" in result["error"]


@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value=None,
)
def test_add_react_no_caller(mock_caller: MagicMock) -> None:
    """add_react when caller cannot be detected returns error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    result = add_react(["post", "1", "thumbsup"])
    assert result["success"] is False
    assert "calling branch" in result["error"]


@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_add_react_target_not_found(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """add_react for a non-existent post returns not-found error."""
    from commons.apps.handlers.curation.curation_ops import add_react

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = add_react(["post", "9999", "thumbsup"])
    assert result["success"] is False
    assert "not found" in result["error"]


# =============================================================================
# curation_ops -- remove_react
# =============================================================================


@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_remove_react_no_existing_reaction(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """remove_react when no reaction exists returns removed=False."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Hello", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = remove_react(["post", str(post_id), "thumbsup"])
    assert result["success"] is True
    assert result["removed"] is False


def test_remove_react_too_few_args() -> None:
    """remove_react with fewer than 3 args returns error."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    result = remove_react(["post"])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_remove_react_invalid_target_type() -> None:
    """remove_react with invalid target type returns error."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    result = remove_react(["thread", "1", "thumbsup"])
    assert result["success"] is False


def test_remove_react_non_numeric_id() -> None:
    """remove_react with non-numeric ID returns error."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    result = remove_react(["post", "xyz", "thumbsup"])
    assert result["success"] is False
    assert "number" in result["error"]


def test_remove_react_invalid_reaction() -> None:
    """remove_react with invalid reaction returns error."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    result = remove_react(["post", "1", "love"])
    assert result["success"] is False


@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value=None,
)
def test_remove_react_no_caller(mock_caller: MagicMock) -> None:
    """remove_react when caller cannot be detected returns error."""
    from commons.apps.handlers.curation.curation_ops import remove_react

    result = remove_react(["post", "1", "thumbsup"])
    assert result["success"] is False
    assert "calling branch" in result["error"]


# =============================================================================
# curation_ops -- show_reactions
# =============================================================================


@patch("commons.apps.handlers.curation.reaction_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
def test_show_reactions_empty(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_rq_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_reactions on a post with no reactions returns empty dict."""
    from commons.apps.handlers.curation.curation_ops import show_reactions

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Hello", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = show_reactions(["post", str(post_id)])
    assert result["success"] is True
    assert result["reactions"] == {}
    assert result["target_type"] == "post"
    assert result["target_id"] == post_id


def test_show_reactions_too_few_args() -> None:
    """show_reactions with fewer than 2 args returns error."""
    from commons.apps.handlers.curation.curation_ops import show_reactions

    result = show_reactions(["post"])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_show_reactions_invalid_target() -> None:
    """show_reactions with invalid target type returns error."""
    from commons.apps.handlers.curation.curation_ops import show_reactions

    result = show_reactions(["thread", "1"])
    assert result["success"] is False


def test_show_reactions_non_numeric_id() -> None:
    """show_reactions with non-numeric ID returns error."""
    from commons.apps.handlers.curation.curation_ops import show_reactions

    result = show_reactions(["post", "abc"])
    assert result["success"] is False
    assert "number" in result["error"]


# =============================================================================
# curation_ops -- pin_post_cmd
# =============================================================================


@patch("commons.apps.handlers.curation.curation_ops.json_handler")
@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_pin_post_cmd_success_by_author(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """pin_post_cmd by the post author succeeds."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Pin Me", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = pin_post_cmd([str(post_id)])
    assert result["success"] is True
    assert result["action"] == "pinned"
    assert result["post_id"] == post_id
    assert result["title"] == "Pin Me"
    assert result["agent"] == "TEST_BRANCH"


@patch("commons.apps.handlers.curation.curation_ops.json_handler")
@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "SYSTEM"},
)
def test_pin_post_cmd_success_by_system(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """SYSTEM can pin any post regardless of authorship."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Pin Me", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = pin_post_cmd([str(post_id)])
    assert result["success"] is True
    assert result["agent"] == "SYSTEM"


@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "OTHER_BRANCH"},
)
def test_pin_post_cmd_rejected_non_author(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Non-author, non-SYSTEM caller cannot pin a post."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_agent(initialized_db, "OTHER_BRANCH")
    post_id = _seed_post(initialized_db, "No Pin", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = pin_post_cmd([str(post_id)])
    assert result["success"] is False
    assert "author" in result["error"] or "SYSTEM" in result["error"]


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_pin_post_cmd_already_pinned(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Pinning an already-pinned post returns error."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Already Pinned", "general", "TEST_BRANCH", pinned=1)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = pin_post_cmd([str(post_id)])
    assert result["success"] is False
    assert "already pinned" in result["error"]


def test_pin_post_cmd_no_args() -> None:
    """pin_post_cmd with no args returns error."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    result = pin_post_cmd([])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_pin_post_cmd_non_numeric() -> None:
    """pin_post_cmd with non-numeric ID returns error."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    result = pin_post_cmd(["abc"])
    assert result["success"] is False
    assert "number" in result["error"]


@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value=None,
)
def test_pin_post_cmd_no_caller(mock_caller: MagicMock) -> None:
    """pin_post_cmd when caller cannot be detected returns error."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    result = pin_post_cmd(["1"])
    assert result["success"] is False
    assert "calling branch" in result["error"]


@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_pin_post_cmd_post_not_found(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """pin_post_cmd for non-existent post returns error."""
    from commons.apps.handlers.curation.curation_ops import pin_post_cmd

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = pin_post_cmd(["9999"])
    assert result["success"] is False
    assert "not found" in result["error"]


# =============================================================================
# curation_ops -- unpin_post_cmd
# =============================================================================


@patch("commons.apps.handlers.curation.curation_ops.json_handler")
@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_unpin_post_cmd_success(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """unpin_post_cmd on a pinned post by its author succeeds."""
    from commons.apps.handlers.curation.curation_ops import unpin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    post_id = _seed_post(initialized_db, "Unpin Me", "general", "TEST_BRANCH", pinned=1)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = unpin_post_cmd([str(post_id)])
    assert result["success"] is True
    assert result["action"] == "unpinned"
    assert result["post_id"] == post_id
    assert result["title"] == "Unpin Me"


@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
@patch(
    "commons.apps.handlers.curation.curation_ops.get_caller_branch",
    return_value={"name": "OTHER_BRANCH"},
)
def test_unpin_post_cmd_rejected_non_author(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Non-author, non-SYSTEM caller cannot unpin a post."""
    from commons.apps.handlers.curation.curation_ops import unpin_post_cmd

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_agent(initialized_db, "OTHER_BRANCH")
    post_id = _seed_post(initialized_db, "Pinned", "general", "TEST_BRANCH", pinned=1)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = unpin_post_cmd([str(post_id)])
    assert result["success"] is False


def test_unpin_post_cmd_no_args() -> None:
    """unpin_post_cmd with no args returns error."""
    from commons.apps.handlers.curation.curation_ops import unpin_post_cmd

    result = unpin_post_cmd([])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# curation_ops -- show_pinned
# =============================================================================


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
def test_show_pinned_no_pinned(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_pinned with no pinned posts returns empty list."""
    from commons.apps.handlers.curation.curation_ops import show_pinned

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_post(initialized_db, "Not Pinned", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = show_pinned([])
    assert result["success"] is True
    assert result["posts"] == []
    assert result["room"] is None


@patch("commons.apps.handlers.curation.pin_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
def test_show_pinned_with_room_filter(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_pin_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_pinned with --room filter returns only pinned posts in that room."""
    from commons.apps.handlers.curation.curation_ops import show_pinned

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_post(initialized_db, "General Pin", "general", "TEST_BRANCH", pinned=1)
    _seed_post(initialized_db, "Dev Pin", "dev", "TEST_BRANCH", pinned=1)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = show_pinned(["--room", "general"])
    assert result["success"] is True
    assert result["room"] == "general"
    assert len(result["posts"]) == 1
    assert result["posts"][0]["title"] == "General Pin"


# =============================================================================
# curation_ops -- show_trending
# =============================================================================


@patch("commons.apps.handlers.curation.trending_queries.json_handler")
@patch("commons.apps.handlers.curation.curation_ops.close_db")
@patch("commons.apps.handlers.curation.curation_ops.get_db")
def test_show_trending_empty(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_trending_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_trending with no engagement returns empty list."""
    from commons.apps.handlers.curation.curation_ops import show_trending

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_post(initialized_db, "Quiet Post", "general", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = show_trending([])
    assert result["success"] is True
    assert result["posts"] == []


# =============================================================================
# explore_ops -- explore_rooms
# =============================================================================


@patch("commons.apps.handlers.rooms.explore_ops.json_handler")
@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_explore_rooms_no_hidden_rooms(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """explore_rooms with no hidden rooms returns empty list."""
    from commons.apps.handlers.rooms.explore_ops import explore_rooms

    _seed_agent(initialized_db, "TEST_BRANCH")
    # Remove any hidden rooms that may have been seeded by init_db
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = explore_rooms([])
    assert result["success"] is True
    assert result["hidden_rooms"] == []
    assert result["rooms_visited"] == 0


@patch("commons.apps.handlers.rooms.explore_ops.json_handler")
@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_explore_rooms_with_hidden_rooms_no_reveal(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """explore_rooms with hidden rooms but < 3 rooms visited does not reveal."""
    from commons.apps.handlers.rooms.explore_ops import explore_rooms

    _seed_agent(initialized_db, "TEST_BRANCH")
    # Ensure no pre-existing hidden rooms interfere
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()
    _seed_room(initialized_db, "secret-lab", "Secret Lab", "SYSTEM", hidden=1, discovery_hint="Look deeper")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = explore_rooms([])
    assert result["success"] is True
    assert len(result["hidden_rooms"]) == 1
    assert result["hidden_rooms"][0]["name"] == "secret-lab"
    assert "revealed" not in result


@patch("commons.apps.handlers.rooms.explore_ops.json_handler")
@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_explore_rooms_reveals_after_3_rooms(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """explore_rooms reveals a hidden room when the caller has visited 3+ rooms."""
    from commons.apps.handlers.rooms.explore_ops import explore_rooms

    _seed_agent(initialized_db, "TEST_BRANCH")
    # Clear any pre-existing hidden rooms
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()

    # Create 3 regular rooms and post in each
    for room in ("room-a", "room-b", "room-c"):
        _seed_room(initialized_db, room, room.title(), "SYSTEM")
        _seed_post(initialized_db, f"Post in {room}", room, "TEST_BRANCH")

    # Create the hidden room to be discovered
    _seed_room(initialized_db, "vault", "The Vault", "SYSTEM", hidden=1, discovery_hint="Find the key")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = explore_rooms([])
    assert result["success"] is True
    assert result["rooms_visited"] >= 3
    assert "revealed" in result
    assert result["revealed"]["name"] == "vault"


@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value=None,
)
def test_explore_rooms_no_caller(mock_caller: MagicMock) -> None:
    """explore_rooms when caller cannot be detected returns error."""
    from commons.apps.handlers.rooms.explore_ops import explore_rooms

    result = explore_rooms([])
    assert result["success"] is False
    assert "calling branch" in result["error"]


# =============================================================================
# explore_ops -- list_secrets
# =============================================================================


@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_list_secrets_none_discovered(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_secrets when no hidden rooms have been posted in returns empty."""
    from commons.apps.handlers.rooms.explore_ops import list_secrets

    _seed_agent(initialized_db, "TEST_BRANCH")
    # Clear any pre-existing hidden rooms
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()
    _seed_room(initialized_db, "hidden-cove", "Hidden Cove", "SYSTEM", hidden=1)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = list_secrets([])
    assert result["success"] is True
    assert result["discovered"] == []
    assert result["total_hidden"] == 1


@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_list_secrets_with_discovered_room(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_secrets returns rooms where the caller has posted."""
    from commons.apps.handlers.rooms.explore_ops import list_secrets

    _seed_agent(initialized_db, "TEST_BRANCH")
    # Clear any pre-existing hidden rooms
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()
    _seed_room(initialized_db, "hidden-cove", "Hidden Cove", "SYSTEM", hidden=1)
    _seed_post(initialized_db, "Secret Post", "hidden-cove", "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = list_secrets([])
    assert result["success"] is True
    assert len(result["discovered"]) == 1
    assert result["discovered"][0]["name"] == "hidden-cove"
    assert result["total_hidden"] == 1


@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_list_secrets_discovered_via_comment(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_secrets counts rooms discovered by commenting on a post in that room."""
    from commons.apps.handlers.rooms.explore_ops import list_secrets

    _seed_agent(initialized_db, "TEST_BRANCH")
    _seed_agent(initialized_db, "OTHER_BRANCH")
    # Clear any pre-existing hidden rooms
    initialized_db.execute("UPDATE rooms SET hidden = 0")
    initialized_db.commit()
    _seed_room(initialized_db, "hidden-den", "Hidden Den", "SYSTEM", hidden=1)

    # Another branch posts in the hidden room; TEST_BRANCH comments
    post_id = _seed_post(initialized_db, "Secret Thread", "hidden-den", "OTHER_BRANCH")
    _seed_comment(initialized_db, post_id, "TEST_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = list_secrets([])
    assert result["success"] is True
    assert len(result["discovered"]) == 1
    assert result["discovered"][0]["name"] == "hidden-den"


@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value=None,
)
def test_list_secrets_no_caller(mock_caller: MagicMock) -> None:
    """list_secrets when caller cannot be detected returns error."""
    from commons.apps.handlers.rooms.explore_ops import list_secrets

    result = list_secrets([])
    assert result["success"] is False
    assert "calling branch" in result["error"]


# =============================================================================
# welcome_ops -- run_welcome (dry-run mode)
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_dry_run_scan(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome --dry-run with no specific branch lists unwelcomed branches."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome

    _seed_agent(initialized_db, "ALPHA")
    _seed_agent(initialized_db, "BETA")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["--dry-run"])
    assert result["success"] is True
    assert result["dry_run"] is True
    assert isinstance(result["would_welcome"], list)
    assert "ALPHA" in result["would_welcome"]
    assert "BETA" in result["would_welcome"]


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_dry_run_specific_branch(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome <branch> --dry-run reports whether the branch would be welcomed."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome

    _seed_agent(initialized_db, "GAMMA")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["gamma", "--dry-run"])
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["branch"] == "GAMMA"
    assert result["would_welcome"] is True


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_dry_run_already_welcomed(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome <branch> --dry-run for already-welcomed branch reports would_welcome=False."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome
    from commons.apps.handlers.welcome.welcome_handler import create_welcome_post

    _seed_agent(initialized_db, "DELTA")
    create_welcome_post(initialized_db, "DELTA")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["delta", "--dry-run"])
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["would_welcome"] is False


# =============================================================================
# welcome_ops -- run_welcome (normal mode)
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_scan_welcomes_new_branches(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome with no args scans and welcomes all unwelcomed branches."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome

    _seed_agent(initialized_db, "NEW_BRANCH")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome([])
    assert result["success"] is True
    assert result["action"] == "scan"
    assert "NEW_BRANCH" in result["welcomed"]


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_specific_branch_success(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome <branch> creates a welcome post for that branch."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome

    _seed_agent(initialized_db, "EPSILON")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["epsilon"])
    assert result["success"] is True
    assert result["action"] == "specific"
    assert result["already_welcomed"] is False
    assert result["branch"] == "EPSILON"
    assert result["post_id"] is not None


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_specific_already_welcomed(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    mock_handler_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome <branch> when already welcomed returns already_welcomed=True."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome
    from commons.apps.handlers.welcome.welcome_handler import create_welcome_post

    _seed_agent(initialized_db, "ZETA")
    create_welcome_post(initialized_db, "ZETA")

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["zeta"])
    assert result["success"] is True
    assert result["action"] == "specific"
    assert result["already_welcomed"] is True


@patch("commons.apps.handlers.welcome.welcome_ops.json_handler")
@patch("commons.apps.handlers.welcome.welcome_ops.close_db")
@patch("commons.apps.handlers.welcome.welcome_ops.get_db")
def test_run_welcome_specific_branch_not_found(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_welcome <nonexistent_branch> returns not-found error."""
    from commons.apps.handlers.welcome.welcome_ops import run_welcome

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = run_welcome(["NONEXISTENT"])
    assert result["success"] is False
    assert "not found" in result["error"]
