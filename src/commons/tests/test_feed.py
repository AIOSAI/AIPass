# =================== AIPass ====================
# Name: test_feed.py
# Description: Unit tests for feed handler and feed module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Unit tests for the feed subsystem.

Tests cover:
- feed_ops.format_time_ago() -- pure timestamp formatting
- feed_ops.display_feed() -- argument parsing and query orchestration
- feed module handle_command() -- command routing logic
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# Coverage imports -- handler layer
from commons.apps.handlers.feed.feed_ops import format_time_ago, display_feed

# Coverage imports -- module layer
from commons.apps.modules.feed import handle_command


# =============================================================================
# format_time_ago tests
# =============================================================================

def test_format_time_ago_just_now():
    """Timestamps less than 60 seconds old should return 'just now'."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    assert result == "just now"


def test_format_time_ago_minutes():
    """Timestamps 1-59 minutes old should return '{n}m ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    assert result == "5m ago"


def test_format_time_ago_hours():
    """Timestamps 1-23 hours old should return '{n}h ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    assert result == "3h ago"


def test_format_time_ago_days():
    """Timestamps 1-6 days old should return '{n}d ago'."""
    ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    assert result == "2d ago"


def test_format_time_ago_old_date():
    """Timestamps older than 7 days should return the date portion (YYYY-MM-DD)."""
    ts = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    # Should be the first 10 chars of the timestamp (date portion)
    assert len(result) == 10
    assert result == ts[:10]


def test_format_time_ago_empty_string():
    """Empty string input should return 'never'."""
    assert format_time_ago("") == "never"


def test_format_time_ago_none():
    """None input should return 'never'."""
    assert format_time_ago(None) == "never"  # type: ignore[arg-type]


def test_format_time_ago_invalid_format():
    """Malformed timestamp string should return 'unknown'."""
    result = format_time_ago("not-a-timestamp")
    assert result == "unknown"


def test_format_time_ago_boundary_60_seconds():
    """Slightly over 60 seconds ago should return '1m ago', not 'just now'."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=65)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = format_time_ago(ts)
    assert result == "1m ago"


# =============================================================================
# display_feed argument parsing tests
# =============================================================================

@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_default_args(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """Calling display_feed with no args should use default sort=hot, limit=25, offset=0."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    result = display_feed([])

    assert result["success"] is True
    assert result["sort"] == "hot"
    assert result["limit"] == 25
    assert result["offset"] == 0
    assert result["room"] is None
    assert result["posts"] == []


@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_room_filter(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """The --room flag should filter the feed to a specific room."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    result = display_feed(["--room", "general"])

    assert result["success"] is True
    assert result["room"] == "general"


@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_sort_modes(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """The --sort flag should accept hot, new, top, activity; invalid values default to hot."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    for mode in ("hot", "new", "top", "activity"):
        result = display_feed(["--sort", mode])
        assert result["sort"] == mode, f"Sort mode '{mode}' was not preserved"

    # Verify the DB was actually queried during sort mode iteration
    assert mock_conn.execute.called

    # Invalid sort should fall back to hot
    result = display_feed(["--sort", "invalid"])
    assert result["sort"] == "hot"


@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_limit_clamping(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """Limit should be clamped between 1 and 100."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    result = display_feed(["--limit", "0"])
    assert result["limit"] == 1

    result = display_feed(["--limit", "999"])
    assert result["limit"] == 100

    result = display_feed(["--limit", "50"])
    assert result["limit"] == 50


@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_page_to_offset(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """The --page flag should convert to an offset based on the limit."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    result = display_feed(["--page", "3", "--limit", "10"])
    assert result["offset"] == 20  # (3-1) * 10


@patch("commons.apps.handlers.feed.feed_ops.json_handler")
@patch("commons.apps.handlers.feed.feed_ops.close_db")
@patch("commons.apps.handlers.feed.feed_ops.get_db")
def test_display_feed_negative_offset_clamped(
    mock_get_db: MagicMock, mock_close_db: MagicMock, mock_json: MagicMock,
) -> None:
    """Negative offset values should be clamped to 0."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_get_db.return_value = mock_conn

    result = display_feed(["--offset", "-5"])
    assert result["offset"] == 0


# =============================================================================
# handle_command routing tests
# =============================================================================

@patch("commons.apps.modules.feed.json_handler")
@patch("commons.apps.modules.feed.display_feed")
@patch("commons.apps.modules.feed.console")
def test_handle_command_routes_feed(
    mock_console: MagicMock, mock_display_feed: MagicMock, mock_json: MagicMock,
) -> None:
    """handle_command should route the 'feed' command and return True."""
    mock_display_feed.return_value = {
        "success": True,
        "posts": [],
        "total": 0,
        "sort": "hot",
        "room": None,
        "limit": 25,
        "offset": 0,
    }

    result = handle_command("feed", [])
    assert result is True
    mock_display_feed.assert_called_once_with([])


@patch("commons.apps.modules.feed.console")
def test_handle_command_rejects_unknown(mock_console: MagicMock) -> None:
    """handle_command should return False for non-feed commands."""
    assert handle_command("post", []) is False
    assert handle_command("search", []) is False
    assert handle_command("", []) is False
