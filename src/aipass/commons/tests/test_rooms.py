# =================== AIPass ====================
# META DATA HEADER
# Name: test_rooms.py - Room and Space Module Tests
# Description: Tests for apps/handlers/rooms/room_ops.py and apps/modules/space.py
# Date: 2026-03-24
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-09-28
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

"""Tests for apps/handlers/rooms/room_ops.py and apps/modules/space.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/rooms/ parses and imports
# seedgo: no-test-needed(library) — the colour rich.panel.Panel paints for a style name; a spy pins the name handed over

import sqlite3
from typing import Any

import pytest
from unittest.mock import patch, MagicMock

from rich.panel import Panel

from aipass.commons.apps.modules import space
from aipass.commons.apps.modules.space import MOOD_STYLES
from aipass.commons.apps.handlers.rooms.room_ops import create_room, list_rooms, join_room
from aipass.commons.apps.modules import room as room_module
from aipass.commons.apps.handlers.rooms.room_state_ops import (
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
    """Each MOOD_STYLES entry should be a (color_str, icon_str) tuple.

    The count assert is the loop's floor: an empty MOOD_STYLES would enter no
    iteration and pass this test with nothing checked.
    """
    assert len(MOOD_STYLES) == 6, f"Expected 6 moods, found {sorted(MOOD_STYLES)}"

    for mood, value in MOOD_STYLES.items():
        assert isinstance(value, tuple), f"Expected tuple for mood '{mood}'"
        assert len(value) == 2, f"Expected 2-element tuple for mood '{mood}'"
        color, icon = value
        assert isinstance(color, str) and color, f"Color must be a non-empty string for '{mood}'"
        assert isinstance(icon, str) and icon, f"Icon must be a non-empty string for '{mood}'"


@pytest.fixture
def space_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point the space handlers at the tmp database and keep the caller lookup off live state."""
    monkeypatch.setattr("aipass.commons.apps.handlers.rooms.space_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.rooms.space_ops.close_db", lambda conn: None)
    monkeypatch.setattr(space, "get_caller_branch", lambda: {"name": "TEST_BRANCH"})
    return initialized_db


def _set_mood(conn: sqlite3.Connection, mood: str) -> None:
    """Give the seeded 'general' room a mood."""
    conn.execute("UPDATE rooms SET mood = ? WHERE name = 'general'", (mood,))
    conn.commit()


def _entrance_border(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, mood: str) -> Any:
    """Run 'enter general' with the given mood; return the border_style the entrance panel was drawn with."""
    _set_mood(conn, mood)
    seen: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> Panel:
        seen.append(kwargs.get("border_style"))
        return Panel(*args, **kwargs)

    monkeypatch.setattr(space, "Panel", spy)
    assert space.handle_command("enter", ["general"]) is True
    assert len(seen) == 1, f"enter drew {len(seen)} panels, want 1"
    return seen[0]


def _look_mood_line(conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str], mood: str) -> str:
    """Run 'look general' with the given mood; return the printed Mood line."""
    _set_mood(conn, mood)
    capsys.readouterr()
    assert space.handle_command("look", ["general"]) is True
    lines = [line.strip() for line in capsys.readouterr().out.splitlines() if "Mood:" in line]
    assert len(lines) == 1, f"look printed {lines!r}"
    return lines[0]


def test_mood_style_returns_correct_color(space_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """'enter' draws the room panel in its mood's Rich color for known moods.

    Mutant: _mood_style's `("dim", "-"))[0]` -> `("dim", "-"))[1]` (icon for colour) reddens this.
    """
    assert _entrance_border(space_db, monkeypatch, "welcoming") == "green"
    assert _entrance_border(space_db, monkeypatch, "tense") == "red"
    assert _entrance_border(space_db, monkeypatch, "celebratory") == "magenta"


def test_mood_style_unknown_mood_returns_dim(space_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """'enter' falls back to a 'dim' border for unrecognized moods.

    An empty mood never reaches the style lookup: the command reads it as 'neutral', also 'dim'.
    Mutant: _mood_style's fallback `("dim", "-"))[0]` -> `("red", "-"))[0]` reddens this.
    """
    assert _entrance_border(space_db, monkeypatch, "chaotic") == "dim"
    assert _entrance_border(space_db, monkeypatch, "") == "dim"


def test_mood_icon_returns_correct_icon(space_db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]) -> None:
    """'look' prints the text icon for known moods.

    Mutant: _mood_icon's `("dim", "-"))[1]` -> `("dim", "-"))[0]` (colour for icon) reddens this.
    """
    assert _look_mood_line(space_db, capsys, "welcoming") == "Mood: welcoming ~"
    assert _look_mood_line(space_db, capsys, "tense") == "Mood: tense !"
    assert _look_mood_line(space_db, capsys, "focused") == "Mood: focused |"


def test_mood_icon_unknown_mood_returns_dash(space_db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]) -> None:
    """'look' falls back to '-' for unrecognized moods.

    An empty mood never reaches the icon lookup: the command reads it as 'neutral', also '-'.
    Mutant: _mood_icon's fallback `("dim", "-"))[1]` -> `("dim", "?"))[1]` reddens this.
    """
    assert _look_mood_line(space_db, capsys, "mysterious") == "Mood: mysterious -"
    assert _look_mood_line(space_db, capsys, "") == "Mood: neutral -"


# =============================================================================
# ROOM OPS — require initialized_db fixture
# =============================================================================


@patch("aipass.commons.apps.handlers.rooms.room_ops.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("aipass.commons.apps.handlers.rooms.room_ops.get_db")
@patch("aipass.commons.apps.handlers.rooms.room_ops.close_db")
@patch("aipass.commons.apps.handlers.rooms.room_ops.json_handler", autospec=True)
def test_create_room_success(
    mock_json: object,
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    mock_caller: object,
    initialized_db: sqlite3.Connection,
) -> None:
    """Creating a room with valid args should return success with room metadata."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    # Insert the agent so the foreign key constraint is satisfied
    conn: sqlite3.Connection = initialized_db
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


@patch("aipass.commons.apps.handlers.rooms.room_ops.get_caller_branch", return_value=None)
def test_create_room_no_caller(mock_caller: object) -> None:
    """Creating a room when caller branch is undetectable should fail gracefully."""
    result = create_room(["orphan-room"])
    assert result["success"] is False
    assert "Could not detect calling branch" in result["error"]
    assert "drone routing" in result["error"]


@patch("aipass.commons.apps.handlers.rooms.room_ops.get_db")
@patch("aipass.commons.apps.handlers.rooms.room_ops.close_db")
def test_list_rooms_returns_seeded_rooms(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_rooms should return the default seeded rooms from init_db."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    result = list_rooms()

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


@patch("aipass.commons.apps.modules.room.create_room")
def test_room_create_help_prints_usage_without_creating(mock_create_room: MagicMock) -> None:
    """'room create --help' should print usage and never reach create_room."""
    handled = room_module.handle_command("room", ["create", "--help"])

    assert handled is True
    mock_create_room.assert_not_called()


# =============================================================================
# ROOM STATE OPS — require initialized_db fixture
# =============================================================================


@patch("aipass.commons.apps.handlers.rooms.room_state_ops.json_handler", autospec=True)
def test_set_and_get_room_state(mock_json: object, initialized_db: sqlite3.Connection) -> None:
    """set_room_state should persist a key/value, and get_room_state should retrieve it."""
    conn: sqlite3.Connection = initialized_db
    ok = set_room_state(conn, "general", "decor_lamp", "A glowing desk lamp")
    assert ok is True

    value = get_room_state(conn, "general", "decor_lamp")
    assert value == "A glowing desk lamp"


@patch("aipass.commons.apps.handlers.rooms.room_state_ops.json_handler", autospec=True)
def test_get_all_room_state_with_multiple_keys(mock_json: object, initialized_db: sqlite3.Connection) -> None:
    """get_all_room_state should return all key/value pairs for a room."""
    conn: sqlite3.Connection = initialized_db
    set_room_state(conn, "general", "decor_plant", "A fern")
    set_room_state(conn, "general", "decor_poster", "AIPass launch poster")

    state = get_all_room_state(conn, "general")
    assert "decor_plant" in state
    assert "decor_poster" in state
    assert state["decor_plant"] == "A fern"


def test_get_room_state_missing_key(initialized_db: sqlite3.Connection) -> None:
    """get_room_state should return None for a key that does not exist."""
    conn: sqlite3.Connection = initialized_db
    value = get_room_state(conn, "general", "nonexistent_key")
    assert value is None


def test_create_room_refuses_naming_a_failed_caller_lookup():
    """A broken caller lookup is refused by name, not as "run from a branch directory".

    Before (DPLAN-0354 leg 3): get_caller_branch logged the error and answered None,
    so the user was told to run from a branch directory. The lookup raises before
    any database is opened.
    """
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.rooms.room_ops.get_db") as db,
    ):
        result = create_room(["pin-room", "a room"])

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


# room_module binds the same join_room / leave_room the 'room join' / 'room leave' commands call.
@pytest.mark.parametrize(
    "command_fn",
    [
        pytest.param(room_module.join_room, id="join_room"),
        pytest.param(room_module.leave_room, id="leave_room"),
    ],
)
def test_room_membership_commands_refuse_naming_a_failed_caller_lookup(command_fn: Any) -> None:
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.rooms.room_ops.get_db") as db,
    ):
        result = command_fn(["general"])

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


def test_enter_shows_the_room_and_logs_the_visit_unrecorded_naming_a_failed_caller_lookup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The room data is handed in so no database opens; record_visit would reach space_ops.get_db.
    room_data = {
        "found": True,
        "room": {"name": "general", "mood": "neutral", "entrance_message": "You step into the pin room."},
        "post_count": 0,
        "recent_count": 0,
        "decorations": {},
    }
    monkeypatch.setattr(space, "get_room_enter_data", lambda room_name: room_data)
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.rooms.space_ops.get_db") as db,
        patch("aipass.commons.apps.modules.space.logger") as log,
    ):
        handled = space.handle_command("enter", ["general"])

    out, _err = capsys.readouterr()
    lookup.assert_called_once()
    db.assert_not_called()
    assert handled is True
    assert "You step into the pin room." in out
    log.warning.assert_called_once_with("[space] Visit not recorded: Caller lookup failed: registry unreadable")


def test_decorate_refuses_naming_a_failed_caller_lookup(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.rooms.space_ops.get_db") as db,
    ):
        handled = space.handle_command("decorate", ["general", "lamp", "A glowing lamp"])

    out, err = capsys.readouterr()
    lookup.assert_called_once()
    db.assert_not_called()
    assert handled is True
    assert "Caller lookup failed: registry unreadable" in err
    assert "Could not detect calling branch" not in err
    assert "Placed" not in out
