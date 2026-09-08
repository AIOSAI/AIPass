# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for cli's entry point routing, help and introspection
# Version: 1.0.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Tests for cli's CLI entry point.

Covers the four things the entry point promises: no-args shows introspection,
--help shows help without executing anything, a subcommand's --help never runs
that subcommand, and an unknown command fails loudly with a non-zero code.

The exit-code assertions are deliberate. A refusal that exits 0 is a refusal the
shell reads as success, so the refusal path is pinned by test rather than assumed.
"""

import sys

import pytest

from aipass.cli.apps import cli as branch_entry
from aipass.cli.apps.modules import display


class _StubModule:
    """Stand-in for a discovered module exposing handle_command()."""

    __name__ = "aipass.cli.apps.modules.stub"
    __doc__ = "Stub module for routing tests."

    def __init__(self, handled_command="probe"):
        self.handled_command = handled_command
        self.calls = []

    def handle_command(self, command, args):
        self.calls.append((command, list(args)))
        return command == self.handled_command


@pytest.fixture(autouse=True)
def _clean_failure_flag():
    """Leave the process-level failure flag as this file found it.

    display.mark_command_failed() sets module state that outlives the test, so a
    seam test that trips it would otherwise decide the exit code of whatever
    runs next. main() resets on entry, but run_cli() tests and any future caller
    that skips main() would not.
    """
    display.reset_command_state()
    yield
    display.reset_command_state()


@pytest.fixture
def stub_module(monkeypatch):
    """Replace module discovery with a single controllable stub."""
    stub = _StubModule()
    monkeypatch.setattr(branch_entry, "discover_modules", lambda: [stub])
    return stub


def _run(monkeypatch, argv):
    """Invoke main() with a synthetic argv."""
    monkeypatch.setattr(sys, "argv", ["cli", *argv])
    return branch_entry.main()


def _raise(exc):
    """Return a no-arg callable that raises `exc` - a main() that goes wrong."""

    def _boom():
        raise exc

    return _boom


# =============================================================================
# HELP AND INTROSPECTION OUTPUT
# =============================================================================


def test_print_introspection_renders_identity_and_help_pointer(capsys):
    """print_introspection names the branch and points at --help."""
    branch_entry.print_introspection()

    out = capsys.readouterr().out
    assert "CLI" in out
    assert "Discovered Modules:" in out
    assert "--help" in out


def test_print_help_has_usage_and_commands(capsys):
    """print_help carries the two sections cli's help actually renders.

    Asserted in cli's own spelling (USAGE:/COMMANDS:, not Usage:/Examples:) --
    the entry point is the contract, and a test does not get to rename it.
    """
    branch_entry.print_help()

    out = capsys.readouterr().out
    assert "USAGE:" in out
    assert "COMMANDS:" in out


# =============================================================================
# TOP-LEVEL ROUTING
# =============================================================================


def test_no_args_triggers_introspection(monkeypatch, capsys):
    """Bare invocation shows the self-map, not help, and exits 0."""
    assert _run(monkeypatch, []) == 0

    out = capsys.readouterr().out
    assert "Discovered Modules:" in out
    assert "USAGE:" not in out


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_help_flag_preempts_routing(monkeypatch, capsys, flag):
    """All three help spellings show help and exit 0."""
    assert _run(monkeypatch, [flag]) == 0

    assert "USAGE:" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag_prints_version(monkeypatch, capsys, flag):
    """--version reports the branch and version, then exits 0."""
    assert _run(monkeypatch, [flag]) == 0

    out = capsys.readouterr().out
    assert "CLI" in out
    assert branch_entry.VERSION in out


# =============================================================================
# COMMAND ROUTING - SUCCESS AND FAILURE PATHS
# =============================================================================


def test_route_command_returns_true_for_known_command(stub_module):
    """A handled command returns a real bool True, not a truthy value."""
    result = branch_entry.route_command("probe", [], [stub_module])

    assert isinstance(result, bool)
    assert result is True


def test_route_command_returns_false_for_unknown_command(stub_module):
    """An unhandled command returns False so main() can refuse."""
    result = branch_entry.route_command("nonexistent", [], [stub_module])

    assert result is False


def test_route_command_survives_a_raising_module(mock_logger):
    """One exploding module must not take the router down with it."""

    class _Exploding:
        __name__ = "exploding"

        def handle_command(self, command, args):
            raise RuntimeError("boom")

    result = branch_entry.route_command("probe", [], [_Exploding()])

    assert result is False
    assert any(level == "error" for level, _ in mock_logger)


def test_known_command_exits_zero(monkeypatch, stub_module):
    """A routed command reports success."""
    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


def test_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """An unrecognized command is a refusal - and a refusal must not exit 0."""
    result = _run(monkeypatch, ["invalid_command"])

    assert result == 1
    assert "Unknown command" in capsys.readouterr().err


# =============================================================================
# THE EXIT SEAM - reset_command_state / resolve_exit
#
# This branch owns these three names, so these are the fleet's contract for
# them, not just cli's own routing tests. The documented codes: 0 routed and
# clean, 2 routed but a refusal went through error(), 1 not routed at all.
# =============================================================================


def test_routed_command_that_refuses_exits_two(monkeypatch, capsys):
    """A routed command that calls error() is handled AND failed -> 2.

    This is the whole point of the seam. Before it was wired, the module below
    printed a red refusal and main() returned 0, so every shell and every caller
    read the run as a success.
    """

    class _Refusing:
        __name__ = "refusing"

        def handle_command(self, command, args):
            display.error("probe rejected the input", suggestion="pass a real target")
            return True

    monkeypatch.setattr(branch_entry, "discover_modules", lambda: [_Refusing()])

    assert _run(monkeypatch, ["probe"]) == 2
    assert "probe rejected the input" in capsys.readouterr().err


def test_unroutable_command_keeps_its_own_one(monkeypatch, stub_module, capsys):
    """The not-handled 1 is decided before the flag, so error() cannot make it 2.

    resolve_exit() checks handled first. A refusal that was never routed is a 1,
    and the seam must not upgrade it just because error() also tripped the flag.
    """
    assert _run(monkeypatch, ["invalid_command"]) == 1

    assert display.command_failed() is True
    assert "Unknown command" in capsys.readouterr().err


def test_main_resets_a_stale_failure_flag(monkeypatch, stub_module):
    """A failure recorded before main() must not colour this command's exit code.

    The flag is process-level. Without the reset on entry, one refused command
    would make every later command in the same process exit 2.
    """
    display.mark_command_failed()

    assert _run(monkeypatch, ["probe"]) == 0


def test_run_cli_maps_cancellation_to_130(monkeypatch, mock_logger, capsys):
    """Ctrl-C is 130 (128 + SIGINT), never 0 - a cancelled run is not a success."""
    monkeypatch.setattr(branch_entry, "main", _raise(KeyboardInterrupt))

    assert branch_entry.run_cli() == 130

    assert "Operation cancelled" in capsys.readouterr().out
    assert any(level == "warning" for level, _ in mock_logger)


def test_run_cli_maps_an_unhandled_crash_to_one(monkeypatch, mock_logger, capsys):
    """An escaped exception is reported through error() and exits 1."""
    monkeypatch.setattr(branch_entry, "main", _raise(RuntimeError("boom")))

    assert branch_entry.run_cli() == 1

    assert "boom" in capsys.readouterr().err
    assert any(level == "error" for level, _ in mock_logger)


def test_run_cli_passes_a_clean_run_through(monkeypatch, stub_module):
    """No interrupt, no crash: run_cli() hands main()'s code straight back."""
    monkeypatch.setattr(sys, "argv", ["cli", "probe"])

    assert branch_entry.run_cli() == 0
    assert stub_module.calls == [("probe", [])]


# =============================================================================
# SUBCOMMAND HELP
# =============================================================================


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`cli probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_falls_back_to_general_help(monkeypatch, stub_module, capsys):
    """`cli ghost --help` shows the general help and exits 0.

    Pinned as cli WROTE it, not as the template wished: when no module claims
    the command, main() falls through to print_help() and returns 0. A help
    request answered with help is not a refusal, so there is nothing here for a
    non-zero exit to mean. The entry point is not bent to fit the test.
    """
    result = _run(monkeypatch, ["nonexistent", "--help"])

    assert result == 0
    assert "USAGE:" in capsys.readouterr().out
