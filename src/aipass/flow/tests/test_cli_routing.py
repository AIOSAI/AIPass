# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for flow's entry point routing, help and introspection
# Version: 1.0.0
# Created: 2026-09-04
# Modified: 2026-10-24
# =============================================

"""Tests for apps/flow.py, the CLI entry point."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/flow.py parses and imports

import pytest

from aipass.cli.apps.modules import error, mark_command_failed, reset_command_state
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
    monkeypatch.setattr("sys.argv", ["flow", *argv])
    return branch_entry.main()


def test_print_introspection_renders_identity_and_help_pointer(capsys, stub_module):
    """print_introspection names the branch and points at --help."""
    branch_entry.print_introspection([stub_module])

    out = capsys.readouterr().out
    assert "Flow" in out
    assert "Discovered Modules:" in out
    assert "--help" in out


def test_print_help_has_usage_and_examples(capsys, stub_module):
    """print_help carries the two sections the house pattern requires."""
    branch_entry.print_help([stub_module])

    out = capsys.readouterr().out
    assert "USAGE:" in out
    assert "EXAMPLES:" in out


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
    assert mock_logger.error.called, "the swallowed module exception was never logged"


def test_known_command_exits_zero(monkeypatch, stub_module):
    """A routed command reports success."""
    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


class _ErroringModule:
    """A handler that reports a failure through cli's error() and still claims the command."""

    __name__ = "aipass.flow.apps.modules.erroring"
    __doc__ = "Erroring stub for exit-code tests."

    def handle_command(self, command, args):
        if command != "probe":
            return False
        error("probe failed")
        return True


@pytest.fixture
def clean_exit_flag():
    """Leave cli's process-wide failure flag cleared after the test, whatever main() did."""
    yield
    reset_command_state()


def test_handled_command_that_reported_an_error_exits_two(monkeypatch, capsys, clean_exit_flag):
    """A handler that calls error() and returns True is a failed command: exit 2, not 0.

    Mutant: return resolve_exit(True) -> return 0 reddens this.
    """
    monkeypatch.setattr(branch_entry, "discover_modules", lambda: [_ErroringModule()])

    result = _run(monkeypatch, ["probe"])

    assert result == 2
    assert "probe failed" in capsys.readouterr().err


def test_good_command_exits_zero_after_an_earlier_failure(monkeypatch, stub_module, clean_exit_flag):
    """main() clears the failure flag on entry, so a previous command's error does not leak.

    Mutant: reset_command_state() removed from _main_impl reddens this.
    """
    mark_command_failed()

    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


def test_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """An unrecognized command is a refusal - and a refusal must not exit 0."""
    result = _run(monkeypatch, ["invalid_command"])

    assert result == 1
    assert "Unknown command" in capsys.readouterr().err


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`flow probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_refuses(monkeypatch, stub_module, capsys):
    """`flow ghost --help` refuses with exit 1: there is no module help to answer with.

    Both streams are read: a silent main() returning 1 must fail.
    """
    result = _run(monkeypatch, ["nonexistent", "--help"])

    assert result == 1
    captured = capsys.readouterr()
    assert "Unknown command: nonexistent" in captured.err
    assert "Run drone @flow --help for available commands" in captured.out
    assert stub_module.calls == [("nonexistent", ["--help"])]
