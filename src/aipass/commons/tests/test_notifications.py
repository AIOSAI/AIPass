# ===================AIPASS====================
# META DATA HEADER
# Name: test_notifications.py - Notification Preferences Tests
# Description: Tests for apps/handlers/notifications/preferences.py
# Date: 2026-03-28
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-09-27
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — notification preferences handler tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger and json_handler to avoid side-effect dependencies
# =============================================

"""Tests for apps/handlers/notifications/preferences.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/notifications/ parses and imports

import sqlite3
from unittest.mock import MagicMock, patch


from aipass.commons.apps.handlers.notifications.preferences import (
    get_preference,
    set_preference,
    get_all_preferences,
    should_notify,
    get_watchers,
)


# =============================================================================
# HELPERS
# =============================================================================


def _insert_test_agent(conn: sqlite3.Connection, name: str = "TEST_BRANCH") -> None:
    """Insert a test agent so foreign key constraints are satisfied."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (name, "Test"),
    )
    conn.commit()


# =============================================================================
# set_preference
# =============================================================================


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_set_preference_and_retrieve(
    mock_json: object,
    initialized_db: object,
) -> None:
    """Setting a preference should persist it and be retrievable via get_preference."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = set_preference(conn, "TEST_BRANCH", "room", "general", "watch")
    assert result is True

    level = get_preference(conn, "TEST_BRANCH", "room", "general")
    assert level == "watch"


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_set_preference_update_existing(
    mock_json: object,
    initialized_db: object,
) -> None:
    """Updating an existing preference should overwrite the previous level."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    set_preference(conn, "TEST_BRANCH", "room", "dev", "watch")
    assert get_preference(conn, "TEST_BRANCH", "room", "dev") == "watch"

    set_preference(conn, "TEST_BRANCH", "room", "dev", "mute")
    assert get_preference(conn, "TEST_BRANCH", "room", "dev") == "mute"


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.notifications.preferences.logger")
def test_set_preference_invalid_level(
    mock_logger: MagicMock,
    mock_json: object,
    initialized_db: object,
) -> None:
    """Setting a preference with an invalid level should return False."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = set_preference(conn, "TEST_BRANCH", "room", "general", "silent")
    assert result is False
    mock_logger.warning.assert_called_once_with("Invalid level: silent")


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
@patch("aipass.commons.apps.handlers.notifications.preferences.logger")
def test_set_preference_invalid_target_type(
    mock_logger: MagicMock,
    mock_json: object,
    initialized_db: object,
) -> None:
    """Setting a preference with an invalid target_type should return False."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = set_preference(conn, "TEST_BRANCH", "channel", "general", "watch")
    assert result is False
    mock_logger.warning.assert_called_once_with("Invalid target_type: channel")


# =============================================================================
# get_preference
# =============================================================================


def test_get_preference_nonexistent(initialized_db: object) -> None:
    """get_preference should return None when no preference exists for the agent/target."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    level = get_preference(conn, "TEST_BRANCH", "room", "nonexistent-room")
    assert level is None


# =============================================================================
# get_all_preferences
# =============================================================================


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_get_all_preferences_returns_all(
    mock_json: object,
    initialized_db: object,
) -> None:
    """get_all_preferences should return all preferences set for an agent."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    set_preference(conn, "TEST_BRANCH", "room", "general", "watch")
    set_preference(conn, "TEST_BRANCH", "room", "dev", "mute")
    set_preference(conn, "TEST_BRANCH", "post", "42", "track")

    prefs = get_all_preferences(conn, "TEST_BRANCH")
    assert len(prefs) == 3

    levels = {(p["target_type"], p["target_id"]): p["level"] for p in prefs}
    assert levels[("room", "general")] == "watch"
    assert levels[("room", "dev")] == "mute"
    assert levels[("post", "42")] == "track"


def test_get_all_preferences_empty_for_new_agent(initialized_db: object) -> None:
    """get_all_preferences should return an empty list for an agent with no preferences."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn, "FRESH_BRANCH")

    prefs = get_all_preferences(conn, "FRESH_BRANCH")
    assert prefs == []


# =============================================================================
# should_notify
# =============================================================================


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_should_notify_mute_returns_false(
    mock_json: object,
    initialized_db: object,
) -> None:
    """An agent with mute preference should never be notified."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    set_preference(conn, "TEST_BRANCH", "room", "general", "mute")

    assert should_notify(conn, "TEST_BRANCH", "room", "general", "mention") is False
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reply") is False
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "new_post") is False


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_should_notify_watch_returns_true_for_any_event(
    mock_json: object,
    initialized_db: object,
) -> None:
    """An agent with watch preference should be notified for all event types."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    set_preference(conn, "TEST_BRANCH", "room", "general", "watch")

    assert should_notify(conn, "TEST_BRANCH", "room", "general", "mention") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reply") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "new_post") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reaction") is True


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_should_notify_track_only_mention_and_reply(
    mock_json: object,
    initialized_db: object,
) -> None:
    """An agent with track preference should only be notified for mention and reply events."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    set_preference(conn, "TEST_BRANCH", "room", "general", "track")

    assert should_notify(conn, "TEST_BRANCH", "room", "general", "mention") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reply") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "new_post") is False
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reaction") is False


def test_should_notify_default_no_preference(initialized_db: object) -> None:
    """With no preference set, default behavior (track) should notify for mention/reply only."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    # No preference set — should default to track behavior
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "mention") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "reply") is True
    assert should_notify(conn, "TEST_BRANCH", "room", "general", "new_post") is False


# =============================================================================
# get_watchers
# =============================================================================


@patch("aipass.commons.apps.handlers.notifications.preferences.json_handler", autospec=True)
def test_get_watchers_returns_watching_agents(
    mock_json: object,
    initialized_db: object,
) -> None:
    """get_watchers should return only agents with watch level on the target."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn, "WATCHER_A")
    _insert_test_agent(conn, "WATCHER_B")
    _insert_test_agent(conn, "TRACKER_C")
    _insert_test_agent(conn, "MUTED_D")

    set_preference(conn, "WATCHER_A", "room", "general", "watch")
    set_preference(conn, "WATCHER_B", "room", "general", "watch")
    set_preference(conn, "TRACKER_C", "room", "general", "track")
    set_preference(conn, "MUTED_D", "room", "general", "mute")

    watchers = get_watchers(conn, "room", "general")
    assert sorted(watchers) == ["WATCHER_A", "WATCHER_B"]


def test_get_watchers_empty_when_no_watchers(initialized_db: object) -> None:
    """get_watchers should return an empty list when no agents are watching."""
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]

    watchers = get_watchers(conn, "room", "nonexistent")
    assert watchers == []
