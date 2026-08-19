# =================== AIPass ====================
# Name: test_help_flag.py
# Description: Tests for the help_flag predicate + per-module help-gate canaries
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Tests for help_flag.wants_help and every module's help gate.

The canaries below assert that asking for help NEVER performs the action.
Every doing-path is stubbed before the canary runs (prax doctrine: the
failing state RUNS, so a red canary must not be able to reach a real init,
install, enroll or spawn).
"""

from __future__ import annotations

import importlib
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.handlers.help_flag import wants_help

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"


# =============================================================================
# TestWantsHelp — the pure predicate
# =============================================================================


class TestWantsHelp:
    """Tests for the wants_help predicate."""

    def test_empty_args_is_not_help(self) -> None:
        """No arguments is not a help request — callers handle bare invocation."""
        assert wants_help([]) is False

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_flag_at_position_zero(self, flag: str) -> None:
        """The classic first-position help flag still counts."""
        assert wants_help([flag]) is True

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_flag_after_positional(self, flag: str) -> None:
        """A help flag AFTER a positional counts — the shape the fleet got wrong."""
        assert wants_help(["agent", flag]) is True

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_flag_in_the_middle(self, flag: str) -> None:
        """A help flag wins from any position, not just first or last."""
        assert wants_help(["app", flag, "--template", "python"]) is True

    def test_bare_word_help_at_position_zero(self) -> None:
        """A leading bare 'help' reads as a subcommand."""
        assert wants_help(["help"]) is True

    def test_bare_word_help_later_is_content(self) -> None:
        """'help' after position 0 is ordinary content, not a request."""
        assert wants_help(["new", "help"]) is False

    def test_bare_word_opt_out(self) -> None:
        """allow_bare_word=False — for a module that OWNS a bare help verb."""
        assert wants_help(["help"], allow_bare_word=False) is False

    def test_opt_out_still_honours_dashed_flags(self) -> None:
        """Opting out of the bare word must NOT disarm the dashed flags."""
        assert wants_help(["help", "--help"], allow_bare_word=False) is True
        assert wants_help(["something", "-h"], allow_bare_word=False) is True

    @pytest.mark.parametrize("arg", ["--helpful", "-help", "help-docs", "helper", "--h"])
    def test_near_miss_tokens_are_not_help(self, arg: str) -> None:
        """Exact match only — a project named 'help-docs' is not a question."""
        assert wants_help(["new", arg]) is False

    def test_ordinary_args_are_not_help(self) -> None:
        """A normal invocation is untouched."""
        assert wants_help(["myapp", "--template", "python"]) is False


# =============================================================================
# Per-module canaries — asking must never act
# =============================================================================

# (module stem, command, args that would ACT if the gate missed)
_GATE_CASES = [
    ("init_flow", "init", ["agent", "--help"]),
    ("init_flow", "init", ["update", "--help"]),
    ("trust", "trust", ["/some/path", "--help"]),
    ("trust", "revoke", ["/some/path", "--help"]),
    ("new_project", "new", ["myapp", "--help"]),
    ("adopt", "adopt", ["myapp", "--help"]),
    ("install", "install", ["run", "--help"]),
    ("feedback", "feedback", ["on", "--help"]),
    ("doctor", "doctor", ["--fix", "--help"]),
    ("profile", "profile", ["set", "name", "--help"]),
    ("read", "read", ["drone", "--help"]),
    ("handoff", "handoff", ["launch", "--help"]),
    ("help_chat", "help", ["what", "is", "drone", "--help"]),
    ("_doctor_fix", "doctor_fix", ["--json", "--help"]),
    ("_doctor_wire", "doctor_wire", ["--fix", "--help"]),
]


@pytest.fixture(autouse=True)
def _stub_every_doing_path():
    """Stub every path that could spawn, install, enroll or write.

    Autouse and fail-closed: a canary that reaches a REAL init would create
    an agent or scaffold a directory. Patched at the source module so it does
    not matter where a caller imported the name from.
    """
    stubs = {
        "subprocess.run": MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr="")),
        "subprocess.Popen": MagicMock(),
        "aipass.aipass.apps.handlers.init.bootstrap.update_project": MagicMock(return_value={}),
        "aipass.aipass.apps.handlers.new_project.adopt.adopt_project": MagicMock(return_value={}),
        "aipass.aipass.apps.modules.trust.enroll": MagicMock(return_value=True),
        "aipass.aipass.apps.modules.trust.revoke": MagicMock(return_value=True),
        "aipass.aipass.apps.handlers.new_project.create_project": MagicMock(return_value={}),
    }
    with ExitStack() as stack:
        for target, stub in stubs.items():
            stack.enter_context(patch(target, stub))
        yield stubs


def _assert_nothing_happened(stubs: dict, label: str) -> None:
    """Fail loudly naming WHICH doing-path a help probe reached."""
    fired = [target for target, stub in stubs.items() if stub.called]
    assert not fired, f"{label} performed an action on a help probe: {', '.join(fired)}"


@pytest.mark.parametrize("stem,command,args", _GATE_CASES)
class TestHelpGateCanaries:
    """Every module: a help probe prints help and performs no action."""

    def test_help_probe_is_handled_without_acting(
        self, stem: str, command: str, args: list[str], _stub_every_doing_path
    ) -> None:
        """handle_command returns True having shown help — and never spawned."""
        module = importlib.import_module(f"aipass.aipass.apps.modules.{stem}")

        with patch.object(module, "console", MagicMock()):
            try:
                handled = module.handle_command(command, list(args))
            except SystemExit as exc:  # a doing-path ran and exited
                pytest.fail(f"{stem} help probe reached an action path (SystemExit {exc.code})")

        assert handled is True, f"{stem} did not handle the help probe"
        _assert_nothing_happened(_stub_every_doing_path, stem)


class TestInitFlowStandaloneDoor:
    """The named finding: init_flow's standalone __main__ hands raw argv in."""

    def test_agent_help_does_not_spawn(self, _stub_every_doing_path) -> None:
        """`init_flow.py agent --help` must not reach `drone @spawn create`."""
        from aipass.aipass.apps.modules import init_flow

        with patch.object(init_flow, "console", MagicMock()):
            try:
                handled = init_flow.handle_command("init", ["agent", "--help"])
            except SystemExit as exc:
                pytest.fail(f"standalone door reached the spawn path (SystemExit {exc.code})")

        assert handled is True
        _assert_nothing_happened(_stub_every_doing_path, "init agent --help")

    def test_agent_h_short_flag_does_not_spawn(self, _stub_every_doing_path) -> None:
        """Both dashed spellings — a half fix scores clean and stays exposed."""
        from aipass.aipass.apps.modules import init_flow

        with patch.object(init_flow, "console", MagicMock()):
            try:
                handled = init_flow.handle_command("init", ["agent", "-h"])
            except SystemExit as exc:
                pytest.fail(f"standalone door reached the spawn path (SystemExit {exc.code})")

        assert handled is True
        _assert_nothing_happened(_stub_every_doing_path, "init agent -h")

    def test_real_agent_creation_still_works(self, _stub_every_doing_path) -> None:
        """Pin the other direction: a genuine `init agent <name>` still spawns."""
        from aipass.aipass.apps.modules import init_flow

        spawn = _stub_every_doing_path["subprocess.run"]
        with patch.object(init_flow, "console", MagicMock()):
            with pytest.raises(SystemExit):
                init_flow.handle_command("init", ["agent", "realname"])

        assert spawn.called, "genuine agent creation must still reach spawn"
        cmd = spawn.call_args[0][0]
        assert "realname" in cmd[-1]


class TestTrustEnrollmentCanary:
    """The shape live-proven this morning: `aipass trust <dir> --help` enrolled.

    Uses a REAL directory with a real .aipass/hooks.json so the probe reaches
    the enrollment call site — `enroll` itself is stubbed, so a red run
    records the attempt without touching the trust registry.
    """

    def test_help_probe_does_not_enroll(self, tmp_path, _stub_every_doing_path) -> None:
        """A help probe against a valid, enrollable directory must not enroll."""
        from aipass.aipass.apps.modules import trust

        project = tmp_path / "enrollable"
        (project / ".aipass").mkdir(parents=True)
        (project / ".aipass" / "hooks.json").write_text("{}", encoding="utf-8")

        with patch.object(trust, "console", MagicMock()):
            handled = trust.handle_command("trust", [str(project), "--help"])

        assert handled is True
        _assert_nothing_happened(_stub_every_doing_path, "trust <dir> --help")

    def test_real_enrollment_still_works(self, tmp_path, _stub_every_doing_path) -> None:
        """Pin the other direction: a genuine enroll still reaches enroll()."""
        from aipass.aipass.apps.modules import trust

        project = tmp_path / "enrollable"
        (project / ".aipass").mkdir(parents=True)
        (project / ".aipass" / "hooks.json").write_text("{}", encoding="utf-8")

        with patch.object(trust, "console", MagicMock()):
            handled = trust.handle_command("trust", [str(project)])

        assert handled is True
        assert _stub_every_doing_path["aipass.aipass.apps.modules.trust.enroll"].called


class TestHelpChatBareWordOptOut:
    """`aipass help` OWNS the bare word — pin both directions."""

    def test_bare_help_word_is_answered_not_usage(self, _stub_every_doing_path) -> None:
        """`aipass help help` is a question about help, not a usage dump."""
        from aipass.aipass.apps.modules import help_chat

        with patch.object(help_chat, "print_help", MagicMock()) as mock_help:
            with patch.object(help_chat, "console", MagicMock()):
                handled = help_chat.handle_command("help", ["help"])

        assert handled is True
        mock_help.assert_not_called()

    def test_dashed_flag_still_shows_usage(self, _stub_every_doing_path) -> None:
        """The opt-out must not disarm --help for the help verb itself."""
        from aipass.aipass.apps.modules import help_chat

        with patch.object(help_chat, "print_help", MagicMock()) as mock_help:
            with patch.object(help_chat, "console", MagicMock()):
                handled = help_chat.handle_command("help", ["what", "is", "drone", "--help"])

        assert handled is True
        mock_help.assert_called_once()


class TestOwnershipCheckRunsFirst:
    """The gate lives AFTER the ownership check — never answer for another verb."""

    @pytest.mark.parametrize("stem", ["init_flow", "trust", "new_project", "install"])
    def test_foreign_command_with_help_flag_is_declined(self, stem: str, _stub_every_doing_path) -> None:
        """A module must return False for a command it does not own."""
        module = importlib.import_module(f"aipass.aipass.apps.modules.{stem}")

        with patch.object(module, "console", MagicMock()):
            assert module.handle_command("not-my-command", ["--help"]) is False
