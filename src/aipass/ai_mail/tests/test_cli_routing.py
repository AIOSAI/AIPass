# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for CLI routing and help display
# Version: 1.1.0
# Created: 2026-03-27
# Modified: 2026-10-17
# =============================================

"""Tests for apps/ai_mail.py's CLI routing: print_help, print_introspection, route_command, main."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the "-V" version alias and the exact "AI_MAIL v1.0.0" banner text

import json
import os
import signal
import subprocess
import sys

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.ai_mail as ai_mail_mod
import aipass.ai_mail.apps.modules as ai_mail_modules
from aipass.ai_mail.apps.ai_mail import (
    print_help,
    print_introspection,
    route_command,
    main,
)
from aipass.cli.apps.modules import error as cli_error


@pytest.fixture(autouse=True)
def _caller_stands_in_a_branch(tmp_path, monkeypatch):
    """Give every test in this file a resolvable caller identity, built from nothing.

    main() refuses an unresolved caller; the seat is built in tmp_path, never the live
    registry (CI has none). The fence is exercised, not stubbed.
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
    """Replace error() and the logger, so no failure flag or live log is written.

    The console stays real: its output goes to stdout, where capsys reads it.
    """
    monkeypatch.setattr(ai_mail_mod, "error", MagicMock())
    monkeypatch.setattr(ai_mail_mod, "logger", MagicMock())


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


def test_print_help_outputs(capsys: pytest.CaptureFixture[str]):
    """print_help names every command it claims to document.

    The verbs come from print_help's own COMMANDS block: this pins the help against
    itself rotting, not against the router.
    """
    print_help()

    lines = capsys.readouterr().out.splitlines()

    assert "COMMANDS:" in lines
    for verb in ("dispatch", "email", "inbox", "view", "reply", "close", "sent", "contacts"):
        assert any(line.startswith(f"  {verb} ") for line in lines), f"{verb} is missing from the help output"


def test_print_introspection_runs(capsys: pytest.CaptureFixture[str]):
    """print_introspection reports the count discover_modules actually returned."""
    with patch.object(ai_mail_mod, "discover_modules", return_value=[]):
        print_introspection()

    lines = capsys.readouterr().out.splitlines()

    assert "Discovered Modules: 0" in lines, lines


def test_discover_modules_finds_the_real_command_modules(monkeypatch):
    """The real discovery returns the modules that hold handle_command.

    MODULES_DIR is pinned because it derives from __file__, which moves when the
    module loads from elsewhere (a mutant copy, a zipped install).
    """
    monkeypatch.setattr(ai_mail_mod, "MODULES_DIR", Path(ai_mail_modules.__file__).parent)

    found = {module.__name__.rsplit(".", 1)[-1] for module in ai_mail_mod.discover_modules()}

    assert {"email", "dispatch"} <= found, found


def test_route_known_command_returns_true(fake_module_handled):
    """Known command routed to module returns True (assert result is True)."""
    result = route_command("email", ["@test", "hi"], [fake_module_handled])
    assert result is True
    fake_module_handled.handle_command.assert_called_once_with("email", ["@test", "hi"])


def test_route_unknown_command_returns_false(fake_module):
    """Unknown command not handled by any module returns False (== False)."""
    result = route_command("unknown_command", [], [fake_module])
    assert result is False


def test_route_no_modules():
    """Empty module list returns False for any command."""
    result = route_command("anything", [], [])
    assert result is False


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


# Handlers return True for "recognised", not "worked": main() must turn error()'s
# process failure flag into a nonzero exit.


def test_main_routed_but_failed_command_exits_nonzero(monkeypatch):
    """CANARY: a handled-but-failed command must not exit 0."""
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
    # Must precede the exit-code checks: the identity fence also returns 2.
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


# SIGPIPE belongs to the program, never to an importer. Each runs in a fresh interpreter: this process imported the module at collection.


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGPIPE")
def test_importing_ai_mail_leaves_sigpipe_as_it_was():
    probe = (
        "import signal\n"
        "before = repr(signal.getsignal(signal.SIGPIPE))\n"
        "import aipass.ai_mail.apps.ai_mail\n"
        "after = repr(signal.getsignal(signal.SIGPIPE))\n"
        "print(before == after, before, after)\n"
    )

    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, encoding="utf-8", timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("True "), result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGPIPE")
def test_ai_mail_run_as_a_program_ends_quietly_on_a_closed_pipe():
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "aipass.ai_mail.apps.ai_mail", "--version"],
            stdout=write_end,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            timeout=60,
        )
    finally:
        os.close(write_end)

    assert result.returncode < 0, result.stderr
    assert signal.Signals(-result.returncode).name == "SIGPIPE"
    assert "BrokenPipeError" not in result.stderr
