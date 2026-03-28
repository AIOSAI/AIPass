# ===================AIPASS====================
# META DATA HEADER
# Name: test_welcome_engagement.py - Welcome & Engagement Tests
# Date: 2026-03-28
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — welcome handler + engagement ops tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger, json_handler, get_db, close_db as needed
# =============================================

"""
Unit tests for the welcome and engagement subsystems.

Covers:
- has_been_welcomed: new vs welcomed branch detection
- create_welcome_post: post creation and double-welcome prevention
- get_onboarding_nudge: nudge for inactive branches, None for active
- welcome_new_branches: bulk scan and welcome
- generate_prompt: daily prompt post creation
- create_event: event creation with and without args
- Module routing for welcome, prompt, event commands
"""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from commons.apps.handlers.welcome.welcome_handler import (
    has_been_welcomed,
    create_welcome_post,
    get_onboarding_nudge,
    welcome_new_branches,
)
from commons.apps.handlers.engagement.engagement_ops import (
    generate_prompt,
    create_event,
)


# =============================================================================
# HELPERS
# =============================================================================


def _seed_test_agents(conn: sqlite3.Connection) -> None:
    """Insert standard test agents into the database."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("TEST_BRANCH", "Test"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("THE_COMMONS", "The Commons"),
    )
    conn.commit()


# =============================================================================
# WELCOME HANDLER — has_been_welcomed
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_has_been_welcomed_new_branch_returns_false(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """A branch with no welcome post should return False."""
    _seed_test_agents(initialized_db)

    assert has_been_welcomed(initialized_db, "TEST_BRANCH") is False


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_has_been_welcomed_welcomed_branch_returns_true(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """A branch that has been welcomed should return True."""
    _seed_test_agents(initialized_db)

    create_welcome_post(initialized_db, "TEST_BRANCH")
    assert has_been_welcomed(initialized_db, "TEST_BRANCH") is True


# =============================================================================
# WELCOME HANDLER — create_welcome_post
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_create_welcome_post_creates_post_in_general(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """create_welcome_post should insert a post in the general room."""
    _seed_test_agents(initialized_db)

    post_id = create_welcome_post(initialized_db, "TEST_BRANCH")

    assert post_id is not None
    row = initialized_db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    assert row is not None
    assert row["room_name"] == "general"
    assert row["author"] == "SYSTEM"
    assert row["post_type"] == "announcement"
    assert "TEST_BRANCH" in row["title"]

    # Verify mention was created
    mention = initialized_db.execute(
        "SELECT * FROM mentions WHERE post_id = ? AND mentioned_agent = ?",
        (post_id, "TEST_BRANCH"),
    ).fetchone()
    assert mention is not None


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_create_welcome_post_double_welcome_prevented(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Calling create_welcome_post twice for the same branch returns None the second time."""
    _seed_test_agents(initialized_db)

    first = create_welcome_post(initialized_db, "TEST_BRANCH")
    assert first is not None

    second = create_welcome_post(initialized_db, "TEST_BRANCH")
    assert second is None


# =============================================================================
# WELCOME HANDLER — get_onboarding_nudge
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_get_onboarding_nudge_no_posts_gets_nudge(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """A branch with zero posts and zero comments should get a nudge."""
    _seed_test_agents(initialized_db)

    nudge = get_onboarding_nudge(initialized_db, "TEST_BRANCH")
    assert nudge is not None
    assert "commons post" in nudge


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_get_onboarding_nudge_active_branch_returns_none(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """A branch with posts should get no nudge (returns None)."""
    _seed_test_agents(initialized_db)

    initialized_db.execute(
        "UPDATE agents SET post_count = 3 WHERE branch_name = ?",
        ("TEST_BRANCH",),
    )
    initialized_db.commit()

    nudge = get_onboarding_nudge(initialized_db, "TEST_BRANCH")
    assert nudge is None


# =============================================================================
# WELCOME HANDLER — welcome_new_branches
# =============================================================================


@patch("commons.apps.handlers.welcome.welcome_handler.json_handler")
def test_welcome_new_branches_welcomes_unwelcomed(
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """welcome_new_branches should welcome all agents that haven't been welcomed yet."""
    _seed_test_agents(initialized_db)

    welcomed = welcome_new_branches(initialized_db)

    assert "TEST_BRANCH" in welcomed
    assert "THE_COMMONS" in welcomed
    assert has_been_welcomed(initialized_db, "TEST_BRANCH") is True
    assert has_been_welcomed(initialized_db, "THE_COMMONS") is True


# =============================================================================
# ENGAGEMENT OPS — generate_prompt
# =============================================================================


@patch("commons.apps.handlers.engagement.engagement_ops.json_handler")
@patch("commons.apps.handlers.engagement.engagement_ops.close_db")
@patch("commons.apps.handlers.engagement.engagement_ops.get_db")
def test_generate_prompt_creates_post(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """generate_prompt should create a discussion post in the watercooler."""
    _seed_test_agents(initialized_db)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = generate_prompt([])

    assert result["success"] is True
    assert result["post_id"] is not None
    assert result["room"] == "watercooler"
    assert result["author"] == "THE_COMMONS"
    assert "theme" in result

    # Verify post exists in DB
    row = initialized_db.execute(
        "SELECT * FROM posts WHERE id = ?", (result["post_id"],)
    ).fetchone()
    assert row is not None
    assert row["post_type"] == "discussion"


# =============================================================================
# ENGAGEMENT OPS — create_event
# =============================================================================


def test_create_event_no_args_returns_error() -> None:
    """create_event with no args should return an error dict."""
    result = create_event([])
    assert result["success"] is False
    assert "Usage" in result["error"]


@patch("commons.apps.handlers.engagement.engagement_ops.json_handler")
@patch("commons.apps.handlers.engagement.engagement_ops.close_db")
@patch("commons.apps.handlers.engagement.engagement_ops.get_db")
def test_create_event_with_args_creates_event_post(
    mock_get_db: MagicMock,
    mock_close: MagicMock,
    mock_json: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """create_event with title and description should create an announcement post."""
    _seed_test_agents(initialized_db)

    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda c: None

    result = create_event(["Code Jam", "Build something cool together"])

    assert result["success"] is True
    assert result["post_id"] is not None
    assert result["room"] == "watercooler"
    assert result["title"] == "Code Jam"
    assert result["author"] == "THE_COMMONS"

    # Verify post exists in DB
    row = initialized_db.execute(
        "SELECT * FROM posts WHERE id = ?", (result["post_id"],)
    ).fetchone()
    assert row is not None
    assert row["post_type"] == "announcement"
    assert "Code Jam" in row["title"]


# =============================================================================
# MODULE ROUTING — welcome.handle_command
# =============================================================================


@patch("commons.apps.modules.welcome.run_welcome")
@patch("commons.apps.modules.welcome.json_handler")
@patch("commons.apps.modules.welcome.console")
def test_welcome_module_routes_welcome_command(
    mock_console: MagicMock,
    mock_json: MagicMock,
    mock_run: MagicMock,
) -> None:
    """welcome.handle_command should route 'welcome' and return True."""
    from commons.apps.modules.welcome import handle_command

    mock_run.return_value = {"success": True, "action": "scan", "welcomed": []}

    result = handle_command("welcome", [])
    assert result is True
    mock_run.assert_called_once_with([])


@patch("commons.apps.modules.welcome.console")
def test_welcome_module_rejects_unknown_command(mock_console: MagicMock) -> None:
    """welcome.handle_command should return False for non-welcome commands."""
    from commons.apps.modules.welcome import handle_command

    result = handle_command("post", [])
    assert result is False


# =============================================================================
# MODULE ROUTING — engagement.handle_command
# =============================================================================


@patch("commons.apps.modules.engagement.generate_prompt")
@patch("commons.apps.modules.engagement.json_handler")
@patch("commons.apps.modules.engagement.console")
def test_engagement_module_routes_prompt_command(
    mock_console: MagicMock,
    mock_json: MagicMock,
    mock_prompt: MagicMock,
) -> None:
    """engagement.handle_command should route 'prompt' and return True."""
    from commons.apps.modules.engagement import handle_command

    mock_prompt.return_value = {
        "success": True,
        "post_id": 1,
        "room": "watercooler",
        "theme": "Test theme",
        "author": "THE_COMMONS",
    }

    result = handle_command("prompt", [])
    assert result is True
    mock_prompt.assert_called_once_with([])


@patch("commons.apps.modules.engagement.create_event")
@patch("commons.apps.modules.engagement.json_handler")
@patch("commons.apps.modules.engagement.console")
def test_engagement_module_routes_event_command(
    mock_console: MagicMock,
    mock_json: MagicMock,
    mock_event: MagicMock,
) -> None:
    """engagement.handle_command should route 'event' and return True."""
    from commons.apps.modules.engagement import handle_command

    mock_event.return_value = {
        "success": True,
        "post_id": 2,
        "room": "watercooler",
        "title": "Hackathon",
        "author": "THE_COMMONS",
    }

    result = handle_command("event", ["Hackathon", "Build stuff"])
    assert result is True
    mock_event.assert_called_once_with(["Hackathon", "Build stuff"])
