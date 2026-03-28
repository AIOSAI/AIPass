# ===================AIPASS====================
# META DATA HEADER
# Name: test_artifacts.py - Artifact, Trade, and Capsule Tests
# Date: 2026-03-28
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-28): Initial creation — artifact, trade, capsule subsystem tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Uses initialized_db fixture from conftest.py for DB isolation
#   - Mocks prax logger, json_handler, get_db, close_db, get_caller_branch
# =============================================

"""
Unit tests for artifact, trade, and capsule subsystems.

Covers:
- _validate_metadata: valid/invalid JSON handling
- craft_artifact / list_artifacts / inspect_artifact operations
- _now_utc helper
- sweep_expired / gift_artifact / drop_item operations
- seal_capsule / list_capsules / open_capsule operations
- Module routing for artifact, trade, capsule handle_command
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from commons.apps.handlers.artifacts.artifact_ops import (
    _validate_metadata,
    craft_artifact,
    list_artifacts,
    inspect_artifact,
)
from commons.apps.handlers.artifacts.trade_ops import (
    _now_utc,
    sweep_expired,
    gift_artifact,
    drop_item,
)
from commons.apps.handlers.artifacts.capsule_ops import (
    seal_capsule,
    list_capsules,
    open_capsule,
)


# =============================================================================
# HELPER: insert test agent into DB
# =============================================================================


def _insert_test_agent(conn: sqlite3.Connection, name: str = "TEST_BRANCH") -> None:
    """Insert a test agent so foreign key constraints are satisfied."""
    conn.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        (name, "Test"),
    )
    conn.commit()


# =============================================================================
# _validate_metadata — pure function, no DB needed
# =============================================================================


def test_validate_metadata_valid_json() -> None:
    """Valid shallow JSON dict should return the parsed dict."""
    result = _validate_metadata('{"key": "value", "count": 42}')
    assert result is not None
    assert isinstance(result, dict)
    assert result["key"] == "value"
    assert result["count"] == 42


def test_validate_metadata_malformed_json() -> None:
    """Malformed JSON string should return None."""
    result = _validate_metadata("{not valid json")
    assert result is None


def test_validate_metadata_nested_objects() -> None:
    """JSON with nested objects or arrays should return None (shallow only)."""
    result = _validate_metadata('{"nested": {"a": 1}}')
    assert result is None

    result = _validate_metadata('{"list": [1, 2, 3]}')
    assert result is None


def test_validate_metadata_non_dict_json() -> None:
    """JSON that parses to a non-dict (list, string, etc.) should return None."""
    result = _validate_metadata('[1, 2, 3]')
    assert result is None

    result = _validate_metadata('"just a string"')
    assert result is None


# =============================================================================
# craft_artifact — requires DB
# =============================================================================


def test_craft_artifact_no_args() -> None:
    """Calling craft_artifact with empty args should return an error."""
    result = craft_artifact([])
    assert result["success"] is False
    assert "Usage" in result["error"]


@patch("commons.apps.modules.commons_identity.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("commons.apps.handlers.artifacts.artifact_ops.get_db")
@patch("commons.apps.handlers.artifacts.artifact_ops.close_db")
@patch("commons.apps.handlers.artifacts.artifact_ops.json_handler")
def test_craft_artifact_success(
    mock_json: MagicMock,
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    mock_caller: MagicMock,
    initialized_db: object,
) -> None:
    """Crafting an artifact with valid args should return success with artifact metadata."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = craft_artifact(["Starforge Hammer", "A legendary smithing tool", "--rarity", "rare"])

    assert result["success"] is True
    assert result["name"] == "Starforge Hammer"
    assert result["rarity"] == "rare"
    assert result["type"] == "crafted"
    assert result["creator"] == "TEST_BRANCH"
    assert isinstance(result["artifact_id"], int)

    # Verify persistence
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (result["artifact_id"],)).fetchone()
    assert row is not None
    assert row["name"] == "Starforge Hammer"


# =============================================================================
# list_artifacts — requires DB
# =============================================================================


@patch("commons.apps.handlers.artifacts.artifact_ops.get_db")
@patch("commons.apps.handlers.artifacts.artifact_ops.close_db")
def test_list_artifacts_with_data(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: object,
) -> None:
    """list_artifacts with --all should return inserted artifacts."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    conn.execute(
        "INSERT INTO artifacts (name, type, creator, owner, rarity, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Test Gem", "crafted", "TEST_BRANCH", "TEST_BRANCH", "uncommon", "A shiny gem"),
    )
    conn.commit()

    result = list_artifacts(["--all"])

    assert result["success"] is True
    assert len(result["artifacts"]) >= 1
    names = [a["name"] for a in result["artifacts"]]
    assert "Test Gem" in names


# =============================================================================
# inspect_artifact — requires DB
# =============================================================================


def test_inspect_artifact_no_args() -> None:
    """Calling inspect_artifact with empty args should return an error."""
    result = inspect_artifact([])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# _now_utc — pure function
# =============================================================================


def test_now_utc_returns_iso_format() -> None:
    """_now_utc should return a string in ISO format ending with Z."""
    result = _now_utc()
    assert isinstance(result, str)
    assert result.endswith("Z")
    # Should parse without error
    parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    assert parsed is not None


# =============================================================================
# sweep_expired — requires DB
# =============================================================================


@patch("commons.apps.handlers.artifacts.trade_ops.get_db")
@patch("commons.apps.handlers.artifacts.trade_ops.close_db")
def test_sweep_expired_removes_expired_items(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: object,
) -> None:
    """sweep_expired should remove artifacts whose expires_at is in the past."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO artifacts (name, type, creator, owner, rarity, description, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Expired Scroll", "found", "TEST_BRANCH", "TEST_BRANCH", "common", "Gone", past),
    )
    conn.commit()

    count = sweep_expired()
    assert count >= 1

    # Verify the artifact was deleted
    row = conn.execute("SELECT * FROM artifacts WHERE name = ?", ("Expired Scroll",)).fetchone()
    assert row is None


# =============================================================================
# gift_artifact — no args
# =============================================================================


def test_gift_artifact_no_args() -> None:
    """Calling gift_artifact with insufficient args should return an error."""
    result = gift_artifact([])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# drop_item — no args
# =============================================================================


def test_drop_item_no_args() -> None:
    """Calling drop_item with insufficient args should return an error."""
    result = drop_item([])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# seal_capsule — requires DB
# =============================================================================


def test_seal_capsule_no_args() -> None:
    """Calling seal_capsule with insufficient args should return an error."""
    result = seal_capsule([])
    assert result["success"] is False
    assert "Usage" in result["error"]


@patch("commons.apps.modules.commons_identity.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("commons.apps.handlers.artifacts.capsule_ops.get_db")
@patch("commons.apps.handlers.artifacts.capsule_ops.close_db")
@patch("commons.apps.handlers.artifacts.capsule_ops.json_handler")
def test_seal_capsule_success(
    mock_json: MagicMock,
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    mock_caller: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Sealing a capsule with valid args should return success with capsule metadata."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db  # type: ignore[assignment]
    _insert_test_agent(conn)

    result = seal_capsule(["Launch Day Note", "We did it!", "30"])

    assert result["success"] is True
    assert result["title"] == "Launch Day Note"
    assert result["creator"] == "TEST_BRANCH"
    assert result["days"] == 30
    assert isinstance(result["capsule_id"], int)

    # Verify persistence
    row = conn.execute("SELECT * FROM time_capsules WHERE id = ?", (result["capsule_id"],)).fetchone()
    assert row is not None
    assert row["title"] == "Launch Day Note"
    assert row["opened"] == 0


# =============================================================================
# list_capsules — requires DB
# =============================================================================


@patch("commons.apps.handlers.artifacts.capsule_ops.get_db")
@patch("commons.apps.handlers.artifacts.capsule_ops.close_db")
def test_list_capsules_empty_db(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_capsules on an empty DB should return success with no capsules."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    result = list_capsules([])

    assert result["success"] is True
    assert result["capsules"] == []


# =============================================================================
# open_capsule — no args
# =============================================================================


def test_open_capsule_no_args() -> None:
    """Calling open_capsule with empty args should return an error."""
    result = open_capsule([])
    assert result["success"] is False
    assert "Usage" in result["error"]


# =============================================================================
# MODULE ROUTING — artifact, trade, capsule handle_command
# =============================================================================


@patch("commons.apps.modules.artifact.craft_artifact")
@patch("commons.apps.modules.artifact.json_handler")
def test_artifact_handle_command_routes_craft(
    mock_json: MagicMock,
    mock_craft: MagicMock,
) -> None:
    """artifact.handle_command should route 'craft' to craft_artifact."""
    mock_craft.return_value = {"success": True, "artifact_id": 1, "name": "X", "type": "crafted", "rarity": "common", "creator": "T", "description": "d"}

    from commons.apps.modules.artifact import handle_command
    result = handle_command("craft", ["Test", "desc"])

    assert result is True
    mock_craft.assert_called_once_with(["Test", "desc"])


@patch("commons.apps.modules.trade.gift_artifact")
@patch("commons.apps.modules.trade.json_handler")
def test_trade_handle_command_routes_gift(
    mock_json: MagicMock,
    mock_gift: MagicMock,
) -> None:
    """trade.handle_command should route 'gift' to gift_artifact."""
    gift_mock: MagicMock = mock_gift
    gift_mock.return_value = {"success": True, "artifact_id": 1, "name": "X", "rarity": "common", "type": "crafted", "sender": "A", "recipient": "B"}

    from commons.apps.modules.trade import handle_command
    result = handle_command("gift", ["1", "@BRANCH"])

    assert result is True
    gift_mock.assert_called_once_with(["1", "@BRANCH"])


@patch("commons.apps.modules.capsule.seal_capsule")
@patch("commons.apps.modules.capsule.json_handler")
def test_capsule_handle_command_routes_capsule(
    mock_json: MagicMock,
    mock_seal: MagicMock,
) -> None:
    """capsule.handle_command should route 'capsule' to seal_capsule."""
    seal_mock: MagicMock = mock_seal
    seal_mock.return_value = {"success": True, "capsule_id": 1, "title": "T", "creator": "C", "days": 7, "opens_at": "2026-04-04T00:00:00Z"}

    from commons.apps.modules.capsule import handle_command
    result = handle_command("capsule", ["Title", "Content", "7"])

    assert result is True
    seal_mock.assert_called_once_with(["Title", "Content", "7"])
