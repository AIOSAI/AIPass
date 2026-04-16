# =================== AIPass ====================
# Name: test_cli_routing_template.py
# Description: Universal CLI Routing Test Template
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Universal CLI Routing Test Template

Copy this file to any AIPass branch's tests/ directory.
Change BRANCH_MODULE below. Run with pytest.

Covers 9 tests across 3 groups:
  - handle_command routing (6)
  - print_help / print_introspection output (2)
  - help preemption (1)

Every AIPass branch exposes a CLI entry point via handle_command().
These tests verify the routing contract: help flags, no-args fallback,
unknown command rejection, and boolean return types.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest


# ============ BRANCH CONFIG ============
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "seedgo"  # e.g. "prax", "drone", "backup", "cli", etc.
# For commons: "commons" (import path is different: aipass -> just commons)
# For skills: "skills" (import path is different: aipass -> just skills)
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------
# Every branch has an import guard in apps/handlers/__init__.py that blocks
# cross-branch imports. When this template lives in its target branch, the
# guard passes naturally. When testing from devpulse (or any other branch),
# we pre-inject an empty handlers __init__ module to skip the guard.

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _cli_mod_path = f"{BRANCH_MODULE}.apps.handlers.cli.cli_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _cli_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.cli.cli_handler"

# If the handlers package is not yet loaded, inject a stub to avoid the guard.
# The stub needs __path__ set so Python treats it as a package for sub-imports.
if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    if BRANCH_MODULE in ("commons", "skills"):
        _handlers_dir = Path(__file__).resolve().parents[3] / BRANCH_MODULE / "apps" / "handlers"
    else:
        _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_cli_mod_path)
cli_handler = _mod


# ---------------------------------------------------------------------------
# Function discovery helpers
# ---------------------------------------------------------------------------


def _find_handle_command():
    """Locate the handle_command function on the CLI handler module."""
    for name in ("handle_command", "handle_cli_command", "route_command"):
        fn = getattr(_mod, name, None)
        if callable(fn):
            return fn
    return None


def _find_print_help():
    """Locate the help printer function."""
    for name in ("print_help", "show_help", "display_help"):
        fn = getattr(_mod, name, None)
        if callable(fn):
            return fn
    return None


def _find_print_introspection():
    """Locate the introspection printer function."""
    for name in ("print_introspection", "show_introspection", "display_introspection"):
        fn = getattr(_mod, name, None)
        if callable(fn):
            return fn
    return None


# ============================================================================
# Group 1 -- handle_command routing (6 tests)
# ============================================================================


def test_handle_command_help_flag() -> None:  # CR-001
    """handle_command with --help flag returns True."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("cmd", ["--help"])
    assert result is True, "handle_command('cmd', ['--help']) must return True"


def test_handle_command_short_help() -> None:  # CR-002
    """handle_command with -h flag returns True."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("cmd", ["-h"])
    assert result is True, "handle_command('cmd', ['-h']) must return True"


def test_handle_command_help_word() -> None:  # CR-003
    """handle_command('help', []) returns True."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("help", [])
    assert result is True, "handle_command('help', []) must return True"


def test_handle_command_no_args() -> None:  # CR-004
    """handle_command with no args triggers introspection fallback, returns True."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("cmd", [])
    assert result is True, "handle_command('cmd', []) must trigger fallback and return True"


def test_handle_command_unknown() -> None:  # CR-005
    """handle_command with unknown/bogus command returns False."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("bogus", [])
    assert result is False, "handle_command('bogus', []) must return False"


def test_handle_command_return_bool() -> None:  # CR-006
    """handle_command always returns a bool (True or False)."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result_true = handle("help", [])
    result_false = handle("bogus", [])
    assert isinstance(result_true, bool), "handle_command must return bool, not truthy"
    assert isinstance(result_false, bool), "handle_command must return bool, not falsy"
    assert result_true is True
    assert result_false is False


# ============================================================================
# Group 2 -- print_help / print_introspection output (2 tests)
# ============================================================================


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:  # CR-007
    """print_help() runs without error and produces stdout output."""
    print_help = _find_print_help()
    if print_help is None:
        pytest.skip("Branch does not expose print_help")
    print_help()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:  # CR-008
    """print_introspection() runs without error and produces stdout output."""
    print_intro = _find_print_introspection()
    if print_intro is None:
        pytest.skip("Branch does not expose print_introspection")
    print_intro()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"


# ============================================================================
# Group 3 -- help preemption (1 test)
# ============================================================================


def test_help_preempts_execution(capsys: pytest.CaptureFixture[str]) -> None:  # CR-009
    """--help flag causes help text output, preempting normal execution."""
    handle = _find_handle_command()
    if handle is None:
        pytest.skip("Branch does not expose handle_command")
    result = handle("cmd", ["--help"])
    captured = capsys.readouterr()
    assert result is True, "--help must return True"
    assert len(captured.out) > 0, "--help must produce help text on stdout"
