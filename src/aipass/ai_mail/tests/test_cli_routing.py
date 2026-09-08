# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for CLI routing and help display
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Tests for CLI routing -- help flags, introspection, unknown commands, output capture."""

import json
import sys

import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.ai_mail as ai_mail_mod
from aipass.ai_mail.apps.ai_mail import (
    print_help,
    print_introspection,
    route_command,
    main,
)


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _caller_stands_in_a_branch(tmp_path, monkeypatch):
    """Give every test in this file a resolvable caller identity, built from nothing.

    These are tests of ROUTING — which command reaches which module, and what the
    exit code says about the result. They are not tests of identity. But main()
    refuses outright when the caller cannot be resolved (Patrick's ruling,
    2026-08-21), so without a caller they assert something about identity they
    never meant to.

    THE SEAT IS SYNTHETIC, and that is the fix. An earlier version pointed
    AIPASS_CALLER_CWD at this branch's real directory, which resolved only
    because the LIVE registry on the author's machine had a row for it. CI is a
    fresh checkout — the registry is untracked runtime state and does not exist
    there — so identity resolved to nobody, the fence refused with 2, and three
    tests here went red (@devpulse, PR 739, 2026-08-23). They were testing the
    machine, not the code.

    Everything identity needs is now built in tmp_path: a repo marker, a
    registry row keyed on the branch's relative path, and a passport at the end
    of the walk. Nothing outside this directory is read, so the result is the
    same on any machine and in any checkout.

    The fence is EXERCISED, not stubbed. These tests still prove a legitimate
    caller reaches routing — they just no longer borrow someone else's registry
    to do it.
    """
    branch = tmp_path / "seat" / "src" / "aipass" / "ai_mail"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "ai_mail", "email": "@ai_mail", "path": "src/aipass/ai_mail"}}),
        encoding="utf-8",
    )
    (tmp_path / "seat" / "AIPASS_REGISTRY.json").write_text(
        json.dumps(
            {
                "metadata": {"version": "1.0.0", "total_branches": 1},
                "branches": [
                    {
                        "name": "AI_MAIL",
                        "path": "src/aipass/ai_mail",
                        "email": "@ai_mail",
                        "status": "active",
                        "profile": "library",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch))
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock console output and logger to prevent real I/O."""
    mock_console = MagicMock()
    monkeypatch.setattr(ai_mail_mod, "console", mock_console)
    monkeypatch.setattr(ai_mail_mod, "error", MagicMock())
    monkeypatch.setattr(ai_mail_mod, "logger", MagicMock())
    yield mock_console


@pytest.fixture
def fake_module():
    """Create a fake module with handle_command."""
    mod = MagicMock()
    mod.__name__ = "fake_module"
    mod.handle_command.return_value = False
    return mod


@pytest.fixture
def fake_module_handled():
    """Create a fake module that handles commands."""
    mod = MagicMock()
    mod.__name__ = "handled_module"
    mod.handle_command.return_value = True
    return mod


# ---- print_help tests -----------------------------------------------


def test_print_help_outputs(_mock_infrastructure):
    """print_help names every command it claims to document.

    This asked for ``capsys`` and never read it, and then had no oracle at all —
    two flags on one unit. Both come from the same fact: this file's autouse
    ``_mock_infrastructure`` replaces ``console`` with a MagicMock, so nothing
    reaches stdout and capsys is structurally blind here. The honest oracle is
    the mock's own call args, which is what the fixture yields it for.

    The verbs are read off print_help's own COMMANDS block, so a command that is
    implemented and undocumented still passes — this pins the help against
    itself rotting, not against the router.
    """
    print_help()

    printed = " ".join(str(call.args[0]) for call in _mock_infrastructure.print.call_args_list if call.args)

    assert "COMMANDS:" in printed
    for verb in ("dispatch", "email", "inbox", "view", "reply", "close", "sent", "contacts"):
        assert f"[cyan]{verb}[/cyan]" in printed, f"{verb} is missing from the help output"


# ---- print_introspection tests ---------------------------------------


def test_print_introspection_runs(_mock_infrastructure):
    """print_introspection reports the count discover_modules actually returned.

    Had no oracle: it called the function and let "did not raise" stand in for
    "displayed the module list". With an empty discovery the honest claim is
    that it says zero — a version that printed a hardcoded roster, or swallowed
    the count, passed the old shape.
    """
    with patch.object(ai_mail_mod, "discover_modules", return_value=[]):
        print_introspection()

    printed = " ".join(str(call.args[0]) for call in _mock_infrastructure.print.call_args_list if call.args)

    assert "Discovered Modules:[/yellow] 0" in printed, printed


# ---- route_command tests --------------------------------------------


def test_route_known_command_returns_true(fake_module_handled):
    """Known command routed to module returns True (assert result is True)."""
    result = route_command("email", ["@test", "hi"], [fake_module_handled])
    assert result is True


def test_route_unknown_command_returns_false(fake_module):
    """Unknown command not handled by any module returns False (== False)."""
    result = route_command("unknown_command", [], [fake_module])
    assert result is False


def test_route_no_modules():
    """Empty module list returns False for any command."""
    result = route_command("anything", [], [])
    assert result is False


# ---- main() tests ---------------------------------------------------


def test_main_no_args_triggers_introspection(monkeypatch):
    """test_no_args: Running with no args triggers print_introspection."""
    monkeypatch.setattr(sys, "argv", ["ai_mail"])
    with patch.object(ai_mail_mod, "print_introspection") as mock_intro:
        result = main()
    mock_intro.assert_called_once()
    assert result == 0


def test_main_help_flag(monkeypatch):
    """--help flag triggers print_help (help_preempts command routing)."""
    monkeypatch.setattr(sys, "argv", ["ai_mail", "--help"])
    with patch.object(ai_mail_mod, "print_help") as mock_help:
        result = main()
    mock_help.assert_called_once()
    assert result == 0


def test_main_short_help_flag(monkeypatch):
    """'-h' short flag triggers help."""
    monkeypatch.setattr(sys, "argv", ["ai_mail", "-h"])
    with patch.object(ai_mail_mod, "print_help") as mock_help:
        result = main()
    mock_help.assert_called_once()
    assert result == 0


def test_main_help_word(monkeypatch):
    """'help' word triggers print_help."""
    monkeypatch.setattr(sys, "argv", ["ai_mail", "help"])
    with patch.object(ai_mail_mod, "print_help") as mock_help:
        result = main()
    mock_help.assert_called_once()
    assert result == 0


def test_main_unknown_command_returns_error(monkeypatch):
    """Unknown command returns exit code 1 (invalid_command path)."""
    monkeypatch.setattr(sys, "argv", ["ai_mail", "nonexistent_xyz"])
    with patch.object(ai_mail_mod, "discover_modules", return_value=[]):
        result = main()
    assert result == 1


def test_main_version_flag(monkeypatch):
    """--version flag shows version string."""
    monkeypatch.setattr(sys, "argv", ["ai_mail", "--version"])
    result = main()
    assert result == 0


# ---- Output capture with StringIO -----------------------------------


def test_output_capture_with_stringio():
    """Verify StringIO can capture command output for testing."""
    buf = StringIO()
    buf.write("test output")
    assert "test output" in buf.getvalue()


# ---- exit-code honesty ----------------------------------------------
#
# Handlers return True for "I recognised this command", which is NOT the
# same as "it worked". Before the resolve_exit flip, a reply that failed
# validation printed its error and exited 0 — callers' scripts read the
# reply as sent. error() sets the process failure flag; main() must
# translate that into a nonzero exit.


def test_main_routed_but_failed_command_exits_nonzero(monkeypatch):
    """CANARY: a handled-but-failed command must not exit 0."""
    from aipass.cli.apps.modules import error as cli_error

    reached = []

    class FailingModule:
        __name__ = "failing_module"

        @staticmethod
        def handle_command(command, args):
            reached.append(True)
            cli_error("Invalid reply_path: /gone/inbox.json")
            return True

    monkeypatch.setattr(sys, "argv", ["ai_mail", "reply", "abc123", "text"])
    with patch.object(ai_mail_mod, "discover_modules", return_value=[FailingModule]):
        result = main()
    # Must precede the exit-code checks: the identity fence ALSO returns 2, so
    # from the repo root this test passed for months-adjacent minutes without ever
    # reaching its module — a canary singing someone else's note. Proven by probe
    # on 2026-08-21: RESULT=2, MODULE_REACHED=False.
    assert reached, "never reached the module — this asserts the fence's 2, not resolve_exit's"
    assert result != 0, "failed delivery exited 0 — the exit code lied"
    assert result == 2


def test_main_routed_and_succeeded_exits_zero(monkeypatch):
    """A handled command that printed no error still exits 0."""

    class OkModule:
        __name__ = "ok_module"

        @staticmethod
        def handle_command(command, args):
            return True

    monkeypatch.setattr(sys, "argv", ["ai_mail", "inbox"])
    with patch.object(ai_mail_mod, "discover_modules", return_value=[OkModule]):
        result = main()
    assert result == 0


def test_main_resets_failure_flag_between_runs(monkeypatch):
    """A previous command's failure must not leak into this process's exit."""
    from aipass.cli.apps.modules import error as cli_error

    class OkModule:
        __name__ = "ok_module"

        @staticmethod
        def handle_command(command, args):
            return True

    cli_error("stale failure from an earlier command")
    monkeypatch.setattr(sys, "argv", ["ai_mail", "inbox"])
    with patch.object(ai_mail_mod, "discover_modules", return_value=[OkModule]):
        result = main()
    assert result == 0
