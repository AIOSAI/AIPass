"""Tests for diagnostics_audit module."""

# =================== META ====================
# Name: test_diagnostics_audit.py
# Description: Unit tests for the diagnostics_audit module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for diagnostics_audit."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()
    mock_normalize = MagicMock(side_effect=lambda x: x.lstrip("@").upper())

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

    # -- drone services -----------------------------------------------------
    drone_mod = MagicMock()
    drone_mod.normalize_branch_arg = mock_normalize
    monkeypatch.setitem(sys.modules, "aipass.drone", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.drone.apps.modules", drone_mod)

    # -- diagnostics discovery handler --------------------------------------
    diag_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.diagnostics", diag_pkg)
    discovery_mod = MagicMock()
    discovery_mod.discover_branches = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.diagnostics.discovery", discovery_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.diagnostics_audit", raising=False)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------

def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    assert handle_command("wrong_command", []) is False


def test_handle_command_accepts_diagnostics_name():
    """handle_command recognises 'diagnostics' as its command."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", [])
    assert result is True


def test_handle_command_accepts_diagnostics_audit_name():
    """handle_command recognises 'diagnostics_audit' as its command."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics_audit", [])
    assert result is True


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", ["help"])
    assert result is True


def test_handle_command_unknown_arg():
    """Unknown argument returns True (error displayed gracefully)."""
    from aipass.seedgo.apps.modules.diagnostics_audit import handle_command
    result = handle_command("diagnostics", ["some_unknown_arg"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — introspection / help
# ---------------------------------------------------------------------------

def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.diagnostics_audit import print_introspection
    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, \
        "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.diagnostics_audit import print_help
    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    mock_cli.header.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called or mock_cli.header.called, \
        "print_help should produce console output"


# ---------------------------------------------------------------------------
# Tests — display functions
# ---------------------------------------------------------------------------

def test_print_branch_diagnostics_clean():
    """print_branch_diagnostics handles clean branch result."""
    from aipass.seedgo.apps.modules.diagnostics_audit import print_branch_diagnostics
    result = {
        "branch": "TEST",
        "total_errors": 0,
        "total_warnings": 0,
        "total_files": 5,
        "files_with_errors": 0,
        "results": [],
    }
    # Should not raise
    print_branch_diagnostics(result)


def test_print_branch_diagnostics_with_errors():
    """print_branch_diagnostics handles branch with errors."""
    from aipass.seedgo.apps.modules.diagnostics_audit import print_branch_diagnostics
    result = {
        "branch": "TEST",
        "total_errors": 15,
        "total_warnings": 3,
        "total_files": 10,
        "files_with_errors": 2,
        "results": [
            {
                "file": "/some/path/test.py",
                "errors": 5,
                "diagnostics": [
                    {"line": 10, "message": "Type mismatch"},
                    {"line": 20, "message": "Undefined variable 'x'"},
                ],
            }
        ],
    }
    # Should not raise
    print_branch_diagnostics(result)


def test_print_system_summary_empty():
    """print_system_summary handles empty results list."""
    from aipass.seedgo.apps.modules.diagnostics_audit import print_system_summary
    print_system_summary([])


def test_print_system_summary_with_data():
    """print_system_summary handles real-ish data."""
    from aipass.seedgo.apps.modules.diagnostics_audit import print_system_summary
    results = [
        {"branch": "FLOW", "total_errors": 0, "total_warnings": 1, "total_files": 5, "files_with_errors": 0},
        {"branch": "CLI", "total_errors": 3, "total_warnings": 0, "total_files": 8, "files_with_errors": 2},
    ]
    print_system_summary(results)
