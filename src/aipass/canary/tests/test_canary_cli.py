# =================== AIPass ====================
# Name: test_canary_cli.py
# Description: Tests for canary's entry point routing, help and introspection
# Version: 1.1.0
# Created: 2026-08-22
# Modified: 2026-10-04
# =============================================

"""Tests for apps/canary.py, the entry point: routing, help and introspection."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — that a Windows console is switched to utf-8 before any print
# seedgo: no-test-needed(logged_fallback) — that a module which fails to import is logged and skipped

import os
import subprocess
import sys

import pytest

from aipass.canary.apps import canary as canary_entry

# Covers the four things the entry point promises: no-args shows introspection,
# --help shows help without executing anything, a subcommand's --help never
# runs that subcommand, and an unknown command fails loudly with a non-zero code.
#
# The exit-code assertions are deliberate. Canary found owner-gate refusals that
# exited 0 in another branch — a refusal the shell reads as success — so its own
# refusal path is pinned by test rather than assumed.


class _StubModule:
    """Stand-in for a discovered module exposing handle_command()."""

    __name__ = "aipass.canary.apps.modules.stub"
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
    monkeypatch.setattr(canary_entry, "discover_modules", lambda: [stub])
    return stub


def _run(monkeypatch, argv):
    """Invoke main() with a synthetic argv."""
    monkeypatch.setattr(sys, "argv", ["canary", *argv])
    return canary_entry.main()


# =============================================================================
# HELP AND INTROSPECTION OUTPUT
# =============================================================================


def test_print_introspection_renders_identity_and_help_pointer(capsys):
    """print_introspection names the branch, its purpose, and points at --help."""
    canary_entry.print_introspection()

    out = capsys.readouterr().out
    assert "CANARY" in out
    assert "Permanent Test Citizen" in out
    assert "--help" in out


def test_print_help_has_usage_and_examples(capsys):
    """print_help carries the two sections the house pattern requires."""
    canary_entry.print_help()

    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "Examples:" in out


# =============================================================================
# TOP-LEVEL ROUTING
# =============================================================================


def test_no_args_triggers_introspection(monkeypatch, capsys):
    """Bare invocation shows the self-map, not help, and exits 0."""
    assert _run(monkeypatch, []) == 0

    out = capsys.readouterr().out
    assert "Discovered Modules:" in out
    assert "Usage:" not in out


@pytest.mark.parametrize("flag", ["--help", "-h", "help"])
def test_help_flag_preempts_routing(monkeypatch, capsys, flag):
    """All three help spellings show help and exit 0."""
    assert _run(monkeypatch, [flag]) == 0

    assert "Usage:" in capsys.readouterr().out


def test_help_preempts_module_discovery(monkeypatch, capsys):
    """--help must not import modules — help is answered before any side effect."""
    discovered = []

    def _tracking_discovery():
        discovered.append(True)
        return []

    monkeypatch.setattr(canary_entry, "discover_modules", _tracking_discovery)

    assert _run(monkeypatch, ["--help"]) == 0
    assert discovered == []
    capsys.readouterr()


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_flag_prints_version(monkeypatch, capsys, flag):
    """--version reports the branch and version, then exits 0."""
    assert _run(monkeypatch, [flag]) == 0

    out = capsys.readouterr().out
    assert "CANARY" in out
    assert canary_entry.__version__ in out


# =============================================================================
# COMMAND ROUTING — SUCCESS AND FAILURE PATHS
# =============================================================================


def test_route_command_returns_true_for_known_command(stub_module):
    """A handled command returns a real bool True, not a truthy value."""
    result = canary_entry.route_command("probe", [], [stub_module])

    assert isinstance(result, bool)
    assert result is True


def test_route_command_returns_false_for_unknown_command(stub_module):
    """An unhandled command returns False so main() can refuse."""
    result = canary_entry.route_command("nonexistent", [], [stub_module])

    assert result is False


def test_route_command_survives_a_raising_module(mock_logger):
    """One exploding module must not take the router down with it."""

    class _Exploding:
        __name__ = "exploding"

        def handle_command(self, command, args):
            raise RuntimeError("boom")

    result = canary_entry.route_command("probe", [], [_Exploding()])

    assert result is False
    assert any(level == "error" for level, _ in mock_logger)


def test_known_command_exits_zero(monkeypatch, stub_module):
    """A routed command reports success."""
    assert _run(monkeypatch, ["probe"]) == 0
    assert stub_module.calls == [("probe", [])]


def test_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """An unrecognized command is a refusal — and a refusal must not exit 0."""
    result = _run(monkeypatch, ["invalid_command"])

    assert result == 1
    assert "Unknown command" in capsys.readouterr().err


# =============================================================================
# SUBCOMMAND HELP
# =============================================================================


def test_subcommand_help_does_not_execute_the_command(monkeypatch, stub_module):
    """`canary probe --help` asks the module for help; it never runs bare."""
    assert _run(monkeypatch, ["probe", "--help"]) == 0

    assert stub_module.calls == [("probe", ["--help"])]


def test_subcommand_help_on_unknown_command_exits_nonzero(monkeypatch, stub_module, capsys):
    """Asking for help on a command that does not exist is still a refusal."""
    result = _run(monkeypatch, ["nonexistent", "--help"])

    assert result == 1
    assert "Unknown command" in capsys.readouterr().err


def test_routed_command_that_refuses_exits_two(monkeypatch, capsys):
    """A module that handles the command but refuses it must not exit 0.

    handle_command returning True means "I handled this", not "it worked" —
    the refusal travels through cli error()'s failure flag. Before the
    resolve_exit wiring (2026-09-12) this exited 0.
    """

    class _Refusing:
        __name__ = "aipass.canary.apps.modules.refusing"

        def handle_command(self, command, args):
            canary_entry.error("refused on purpose")
            return True

    monkeypatch.setattr(canary_entry, "discover_modules", lambda: [_Refusing()])

    assert _run(monkeypatch, ["anything"]) == 2
    assert "refused on purpose" in capsys.readouterr().err


def test_failure_flag_from_an_earlier_command_does_not_leak(monkeypatch, stub_module, capsys):
    """main() resets the flag first, so a clean command after a refusal exits 0."""
    canary_entry.error("an earlier refusal in this process")
    capsys.readouterr()

    assert _run(monkeypatch, ["probe"]) == 0


# =============================================================================
# IMPORT-TIME INFRASTRUCTURE
# =============================================================================


def test_a_fresh_import_stamps_the_branch_name_into_an_environment_without_one(tmp_path):
    """A child interpreter imports the entry point cold, so the module body runs; proven by its mutant."""
    env = {key: value for key, value in os.environ.items() if key != "AIPASS_BRANCH_NAME"}
    probe = "import os\nimport aipass.canary.apps.canary\nprint(os.environ.get('AIPASS_BRANCH_NAME'))\n"

    child = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(tmp_path),
        env=env,
    )

    assert child.returncode == 0, child.stderr
    assert child.stdout == "canary\n"
