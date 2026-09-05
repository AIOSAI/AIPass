# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for hooks's entry point routing, help and introspection
# Version: 1.1.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Tests for hooks's CLI entry point.

Covers the four things the entry point promises: no-args shows introspection,
--help shows help without executing anything, a subcommand's --help never runs
that subcommand, and an unknown command fails loudly with a non-zero code.

The exit-code assertions are deliberate. A refusal that exits 0 is a refusal the
shell reads as success, so the refusal path is pinned by test rather than assumed.

Arrived with the citizen template on 2026-09-03 (the DPLAN-0325 lane adds any
missing template file) and is adapted here to the entry point hooks actually
has. Three template assumptions do not hold for this branch and are asserted in
this branch's spelling instead of the template's: help sections are uppercase
(``USAGE:``), ``--version`` prints the lowercase branch name, and the refusal
message is written with the rest of the CLI's output rather than to stderr. The
template's ``__version__`` and ``_module_import_path`` pins are dropped
outright — hooks.py has neither name, so there was nothing to measure.
"""

import importlib
import os
import sys

import pytest

from aipass.hooks.apps import hooks as branch_entry


class _StubModule:
    """Stand-in for a discovered module exposing handle_command()."""

    __name__ = "aipass.hooks.apps.modules.stub"
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


@pytest.fixture
def entry_logger(monkeypatch):
    """Capture calls made to the ENTRY POINT's logger.

    Local on purpose: this branch's conftest already owns a ``mock_logger``
    that patches the engine's logger, and the two must not be confused.

    Returns:
        A list that fills with (level, args) tuples as the code under test logs.
    """
    captured: list = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured


def _run(monkeypatch, argv):
    """Invoke main() with a synthetic argv."""
    monkeypatch.setattr(sys, "argv", ["hooks", *argv])
    return branch_entry.main()


# =============================================================================
# HELP AND INTROSPECTION OUTPUT
# =============================================================================


def test_print_introspection_renders_identity_and_help_pointer(capsys):
    """print_introspection names the branch and points at --help."""
    branch_entry.print_introspection()

    out = capsys.readouterr().out
    assert "HOOKS" in out
    assert "Discovered Modules:" in out
    assert "--help" in out


def test_print_help_has_usage_and_examples(capsys):
    """print_help carries the two sections the house pattern requires."""
    branch_entry.print_help()

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
    """--version reports the branch and a version, then exits 0."""
    assert _run(monkeypatch, [flag]) == 0

    out = capsys.readouterr().out
    assert "hooks" in out
    assert "1.1.0" in out


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


def test_route_command_survives_a_raising_module(entry_logger):
    """One exploding module must not take the router down with it."""

    class _Exploding:
        __name__ = "exploding"

        def handle_command(self, command, args):
            raise RuntimeError("boom")

    result = branch_entry.route_command("probe", [], [_Exploding()])

    assert result is False
    assert any(level == "error" for level, _ in entry_logger)


def test_known_command_exits_zero(monkeypatch, stub_module):
    """A routed command reports success."""
    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


def test_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """An unrecognized command is a refusal - and a refusal must not exit 0."""
    result = _run(monkeypatch, ["invalid_command"])

    captured = capsys.readouterr()

    assert result == 1
    # Stream-agnostic on purpose: hooks writes the refusal with the rest of its
    # CLI output rather than to stderr, unlike the template this file came from.
    # The exit code is the contract; which stream carries the sentence is an
    # open question for the entry point, not something to bless here.
    assert "Unknown command" in captured.out + captured.err


# =============================================================================
# SUBCOMMAND HELP
# =============================================================================


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`hooks probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """Asking for help on a command that does not exist is still a refusal."""
    result = _run(monkeypatch, ["nonexistent", "--help"])

    captured = capsys.readouterr()

    assert result == 1
    assert "Unknown command" in captured.out + captured.err


# =============================================================================
# IMPORT-TIME INFRASTRUCTURE
# =============================================================================


def test_branch_name_is_set_at_import_time(monkeypatch):
    """The entry point stamps AIPASS_BRANCH_NAME before prax resolves a branch.

    Uses importlib.reload so the module body actually re-executes - asserting on
    the already-imported module would pass even if the line were deleted.
    """
    monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

    reloaded = importlib.reload(sys.modules["aipass.hooks.apps.hooks"])

    assert os.environ["AIPASS_BRANCH_NAME"] == "hooks"
    assert reloaded.discover_modules is not None
