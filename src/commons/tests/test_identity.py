# ===================AIPASS====================
# META DATA HEADER
# Name: test_identity.py - Identity Module Unit Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation — 14 unit tests
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Mock heavy deps (prax logger, database)
#   - Tests extract_mentions, find_branch_root, resolve_display_name
# =============================================

"""
Unit tests for the commons identity module and identity_ops handler.

Tests extract_mentions (pure regex), find_branch_root (filesystem walk),
resolve_display_name, and DB-backed mention validation.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock the prax logger before importing the modules under test
import sys

_mock_logger = MagicMock()
_mock_logger_module = MagicMock()
_mock_logger_module.system_logger = _mock_logger

try:
    from aipass.prax.apps.modules.logger import system_logger  # noqa: F401
except ImportError:
    sys.modules.setdefault("aipass.prax", MagicMock())
    sys.modules.setdefault("aipass.prax.apps", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules", MagicMock())
    sys.modules.setdefault("aipass.prax.apps.modules.logger", _mock_logger_module)

# Mock CLI console too — commons_identity imports it
try:
    from aipass.cli.apps.modules import console  # noqa: F401
except ImportError:
    _mock_cli = MagicMock()
    sys.modules.setdefault("aipass.cli", _mock_cli)
    sys.modules.setdefault("aipass.cli.apps", MagicMock())
    sys.modules.setdefault("aipass.cli.apps.modules", MagicMock())

from commons.apps.modules.commons_identity import extract_mentions
from commons.apps.handlers.identity.identity_ops import (
    find_branch_root,
    resolve_display_name,
)
import commons.apps.handlers.identity.identity_ops as identity_ops_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_db_for_mentions(initialized_db: sqlite3.Connection):
    """
    Patch get_db/close_db in the database module so that
    extract_mentions (which does a lazy import) uses the test database.
    """
    with patch(
        "commons.apps.handlers.database.db.get_db",
        return_value=initialized_db,
    ), patch(
        "commons.apps.handlers.database.db.close_db",
    ):
        yield


# ===========================================================================
# extract_mentions — regex extraction + DB validation
# ===========================================================================

def test_extract_mentions_empty_string(initialized_db: sqlite3.Connection):
    """Empty string returns empty list."""
    result = extract_mentions("")
    assert result == []


def test_extract_mentions_no_mentions(initialized_db: sqlite3.Connection):
    """Text without @mentions returns empty list."""
    result = extract_mentions("Hello world, no mentions here")
    assert result == []


def test_extract_mentions_single(initialized_db: sqlite3.Connection):
    """Single @mention of a registered agent is returned."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("drone", "Drone"),
    )
    initialized_db.commit()

    result = extract_mentions("Hey @drone check this out")
    assert result == ["drone"]


def test_extract_mentions_multiple(initialized_db: sqlite3.Connection):
    """Multiple @mentions of registered agents are all returned."""
    for name, display in [("flow", "Flow"), ("seed", "Seed")]:
        initialized_db.execute(
            "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
            (name, display),
        )
    initialized_db.commit()

    result = extract_mentions("@flow and @seed please review")
    assert result == ["flow", "seed"]


def test_extract_mentions_unregistered_filtered(initialized_db: sqlite3.Connection):
    """Mentions of agents not in the DB are filtered out."""
    result = extract_mentions("@nonexistent_branch please help")
    assert result == []


def test_extract_mentions_case_insensitive(initialized_db: sqlite3.Connection):
    """Mentions are lowercased for DB lookup."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("prax", "Prax"),
    )
    initialized_db.commit()

    result = extract_mentions("Hey @PRAX look at this")
    assert result == ["prax"]


def test_extract_mentions_with_underscores(initialized_db: sqlite3.Connection):
    """Mentions with underscores (e.g., @seed_cortex) are matched."""
    initialized_db.execute(
        "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
        ("seed_cortex", "Seed Cortex"),
    )
    initialized_db.commit()

    result = extract_mentions("Asking @seed_cortex for analysis")
    assert result == ["seed_cortex"]


# ===========================================================================
# find_branch_root — filesystem walk
# ===========================================================================

def test_find_branch_root_with_trinity(tmp_path: Path):
    """Finds root when .trinity/passport.json exists."""
    trinity_dir = tmp_path / ".trinity"
    trinity_dir.mkdir()
    (trinity_dir / "passport.json").write_text("{}", encoding="utf-8")

    sub = tmp_path / "apps" / "handlers"
    sub.mkdir(parents=True)

    result = find_branch_root(sub)
    assert result is not None
    assert result == tmp_path.resolve()


def test_find_branch_root_no_trinity(tmp_path: Path):
    """Returns None when no .trinity directory exists in ancestry."""
    sub = tmp_path / "deep" / "nested" / "dir"
    sub.mkdir(parents=True)

    result = find_branch_root(sub)
    assert result is None


def test_find_branch_root_at_start(tmp_path: Path):
    """Finds root when start_path IS the branch root."""
    trinity_dir = tmp_path / ".trinity"
    trinity_dir.mkdir()
    (trinity_dir / "passport.json").write_text("{}", encoding="utf-8")

    result = find_branch_root(tmp_path)
    assert result is not None
    assert result == tmp_path.resolve()


# ===========================================================================
# resolve_display_name
# ===========================================================================

def test_resolve_display_name_no_alias(monkeypatch: pytest.MonkeyPatch):
    """Falls back to branch_name when no alias is cached."""
    # Reset the alias cache to a known state
    monkeypatch.setattr(identity_ops_mod, "_alias_cache", {})
    result = resolve_display_name("UNKNOWN_BRANCH")
    assert result == "UNKNOWN_BRANCH"


def test_resolve_display_name_with_alias(monkeypatch: pytest.MonkeyPatch):
    """Returns 'Alias (SYSTEM_NAME)' format when alias exists."""
    monkeypatch.setattr(identity_ops_mod, "_alias_cache", {"TEAM_1": "Alpha Team"})
    result = resolve_display_name("TEAM_1")
    assert result == "Alpha Team (TEAM_1)"


def test_resolve_display_name_compact(monkeypatch: pytest.MonkeyPatch):
    """Compact mode returns alias only, no parenthesized system name."""
    monkeypatch.setattr(identity_ops_mod, "_alias_cache", {"TEAM_1": "Alpha Team"})
    result = resolve_display_name("TEAM_1", compact=True)
    assert result == "Alpha Team"


def test_resolve_display_name_compact_no_alias(monkeypatch: pytest.MonkeyPatch):
    """Compact mode without alias still falls back to branch_name."""
    monkeypatch.setattr(identity_ops_mod, "_alias_cache", {})
    result = resolve_display_name("RAW_NAME", compact=True)
    assert result == "RAW_NAME"
