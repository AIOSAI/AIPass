# =================== AIPass ====================
# Name: test_branch_ping.py
# Description: Tests for branch ping orchestration module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for branch_ping module -- command routing and orchestration."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.modules.branch_ping as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


@pytest.fixture(autouse=True)
def _suppress_logger(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(mod, "logger", MagicMock())


@pytest.fixture(autouse=True)
def _mock_console(monkeypatch):
    """Mock console and error to prevent real rich output."""
    mock_console = MagicMock()
    monkeypatch.setattr(mod, "console", mock_console)
    monkeypatch.setattr(mod, "error", MagicMock())
    return mock_console


# --- handle_command tests ---------------------------------------------


def test_handle_command_returns_false_for_unknown_command():
    """Returns False for commands not handled by this module."""
    assert mod.handle_command("unknown_cmd", ["run"]) is False


def test_handle_command_returns_false_for_empty_unknown():
    """Returns False for another unrecognized command."""
    assert mod.handle_command("deploy", []) is False


def test_handle_command_routes_ping(monkeypatch):
    """Routes 'ping' command to handle_ping."""
    mock_ping = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "handle_ping", mock_ping)

    result = mod.handle_command("ping", ["run"])
    assert result is True
    mock_ping.assert_called_once()


def test_handle_command_routes_ping_with_verbose(monkeypatch):
    """Routes 'ping' with --verbose flag."""
    mock_ping = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "handle_ping", mock_ping)

    mod.handle_command("ping", ["--verbose"])
    mock_ping.assert_called_once_with(True)


def test_handle_command_routes_status(monkeypatch):
    """Routes 'status' command to handle_status."""
    mock_status = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "handle_status", mock_status)

    result = mod.handle_command("status", ["run"])
    assert result is True
    mock_status.assert_called_once()


def test_handle_command_routes_registry(monkeypatch):
    """Routes 'registry' command to handle_registry."""
    mock_registry = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "handle_registry", mock_registry)

    result = mod.handle_command("registry", ["run"])
    assert result is True
    mock_registry.assert_called_once()


def test_handle_command_routes_thresholds():
    """Routes 'thresholds' command to handle_thresholds."""
    result = mod.handle_command("thresholds", ["run"])
    assert result is True


def test_handle_command_help_flag(monkeypatch):
    """--help flag calls print_help and returns True."""
    mock_help = MagicMock()
    monkeypatch.setattr(mod, "print_help", mock_help)

    result = mod.handle_command("ping", ["--help"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_h_flag(monkeypatch):
    """-h flag calls print_help and returns True."""
    mock_help = MagicMock()
    monkeypatch.setattr(mod, "print_help", mock_help)

    result = mod.handle_command("status", ["-h"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_help_word(monkeypatch):
    """'help' as first arg calls print_help and returns True."""
    mock_help = MagicMock()
    monkeypatch.setattr(mod, "print_help", mock_help)

    result = mod.handle_command("registry", ["help"])
    assert result is True
    mock_help.assert_called_once()


def test_handle_command_no_args_calls_introspection(monkeypatch):
    """No args calls print_introspection and returns True."""
    mock_introspect = MagicMock()
    monkeypatch.setattr(mod, "print_introspection", mock_introspect)

    result = mod.handle_command("ping", [])
    assert result is True
    mock_introspect.assert_called_once()


# --- handle_thresholds tests ------------------------------------------


def test_handle_thresholds_returns_true():
    """handle_thresholds returns True."""
    assert mod.handle_thresholds() is True


def test_handle_thresholds_prints_values(_mock_console):
    """handle_thresholds prints threshold range values."""
    mod.handle_thresholds()

    printed = " ".join(str(c) for c in _mock_console.print.call_args_list)
    assert "400" in printed
    assert "401" in printed
    assert "550" in printed
    assert "551" in printed


# --- handle_ping tests ------------------------------------------------


def test_handle_ping_returns_true_on_success(monkeypatch):
    """handle_ping returns True when all handlers succeed."""
    monkeypatch.setattr(mod, "get_branch_context", lambda: ("test-branch", Path("/tmp/test")))
    monkeypatch.setattr(mod, "count_file_lines", lambda f: 100)
    monkeypatch.setattr(mod, "get_status_from_count", lambda c: "green")
    monkeypatch.setattr(mod, "update_json_memory_health", MagicMock())
    monkeypatch.setattr(mod, "ping_registry", MagicMock())

    assert mod.handle_ping(verbose=False) is True


def test_handle_ping_verbose_prints_output(monkeypatch, _mock_console):
    """handle_ping with verbose=True prints status info."""
    monkeypatch.setattr(mod, "get_branch_context", lambda: ("my-branch", Path("/tmp/test")))
    monkeypatch.setattr(mod, "count_file_lines", lambda f: 250)
    monkeypatch.setattr(mod, "get_status_from_count", lambda c: "yellow")
    monkeypatch.setattr(mod, "update_json_memory_health", MagicMock())
    monkeypatch.setattr(mod, "ping_registry", MagicMock())

    mod.handle_ping(verbose=True)

    printed = " ".join(str(c) for c in _mock_console.print.call_args_list)
    assert "my-branch" in printed
    assert "250" in printed
    assert "yellow" in printed


def test_handle_ping_returns_false_on_exception(monkeypatch):
    """handle_ping returns False when get_branch_context raises."""
    def raise_error():
        raise RuntimeError("git not found")

    monkeypatch.setattr(mod, "get_branch_context", raise_error)

    assert mod.handle_ping(verbose=False) is False


def test_handle_ping_calls_ping_registry(monkeypatch):
    """handle_ping calls ping_registry with correct arguments."""
    mock_ping_reg = MagicMock()
    monkeypatch.setattr(mod, "get_branch_context", lambda: ("feat-x", Path("/tmp/feat")))
    monkeypatch.setattr(mod, "count_file_lines", lambda f: 50)
    monkeypatch.setattr(mod, "get_status_from_count", lambda c: "green")
    monkeypatch.setattr(mod, "update_json_memory_health", MagicMock())
    monkeypatch.setattr(mod, "ping_registry", mock_ping_reg)

    mod.handle_ping(verbose=False)

    mock_ping_reg.assert_called_once_with(
        "feat-x",
        Path("/tmp/feat"),
        {"line_count": 50, "status": "green"},
        {"line_count": 50, "status": "green"},
    )


# --- handle_status tests ---------------------------------------------


def test_handle_status_returns_true_on_success(monkeypatch):
    """handle_status returns True when handlers succeed."""
    monkeypatch.setattr(mod, "get_branch_context", lambda: ("main", Path("/tmp/main")))
    monkeypatch.setattr(mod, "get_health_info", lambda f: {"line_count": 100, "status": "green"})

    assert mod.handle_status() is True


def test_handle_status_returns_false_on_exception(monkeypatch):
    """handle_status returns False when an exception is raised."""
    def raise_error():
        raise RuntimeError("file not found")

    monkeypatch.setattr(mod, "get_branch_context", raise_error)

    assert mod.handle_status() is False


# --- print_introspection tests ----------------------------------------


def test_print_introspection_prints_module_info(_mock_console):
    """print_introspection prints module name and handler info."""
    mod.print_introspection()

    printed = " ".join(str(c) for c in _mock_console.print.call_args_list)
    assert "branch_ping" in printed
    assert "handlers/monitoring/" in printed
    assert "handlers/registry/" in printed


# --- print_help tests -------------------------------------------------


def test_print_help_prints_command_list(_mock_console):
    """print_help prints available commands."""
    mod.print_help()

    printed = " ".join(str(c) for c in _mock_console.print.call_args_list)
    assert "ping" in printed
    assert "status" in printed
    assert "registry" in printed
    assert "thresholds" in printed
