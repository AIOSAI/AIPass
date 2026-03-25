# =================== AIPass ====================
# Name: test_agent_status.py
# Description: Unit tests for PRAX agent_status module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for prax agent_status module command routing, help text, and introspection.

All module imports happen inside test functions so that conftest's
autouse mock_prax_infrastructure fixture injects sys.modules mocks first.
"""

import sys
from unittest.mock import MagicMock


# =============================================
# HELPERS
# =============================================

def _ensure_dashboard_mock(monkeypatch):
    """Inject a mock for the agent_status_writer handler."""
    mock_writer = MagicMock()
    mock_writer.build_agent_status_section = MagicMock(return_value={
        "agent_count": 3,
        "stale_agents": ["backup"],
        "active_agents": ["prax", "drone", "flow"],
        "last_updated": "2026-03-24T12:00:00",
    })
    mock_writer.push_agent_status_dashboard = MagicMock(return_value=True)
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.dashboard.agent_status_writer",
        mock_writer,
    )
    return mock_writer


def _fresh_import():
    """Force re-import of the agent_status module."""
    mod_name = "aipass.prax.apps.modules.agent_status"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.agent_status import (
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
    _ensure_dashboard_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("agent-status-push", ["--help"])
    assert result is True
    mock_prax_infrastructure.console.print.assert_called()


def test_handle_command_help_h_flag(mock_prax_infrastructure, monkeypatch):
    """-h flag also triggers help with agent/push keywords."""
    _ensure_dashboard_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("agent-status-push", ["-h"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("agent" in c.lower() for c in calls)


def test_handle_command_no_args_calls_introspection(mock_prax_infrastructure, monkeypatch):
    """No args prints introspection and returns True."""
    handle_command, _, _ = _fresh_import()

    result = handle_command("agent-status-push", [])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Agent Status Module" in c for c in calls)


def test_handle_command_wrong_command(mock_prax_infrastructure, monkeypatch):
    """Wrong command name returns False."""
    handle_command, _, _ = _fresh_import()

    result = handle_command("not-agent-status", [])
    assert result is False


def test_print_help_runs(mock_prax_infrastructure, monkeypatch):
    """print_help runs without error and prints usage content."""
    _, print_help, _ = _fresh_import()

    print_help()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("dry-run" in c for c in calls)


def test_print_introspection_runs(mock_prax_infrastructure, monkeypatch):
    """print_introspection runs without error."""
    _, _, print_introspection = _fresh_import()

    print_introspection()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Connected Handlers" in c for c in calls)


def test_handle_command_push_routes_to_handler(mock_prax_infrastructure, monkeypatch):
    """'push' arg triggers build + push via handler and shows result data."""
    mock_writer = _ensure_dashboard_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("agent-status-push", ["push"])
    assert result is True
    mock_writer.build_agent_status_section.assert_called_once()
    mock_writer.push_agent_status_dashboard.assert_called_once()
    # Verify console output includes result data from handler
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Active agents" in c for c in calls)
    assert any("Pushed" in c for c in calls)


def test_handle_command_dry_run(mock_prax_infrastructure, monkeypatch):
    """--dry-run flag builds section data, prints it, but does not push."""
    mock_writer = _ensure_dashboard_mock(monkeypatch)
    handle_command, _, _ = _fresh_import()

    result = handle_command("agent-status-push", ["--dry-run"])
    assert result is True
    mock_writer.build_agent_status_section.assert_called_once()
    mock_writer.push_agent_status_dashboard.assert_not_called()
    # Verify dry-run output was printed with section data
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("dry-run" in c.lower() for c in calls)
    assert any("agent_count" in c for c in calls)
