# ===================AIPASS====================
# META DATA HEADER
# Name: test_space_catchup.py - Space Ops, Room State Extras, Catchup & Search Tests
# Date: 2026-03-29
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-29): Initial creation — space_ops, room_state extras,
#     catchup_queries, search sync/backfill, log_export
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger, json_handler, get_db, close_db as needed
# =============================================

"""
Unit tests for space_ops, room_state personality setters, catchup queries,
FTS sync/backfill, and room log export.
"""

import sqlite3
from unittest.mock import patch

import pytest

from commons.apps.handlers.rooms.room_state_ops import (
    set_mood,
    set_flavor,
    set_entrance,
)
from commons.apps.handlers.rooms.space_ops import (
    get_room_enter_data,
    record_visit,
    get_room_look_data,
    place_decoration,
    get_visitors_data,
)
from commons.apps.handlers.database.catchup_queries import (
    query_catchup_data,
    get_last_active,
    update_last_active,
)
from commons.apps.handlers.search.search_queries import (
    sync_post_to_fts,
    sync_comment_to_fts,
    backfill_fts_index,
    search_posts,
    search_comments,
)
from commons.apps.handlers.search.log_export import export_room_log


# =============================================================================
# HELPERS
# =============================================================================


def _seed_agent_and_post(conn: sqlite3.Connection) -> int:
    """Insert a test agent and post, return the post id."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("TEST_BRANCH", "Test"),
    )
    cursor = conn.execute(
        "INSERT INTO posts (title, content, room_name, author) VALUES (?, ?, ?, ?)",
        ("Test Post", "Some interesting content here", "general", "TEST_BRANCH"),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def _seed_comment(conn: sqlite3.Connection, post_id: int, content: str = "A comment") -> int:
    """Insert a comment on a post, return the comment id."""
    cursor = conn.execute(
        "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
        (post_id, "TEST_BRANCH", content),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


# =============================================================================
# ROOM STATE OPS — personality column setters (not in test_rooms.py)
# =============================================================================


@patch("commons.apps.handlers.rooms.room_state_ops.logger")
def test_set_mood(mock_logger: object, initialized_db: sqlite3.Connection) -> None:
    """set_mood should update the mood column on a room."""
    ok = set_mood(initialized_db, "general", "celebratory")
    assert ok is True

    row = initialized_db.execute(
        "SELECT mood FROM rooms WHERE name = ?", ("general",)
    ).fetchone()
    assert row["mood"] == "celebratory"


@patch("commons.apps.handlers.rooms.room_state_ops.logger")
def test_set_flavor(mock_logger: object, initialized_db: sqlite3.Connection) -> None:
    """set_flavor should update the flavor_text column on a room."""
    ok = set_flavor(initialized_db, "general", "A cozy gathering place")
    assert ok is True

    row = initialized_db.execute(
        "SELECT flavor_text FROM rooms WHERE name = ?", ("general",)
    ).fetchone()
    assert row["flavor_text"] == "A cozy gathering place"


@patch("commons.apps.handlers.rooms.room_state_ops.logger")
def test_set_entrance(mock_logger: object, initialized_db: sqlite3.Connection) -> None:
    """set_entrance should update the entrance_message column on a room."""
    ok = set_entrance(initialized_db, "general", "Welcome, traveler!")
    assert ok is True

    row = initialized_db.execute(
        "SELECT entrance_message FROM rooms WHERE name = ?", ("general",)
    ).fetchone()
    assert row["entrance_message"] == "Welcome, traveler!"


# =============================================================================
# SPACE OPS — spatial navigation data handlers
# =============================================================================


@patch("commons.apps.handlers.rooms.space_ops.json_handler")
@patch("commons.apps.handlers.rooms.space_ops.logger")
@patch("commons.apps.handlers.rooms.space_ops.close_db", side_effect=lambda c: None)
@patch("commons.apps.handlers.rooms.space_ops.get_db")
def test_get_room_enter_data(
    mock_get_db: object,
    mock_close: object,
    mock_logger: object,
    mock_json: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """get_room_enter_data should return room info, post count, and decorations."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]
    _seed_agent_and_post(initialized_db)

    result = get_room_enter_data("general")

    assert result["found"] is True
    assert result["room"]["name"] == "general"
    assert result["post_count"] >= 1
    assert result["error"] is None
    assert isinstance(result["decorations"], dict)


@patch("commons.apps.handlers.rooms.space_ops.logger")
@patch("commons.apps.handlers.rooms.space_ops.close_db", side_effect=lambda c: None)
@patch("commons.apps.handlers.rooms.space_ops.get_db")
def test_record_visit(
    mock_get_db: object,
    mock_close: object,
    mock_logger: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """record_visit should insert a row into room_visits."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]

    record_visit("general", "TEST_BRANCH")

    row = initialized_db.execute(
        "SELECT * FROM room_visits WHERE room_name = ? AND visitor = ?",
        ("general", "TEST_BRANCH"),
    ).fetchone()
    assert row is not None
    assert row["visitor"] == "TEST_BRANCH"


@patch("commons.apps.handlers.rooms.space_ops.logger")
@patch("commons.apps.handlers.rooms.space_ops.close_db", side_effect=lambda c: None)
@patch("commons.apps.handlers.rooms.space_ops.get_db")
def test_get_room_look_data(
    mock_get_db: object,
    mock_close: object,
    mock_logger: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """get_room_look_data should return room description and recent posts."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]
    _seed_agent_and_post(initialized_db)

    result = get_room_look_data("general")

    assert result["found"] is True
    assert result["error"] is None
    assert len(result["recent_posts"]) >= 1
    assert result["recent_posts"][0]["title"] == "Test Post"


@patch("commons.apps.handlers.rooms.room_state_ops.json_handler")
@patch("commons.apps.handlers.rooms.space_ops.json_handler")
@patch("commons.apps.handlers.rooms.space_ops.logger")
@patch("commons.apps.handlers.rooms.space_ops.close_db", side_effect=lambda c: None)
@patch("commons.apps.handlers.rooms.space_ops.get_db")
def test_place_decoration(
    mock_get_db: object,
    mock_close: object,
    mock_logger: object,
    mock_json_space: object,
    mock_json_state: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """place_decoration should insert a decor_ state key for the room."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]

    result = place_decoration("general", "potted_plant", "A leafy fern", "TEST_BRANCH")

    assert result["success"] is True
    assert result["display_name"] == "Potted Plant"
    assert result["error"] is None


@patch("commons.apps.handlers.rooms.space_ops.logger")
@patch("commons.apps.handlers.rooms.space_ops.close_db", side_effect=lambda c: None)
@patch("commons.apps.handlers.rooms.space_ops.get_db")
def test_get_visitors_data(
    mock_get_db: object,
    mock_close: object,
    mock_logger: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """get_visitors_data should return visitors from visits and post authors."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]
    _seed_agent_and_post(initialized_db)

    # Also record a visit
    initialized_db.execute(
        "INSERT INTO room_visits (room_name, visitor) VALUES (?, ?)",
        ("general", "TEST_BRANCH"),
    )
    initialized_db.commit()

    result = get_visitors_data("general")

    assert result["found"] is True
    assert "TEST_BRANCH" in result["visitors"]


# =============================================================================
# CATCHUP QUERIES — database query functions
# =============================================================================


@patch("commons.apps.handlers.database.catchup_queries.json_handler")
def test_query_catchup_data_counts(
    mock_json: object, initialized_db: sqlite3.Connection
) -> None:
    """query_catchup_data should return correct new_posts_count and new_comments_count."""
    post_id = _seed_agent_and_post(initialized_db)
    _seed_comment(initialized_db, post_id)

    # Use a timestamp well in the past so all data is "new"
    result = query_catchup_data(initialized_db, "TEST_BRANCH", "2000-01-01T00:00:00Z")

    assert result["new_posts_count"] >= 1
    assert result["new_comments_count"] >= 1
    assert isinstance(result["unread_mentions"], list)
    assert isinstance(result["replies"], list)
    assert result["karma_change"] == 0


def test_get_last_active_new_agent(initialized_db: sqlite3.Connection) -> None:
    """get_last_active should return None for an agent that has never been active."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("FRESH_BRANCH", "Fresh"),
    )
    initialized_db.commit()

    result = get_last_active(initialized_db, "FRESH_BRANCH")
    assert result is None


def test_get_last_active_after_update(initialized_db: sqlite3.Connection) -> None:
    """After update_last_active, get_last_active should return the set timestamp."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("ACTIVE_BRANCH", "Active"),
    )
    initialized_db.commit()

    ts = update_last_active(initialized_db, "ACTIVE_BRANCH")
    result = get_last_active(initialized_db, "ACTIVE_BRANCH")

    assert result is not None
    assert result == ts


def test_update_last_active_returns_timestamp(initialized_db: sqlite3.Connection) -> None:
    """update_last_active should return an ISO-format timestamp string."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("TS_BRANCH", "Timestamp"),
    )
    initialized_db.commit()

    ts = update_last_active(initialized_db, "TS_BRANCH")

    assert isinstance(ts, str)
    assert "T" in ts
    assert ts.endswith("Z")


# =============================================================================
# SEARCH QUERIES — FTS sync and backfill
# =============================================================================


def test_sync_post_to_fts_and_search(initialized_db: sqlite3.Connection) -> None:
    """sync_post_to_fts should make the post searchable via FTS."""
    post_id = _seed_agent_and_post(initialized_db)
    sync_post_to_fts(
        initialized_db, post_id, "Test Post", "Some interesting content here",
        "TEST_BRANCH", "general",
    )
    initialized_db.commit()

    results = search_posts(initialized_db, "interesting")
    assert len(results) >= 1
    assert results[0]["title"] == "Test Post"


def test_sync_comment_to_fts_and_search(initialized_db: sqlite3.Connection) -> None:
    """sync_comment_to_fts should make the comment searchable via FTS."""
    post_id = _seed_agent_and_post(initialized_db)
    comment_id = _seed_comment(initialized_db, post_id, "Remarkable observation")

    sync_comment_to_fts(initialized_db, comment_id, "Remarkable observation", "TEST_BRANCH")
    initialized_db.commit()

    results = search_comments(initialized_db, "remarkable")
    assert len(results) >= 1
    assert "Remarkable" in results[0]["content_snippet"]


def test_backfill_fts_index_counts(initialized_db: sqlite3.Connection) -> None:
    """backfill_fts_index should return counts of synced posts and comments."""
    post_id = _seed_agent_and_post(initialized_db)
    _seed_comment(initialized_db, post_id, "Backfill test comment")

    result = backfill_fts_index(initialized_db)

    assert result["posts_indexed"] >= 1
    assert result["comments_indexed"] >= 1


# =============================================================================
# LOG EXPORT
# =============================================================================


@patch("commons.apps.handlers.search.log_export.json_handler")
def test_export_room_log(mock_json: object, initialized_db: sqlite3.Connection) -> None:
    """export_room_log should return a formatted plaintext log with posts and comments."""
    post_id = _seed_agent_and_post(initialized_db)
    _seed_comment(initialized_db, post_id, "Log export test reply")

    log = export_room_log(initialized_db, "general")

    assert "r/general" in log
    assert "Test Post" in log
    assert "TEST_BRANCH" in log
    assert "Log export test reply" in log
