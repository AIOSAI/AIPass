# ===================AIPASS====================
# META DATA HEADER
# Name: test_rooms.py - Room and Space Module Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation — rooms handler + space module tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger and json_handler to avoid side-effect dependencies
# =============================================

"""
Unit tests for room operations and spatial navigation helpers.

Covers:
- MOOD_STYLES dict completeness
- _mood_style() and _mood_icon() pure functions
- create_room / list_rooms / join_room via room_ops (with DB fixture)
- Room state operations (set/get room state)
- Room query edge cases (nonexistent rooms, empty args)
"""

from unittest.mock import patch

import pytest

from commons.apps.modules.space import MOOD_STYLES, _mood_style, _mood_icon
from commons.apps.handlers.rooms.room_ops import create_room, list_rooms, join_room
from commons.apps.handlers.rooms.room_state_ops import (
    set_room_state,
    get_room_state,
    get_all_room_state,
)


# =============================================================================
# MOOD HELPERS — pure functions, no DB needed
# =============================================================================


def test_mood_styles_contains_expected_moods():
    """Verify MOOD_STYLES contains all six documented moods."""
    expected = {"welcoming", "relaxed", "focused", "neutral", "tense", "celebratory"}
    assert expected == set(MOOD_STYLES.keys())


def test_mood_styles_values_are_color_icon_tuples():
    """Each MOOD_STYLES entry should be a (color_str, icon_str) tuple."""
    for mood, value in MOOD_STYLES.items():
        assert isinstance(value, tuple), f"Expected tuple for mood '{mood}'"
        assert len(value) == 2, f"Expected 2-element tuple for mood '{mood}'"
        color, icon = value
        assert isinstance(color, str) and color, f"Color must be a non-empty string for '{mood}'"
        assert isinstance(icon, str) and icon, f"Icon must be a non-empty string for '{mood}'"


def test_mood_style_returns_correct_color():
    """_mood_style should return the Rich color string for known moods."""
    assert _mood_style("welcoming") == "green"
    assert _mood_style("tense") == "red"
    assert _mood_style("celebratory") == "magenta"


def test_mood_style_unknown_mood_returns_dim():
    """_mood_style should fall back to 'dim' for unrecognized moods."""
    assert _mood_style("chaotic") == "dim"
    assert _mood_style("") == "dim"


def test_mood_icon_returns_correct_icon():
    """_mood_icon should return the text icon for known moods."""
    assert _mood_icon("welcoming") == "~"
    assert _mood_icon("tense") == "!"
    assert _mood_icon("focused") == "|"


def test_mood_icon_unknown_mood_returns_dash():
    """_mood_icon should fall back to '-' for unrecognized moods."""
    assert _mood_icon("mysterious") == "-"
    assert _mood_icon("") == "-"


# =============================================================================
# ROOM OPS — require initialized_db fixture
# =============================================================================


@patch("commons.apps.handlers.rooms.room_ops.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("commons.apps.handlers.rooms.room_ops.get_db")
@patch("commons.apps.handlers.rooms.room_ops.close_db")
@patch("commons.apps.handlers.rooms.room_ops.json_handler")
def test_create_room_success(
    mock_json: object,
    mock_close: object,
    mock_get_db: object,
    mock_caller: object,
    initialized_db: object,
) -> None:
    """Creating a room with valid args should return success with room metadata."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]
    mock_close.side_effect = lambda conn: None  # type: ignore[union-attr]

    # Insert the agent so the foreign key constraint is satisfied
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("TEST_BRANCH", "Test Branch"),
    )
    conn.commit()

    result = create_room(["test-lab", "A", "test", "laboratory"])

    assert result["success"] is True
    assert result["name"] == "test-lab"
    assert result["description"] == "A test laboratory"
    assert result["created_by"] == "TEST_BRANCH"

    # Verify the room was actually persisted in the database
    row = conn.execute("SELECT * FROM rooms WHERE name = ?", ("test-lab",)).fetchone()
    assert row is not None


def test_create_room_no_args() -> None:
    """Calling create_room with empty args should return an error dict."""
    result = create_room([])
    assert result["success"] is False
    assert "Room name required" in result["error"]


@patch("commons.apps.handlers.rooms.room_ops.get_caller_branch", return_value=None)
def test_create_room_no_caller(mock_caller: object) -> None:
    """Creating a room when caller branch is undetectable should fail gracefully."""
    result = create_room(["orphan-room"])
    assert result["success"] is False
    assert "Could not detect calling branch" in result["error"]


@patch("commons.apps.handlers.rooms.room_ops.get_db")
@patch("commons.apps.handlers.rooms.room_ops.close_db")
def test_list_rooms_returns_seeded_rooms(
    mock_close: object,
    mock_get_db: object,
    initialized_db: object,
) -> None:
    """list_rooms should return the default seeded rooms from init_db."""
    mock_get_db.return_value = initialized_db  # type: ignore[union-attr]
    mock_close.side_effect = lambda conn: None  # type: ignore[union-attr]

    result = list_rooms([])

    assert result["success"] is True
    room_names = [r["name"] for r in result["rooms"]]
    # init_db seeds these five rooms (hidden rooms excluded by query)
    for expected in ("general", "dev", "watercooler", "announcements", "ideas"):
        assert expected in room_names, f"Expected seeded room '{expected}' in listing"


def test_join_room_no_args() -> None:
    """Calling join_room with empty args should return an error dict."""
    result = join_room([])
    assert result["success"] is False
    assert "Room name required" in result["error"]


# =============================================================================
# ROOM STATE OPS — require initialized_db fixture
# =============================================================================


@patch("commons.apps.handlers.rooms.room_state_ops.json_handler")
def test_set_and_get_room_state(mock_json: object, initialized_db: object) -> None:
    """set_room_state should persist a key/value, and get_room_state should retrieve it."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    ok = set_room_state(conn, "general", "decor_lamp", "A glowing desk lamp")
    assert ok is True

    value = get_room_state(conn, "general", "decor_lamp")
    assert value == "A glowing desk lamp"


@patch("commons.apps.handlers.rooms.room_state_ops.json_handler")
def test_get_all_room_state_with_multiple_keys(mock_json: object, initialized_db: object) -> None:
    """get_all_room_state should return all key/value pairs for a room."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    set_room_state(conn, "general", "decor_plant", "A fern")
    set_room_state(conn, "general", "decor_poster", "AIPass launch poster")

    state = get_all_room_state(conn, "general")
    assert "decor_plant" in state
    assert "decor_poster" in state
    assert state["decor_plant"] == "A fern"


def test_get_room_state_missing_key(initialized_db: object) -> None:
    """get_room_state should return None for a key that does not exist."""
    import sqlite3
    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    value = get_room_state(conn, "general", "nonexistent_key")
    assert value is None
