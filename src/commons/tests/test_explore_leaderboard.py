# ===================AIPASS====================
# META DATA HEADER
# Name: test_explore_leaderboard.py - Explore & Leaderboard Tests
# Date: 2026-03-28
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — explore + leaderboard subsystem tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger, json_handler, get_db, close_db, get_caller_branch as needed
# =============================================

"""
Unit tests for the explore and leaderboard subsystems.

Covers:
- leaderboard_ops DB query functions (empty + populated tables)
- show_leaderboard public API with mock DB
- explore module command routing
"""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from commons.apps.handlers.social.leaderboard_ops import (
    _query_posts,
    _query_artifacts,
    _query_trades,
    _query_rooms,
    _query_karma,
    show_leaderboard,
)
from commons.apps.modules.explore import handle_command as explore_handle_command


# =============================================================================
# HELPERS
# =============================================================================


def _insert_agent(conn: sqlite3.Connection, branch: str, display: str = "Test") -> None:
    """Insert a test agent into the DB."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (branch, display),
    )
    conn.commit()


def _insert_post(conn: sqlite3.Connection, title: str, room: str, author: str) -> None:
    """Insert a test post into the DB."""
    conn.execute(
        "INSERT INTO posts (title, content, room_name, author) VALUES (?, ?, ?, ?)",
        (title, "Content", room, author),
    )
    conn.commit()


def _insert_artifact(conn: sqlite3.Connection, name: str, owner: str, creator: str) -> None:
    """Insert a test artifact into the DB."""
    conn.execute(
        "INSERT INTO artifacts (name, description, type, rarity, owner, creator) VALUES (?, ?, ?, ?, ?, ?)",
        (name, "desc", "crafted", "common", owner, creator),
    )
    conn.commit()


# =============================================================================
# LEADERBOARD OPS - _query_posts
# =============================================================================


def test_query_posts_empty_db(initialized_db: sqlite3.Connection) -> None:
    """_query_posts on an empty agents table (no post_count > 0) returns empty list."""
    result = _query_posts(initialized_db)
    assert result == []


def test_query_posts_with_data_sorted_by_count(initialized_db: sqlite3.Connection) -> None:
    """_query_posts returns agents sorted by post_count descending."""
    _insert_agent(initialized_db, "BRANCH_A", "A")
    _insert_agent(initialized_db, "BRANCH_B", "B")
    initialized_db.execute("UPDATE agents SET post_count = 5 WHERE branch_name = 'BRANCH_A'")
    initialized_db.execute("UPDATE agents SET post_count = 12 WHERE branch_name = 'BRANCH_B'")
    initialized_db.commit()

    result = _query_posts(initialized_db)
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 12
    assert result[1]["branch"] == "BRANCH_A"
    assert result[1]["count"] == 5


# =============================================================================
# LEADERBOARD OPS - _query_artifacts
# =============================================================================


def test_query_artifacts_empty_db(initialized_db: sqlite3.Connection) -> None:
    """_query_artifacts on an empty artifacts table returns empty list."""
    result = _query_artifacts(initialized_db)
    assert result == []


def test_query_artifacts_with_data_sorted(initialized_db: sqlite3.Connection) -> None:
    """_query_artifacts returns owners sorted by artifact count descending."""
    _insert_agent(initialized_db, "BRANCH_A", "A")
    _insert_agent(initialized_db, "BRANCH_B", "B")
    _insert_artifact(initialized_db, "Item1", "BRANCH_A", "BRANCH_A")
    _insert_artifact(initialized_db, "Item2", "BRANCH_B", "BRANCH_B")
    _insert_artifact(initialized_db, "Item3", "BRANCH_B", "BRANCH_B")

    result = _query_artifacts(initialized_db)
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 2
    assert result[1]["branch"] == "BRANCH_A"
    assert result[1]["count"] == 1


# =============================================================================
# LEADERBOARD OPS - _query_trades
# =============================================================================


def test_query_trades_empty_db(initialized_db: sqlite3.Connection) -> None:
    """_query_trades on an empty artifact_history table returns empty list."""
    result = _query_trades(initialized_db)
    assert result == []


# =============================================================================
# LEADERBOARD OPS - _query_rooms
# =============================================================================


def test_query_rooms_empty_db(initialized_db: sqlite3.Connection) -> None:
    """_query_rooms with no posts returns empty list."""
    result = _query_rooms(initialized_db)
    assert result == []


def test_query_rooms_with_posts_sorted(initialized_db: sqlite3.Connection) -> None:
    """_query_rooms returns rooms sorted by post count descending (last 7 days)."""
    _insert_agent(initialized_db, "TEST_BRANCH", "Test")
    # Insert posts into two different seeded rooms
    _insert_post(initialized_db, "Post1", "general", "TEST_BRANCH")
    _insert_post(initialized_db, "Post2", "general", "TEST_BRANCH")
    _insert_post(initialized_db, "Post3", "general", "TEST_BRANCH")
    _insert_post(initialized_db, "Post4", "dev", "TEST_BRANCH")

    result = _query_rooms(initialized_db)
    assert len(result) == 2
    # general has 3 posts, dev has 1
    room_names = [r["room"] for r in result]
    assert room_names[0] == "general"
    assert result[0]["count"] == 3


# =============================================================================
# LEADERBOARD OPS - _query_karma
# =============================================================================


def test_query_karma_empty_db(initialized_db: sqlite3.Connection) -> None:
    """_query_karma with no agents having karma > 0 returns empty list."""
    result = _query_karma(initialized_db)
    assert result == []


def test_query_karma_with_data(initialized_db: sqlite3.Connection) -> None:
    """_query_karma returns agents sorted by karma descending."""
    _insert_agent(initialized_db, "BRANCH_A", "A")
    _insert_agent(initialized_db, "BRANCH_B", "B")
    initialized_db.execute("UPDATE agents SET karma = 10 WHERE branch_name = 'BRANCH_A'")
    initialized_db.execute("UPDATE agents SET karma = 25 WHERE branch_name = 'BRANCH_B'")
    initialized_db.commit()

    result = _query_karma(initialized_db)
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 25


# =============================================================================
# LEADERBOARD OPS - show_leaderboard (public API)
# =============================================================================


@patch("commons.apps.handlers.social.leaderboard_ops.json_handler")
@patch("commons.apps.handlers.social.leaderboard_ops.close_db")
@patch("commons.apps.handlers.social.leaderboard_ops.get_db")
def test_show_leaderboard_returns_all_categories(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_leaderboard with no category filter returns all five boards."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    result = show_leaderboard([])
    assert result["success"] is True
    assert result["category"] == "all"
    assert set(result["boards"].keys()) == {"artifacts", "trades", "posts", "rooms", "karma"}


@patch("commons.apps.handlers.social.leaderboard_ops.json_handler")
@patch("commons.apps.handlers.social.leaderboard_ops.close_db")
@patch("commons.apps.handlers.social.leaderboard_ops.get_db")
def test_show_leaderboard_single_category(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """show_leaderboard with --category posts returns only the posts board."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    result = show_leaderboard(["--category", "posts"])
    assert result["success"] is True
    assert result["category"] == "posts"
    assert "posts" in result["boards"]
    assert len(result["boards"]) == 1


def test_show_leaderboard_invalid_category() -> None:
    """show_leaderboard with an invalid category returns an error."""
    result = show_leaderboard(["--category", "bananas"])
    assert result["success"] is False
    assert "Invalid category" in result["error"]


# =============================================================================
# EXPLORE MODULE - handle_command routing
# =============================================================================


@patch("commons.apps.handlers.rooms.explore_ops.json_handler")
@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch("commons.apps.modules.explore.json_handler")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_explore_handle_command_routes_explore(
    mock_caller: MagicMock,
    mock_mod_json: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """handle_command('explore', ...) should route and return True."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    _insert_agent(initialized_db, "TEST_BRANCH", "Test")

    result = explore_handle_command("explore", [])
    assert result is True


@patch("commons.apps.handlers.rooms.explore_ops.json_handler")
@patch("commons.apps.handlers.rooms.explore_ops.close_db")
@patch("commons.apps.handlers.rooms.explore_ops.get_db")
@patch("commons.apps.modules.explore.json_handler")
@patch(
    "commons.apps.modules.commons_identity.get_caller_branch",
    return_value={"name": "TEST_BRANCH"},
)
def test_explore_handle_command_routes_secrets(
    mock_caller: MagicMock,
    mock_mod_json: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_ops_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """handle_command('secrets', ...) should route and return True."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    _insert_agent(initialized_db, "TEST_BRANCH", "Test")

    result = explore_handle_command("secrets", [])
    assert result is True


def test_explore_handle_command_rejects_unknown() -> None:
    """handle_command with an unrecognized command should return False."""
    result = explore_handle_command("teleport", [])
    assert result is False
