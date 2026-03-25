# ===================AIPASS====================
# META DATA HEADER
# Name: test_profiles.py - Profile Handler Unit Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation — profile queries + ops tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger and json_handler to avoid side-effect dependencies
# =============================================

"""
Unit tests for profile queries and profile operations.

Covers:
- format_time_ago() pure function with various timestamp inputs
- get_profile / update_bio / update_status / update_role DB operations
- get_activity_stats / get_all_agents_brief DB queries
- increment_post_count / increment_comment_count mutations
- Edge cases: missing agents, empty strings, malformed timestamps
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from commons.apps.handlers.profiles.profile_queries import (
    format_time_ago,
    get_profile,
    update_bio,
    update_status,
    update_role,
    get_activity_stats,
    get_all_agents_brief,
    increment_post_count,
    increment_comment_count,
)
from commons.apps.handlers.profiles.profile_ops import show_profile, list_members


# =============================================================================
# format_time_ago — pure function, no DB
# =============================================================================


def test_format_time_ago_empty_string_returns_never() -> None:
    """An empty timestamp string should return 'never'."""
    assert format_time_ago("") == "never"


def test_format_time_ago_just_now() -> None:
    """A timestamp from seconds ago should return 'just now'."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert format_time_ago(now) == "just now"


def test_format_time_ago_minutes() -> None:
    """A timestamp from 10 minutes ago should return '10m ago'."""
    ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = format_time_ago(ten_min_ago)
    assert result.endswith("m ago")
    minutes = int(result.replace("m ago", ""))
    assert 9 <= minutes <= 11


def test_format_time_ago_hours() -> None:
    """A timestamp from 5 hours ago should return '5h ago'."""
    five_h_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = format_time_ago(five_h_ago)
    assert result.endswith("h ago")
    hours = int(result.replace("h ago", ""))
    assert 4 <= hours <= 6


def test_format_time_ago_days() -> None:
    """A timestamp from 3 days ago should return '3d ago'."""
    three_d_ago = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = format_time_ago(three_d_ago)
    assert result.endswith("d ago")
    days = int(result.replace("d ago", ""))
    assert 2 <= days <= 4


def test_format_time_ago_old_returns_date_prefix() -> None:
    """A timestamp older than 7 days should return the date portion (YYYY-MM-DD)."""
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    result = format_time_ago(old)
    # Should be the first 10 chars of the ISO timestamp
    assert result == old[:10]


def test_format_time_ago_invalid_format_returns_unknown() -> None:
    """A malformed timestamp should return 'unknown' without raising."""
    assert format_time_ago("not-a-timestamp") == "unknown"
    assert format_time_ago("2026/01/01 12:00:00") == "unknown"


# =============================================================================
# PROFILE QUERIES — require initialized_db fixture
# =============================================================================


def _insert_test_agent(conn: sqlite3.Connection, name: str = "TEST_AGENT") -> None:
    """Helper to insert a test agent into the initialized database."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name, description, bio, status, role) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, "Test Agent", "A test agent", "Hello world", "online", "tester"),
    )
    conn.commit()


@patch("commons.apps.handlers.profiles.profile_queries.json_handler")
def test_get_profile_returns_agent_data(mock_json: object, initialized_db: object) -> None:
    """get_profile should return a dict with all profile fields for an existing agent."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    profile = get_profile(conn, "TEST_AGENT")
    assert profile is not None
    assert profile["branch_name"] == "TEST_AGENT"
    assert profile["bio"] == "Hello world"
    assert profile["status"] == "online"
    assert profile["role"] == "tester"


def test_get_profile_nonexistent_returns_none(initialized_db: object) -> None:
    """get_profile should return None for an agent that does not exist."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    profile = get_profile(conn, "GHOST_BRANCH")
    assert profile is None


@patch("commons.apps.handlers.profiles.profile_queries.json_handler")
def test_update_bio_changes_agent_bio(mock_json: object, initialized_db: object) -> None:
    """update_bio should change the bio text and return True for an existing agent."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = update_bio(conn, "TEST_AGENT", "New bio text")
    assert result is True

    profile = get_profile(conn, "TEST_AGENT")
    assert profile is not None
    assert profile["bio"] == "New bio text"


def test_update_bio_nonexistent_returns_false(initialized_db: object) -> None:
    """update_bio should return False when the agent does not exist."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    with patch("commons.apps.handlers.profiles.profile_queries.json_handler"):
        result = update_bio(conn, "NOBODY", "irrelevant")
    assert result is False


def test_update_status_changes_agent_status(initialized_db: object) -> None:
    """update_status should change the status and return True."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = update_status(conn, "TEST_AGENT", "busy building")
    assert result is True

    profile = get_profile(conn, "TEST_AGENT")
    assert profile is not None
    assert profile["status"] == "busy building"


def test_update_role_changes_agent_role(initialized_db: object) -> None:
    """update_role should change the role and return True."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = update_role(conn, "TEST_AGENT", "architect")
    assert result is True

    profile = get_profile(conn, "TEST_AGENT")
    assert profile is not None
    assert profile["role"] == "architect"


def test_increment_post_count(initialized_db: object) -> None:
    """increment_post_count should increase the agent's post_count by 1."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    stats_before = get_activity_stats(conn, "TEST_AGENT")
    assert stats_before is not None
    assert stats_before["post_count"] == 0

    increment_post_count(conn, "TEST_AGENT")
    conn.commit()

    stats = get_activity_stats(conn, "TEST_AGENT")
    assert stats is not None
    assert stats["post_count"] == 1


def test_increment_comment_count(initialized_db: object) -> None:
    """increment_comment_count should increase the agent's comment_count by 1."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    stats_before = get_activity_stats(conn, "TEST_AGENT")
    assert stats_before is not None
    assert stats_before["comment_count"] == 0

    increment_comment_count(conn, "TEST_AGENT")
    conn.commit()

    stats = get_activity_stats(conn, "TEST_AGENT")
    assert stats is not None
    assert stats["comment_count"] == 1


def test_get_all_agents_brief_includes_inserted_agents(initialized_db: object) -> None:
    """get_all_agents_brief should include agents inserted into the DB."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn, "ALPHA")
    _insert_test_agent(conn, "BETA")

    agents = get_all_agents_brief(conn)
    names = [a["branch_name"] for a in agents]
    assert "ALPHA" in names
    assert "BETA" in names
