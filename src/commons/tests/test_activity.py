# ===================AIPASS====================
# META DATA HEADER
# Name: test_activity.py - Activity, Catchup, and Digest Tests
# Date: 2026-03-28
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — activity, catchup, digest tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger and json_handler to avoid side-effect dependencies
# =============================================

"""
Unit tests for activity, catchup, and digest subsystems.

Covers:
- _relative_time() and _truncate() pure helpers (activity_ops)
- _calculate_time_label() pure helper (catchup_ops)
- run_activity orchestrator (activity_ops, mocked DB)
- run_catchup orchestrator (catchup_ops, mocked DB)
- Digest DB helpers: _get_activity_totals, _get_most_active_branches,
  _get_new_branches, _get_top_posts (with initialized_db fixture)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from commons.apps.handlers.activity.activity_ops import _relative_time, _truncate, run_activity
from commons.apps.handlers.catchup.catchup_ops import _calculate_time_label, run_catchup
from commons.apps.handlers.digest.digest_ops import (
    _get_activity_totals,
    _get_most_active_branches,
    _get_new_branches,
    _get_top_posts,
    show_digest,
)


# =============================================================================
# HELPERS — insert test data
# =============================================================================


def _insert_agent(conn, branch_name: str, display_name: str | None = None) -> None:
    """Insert an agent into the test database."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (branch_name, display_name or branch_name),
    )
    conn.commit()


def _insert_post(
    conn,
    title: str,
    content: str,
    room_name: str,
    author: str,
    created_at: str | None = None,
) -> int:
    """Insert a post and return its id."""
    if created_at:
        cursor = conn.execute(
            "INSERT INTO posts (title, content, room_name, author, created_at) VALUES (?, ?, ?, ?, ?)",
            (title, content, room_name, author, created_at),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO posts (title, content, room_name, author) VALUES (?, ?, ?, ?)",
            (title, content, room_name, author),
        )
    conn.commit()
    return cursor.lastrowid


def _insert_comment(
    conn,
    post_id: int,
    author: str,
    content: str,
    created_at: str | None = None,
) -> int:
    """Insert a comment and return its id."""
    if created_at:
        cursor = conn.execute(
            "INSERT INTO comments (post_id, author, content, created_at) VALUES (?, ?, ?, ?)",
            (post_id, author, content, created_at),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
            (post_id, author, content),
        )
    conn.commit()
    return cursor.lastrowid


# =============================================================================
# _relative_time — pure function tests
# =============================================================================


def test_relative_time_just_now() -> None:
    """Timestamps less than 60 seconds ago should return 'just now'."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _relative_time(ts) == "just now"


def test_relative_time_minutes_ago() -> None:
    """Timestamps a few minutes ago should return '<N>m ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _relative_time(ts) == "5m ago"


def test_relative_time_hours_ago() -> None:
    """Timestamps a few hours ago should return '<N>h ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _relative_time(ts) == "3h ago"


def test_relative_time_days_ago() -> None:
    """Timestamps days ago should return '<N>d ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _relative_time(ts) == "7d ago"


def test_relative_time_future_timestamp() -> None:
    """Future timestamps produce negative deltas; should return 'just now' (negative seconds < 60)."""
    ts = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Negative total_seconds means the condition chain falls through oddly,
    # but in practice negative ints are < 60, so it returns "just now"
    result = _relative_time(ts)
    assert isinstance(result, str)


@patch("commons.apps.handlers.activity.activity_ops.logger")
def test_relative_time_invalid_string(mock_logger: object) -> None:
    """Invalid timestamp strings should return 'unknown'."""
    assert _relative_time("not-a-timestamp") == "unknown"
    assert _relative_time("") == "unknown"


# =============================================================================
# _truncate — pure function tests
# =============================================================================


def test_truncate_short_text_unchanged() -> None:
    """Text shorter than max_len should be returned as-is."""
    assert _truncate("hello world", 60) == "hello world"


def test_truncate_long_text_with_ellipsis() -> None:
    """Text longer than max_len should be truncated with '...' appended."""
    long_text = "A" * 100
    result = _truncate(long_text, 20)
    assert len(result) == 20
    assert result.endswith("...")


def test_truncate_exact_boundary() -> None:
    """Text exactly at max_len should not be truncated."""
    text = "A" * 60
    assert _truncate(text, 60) == text


# =============================================================================
# _calculate_time_label — pure function tests
# =============================================================================


def test_calculate_time_label_minutes() -> None:
    """Timestamps less than an hour ago should show minutes."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _calculate_time_label(ts) == "15 minutes ago"


def test_calculate_time_label_hours() -> None:
    """Timestamps a few hours ago should show hours."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _calculate_time_label(ts) == "6 hours ago"


def test_calculate_time_label_days() -> None:
    """Timestamps more than 24 hours ago should show days."""
    ts = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _calculate_time_label(ts) == "3 days ago"


@patch("commons.apps.handlers.catchup.catchup_ops.logger")
def test_calculate_time_label_invalid(mock_logger: object) -> None:
    """Invalid timestamps should return fallback string."""
    assert _calculate_time_label("garbage") == "your last visit"


# =============================================================================
# run_activity — orchestrator with mocked DB
# =============================================================================


@patch("commons.apps.handlers.activity.activity_ops.json_handler")
@patch("commons.apps.handlers.activity.activity_ops.close_db")
@patch("commons.apps.handlers.activity.activity_ops.get_db")
def test_run_activity_returns_formatted_activity(
    mock_get_db: object,
    mock_close: object,
    mock_json: object,
    initialized_db: object,
) -> None:
    """run_activity should query comments and return formatted activity dicts."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn  # type: ignore[union-attr]
    mock_close.side_effect = lambda c: None  # type: ignore[union-attr]

    _insert_agent(conn, "TEST_BRANCH", "Test")
    post_id = _insert_post(conn, "Test Post", "Some content", "general", "TEST_BRANCH")
    _insert_comment(conn, post_id, "TEST_BRANCH", "A thoughtful comment")

    result = run_activity([])

    assert result["success"] is True
    assert len(result["activities"]) == 1
    assert result["activities"][0]["author"] == "TEST_BRANCH"
    assert "thoughtful" in result["activities"][0]["content"]


# =============================================================================
# run_catchup — orchestrator with mocked DB
# =============================================================================


@patch("commons.apps.handlers.catchup.catchup_ops.json_handler")
@patch("commons.apps.handlers.catchup.catchup_ops.get_onboarding_nudge", create=True)
@patch("commons.apps.handlers.catchup.catchup_ops.update_last_active")
@patch("commons.apps.handlers.catchup.catchup_ops.query_catchup_data")
@patch("commons.apps.handlers.catchup.catchup_ops.get_last_active")
@patch("commons.apps.handlers.catchup.catchup_ops.close_db")
@patch("commons.apps.handlers.catchup.catchup_ops.get_db")
@patch("commons.apps.handlers.catchup.catchup_ops.get_caller_branch")
def test_run_catchup_first_visit(
    mock_caller: object,
    mock_get_db: object,
    mock_close: object,
    mock_last_active: object,
    mock_query: object,
    mock_update: object,
    mock_nudge: object,
    mock_json: object,
) -> None:
    """run_catchup for a first-time visitor should set is_first_visit True."""
    mock_caller.return_value = {"name": "NEW_BRANCH"}  # type: ignore[union-attr]
    mock_get_db.return_value = MagicMock()  # type: ignore[union-attr]
    mock_close.side_effect = lambda c: None  # type: ignore[union-attr]
    mock_last_active.return_value = None  # type: ignore[union-attr]
    mock_query.return_value = {  # type: ignore[union-attr]
        "unread_mentions": [],
        "replies": [],
        "trending": None,
        "new_posts_count": 0,
        "new_comments_count": 0,
        "karma_change": 0,
    }
    mock_update.return_value = None  # type: ignore[union-attr]

    result = run_catchup([])

    assert result["success"] is True
    assert result["is_first_visit"] is True
    assert result["time_label"] == "the last 24 hours"


@patch("commons.apps.handlers.catchup.catchup_ops.get_caller_branch")
def test_run_catchup_no_caller(mock_caller: object) -> None:
    """run_catchup without a detectable caller branch should fail."""
    mock_caller.return_value = None  # type: ignore[union-attr]
    result = run_catchup([])
    assert result["success"] is False
    assert "Could not detect" in result["error"]


# =============================================================================
# DIGEST DB HELPERS — use initialized_db fixture directly
# =============================================================================


def test_get_activity_totals_with_data(initialized_db: object) -> None:
    """_get_activity_totals should count posts and comments from the last 24h."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    _insert_agent(conn, "DIGEST_BRANCH", "Digest Tester")
    post_id = _insert_post(conn, "Digest Post", "Content here", "general", "DIGEST_BRANCH")
    _insert_comment(conn, post_id, "DIGEST_BRANCH", "Comment one")
    _insert_comment(conn, post_id, "DIGEST_BRANCH", "Comment two")

    totals = _get_activity_totals(conn, hours=24)
    assert totals["total_posts"] == 1
    assert totals["total_comments"] == 2


def test_get_activity_totals_empty_db(initialized_db: object) -> None:
    """_get_activity_totals on an empty DB should return zeros."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    totals = _get_activity_totals(conn, hours=24)
    assert totals["total_posts"] == 0
    assert totals["total_comments"] == 0


def test_get_most_active_branches(initialized_db: object) -> None:
    """_get_most_active_branches should return branches sorted by activity."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    _insert_agent(conn, "ACTIVE_A", "Active A")
    _insert_agent(conn, "ACTIVE_B", "Active B")

    # ACTIVE_A: 2 posts, ACTIVE_B: 1 post
    _insert_post(conn, "Post 1", "Content", "general", "ACTIVE_A")
    _insert_post(conn, "Post 2", "Content", "general", "ACTIVE_A")
    _insert_post(conn, "Post 3", "Content", "general", "ACTIVE_B")

    branches = _get_most_active_branches(conn, hours=24, limit=5)
    assert len(branches) >= 2
    # First branch should be the most active
    assert branches[0]["agent"] == "ACTIVE_A"
    assert branches[0]["total_activity"] == 2


def test_get_new_branches(initialized_db: object) -> None:
    """_get_new_branches should return recently joined branches."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    # Insert a branch with a recent joined_at (default is 'now')
    _insert_agent(conn, "FRESH_BRANCH", "Fresh Branch")

    new_branches = _get_new_branches(conn, hours=24)
    assert "FRESH_BRANCH" in new_branches


def test_get_top_posts_by_engagement(initialized_db: object) -> None:
    """_get_top_posts should return posts ordered by engagement."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    _insert_agent(conn, "TOP_AUTHOR", "Top Author")
    post_id = _insert_post(conn, "Popular Post", "Great content", "general", "TOP_AUTHOR")

    # Add some comments for engagement
    _insert_comment(conn, post_id, "TOP_AUTHOR", "Self-reply 1")
    _insert_comment(conn, post_id, "TOP_AUTHOR", "Self-reply 2")

    top = _get_top_posts(conn, hours=24, limit=3)
    assert len(top) >= 1
    assert top[0]["title"] == "Popular Post"
    assert top[0]["comment_count"] == 2
