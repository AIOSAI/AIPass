# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for flow's entry point routing, help and introspection
# Version: 1.0.0
# Created: 2026-09-04
# Modified: 2026-09-04
# =============================================

"""Tests for flow's CLI entry point.

Covers the four things the entry point promises: no-args shows introspection,
--help shows help without executing anything, a subcommand's --help never runs
that subcommand, and an unknown command fails loudly with a non-zero code.

The exit-code assertions are deliberate. A refusal that exits 0 is a refusal the
shell reads as success, so the refusal path is pinned by test rather than assumed.
"""

import sys

import pytest

from aipass.flow.apps import flow as branch_entry


class _StubModule:
    """Stand-in for a discovered module exposing handle_command()."""

    __name__ = "aipass.flow.apps.modules.stub"
    __doc__ = "Stub module for routing tests."

    def __init__(self, handled_command="probe"):
        self.handled_command = handled_command
        self.calls = []

    def handle_command(self, command, args):
        self.calls.append((command, list(args)))
        return command == self.handled_command


@pytest.fixture
def stub_module(monkeypatch):
    """Replace module discovery with a single controllable stub."""
    stub = _StubModule()
    monkeypatch.setattr(branch_entry, "discover_modules", lambda: [stub])
    return stub


def _run(monkeypatch, argv):
    """Invoke main() with a synthetic argv."""
    monkeypatch.setattr(sys, "argv", ["flow", *argv])
    return branch_entry.main()


# =============================================================================
# HELP AND INTROSPECTION OUTPUT
# =============================================================================


def test_print_introspection_renders_identity_and_help_pointer(capsys, stub_module):
    """print_introspection names the branch and points at --help.

    flow's introspection and help both TAKE the discovered modules rather than
    rediscovering them, so the list is passed here. Adapted to what flow wrote;
    the entry point is the contract.
    """
    branch_entry.print_introspection([stub_module])

    out = capsys.readouterr().out
    assert "Flow" in out
    assert "Discovered Modules:" in out
    assert "--help" in out


def test_print_help_has_usage_and_examples(capsys, stub_module):
    """print_help carries the two sections the house pattern requires.

    Asserted in flow's own casing (USAGE:/EXAMPLES:) - a test does not get to
    rename the entry point's headings.
    """
    branch_entry.print_help([stub_module])

    out = capsys.readouterr().out
    assert "USAGE:" in out
    assert "EXAMPLES:" in out


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
    assert "FLOW" in out


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
    # flow's mock_logger is a MagicMock standing in for the prax logger, not the
    # template's (level, args) list - asserted in the shape flow's conftest
    # actually yields.
    assert mock_logger.error.called, "the swallowed module exception was never logged"


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
# SUBCOMMAND HELP
# =============================================================================


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`flow probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_shows_module_help(monkeypatch, stub_module, capsys):
    """`flow ghost --help` falls through to module help and exits 0.

    Pinned as flow WROTE it, not as the template wished: when no module claims
    the command and a help flag follows, main() calls print_module_help() and
    returns 0. A help request answered with help is not a refusal, so there is
    nothing here for a non-zero exit to mean. The entry point is not bent to
    fit the test.
    """
    result = _run(monkeypatch, ["nonexistent", "--help"])

    assert result == 0
