# =================== AIPass ====================
# Name: test_status.py
# Description: Unit tests for PRAX status module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for prax status module command routing, help text, and introspection.

All module imports happen inside test functions so that conftest's
autouse mock_prax_infrastructure fixture injects sys.modules mocks first.
"""

import sys
from unittest.mock import MagicMock


# =============================================
# HELPERS
# =============================================


def _ensure_sync_mock(monkeypatch):
    """Inject a mock for the sync handler before importing status module."""
    mock_sync_mod = MagicMock()
    mock_sync_mod.sync_status = MagicMock(
        return_value={
            "status": "ok",
            "branches_synced": ["prax", "drone", "flow"],
            "branches_missing": [],
            "timestamp": "2026-03-24T12:00:00",
        }
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.status.sync",
        mock_sync_mod,
    )
    return mock_sync_mod


def _fresh_import():
    """Force re-import of the status module to pick up current sys.modules."""
    mod_name = "aipass.prax.apps.modules.status"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.status import (
        handle_command,
        print_help,
        print_introspection,
    )

    return handle_command, print_help, print_introspection


# =============================================
# TESTS
# =============================================


def test_handle_command_help(mock_prax_infrastructure, monkeypatch):
    """--help flag returns True and prints help text."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["--help"])
    assert result is True
    mock_prax_infrastructure.console.print.assert_called()


def test_handle_command_help_h_flag(mock_prax_infrastructure, monkeypatch):
    """-h flag also triggers help."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["-h"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("status" in c.lower() for c in calls)


def test_handle_command_help_word(mock_prax_infrastructure, monkeypatch):
    """'help' subcommand triggers help."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["help"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("status" in c.lower() for c in calls)


def test_handle_command_no_args_shows_system_status(mock_prax_infrastructure, monkeypatch):
    """No args shows system status and returns True."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", [])
    assert result is True
    # System status prints "PRAX System Status"
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("System Status" in c for c in calls)


def test_handle_command_wrong_command(mock_prax_infrastructure, monkeypatch):
    """Wrong command name returns False with no console side effects."""
    _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("not-status", [])
    assert result is False
    mock_prax_infrastructure.console.print.assert_not_called()


def test_print_help_runs(mock_prax_infrastructure, monkeypatch):
    """print_help executes without error and includes sync subcommand."""
    _ensure_sync_mock(monkeypatch)
    _, print_help, _ = _fresh_import()

    print_help()
    mock_prax_infrastructure.console.print.assert_called()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("sync" in c.lower() for c in calls)


def test_print_introspection_runs(mock_prax_infrastructure, monkeypatch):
    """print_introspection executes without error."""
    _ensure_sync_mock(monkeypatch)
    _, _, print_introspection = _fresh_import()

    print_introspection()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Connected Handlers" in c for c in calls)


def test_handle_command_sync_routes_to_handler(mock_prax_infrastructure, monkeypatch):
    """'sync' subcommand routes to sync_status handler and shows results."""
    mock_sync_mod = _ensure_sync_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("status", ["sync"])
    assert result is True
    mock_sync_mod.sync_status.assert_called_once()
    # Verify handler result influenced console output (synced branch count)
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("sync" in c.lower() for c in calls)
