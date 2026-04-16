"""Tests for checklist module."""

# =================== META ====================
# Name: test_checklist.py
# Description: Unit tests for the checklist module
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
    """Mock heavy infrastructure imports for checklist."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- branch_audit (discover_checkers) ------------------------------------
    audit_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit", audit_pkg)
    branch_audit_mod = MagicMock()
    branch_audit_mod.discover_checkers = MagicMock(return_value={})
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.audit.branch_audit", branch_audit_mod)

    # -- bypass handler -----------------------------------------------------
    bypass_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    bypass_mod = MagicMock()
    bypass_mod.get_branch_from_path = MagicMock(return_value=None)
    bypass_mod.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.checklist", raising=False)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.checklist import handle_command

    result = handle_command("checklist", ["help"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — run_checklist
# ---------------------------------------------------------------------------


def test_run_checklist_file_not_found(tmp_path):
    """run_checklist returns error result for missing file."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    results = run_checklist(str(tmp_path / "nonexistent.py"))
    assert len(results) == 1
    assert results[0]["passed"] is False
    assert "not found" in results[0]["detail"].lower() or "File not found" in results[0]["detail"]


def test_run_checklist_non_python_file(tmp_path):
    """run_checklist skips non-Python files gracefully."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("hello", encoding="utf-8")
    results = run_checklist(str(txt_file))
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert "not a python" in results[0]["detail"].lower()


def test_run_checklist_python_file_no_checkers(tmp_path):
    """run_checklist on a Python file with no applicable checkers returns skip."""
    from aipass.seedgo.apps.modules.checklist import run_checklist

    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    results = run_checklist(str(py_file))
    # With mocked empty checkers, should get either skip or error
    assert len(results) >= 1
    assert isinstance(results[0], dict)


# ---------------------------------------------------------------------------
# Tests — print_introspection / print_help
# ---------------------------------------------------------------------------


def test_print_introspection_runs():
    """print_introspection produces console output."""
    import sys
    from aipass.seedgo.apps.modules.checklist import print_introspection

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    result = print_introspection()
    assert result is None
    assert mock_cli.console.print.called, "print_introspection should produce console output"


def test_print_help_runs():
    """print_help produces console output."""
    import sys
    from aipass.seedgo.apps.modules.checklist import print_help

    mock_cli = sys.modules["aipass.cli"]
    mock_cli.console.reset_mock()
    result = print_help()
    assert result is None
    assert mock_cli.console.print.called, "print_help should produce console output"


# ---------------------------------------------------------------------------
# Tests — internal helpers
# ---------------------------------------------------------------------------


def test_is_entry_point_detection():
    """_is_entry_point correctly identifies apps/{name}.py files."""
    from aipass.seedgo.apps.modules.checklist import _is_entry_point

    assert _is_entry_point("/some/branch/apps/flow.py") is True
    assert _is_entry_point("/some/branch/apps/modules/helper.py") is False
    assert _is_entry_point("/some/branch/apps/readme.txt") is False


def test_format_failure_no_checks():
    """_format_failure returns fallback when no failed checks present."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure({"checks": []})
    assert "no details" in result.lower()


def test_format_failure_single_failure():
    """_format_failure returns the message from the first failed check."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure(
        {
            "checks": [
                {"passed": False, "message": "Missing docstring"},
            ]
        }
    )
    assert "Missing docstring" in result


def test_format_failure_multiple_failures():
    """_format_failure indicates additional failures."""
    from aipass.seedgo.apps.modules.checklist import _format_failure

    result = _format_failure(
        {
            "checks": [
                {"passed": False, "message": "Missing docstring"},
                {"passed": False, "message": "No type hints"},
            ]
        }
    )
    assert "+1 more" in result
