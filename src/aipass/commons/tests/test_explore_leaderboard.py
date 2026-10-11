# =================== AIPass ====================
# META DATA HEADER
# Name: test_explore_leaderboard.py - Explore & Leaderboard Tests
# Description: Tests for apps/handlers/social/leaderboard_ops.py and apps/modules/explore.py
# Date: 2026-03-28
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-09-27
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

"""Tests for apps/handlers/social/leaderboard_ops.py and apps/modules/explore.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/social/ parses and imports
# seedgo: no-test-needed(covered) — what explore_rooms() and list_secrets() return: test_curation_explore_welcome_ops

import sqlite3
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest

from aipass.commons.apps.handlers.social.leaderboard_ops import show_leaderboard
from aipass.commons.apps.modules.explore import handle_command as explore_handle_command


# =============================================================================
# HELPERS
# =============================================================================


@pytest.fixture
def board_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point show_leaderboard at the tmp database, and its operation log at nothing."""
    monkeypatch.setattr("aipass.commons.apps.handlers.social.leaderboard_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.social.leaderboard_ops.close_db", lambda conn: None)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.social.leaderboard_ops.json_handler.log_operation", lambda *a, **k: None
    )
    return initialized_db


def _board(category: str) -> List[Dict[str, Any]]:
    """Ask show_leaderboard for one category, the way 'commons leaderboard --category X' does."""
    result = show_leaderboard(["--category", category])
    assert result["success"] is True, result
    assert list(result["boards"]) == [category]
    return result["boards"][category]


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


def test_query_posts_empty_db(board_db: sqlite3.Connection) -> None:
    """The posts board on an empty agents table (no post_count > 0) is an empty list.

    Mutant: _query_posts' return -> `return [{"branch": "x", "count": 0}]` (an invented row) reddens this.
    """
    result = _board("posts")
    assert result == []


def test_query_posts_with_data_sorted_by_count(board_db: sqlite3.Connection) -> None:
    """The posts board lists agents sorted by post_count descending.

    Mutant: `ORDER BY post_count DESC` -> `ORDER BY post_count ASC` reddens this.
    """
    _insert_agent(board_db, "BRANCH_A", "A")
    _insert_agent(board_db, "BRANCH_B", "B")
    board_db.execute("UPDATE agents SET post_count = 5 WHERE branch_name = 'BRANCH_A'")
    board_db.execute("UPDATE agents SET post_count = 12 WHERE branch_name = 'BRANCH_B'")
    board_db.commit()

    result = _board("posts")
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 12
    assert result[1]["branch"] == "BRANCH_A"
    assert result[1]["count"] == 5


# =============================================================================
# LEADERBOARD OPS - _query_artifacts
# =============================================================================


def test_query_artifacts_empty_db(board_db: sqlite3.Connection) -> None:
    """The artifacts board on an empty artifacts table is an empty list.

    Mutant: _query_artifacts' return -> `return [{"branch": "x", "count": 0}]` (an invented row) reddens this.
    """
    result = _board("artifacts")
    assert result == []


def test_query_artifacts_with_data_sorted(board_db: sqlite3.Connection) -> None:
    """The artifacts board lists owners sorted by artifact count descending.

    Mutant: `GROUP BY owner ORDER BY cnt DESC` -> `GROUP BY owner ORDER BY cnt ASC` reddens this.
    """
    _insert_agent(board_db, "BRANCH_A", "A")
    _insert_agent(board_db, "BRANCH_B", "B")
    _insert_artifact(board_db, "Item1", "BRANCH_A", "BRANCH_A")
    _insert_artifact(board_db, "Item2", "BRANCH_B", "BRANCH_B")
    _insert_artifact(board_db, "Item3", "BRANCH_B", "BRANCH_B")

    result = _board("artifacts")
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 2
    assert result[1]["branch"] == "BRANCH_A"
    assert result[1]["count"] == 1


# =============================================================================
# LEADERBOARD OPS - _query_trades
# =============================================================================


def test_query_trades_empty_db(board_db: sqlite3.Connection) -> None:
    """The trades board on an empty artifact_history table is an empty list.

    Mutant: _query_trades' return -> `return [{"branch": "x", "count": 0}]` (an invented row) reddens this.
    """
    result = _board("trades")
    assert result == []


# =============================================================================
# LEADERBOARD OPS - _query_rooms
# =============================================================================


def test_query_rooms_empty_db(board_db: sqlite3.Connection) -> None:
    """The rooms board with no posts is an empty list.

    Mutant: _query_rooms' return -> `return [{"room": "general", "count": 0}]` (an invented row) reddens this.
    """
    result = _board("rooms")
    assert result == []


def test_query_rooms_with_posts_sorted(board_db: sqlite3.Connection) -> None:
    """The rooms board lists rooms sorted by post count descending (last 7 days).

    Mutant: `GROUP BY room_name ORDER BY cnt DESC` -> `GROUP BY room_name ORDER BY cnt ASC` reddens this.
    """
    _insert_agent(board_db, "TEST_BRANCH", "Test")
    # Insert posts into two different seeded rooms
    _insert_post(board_db, "Post1", "general", "TEST_BRANCH")
    _insert_post(board_db, "Post2", "general", "TEST_BRANCH")
    _insert_post(board_db, "Post3", "general", "TEST_BRANCH")
    _insert_post(board_db, "Post4", "dev", "TEST_BRANCH")

    result = _board("rooms")
    assert len(result) == 2
    # general has 3 posts, dev has 1
    room_names = [r["room"] for r in result]
    assert room_names[0] == "general"
    assert result[0]["count"] == 3


# =============================================================================
# LEADERBOARD OPS - _query_karma
# =============================================================================


def test_query_karma_empty_db(board_db: sqlite3.Connection) -> None:
    """The karma board with no agents having karma > 0 is an empty list.

    Mutant: _query_karma's return -> `return [{"branch": "x", "count": 0}]` (an invented row) reddens this.
    """
    result = _board("karma")
    assert result == []


def test_query_karma_with_data(board_db: sqlite3.Connection) -> None:
    """The karma board lists agents sorted by karma descending.

    Mutant: `ORDER BY karma DESC` -> `ORDER BY karma ASC` reddens this.
    """
    _insert_agent(board_db, "BRANCH_A", "A")
    _insert_agent(board_db, "BRANCH_B", "B")
    board_db.execute("UPDATE agents SET karma = 10 WHERE branch_name = 'BRANCH_A'")
    board_db.execute("UPDATE agents SET karma = 25 WHERE branch_name = 'BRANCH_B'")
    board_db.commit()

    result = _board("karma")
    assert len(result) == 2
    assert result[0]["branch"] == "BRANCH_B"
    assert result[0]["count"] == 25


# =============================================================================
# LEADERBOARD OPS - show_leaderboard (public API)
# =============================================================================


@patch("aipass.commons.apps.handlers.social.leaderboard_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.social.leaderboard_ops.close_db")
@patch("aipass.commons.apps.handlers.social.leaderboard_ops.get_db")
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


@patch("aipass.commons.apps.handlers.social.leaderboard_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.social.leaderboard_ops.close_db")
@patch("aipass.commons.apps.handlers.social.leaderboard_ops.get_db")
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


@patch("aipass.commons.apps.handlers.rooms.explore_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.rooms.explore_ops.close_db")
@patch("aipass.commons.apps.handlers.rooms.explore_ops.get_db")
@patch("aipass.commons.apps.modules.explore.json_handler", autospec=True)
@patch(
    "aipass.commons.apps.modules.commons_identity.get_caller_branch",
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


@patch("aipass.commons.apps.handlers.rooms.explore_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.rooms.explore_ops.close_db")
@patch("aipass.commons.apps.handlers.rooms.explore_ops.get_db")
@patch("aipass.commons.apps.modules.explore.json_handler", autospec=True)
@patch(
    "aipass.commons.apps.modules.commons_identity.get_caller_branch",
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
