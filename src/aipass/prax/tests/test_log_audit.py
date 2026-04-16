# =================== AIPass ====================
# Name: test_log_audit.py
# Description: Unit tests for PRAX log_audit module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for prax log_audit module command routing, help text, and display formatting.

All module imports happen inside test functions so that conftest's
autouse mock_prax_infrastructure fixture injects sys.modules mocks first.
"""

import sys
from unittest.mock import MagicMock


# =============================================
# HELPERS
# =============================================


def _ensure_watchdog_mock(monkeypatch):
    """Inject a mock for the log_watchdog handler."""
    mock_watchdog = MagicMock()
    mock_watchdog.scan_log_files = MagicMock(
        return_value=[
            {"name": "system.log", "lines": 500, "size_kb": 45, "status": "ok"},
            {"name": "error.log", "lines": 2500, "size_kb": 200, "status": "oversized"},
        ]
    )
    mock_watchdog.log_health_summary = MagicMock(
        return_value={
            "total_files": 2,
            "total_lines": 3000,
            "largest_file": "error.log",
            "largest_lines": 2500,
            "healthy": False,
            "oversized_count": 1,
            "critical_count": 0,
        }
    )
    mock_watchdog.enforce_log_limits = MagicMock(
        return_value=[
            {"name": "error.log", "truncated": True, "original_lines": 2500, "new_lines": 1000},
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.prax.apps.handlers.logging.log_watchdog",
        mock_watchdog,
    )
    return mock_watchdog


def _fresh_import():
    """Force re-import of the log_audit module."""
    mod_name = "aipass.prax.apps.modules.log_audit"
    sys.modules.pop(mod_name, None)
    from aipass.prax.apps.modules.log_audit import (
        handle_command,
        print_help,
        print_introspection,
        _display_audit,
    )

    return handle_command, print_help, print_introspection, _display_audit


# =============================================
# TESTS
# =============================================


def test_handle_command_help(mock_prax_infrastructure, monkeypatch):
    """--help flag returns True and displays help text."""
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("log-audit", ["--help"])
    assert result is True
    mock_prax_infrastructure.console.print.assert_called()


def test_handle_command_help_h_flag(mock_prax_infrastructure, monkeypatch):
    """-h flag also triggers help with audit-related content."""
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("log-audit", ["-h"])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("audit" in c.lower() for c in calls)


def test_handle_command_no_args_calls_introspection(mock_prax_infrastructure, monkeypatch):
    """No args prints introspection and returns True."""
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("log-audit", [])
    assert result is True
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Log Audit Module" in c for c in calls)


def test_handle_command_wrong_command(mock_prax_infrastructure, monkeypatch):
    """Wrong command name returns False."""
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("not-log-audit", [])
    assert result is False


def test_print_help_runs(mock_prax_infrastructure, monkeypatch):
    """print_help runs without error and includes audit/enforce subcommands."""
    _, print_help, _, _ = _fresh_import()

    print_help()
    mock_prax_infrastructure.console.print.assert_called()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("audit" in c.lower() for c in calls)
    assert any("enforce" in c.lower() for c in calls)


def test_print_introspection_runs(mock_prax_infrastructure, monkeypatch):
    """print_introspection runs without error."""
    _, _, print_introspection, _ = _fresh_import()

    print_introspection()
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("Connected Handlers" in c for c in calls)


def test_display_audit_healthy(mock_prax_infrastructure, monkeypatch):
    """_display_audit formats healthy summary correctly."""
    _, _, _, _display_audit = _fresh_import()

    files = [{"name": "system.log", "lines": 200, "size_kb": 10, "status": "ok"}]
    summary = {
        "total_files": 1,
        "total_lines": 200,
        "largest_file": "system.log",
        "largest_lines": 200,
        "healthy": True,
        "oversized_count": 0,
        "critical_count": 0,
    }

    _display_audit(files, summary)
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("HEALTHY" in c for c in calls)
    assert any("system.log" in c for c in calls)


def test_display_audit_oversized(mock_prax_infrastructure, monkeypatch):
    """_display_audit shows oversized files when present."""
    _, _, _, _display_audit = _fresh_import()

    files = [
        {"name": "system.log", "lines": 500, "size_kb": 45, "status": "ok"},
        {"name": "error.log", "lines": 2500, "size_kb": 200, "status": "oversized"},
        {"name": "crash.log", "lines": 5000, "size_kb": 400, "status": "critical"},
    ]
    summary = {
        "total_files": 3,
        "total_lines": 8000,
        "largest_file": "crash.log",
        "largest_lines": 5000,
        "healthy": False,
        "oversized_count": 1,
        "critical_count": 1,
    }

    _display_audit(files, summary)
    calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    # Should show oversized section
    assert any("Oversized files" in c for c in calls)
    # File names appear in output
    assert any("error.log" in c for c in calls)
    assert any("crash.log" in c for c in calls)
    # error() called for unhealthy status
    mock_prax_infrastructure.cli.error.assert_called()


def test_handle_command_unknown_subcommand(mock_prax_infrastructure, monkeypatch):
    """Unknown subcommand shows error and help text."""
    _ensure_watchdog_mock(monkeypatch)
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("log-audit", ["bogus"])
    assert result is True
    # error() called with unknown subcommand message
    calls = [str(c) for c in mock_prax_infrastructure.cli.error.call_args_list]
    assert any("bogus" in c for c in calls)
    # Help text printed after error
    console_calls = [str(c) for c in mock_prax_infrastructure.console.print.call_args_list]
    assert any("audit" in c.lower() for c in console_calls)


def test_handle_command_audit_subcommand(mock_prax_infrastructure, monkeypatch):
    """'audit' subcommand calls scan_log_files and log_health_summary."""
    mock_watchdog = _ensure_watchdog_mock(monkeypatch)
    handle_command, _, _, _ = _fresh_import()

    result = handle_command("log-audit", ["audit"])
    assert result is True
    mock_watchdog.scan_log_files.assert_called_once()
    mock_watchdog.log_health_summary.assert_called_once()
