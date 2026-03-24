"""Tests for proof_query module."""

# =================== META ====================
# Name: test_proof_query.py
# Description: Unit tests for the proof_query module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for proof_query."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_warning = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    cli_mod.header = mock_header
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.proof_query", raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    result = handle_command("proof_query", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    result = handle_command("proof_query", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    result = handle_command("proof_query", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    result = handle_command("proof_query", ["help"])
    assert result is True


def test_handle_command_unknown_pack():
    """Unknown pack name returns True (error displayed to user)."""
    from aipass.seedgo.apps.modules.proof_query import handle_command
    result = handle_command("proof_query", ["nonexistent_pack_xyz"])
    assert result is True


def test_print_introspection_runs():
    """print_introspection executes without raising."""
    from aipass.seedgo.apps.modules.proof_query import print_introspection
    print_introspection()


def test_print_help_runs():
    """print_help executes without raising."""
    from aipass.seedgo.apps.modules.proof_query import print_help
    print_help()


def test_discover_proof_packs_returns_dict():
    """_discover_proof_packs returns a dict."""
    from aipass.seedgo.apps.modules.proof_query import _discover_proof_packs
    packs = _discover_proof_packs()
    assert isinstance(packs, dict)


def test_discover_proof_content_empty_dir(tmp_path):
    """_discover_proof_content returns empty dict for a directory with no content files."""
    from aipass.seedgo.apps.modules.proof_query import _discover_proof_content
    result = _discover_proof_content(tmp_path)
    assert result == {}


def test_discover_proof_content_finds_content_files(tmp_path):
    """_discover_proof_content discovers *_content.py files correctly."""
    from aipass.seedgo.apps.modules.proof_query import _discover_proof_content
    # Create a fake content file
    (tmp_path / "triplet_content.py").write_text("# fake", encoding="utf-8")
    (tmp_path / "not_a_content.py").write_text("# fake", encoding="utf-8")
    result = _discover_proof_content(tmp_path)
    assert "triplet" in result
    assert "not_a_content" not in result
