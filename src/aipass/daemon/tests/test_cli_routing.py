# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for DAEMON
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
CLI Routing Tests for DAEMON branch.

Tests daemon.py routing: help flags, introspection, unknown commands,
no-args behavior, and output capture.

Covers 9 tests:
  - help_flag (--help)
  - short_help (-h)
  - help_word ("help")
  - no_args (no arguments)
  - unknown_command
  - print_help
  - print_introspection
  - output_capture
  - version_flag (bonus)
"""

import sys
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# We import the daemon module and mock json_handler.log_operation to
# prevent real file writes during routing tests.
# ---------------------------------------------------------------------------

from aipass.daemon.apps import daemon as _daemon_mod


@pytest.fixture(autouse=True)
def _mock_log_operation():
    """Prevent json_handler.log_operation from touching real files."""
    with patch.object(_daemon_mod.json_handler, "log_operation", return_value=True):
        yield


# ============================================================================
# CLI Routing Tests
# ============================================================================

def test_help_flag() -> None:
    """--help flag triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "--help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --help must return exit code 0"


def test_short_help() -> None:
    """short_help: -h flag triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "-h"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon -h must return exit code 0"


def test_help_word() -> None:
    """help_word: 'help' as command triggers help and returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "help"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon help must return exit code 0"


def test_no_args() -> None:
    """no_args: running daemon with no arguments shows introspection and returns 0."""
    with patch.object(sys, "argv", ["daemon"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon with no args must return exit code 0"


def test_unknown_command() -> None:
    """unknown_command: unrecognized command returns exit code 1."""
    with patch.object(sys, "argv", ["daemon", "nonexistent_command_xyz"]):
        result = _daemon_mod.main()
    assert result == 1, "Unknown command must return exit code 1"


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:
    """print_help: produces stdout output without error."""
    modules = _daemon_mod.get_modules()
    _daemon_mod.print_help(modules)
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"
    assert "DAEMON" in captured.out, "print_help output must mention DAEMON"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:
    """print_introspection: produces stdout output listing modules."""
    modules = _daemon_mod.get_modules()
    _daemon_mod.print_introspection(modules)
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"
    assert "DAEMON" in captured.out, "print_introspection output must mention DAEMON"


def test_output_capture(capsys: pytest.CaptureFixture[str]) -> None:
    """output_capture: help flag produces captured output on stdout."""
    with patch.object(sys, "argv", ["daemon", "--help"]):
        _daemon_mod.main()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "Help output must be capturable on stdout"
    assert "USAGE" in captured.out or "daemon" in captured.out.lower(), (
        "Captured help output must contain usage information"
    )


def test_version_flag() -> None:
    """--version flag returns exit code 0."""
    with patch.object(sys, "argv", ["daemon", "--version"]):
        result = _daemon_mod.main()
    assert result == 0, "daemon --version must return exit code 0"
