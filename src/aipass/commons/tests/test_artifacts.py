# =================== AIPass ====================
# META DATA HEADER
# Name: test_artifacts.py - Artifact, Trade, and Capsule Tests
# Description: Tests for apps/handlers/artifacts/artifact_ops.py, trade_ops.py and capsule_ops.py
# Date: 2026-03-28
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-09-28
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

"""Tests for apps/handlers/artifacts/artifact_ops.py, trade_ops.py and capsule_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/artifacts/ parses and imports
# seedgo: no-test-needed(constant) — the VALID_TYPES and VALID_RARITIES rosters; craft's success case names one of each

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from aipass.commons.apps.handlers.artifacts.artifact_ops import (
    craft_artifact,
    list_artifacts,
    inspect_artifact,
)
from aipass.commons.apps.handlers.artifacts.trade_ops import (
    sweep_expired,
    gift_artifact,
    drop_item,
)
from aipass.commons.apps.modules import artifact as artifact_module
from aipass.commons.apps.modules import capsule as capsule_module
from aipass.commons.apps.modules import trade as trade_module
from aipass.commons.apps.handlers.artifacts.capsule_ops import (
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
# craft --metadata — the metadata validation, reached through craft_artifact
# =============================================================================


@pytest.fixture
def craft_db(initialized_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """Point craft_artifact at the tmp database with TEST_BRANCH as the caller.

    Every metadata test takes this, the refusals too: a mutant that lets bad metadata
    through reaches the caller lookup and the INSERT, and both must land here.
    """
    monkeypatch.setattr("aipass.commons.apps.handlers.artifacts.artifact_ops.get_db", lambda: initialized_db)
    monkeypatch.setattr("aipass.commons.apps.handlers.artifacts.artifact_ops.close_db", lambda conn: None)
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.artifacts.artifact_ops.json_handler.log_operation", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "aipass.commons.apps.handlers.identity.identity_ops.get_caller_branch", lambda: {"name": "TEST_BRANCH"}
    )
    _insert_test_agent(initialized_db)
    return initialized_db


def _craft_with_metadata(metadata: str) -> Dict[str, Any]:
    """Craft an artifact the way 'commons craft "Gem" "desc" --metadata JSON' does."""
    return craft_artifact(["Gem", "desc", "--metadata", metadata])


def _assert_metadata_refused(conn: sqlite3.Connection, metadata: str) -> None:
    """The craft is refused with the metadata error and nothing is stored."""
    result = _craft_with_metadata(metadata)
    assert result["success"] is False, result
    assert "Invalid metadata" in result["error"]
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_validate_metadata_valid_json(craft_db: sqlite3.Connection) -> None:
    """Valid shallow JSON dict is accepted and stored as the parsed dict.

    Mutant: `for value in data.values():` -> `for value in [{}]:` (every dict refused) reddens this.
    """
    result = _craft_with_metadata('{"key": "value", "count": 42}')
    assert result["success"] is True, result
    row = craft_db.execute("SELECT metadata FROM artifacts WHERE id = ?", (result["artifact_id"],)).fetchone()
    stored = json.loads(row["metadata"])
    assert isinstance(stored, dict)
    assert stored["key"] == "value"
    assert stored["count"] == 42


def test_validate_metadata_malformed_json(craft_db: sqlite3.Connection) -> None:
    """Malformed JSON string is refused.

    Mutant: the decode-error branch's `return None` -> `return {}` reddens this.
    """
    _assert_metadata_refused(craft_db, "{not valid json")


def test_validate_metadata_nested_objects(craft_db: sqlite3.Connection) -> None:
    """JSON with nested objects or arrays is refused (shallow only).

    Mutant: `isinstance(value, (dict, list))` -> `isinstance(value, (list,))` reddens this (the dict case).
    """
    _assert_metadata_refused(craft_db, '{"nested": {"a": 1}}')
    _assert_metadata_refused(craft_db, '{"list": [1, 2, 3]}')


def test_validate_metadata_non_dict_json(craft_db: sqlite3.Connection) -> None:
    """JSON that parses to a non-dict (list, string, etc.) is refused.

    Mutant: the non-dict branch's `return None` -> `return {}` reddens this.
    """
    _assert_metadata_refused(craft_db, "[1, 2, 3]")
    _assert_metadata_refused(craft_db, '"just a string"')


# =============================================================================
# craft_artifact — requires DB
# =============================================================================


def test_craft_artifact_no_args() -> None:
    """Calling craft_artifact with empty args should return an error."""
    result = craft_artifact([])
    assert result["success"] is False
    assert "Usage" in result["error"]


@patch("aipass.commons.apps.handlers.identity.identity_ops.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("aipass.commons.apps.handlers.artifacts.artifact_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.artifact_ops.close_db")
@patch("aipass.commons.apps.handlers.artifacts.artifact_ops.json_handler", autospec=True)
def test_craft_artifact_success(
    mock_json: MagicMock,
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    mock_caller: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """Crafting an artifact with valid args should return success with artifact metadata."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db
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


@patch("aipass.commons.apps.handlers.artifacts.artifact_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.artifact_ops.close_db")
def test_list_artifacts_with_data(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_artifacts with --all should return inserted artifacts."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db
    _insert_test_agent(conn)

    conn.execute(
        "INSERT INTO artifacts (name, type, creator, owner, rarity, description) VALUES (?, ?, ?, ?, ?, ?)",
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
# sweep's clock — the ISO-Z "now" sweep_expired compares expires_at against
# =============================================================================


@patch("aipass.commons.apps.handlers.artifacts.trade_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.trade_ops.close_db")
def test_now_utc_returns_iso_format(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """sweep_expired's "now" is UTC in ISO format ending with Z, comparable to a stored expires_at.

    An item two minutes past its ISO-Z expiry is swept; one an hour short of it is kept.
    Mutant: _now_utc's `strftime("%Y-%m-%dT%H:%M:%SZ")` -> `strftime("%Y-%m-%d %H:%M:%S")` reddens this.
    """
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None
    _insert_test_agent(initialized_db)

    now = datetime.now(timezone.utc)
    for name, when in (("Just Expired", now - timedelta(minutes=2)), ("Still Fresh", now + timedelta(hours=1))):
        initialized_db.execute(
            "INSERT INTO artifacts (name, type, creator, owner, rarity, description, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, "found", "TEST_BRANCH", "TEST_BRANCH", "common", "d", when.strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
    initialized_db.commit()

    assert sweep_expired() == 1
    left = [r["name"] for r in initialized_db.execute("SELECT name FROM artifacts")]
    assert left == ["Still Fresh"]


# =============================================================================
# sweep_expired — requires DB
# =============================================================================


@patch("aipass.commons.apps.handlers.artifacts.trade_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.trade_ops.close_db")
def test_sweep_expired_removes_expired_items(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """sweep_expired should remove artifacts whose expires_at is in the past."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    conn: sqlite3.Connection = initialized_db
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


@patch("aipass.commons.apps.handlers.identity.identity_ops.get_caller_branch", return_value={"name": "TEST_BRANCH"})
@patch("aipass.commons.apps.handlers.artifacts.capsule_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.capsule_ops.close_db")
@patch("aipass.commons.apps.handlers.artifacts.capsule_ops.json_handler", autospec=True)
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

    conn: sqlite3.Connection = initialized_db
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


@patch("aipass.commons.apps.handlers.artifacts.capsule_ops.get_db")
@patch("aipass.commons.apps.handlers.artifacts.capsule_ops.close_db")
def test_list_capsules_empty_db(
    mock_close: MagicMock,
    mock_get_db: MagicMock,
    initialized_db: sqlite3.Connection,
) -> None:
    """list_capsules on an empty DB should return success with no capsules."""
    mock_get_db.return_value = initialized_db
    mock_close.side_effect = lambda conn: None

    result = list_capsules()

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


@patch("aipass.commons.apps.modules.artifact.craft_artifact")
@patch("aipass.commons.apps.modules.artifact.json_handler", autospec=True)
def test_artifact_handle_command_routes_craft(
    mock_json: MagicMock,
    mock_craft: MagicMock,
) -> None:
    """artifact.handle_command should route 'craft' to craft_artifact."""
    mock_craft.return_value = {
        "success": True,
        "artifact_id": 1,
        "name": "X",
        "type": "crafted",
        "rarity": "common",
        "creator": "T",
        "description": "d",
    }

    result = artifact_module.handle_command("craft", ["Test", "desc"])

    assert result is True
    mock_craft.assert_called_once_with(["Test", "desc"])


@patch("aipass.commons.apps.modules.trade.gift_artifact")
@patch("aipass.commons.apps.modules.trade.json_handler", autospec=True)
def test_trade_handle_command_routes_gift(
    mock_json: MagicMock,
    mock_gift: MagicMock,
) -> None:
    """trade.handle_command should route 'gift' to gift_artifact."""
    gift_mock: MagicMock = mock_gift
    gift_mock.return_value = {
        "success": True,
        "artifact_id": 1,
        "name": "X",
        "rarity": "common",
        "type": "crafted",
        "sender": "A",
        "recipient": "B",
    }

    result = trade_module.handle_command("gift", ["1", "@BRANCH"])

    assert result is True
    gift_mock.assert_called_once_with(["1", "@BRANCH"])


@patch("aipass.commons.apps.modules.capsule.seal_capsule")
@patch("aipass.commons.apps.modules.capsule.json_handler", autospec=True)
def test_capsule_handle_command_routes_capsule(
    mock_json: MagicMock,
    mock_seal: MagicMock,
) -> None:
    """capsule.handle_command should route 'capsule' to seal_capsule."""
    seal_mock: MagicMock = mock_seal
    seal_mock.return_value = {
        "success": True,
        "capsule_id": 1,
        "title": "T",
        "creator": "C",
        "days": 7,
        "opens_at": "2026-04-04T00:00:00Z",
    }

    result = capsule_module.handle_command("capsule", ["Title", "Content", "7"])

    assert result is True
    seal_mock.assert_called_once_with(["Title", "Content", "7"])


def test_sweep_expired_answers_minus_one_when_the_database_fails() -> None:
    """A failed sweep answers -1, never 0: 0 means "nothing expired", so the caller could not tell the two apart.

    get_db is stubbed to raise, so nothing reaches the live database.
    Mutant: the handler returns 0 again - the failure reads as "nothing expired".
    """
    with patch(
        "aipass.commons.apps.handlers.artifacts.trade_ops.get_db",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        assert sweep_expired() == -1


def test_gift_trade_mint_collab_name_an_unreadable_registry(tmp_path) -> None:
    """An unreadable registry is reported as such, never as "branch not found".

    The registry is a tmp_path file holding broken JSON; each command stops at the name lookup, before any
    caller detection or database write.
    Mutant: trade_ops/artifact_ops _resolve_branch_name returns None again - the error reads "not found".
    """
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{not json", encoding="utf-8")
    with (
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.BRANCH_REGISTRY_PATH", str(registry)),
        patch("aipass.commons.apps.handlers.artifacts.artifact_ops.BRANCH_REGISTRY_PATH", str(registry)),
    ):
        results = [
            gift_artifact(["1", "@ghost"]),
            trade_module.trade_artifact(["1", "2", "@ghost"]),
            trade_module.mint_event_artifact(["Event", "@ghost"]),
            artifact_module.collab_artifact(["Name", "Desc", "@ghost"]),
        ]
    assert [r["success"] for r in results] == [False] * 4
    assert [r["error"].startswith("Branch registry unreadable") for r in results] == [True] * 4


def test_find_command_says_the_expired_sweep_failed_and_still_finds(
    initialized_db: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'commons find' still picks the item up when the expired-item sweep fails, and says the sweep failed.

    Before the cure find_item dropped sweep_expired's -1 on the floor: the user was told nothing, and expired
    drops piled up unseen. The find itself stays safe, since it checks the item's own expires_at.
    sweep_expired is stubbed to answer -1; the find runs against the tmp database with a patched caller.
    Mutants (runner, killed): trade_ops `sweep_failed = sweep_expired() == -1` -> `sweep_failed = False`;
    trade `if result.get("sweep_failed"):` -> `if False:`.
    """
    _insert_test_agent(initialized_db)
    _insert_test_agent(initialized_db, "FINDER")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = initialized_db.execute(
        "INSERT INTO artifacts (name, type, creator, owner, rarity, description, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Lost Coin", "found", "TEST_BRANCH", "TEST_BRANCH", "common", "Shiny", future),
    )
    initialized_db.commit()
    artifact_id = str(cursor.lastrowid)

    with (
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.sweep_expired", return_value=-1) as sweep,
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.get_db", return_value=initialized_db),
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.close_db") as close,
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.get_caller_branch",
            return_value={"name": "FINDER"},
        ),
        patch("aipass.commons.apps.modules.trade.json_handler", autospec=True),
    ):
        handled = trade_module.handle_command("find", [artifact_id])

    sweep.assert_called_once_with()
    close.assert_called_once_with(initialized_db)
    assert handled is True
    captured = capsys.readouterr()
    assert "Item Found!" in captured.out
    assert "sweep of expired items failed" in " ".join(captured.err.split())
    row = initialized_db.execute("SELECT owner FROM artifacts WHERE id = ?", (int(artifact_id),)).fetchone()
    assert row["owner"] == "FINDER"


def test_craft_artifact_refuses_naming_a_failed_caller_lookup():
    """A broken caller lookup is refused by name, not as "run from a branch directory".

    Before (DPLAN-0354 leg 3): get_caller_branch logged the error and answered None.
    The lookup raises before any database is opened.
    """
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.artifacts.artifact_ops.get_db") as db,
    ):
        result = craft_artifact(["Pin Relic", "made by a pin"])

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


def test_seal_capsule_refuses_naming_a_failed_caller_lookup():
    """The capsule family names a broken caller lookup too (DPLAN-0354 leg 3)."""
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.artifacts.capsule_ops.get_db") as db,
    ):
        result = seal_capsule(["Pin", "sealed by a pin", "3"])

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


@pytest.mark.parametrize(
    ("command", "args"),
    [
        pytest.param(trade_module.gift_artifact, ["1", "@pal"], id="gift_artifact"),
        pytest.param(trade_module.trade_artifact, ["1", "2", "@pal"], id="trade_artifact"),
        pytest.param(trade_module.drop_item, ["Coin", "Shiny", "lobby"], id="drop_item"),
        pytest.param(trade_module.find_item, ["1"], id="find_item"),
    ],
)
def test_trade_commands_refuse_naming_a_failed_caller_lookup(tmp_path, command, args) -> None:
    """Each trade_ops command names a broken caller lookup and opens no database."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(json.dumps({"branches": [{"name": "PAL"}]}), encoding="utf-8")
    with (
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.BRANCH_REGISTRY_PATH", str(registry)),
        # find_item sweeps expired drops (its own get_db) before the lookup; stubbed so only the lookup is guarded.
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.sweep_expired", return_value=0),
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.artifacts.trade_ops.get_db") as db,
    ):
        result = command(args)

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


@pytest.mark.parametrize(
    ("command", "args"),
    [
        pytest.param(artifact_module.list_artifacts, [], id="list_artifacts"),
        pytest.param(artifact_module.collab_artifact, ["Pact", "made by a pin", "@pal"], id="collab_artifact"),
        pytest.param(artifact_module.sign_artifact, ["1"], id="sign_artifact"),
    ],
)
def test_artifact_commands_refuse_naming_a_failed_caller_lookup(tmp_path, command, args) -> None:
    """Each artifact_ops command names a broken caller lookup and opens no database."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(json.dumps({"branches": [{"name": "PAL"}]}), encoding="utf-8")
    with (
        patch("aipass.commons.apps.handlers.artifacts.artifact_ops.BRANCH_REGISTRY_PATH", str(registry)),
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.artifacts.artifact_ops.get_db") as db,
    ):
        result = command(args)

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]


def test_open_capsule_refuses_naming_a_failed_caller_lookup() -> None:
    with (
        patch(
            "aipass.commons.apps.handlers.identity.identity_ops.find_branch_root",
            side_effect=OSError("registry unreadable"),
        ) as lookup,
        patch("aipass.commons.apps.handlers.artifacts.capsule_ops.get_db") as db,
    ):
        result = open_capsule(["1"])

    lookup.assert_called_once()
    db.assert_not_called()
    assert result["success"] is False
    assert "Caller lookup failed: registry unreadable" in result["error"]
