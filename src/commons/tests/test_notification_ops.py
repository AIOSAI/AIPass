# ===================AIPASS====================
# META DATA HEADER
# Name: test_notification_ops.py - Notification Operations Tests
# Date: 2026-04-03
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-04-03): Initial creation — notification_ops handler tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks get_db, close_db, get_caller_branch, json_handler, and logger
# =============================================

"""
Unit tests for notification_ops.py — the high-level notification operations layer.

Covers:
- set_watch: watch a room, post, or thread
- set_mute: mute a room, post, or thread
- set_track: track a room, post, or thread
- _set_notification_level: shared arg parsing, validation, target existence checks
- show_preferences: display all preferences for the calling agent

NOTE: test_notifications.py already covers the lower-level preferences.py functions
(set_preference, get_preference, get_all_preferences, should_notify, get_watchers).
These tests focus on the operations layer: arg parsing, caller detection, DB lifecycle,
target validation, and error paths.
"""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest


# =============================================================================
# HELPERS
# =============================================================================


def _insert_agent(conn: sqlite3.Connection, name: str = "test-branch") -> None:
    """Insert a test agent so foreign key constraints are satisfied."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (name, name.replace("-", " ").title()),
    )
    conn.commit()


def _insert_room(conn: sqlite3.Connection, name: str = "general") -> None:
    """Insert a room (requires SYSTEM agent)."""
    _insert_agent(conn, "SYSTEM")
    conn.execute(
        "INSERT OR IGNORE INTO rooms (name, display_name, description, created_by) "
        "VALUES (?, ?, ?, ?)",
        (name, name.title(), f"Test room {name}", "SYSTEM"),
    )
    conn.commit()


def _insert_post(conn: sqlite3.Connection, post_id: int = 1, room: str = "general", author: str = "test-branch") -> int:
    """Insert a post and return its id."""
    _insert_agent(conn, author)
    _insert_room(conn, room)
    conn.execute(
        "INSERT OR REPLACE INTO posts (id, room_name, author, title, content) "
        "VALUES (?, ?, ?, ?, ?)",
        (post_id, room, author, "Test Post", "Test content"),
    )
    conn.commit()
    return post_id


# The mock target paths — all point into notification_ops module namespace
_MOCK_GET_DB = "commons.apps.handlers.notifications.notification_ops.get_db"
_MOCK_CLOSE_DB = "commons.apps.handlers.notifications.notification_ops.close_db"
_MOCK_CALLER = "commons.apps.handlers.notifications.notification_ops.get_caller_branch"
_MOCK_JSON = "commons.apps.handlers.notifications.notification_ops.json_handler"
_MOCK_LOGGER = "commons.apps.handlers.notifications.notification_ops.logger"
# Also mock the preferences-layer logger/json to avoid side effects
_MOCK_PREF_JSON = "commons.apps.handlers.notifications.preferences.json_handler"
_MOCK_PREF_LOGGER = "commons.apps.handlers.notifications.preferences.logger"


# =============================================================================
# set_watch
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_room_success(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """set_watch should set notification level to 'watch' for a valid room."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")
    # 'general' room is seeded by initialized_db

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general"])

    assert result["success"] is True
    assert result["level"] == "watch"
    assert result["target_type"] == "room"
    assert result["target_id"] == "general"
    assert result["agent"] == "test-branch"
    mock_close_db.assert_called_once_with(conn)


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_post_success(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """set_watch should set notification level to 'watch' for a valid post."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")
    _insert_post(conn, post_id=42)

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["post", "42"])

    assert result["success"] is True
    assert result["level"] == "watch"
    assert result["target_type"] == "post"
    assert result["target_id"] == "42"


# =============================================================================
# set_mute
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_mute_room_success(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """set_mute should set notification level to 'mute' for a valid room."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["room", "general"])

    assert result["success"] is True
    assert result["level"] == "mute"
    assert result["target_type"] == "room"
    assert result["target_id"] == "general"
    assert result["agent"] == "test-branch"


# =============================================================================
# set_track
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_track_thread_success(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """set_track should set notification level to 'track' for a valid thread (post)."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")
    _insert_post(conn, post_id=10)

    from commons.apps.handlers.notifications.notification_ops import set_track

    result = set_track(["thread", "10"])

    assert result["success"] is True
    assert result["level"] == "track"
    assert result["target_type"] == "thread"
    assert result["target_id"] == "10"


# =============================================================================
# Argument validation (too few args)
# =============================================================================


def test_set_watch_too_few_args() -> None:
    """set_watch with fewer than 2 args should return usage error."""
    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room"])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_set_mute_no_args() -> None:
    """set_mute with no args should return usage error."""
    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute([])
    assert result["success"] is False
    assert "Usage" in result["error"]


def test_set_track_single_arg() -> None:
    """set_track with 1 arg should return usage error."""
    from commons.apps.handlers.notifications.notification_ops import set_track

    result = set_track(["post"])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# Invalid target type
# =============================================================================


@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
def test_set_watch_invalid_target_type(mock_caller: MagicMock) -> None:
    """Passing an unsupported target type should return an error."""
    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["channel", "general"])
    assert result["success"] is False
    assert "Invalid target type" in result["error"]
    assert "'channel'" in result["error"]


@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
def test_set_mute_invalid_target_type(mock_caller: MagicMock) -> None:
    """Passing 'user' as target type should fail validation."""
    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["user", "someone"])
    assert result["success"] is False
    assert "Invalid target type" in result["error"]


# =============================================================================
# Caller not detected
# =============================================================================


@patch(_MOCK_CALLER, return_value=None)
def test_set_watch_no_caller(mock_caller: MagicMock) -> None:
    """When get_caller_branch returns None, operations should fail with caller error."""
    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general"])
    assert result["success"] is False
    assert "Could not detect calling branch" in result["error"]


@patch(_MOCK_CALLER, return_value=None)
def test_set_mute_no_caller(mock_caller: MagicMock) -> None:
    """set_mute should also fail when caller is undetectable."""
    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["room", "general"])
    assert result["success"] is False
    assert "Could not detect" in result["error"]


@patch(_MOCK_CALLER, return_value=None)
def test_set_track_no_caller(mock_caller: MagicMock) -> None:
    """set_track should also fail when caller is undetectable."""
    from commons.apps.handlers.notifications.notification_ops import set_track

    result = set_track(["post", "1"])
    assert result["success"] is False
    assert "Could not detect" in result["error"]


# =============================================================================
# Target does not exist in DB
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_room_not_found(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Watching a nonexistent room should return room-not-found error."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "nonexistent-room"])
    assert result["success"] is False
    assert "not found" in result["error"]
    mock_close_db.assert_called_once_with(conn)


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_mute_post_not_found(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Muting a nonexistent post should return post-not-found error."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["post", "9999"])
    assert result["success"] is False
    assert "not found" in result["error"]


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_track_thread_not_found(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Tracking a nonexistent thread should return not-found error."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_track

    result = set_track(["thread", "8888"])
    assert result["success"] is False
    assert "not found" in result["error"]


# =============================================================================
# Invalid post/thread ID (not a number)
# =============================================================================


@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_post_id_not_numeric(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Watching a post with a non-numeric ID should return an error."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["post", "abc"])
    assert result["success"] is False
    assert "must be a number" in result["error"]


@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_track_thread_id_not_numeric(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Tracking a thread with a non-numeric ID should return an error."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_track

    result = set_track(["thread", "not-a-number"])
    assert result["success"] is False
    assert "must be a number" in result["error"]


# =============================================================================
# Room name case normalization
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_room_name_lowercased(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Room names should be lowercased before lookup and storage."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    # Pass mixed-case — 'General' should resolve to 'general'
    result = set_watch(["room", "General"])
    assert result["success"] is True
    assert result["target_id"] == "general"


# =============================================================================
# Target type case normalization
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_mute_target_type_case_insensitive(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Target type should be lowercased, so 'ROOM' works like 'room'."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["ROOM", "general"])
    assert result["success"] is True
    assert result["target_type"] == "room"


# =============================================================================
# DB exception handling
# =============================================================================


@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_GET_DB, side_effect=Exception("disk full"))
def test_set_watch_db_exception(
    mock_get_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """When get_db raises an exception, result should capture the error."""
    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general"])
    assert result["success"] is False
    assert "disk full" in result["error"]


# =============================================================================
# show_preferences
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_show_preferences_empty(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """show_preferences with no preferences set should return empty list."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import show_preferences

    result = show_preferences([])
    assert result["success"] is True
    assert result["agent"] == "test-branch"
    assert result["preferences"] == []
    mock_close_db.assert_called_once_with(conn)


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_show_preferences_with_data(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """show_preferences should return all preferences for the agent."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.preferences import set_preference
    from commons.apps.handlers.notifications.notification_ops import show_preferences

    set_preference(conn, "test-branch", "room", "general", "watch")
    set_preference(conn, "test-branch", "post", "5", "mute")

    result = show_preferences([])
    assert result["success"] is True
    assert result["agent"] == "test-branch"
    assert len(result["preferences"]) == 2

    levels = {(p["target_type"], p["target_id"]): p["level"] for p in result["preferences"]}
    assert levels[("room", "general")] == "watch"
    assert levels[("post", "5")] == "mute"


@patch(_MOCK_CALLER, return_value=None)
def test_show_preferences_no_caller(mock_caller: MagicMock) -> None:
    """show_preferences should fail when caller is not detected."""
    from commons.apps.handlers.notifications.notification_ops import show_preferences

    result = show_preferences([])
    assert result["success"] is False
    assert "Could not detect" in result["error"]


@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_GET_DB, side_effect=Exception("connection refused"))
def test_show_preferences_db_exception(
    mock_get_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
) -> None:
    """show_preferences should handle DB exceptions gracefully."""
    from commons.apps.handlers.notifications.notification_ops import show_preferences

    result = show_preferences([])
    assert result["success"] is False
    assert "connection refused" in result["error"]


# =============================================================================
# json_handler.log_operation is called on success
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_logs_operation(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Successful watch should call json_handler.log_operation with 'notification_set'."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general"])
    assert result["success"] is True
    mock_json.log_operation.assert_called_once_with(
        "notification_set",
        {"agent": "test-branch", "level": "watch", "target_type": "room"},
    )


# =============================================================================
# set_preference returns False path
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
@patch("commons.apps.handlers.notifications.notification_ops.set_preference", return_value=False)
def test_set_watch_preference_fails(
    mock_set_pref: MagicMock,
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """When set_preference returns False, the operation should report failure."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general"])
    assert result["success"] is False
    assert "Failed to set preference" in result["error"]


# =============================================================================
# Extra args are ignored (only first two used)
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_watch_extra_args_ignored(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Extra arguments beyond the first two should be ignored."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")

    from commons.apps.handlers.notifications.notification_ops import set_watch

    result = set_watch(["room", "general", "extra", "stuff"])
    assert result["success"] is True
    assert result["target_type"] == "room"
    assert result["target_id"] == "general"


# =============================================================================
# Post ID normalization (string -> int -> string)
# =============================================================================


@patch(_MOCK_PREF_LOGGER)
@patch(_MOCK_PREF_JSON)
@patch(_MOCK_LOGGER)
@patch(_MOCK_JSON)
@patch(_MOCK_CALLER, return_value={"name": "test-branch"})
@patch(_MOCK_CLOSE_DB)
@patch(_MOCK_GET_DB)
def test_set_mute_post_id_normalized(
    mock_get_db: MagicMock,
    mock_close_db: MagicMock,
    mock_caller: MagicMock,
    mock_json: MagicMock,
    mock_logger: MagicMock,
    mock_pref_json: MagicMock,
    mock_pref_logger: MagicMock,
    initialized_db: object,
) -> None:
    """Post ID should be normalized through int conversion (e.g. '042' -> '42')."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    mock_get_db.return_value = conn
    _insert_agent(conn, "test-branch")
    _insert_post(conn, post_id=42)

    from commons.apps.handlers.notifications.notification_ops import set_mute

    result = set_mute(["post", "042"])
    assert result["success"] is True
    assert result["target_id"] == "42"
