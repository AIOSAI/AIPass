# =================== AIPass ====================
# META DATA HEADER
# Name: test_activity.py - Activity, Catchup, and Digest Tests
# Description: Tests for apps/handlers/activity/activity_ops.py, catchup_ops.py and digest_ops.py
# Date: 2026-03-28
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-09-28
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

"""Tests for apps/handlers/activity/activity_ops.py, catchup_ops.py and digest_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/activity/, catchup/, digest/ parses and imports
# seedgo: no-test-needed(covered) — what query_catchup_data() gathers for catchup: test_space_catchup

import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from aipass.commons.apps.handlers.activity.activity_ops import run_activity
from aipass.commons.apps.handlers.catchup.catchup_ops import run_catchup
from aipass.commons.apps.handlers.digest.digest_ops import show_digest


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


def _ago(**delta: float) -> str:
    """An ISO-Z timestamp the given timedelta before now (negative values reach into the future)."""
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def activity_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point run_activity at the tmp database, and its operation log at nothing."""
    monkeypatch.setattr("aipass.commons.apps.handlers.activity.activity_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.activity.activity_ops.close_db", lambda conn: None)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.activity.activity_ops.json_handler.log_operation", lambda *a, **k: None
    )
    _insert_agent(initialized_db, "TEST_BRANCH", "Test")
    return initialized_db


def _one_activity(conn: sqlite3.Connection, content: str = "c", created_at: str | None = None) -> Dict[str, Any]:
    """Post one comment, run 'commons activity', return the one activity row it shows."""
    conn.execute("DELETE FROM comments")
    conn.commit()
    post_id = _insert_post(conn, "Post", "Body", "general", "TEST_BRANCH")
    _insert_comment(conn, post_id, "TEST_BRANCH", content)
    if created_at is not None:
        # Set after the insert: _insert_comment reads "" as "use the default", and "" is a case here.
        conn.execute("UPDATE comments SET created_at = ?", (created_at,))
        conn.commit()
    result = run_activity([])
    assert result["success"] is True, result
    assert len(result["activities"]) == 1
    return result["activities"][0]


@pytest.fixture
def catchup_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point run_catchup at the tmp database with CATCHUP_BRANCH as the caller."""
    monkeypatch.setattr("aipass.commons.apps.handlers.catchup.catchup_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.catchup.catchup_ops.close_db", lambda conn: None)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.catchup.catchup_ops.get_caller_branch", lambda: {"name": "CATCHUP_BRANCH"}
    )
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.catchup.catchup_ops.json_handler.log_operation", lambda *a, **k: None
    )
    _insert_agent(initialized_db, "CATCHUP_BRANCH")
    return initialized_db


def _catchup_label(conn: sqlite3.Connection, last_active: str) -> str:
    """Give CATCHUP_BRANCH a last visit, run 'commons catchup', return its time label."""
    conn.execute("UPDATE agents SET last_active = ? WHERE branch_name = 'CATCHUP_BRANCH'", (last_active,))
    conn.commit()
    result = run_catchup()
    assert result["success"] is True, result
    assert result["is_first_visit"] is False
    return result["time_label"]


@pytest.fixture
def digest_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point show_digest at the tmp database, and its operation log at nothing."""
    monkeypatch.setattr("aipass.commons.apps.handlers.digest.digest_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.digest.digest_ops.close_db", lambda conn: None)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.digest.digest_ops.json_handler.log_operation", lambda *a, **k: None
    )
    return initialized_db


def _digest() -> Dict[str, Any]:
    """Run 'commons digest' and return its data."""
    result = show_digest()
    assert result["success"] is True, result
    return result


# =============================================================================
# activity's relative time — the "time" column of 'commons activity'
# =============================================================================


def test_relative_time_just_now(activity_db: sqlite3.Connection) -> None:
    """Timestamps less than 60 seconds ago should show 'just now'.

    Mutant: `if total_seconds < 60:` -> `if total_seconds < 5:` reddens this.
    """
    assert _one_activity(activity_db, created_at=_ago(seconds=10))["time"] == "just now"


def test_relative_time_minutes_ago(activity_db: sqlite3.Connection) -> None:
    """Timestamps a few minutes ago should show '<N>m ago'.

    Mutant: `minutes = total_seconds // 60` -> `minutes = total_seconds // 30` reddens this.
    """
    assert _one_activity(activity_db, created_at=_ago(minutes=5))["time"] == "5m ago"


def test_relative_time_hours_ago(activity_db: sqlite3.Connection) -> None:
    """Timestamps a few hours ago should show '<N>h ago'.

    Mutant: `hours = total_seconds // 3600` -> `hours = total_seconds // 60` reddens this.
    """
    assert _one_activity(activity_db, created_at=_ago(hours=3))["time"] == "3h ago"


def test_relative_time_days_ago(activity_db: sqlite3.Connection) -> None:
    """Timestamps days ago should show '<N>d ago'.

    Mutant: `days = total_seconds // 86400` -> `days = total_seconds // 3600` reddens this.
    """
    assert _one_activity(activity_db, created_at=_ago(days=7))["time"] == "7d ago"


def test_relative_time_future_timestamp(activity_db: sqlite3.Connection) -> None:
    """Future timestamps produce negative deltas; should show 'just now' (negative seconds < 60).

    Mutant: `if total_seconds < 60:` -> `if 0 <= total_seconds < 60:` reddens this.
    """
    # A negative delta is still < 60, so the first arm claims it and a clock
    # skew reads as "just now" rather than "unknown" or a negative "-60m ago".
    # Naming the string is what makes that a decision instead of an accident.
    assert _one_activity(activity_db, created_at=_ago(hours=-1))["time"] == "just now"


@patch("aipass.commons.apps.handlers.activity.activity_ops.logger")
def test_relative_time_invalid_string(mock_logger: MagicMock, activity_db: sqlite3.Connection) -> None:
    """Invalid timestamp strings should show 'unknown'.

    Mutant: the except branch's `return "unknown"` -> `return "just now"` reddens this.
    """
    assert _one_activity(activity_db, created_at="not-a-timestamp")["time"] == "unknown"
    assert _one_activity(activity_db, created_at="")["time"] == "unknown"
    assert mock_logger.warning.call_count == 2


# =============================================================================
# activity's truncation — the "content" column of 'commons activity' (60 chars)
# =============================================================================


def test_truncate_short_text_unchanged(activity_db: sqlite3.Connection) -> None:
    """Text shorter than max_len should be shown as-is.

    Mutant: `if len(text) <= max_len:` -> `if len(text) <= 5:` reddens this.
    """
    assert _one_activity(activity_db, content="hello world")["content"] == "hello world"


def test_truncate_long_text_with_ellipsis(activity_db: sqlite3.Connection) -> None:
    """Text longer than max_len should be truncated with '...' appended.

    Mutant: `text[: max_len - 3] + "..."` -> `text[:max_len] + "..."` reddens this.
    """
    result = _one_activity(activity_db, content="A" * 100)["content"]
    assert len(result) == 60
    assert result.endswith("...")


def test_truncate_exact_boundary(activity_db: sqlite3.Connection) -> None:
    """Text exactly at max_len should not be truncated.

    Mutant: `if len(text) <= max_len:` -> `if len(text) < max_len:` reddens this.
    """
    text = "A" * 60
    assert _one_activity(activity_db, content=text)["content"] == text


# =============================================================================
# catchup's time label — how 'commons catchup' names the last visit
# =============================================================================


def test_calculate_time_label_minutes(catchup_db: sqlite3.Connection) -> None:
    """Timestamps less than an hour ago should show minutes.

    Mutant: `if hours < 1:` -> `if hours < 0:` reddens this.
    """
    assert _catchup_label(catchup_db, _ago(minutes=15)) == "15 minutes ago"


def test_calculate_time_label_hours(catchup_db: sqlite3.Connection) -> None:
    """Timestamps a few hours ago should show hours.

    Mutant: `elif hours < 24:` -> `elif hours < 2:` reddens this.
    """
    assert _catchup_label(catchup_db, _ago(hours=6)) == "6 hours ago"


def test_calculate_time_label_days(catchup_db: sqlite3.Connection) -> None:
    """Timestamps more than 24 hours ago should show days.

    Mutant: `days = hours // 24` -> `days = hours // 12` reddens this.
    """
    assert _catchup_label(catchup_db, _ago(days=3)) == "3 days ago"


@patch("aipass.commons.apps.handlers.catchup.catchup_ops.logger")
def test_calculate_time_label_invalid(mock_logger: MagicMock, catchup_db: sqlite3.Connection) -> None:
    """Invalid timestamps should show the fallback string.

    Mutant: the except branch's `return "your last visit"` -> `return "the last 24 hours"` reddens this.
    """
    assert _catchup_label(catchup_db, "garbage") == "your last visit"
    parse_warnings = [c for c in mock_logger.warning.call_args_list if "last_active" in str(c)]
    assert len(parse_warnings) == 1


# =============================================================================
# run_activity — orchestrator with mocked DB
# =============================================================================


@patch("aipass.commons.apps.handlers.activity.activity_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.activity.activity_ops.close_db")
@patch("aipass.commons.apps.handlers.activity.activity_ops.get_db")
def test_run_activity_returns_formatted_activity(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """run_activity should query comments and return formatted activity dicts."""
    conn: sqlite3.Connection = initialized_db
    mock_get_db.return_value = conn
    mock_close.side_effect = lambda c: None

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


@patch("aipass.commons.apps.handlers.catchup.catchup_ops.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.update_last_active")
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.query_catchup_data")
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.get_last_active")
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.close_db")
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.get_db")
@patch("aipass.commons.apps.handlers.catchup.catchup_ops.get_caller_branch")
def test_run_catchup_first_visit(
    mock_caller: MagicMock,
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_last_active: MagicMock,
    mock_query: MagicMock,
    mock_update: MagicMock,
    mock_json: object,
) -> None:
    """run_catchup for a first-time visitor should set is_first_visit True.

    get_onboarding_nudge is no longer patched here: catchup_ops imports it
    locally inside run_catchup (`from ...welcome_handler import
    get_onboarding_nudge`), so a patch on the catchup_ops module attribute
    never reaches the call — a dead patch (discarded_patch.md's known limit),
    not a discarded one. Dropping it changes nothing: the real function
    already ran against the mocked db connection either way, and any error
    it raises is swallowed by run_catchup's own except-and-warn.
    """
    mock_caller.return_value = {"name": "NEW_BRANCH"}
    mock_get_db.return_value = MagicMock()
    mock_close.side_effect = lambda c: None
    mock_last_active.return_value = None
    mock_query.return_value = {
        "unread_mentions": [],
        "replies": [],
        "trending": None,
        "new_posts_count": 0,
        "new_comments_count": 0,
        "karma_change": 0,
    }
    mock_update.return_value = None

    result = run_catchup()

    assert result["success"] is True
    assert result["is_first_visit"] is True
    assert result["time_label"] == "the last 24 hours"


@patch("aipass.commons.apps.handlers.catchup.catchup_ops.get_caller_branch")
def test_run_catchup_no_caller(mock_caller: MagicMock) -> None:
    """run_catchup without a detectable caller branch should fail."""
    mock_caller.return_value = None
    result = run_catchup()
    assert result["success"] is False
    assert "Could not detect" in result["error"]


# =============================================================================
# DIGEST — the four boards of 'commons digest', reached through show_digest
# =============================================================================


def test_get_activity_totals_with_data(digest_db: sqlite3.Connection) -> None:
    """The digest totals count posts and comments from the last 24h.

    Mutant: the comment total's `FROM comments WHERE created_at >=` -> `FROM posts WHERE created_at >=` reddens this.
    """
    conn = digest_db

    _insert_agent(conn, "DIGEST_BRANCH", "Digest Tester")
    post_id = _insert_post(conn, "Digest Post", "Content here", "general", "DIGEST_BRANCH")
    _insert_comment(conn, post_id, "DIGEST_BRANCH", "Comment one")
    _insert_comment(conn, post_id, "DIGEST_BRANCH", "Comment two")

    totals = _digest()["totals"]
    assert totals["total_posts"] == 1
    assert totals["total_comments"] == 2


def test_get_activity_totals_empty_db(digest_db: sqlite3.Connection) -> None:
    """The digest totals on an empty DB are zeros.

    Mutant: _get_activity_totals' return -> `{"total_posts": post_count + 1, ...}` reddens this.
    """
    totals = _digest()["totals"]
    assert totals["total_posts"] == 0
    assert totals["total_comments"] == 0


def test_get_most_active_branches(digest_db: sqlite3.Connection) -> None:
    """The digest's active branches are sorted by activity.

    Mutant: `ORDER BY total_activity DESC` -> `ORDER BY total_activity ASC` reddens this.
    """
    conn = digest_db

    _insert_agent(conn, "ACTIVE_A", "Active A")
    _insert_agent(conn, "ACTIVE_B", "Active B")

    # ACTIVE_A: 2 posts, ACTIVE_B: 1 post
    _insert_post(conn, "Post 1", "Content", "general", "ACTIVE_A")
    _insert_post(conn, "Post 2", "Content", "general", "ACTIVE_A")
    _insert_post(conn, "Post 3", "Content", "general", "ACTIVE_B")

    branches = _digest()["active_branches"]
    assert len(branches) >= 2
    # First branch should be the most active
    assert branches[0]["agent"] == "ACTIVE_A"
    assert branches[0]["total_activity"] == 2


def test_get_new_branches(digest_db: sqlite3.Connection) -> None:
    """The digest's new branches include a branch that joined just now.

    Mutant: `AND branch_name NOT IN ('SYSTEM',` -> `AND branch_name IN ('SYSTEM',` reddens this.
    """
    # Insert a branch with a recent joined_at (default is 'now')
    _insert_agent(digest_db, "FRESH_BRANCH", "Fresh Branch")

    new_branches = _digest()["new_branches"]
    assert "FRESH_BRANCH" in new_branches


def test_get_top_posts_by_engagement(digest_db: sqlite3.Connection) -> None:
    """The digest's top posts are ordered by engagement.

    Mutant: `COALESCE(c.comment_count, 0) AS comment_count,` -> `0 AS comment_count,` reddens this.
    """
    conn = digest_db

    _insert_agent(conn, "TOP_AUTHOR", "Top Author")
    post_id = _insert_post(conn, "Popular Post", "Great content", "general", "TOP_AUTHOR")

    # Add some comments for engagement
    _insert_comment(conn, post_id, "TOP_AUTHOR", "Self-reply 1")
    _insert_comment(conn, post_id, "TOP_AUTHOR", "Self-reply 2")

    top = _digest()["top_posts"]
    assert len(top) >= 1
    assert top[0]["title"] == "Popular Post"
    assert top[0]["comment_count"] == 2


def test_run_catchup_refuses_naming_a_failed_caller_lookup():
    """A broken caller lookup is refused by name, not as "run from a branch directory".

    Before (DPLAN-0354 leg 3): get_caller_branch logged the error and answered None.
    The lookup raises before any database is opened.
    Mutant: catchup_ops `except CallerLookupFailed as exc:` -> `except KeyError as exc:` turns this red.
    """
    with patch(
        "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
        side_effect=OSError("registry unreadable"),
    ) as lookup:
        result = run_catchup()

    lookup.assert_called_once()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]
