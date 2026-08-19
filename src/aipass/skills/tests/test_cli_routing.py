# ===================AIPASS====================
# META DATA HEADER
# Name: test_cli_routing.py - Unit tests for skills.py CLI routing
# Date: 2026-03-10
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills entry point CLI routing."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

skills_root = Path(__file__).resolve().parent.parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))

from aipass.skills.apps.skills import handle_command, _parse_extra_args  # noqa: E402


class TestParseExtraArgs:
    def test_key_value_pairs(self):
        result = _parse_extra_args(["host=localhost", "port=8080"])
        assert result == {"host": "localhost", "port": "8080"}

    def test_positional_args(self):
        result = _parse_extra_args(["foo", "bar"])
        assert result == {"arg0": "foo", "arg1": "bar"}

    def test_mixed_args(self):
        result = _parse_extra_args(["foo", "key=val", "bar"])
        assert result == {"arg0": "foo", "key": "val", "arg1": "bar"}

    def test_empty_args(self):
        result = _parse_extra_args([])
        assert result == {}

    def test_value_with_equals_sign(self):
        """key=value where value itself contains '='."""
        result = _parse_extra_args(["query=a=b"])
        assert result == {"query": "a=b"}


class TestHandleCommand:
    def test_none_command_shows_introspection(self):
        result = handle_command(None)
        assert result is True

    def test_help_command(self):
        result = handle_command("--help")
        assert result is True

    def test_help_alias(self):
        result = handle_command("help")
        assert result is True

    def test_h_flag(self):
        result = handle_command("-h")
        assert result is True

    def test_version_command(self):
        result = handle_command("--version")
        assert result is True

    def test_version_short_flag(self):
        result = handle_command("-V")
        assert result is True

    def test_unknown_command_returns_false(self):
        result = handle_command("bogus_command_xyz")
        assert result is False

    def test_list_command(self):
        result = handle_command("list")
        assert result is True

    def test_info_missing_args_returns_false(self):
        result = handle_command("info")
        assert result is False

    def test_info_with_valid_skill(self):
        result = handle_command("info", ["github"])
        assert result is True

    def test_run_missing_args_returns_false(self):
        result = handle_command("run")
        assert result is False

    def test_run_with_valid_skill(self):
        result = handle_command("run", ["system_status", "disk"])
        assert result is True

    def test_validate_missing_args_returns_false(self):
        result = handle_command("validate")
        assert result is False

    def test_validate_with_valid_skill(self):
        result = handle_command("validate", ["github"])
        assert result is True

    def test_create_missing_args_returns_false(self):
        result = handle_command("create")
        assert result is False

    def test_create_help_flag_returns_true(self):
        """create --help shows help instead of treating --help as a skill name."""
        result = handle_command("create", ["--help"])
        assert result is True

    def test_create_help_flag_shows_usage(self, capsys):
        """create --help prints usage text."""
        handle_command("create", ["--help"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "create" in captured.out.lower()

    def test_create_h_flag_returns_true(self):
        """create -h shows help."""
        result = handle_command("create", ["-h"])
        assert result is True

    def test_create_help_word_returns_true(self):
        """create help shows help."""
        result = handle_command("create", ["help"])
        assert result is True


# ===================================================================
# Missing coverage: no_args, print_help, print_introspection, output_capture
# ===================================================================


class TestNoArgs:
    """Test no_args behavior -- None command triggers introspection."""

    def test_no_args_returns_true(self):
        """no_args: handle_command(None) returns True."""
        result = handle_command(None)
        assert result is True

    def test_no_args_triggers_introspection(self, capsys):
        """no_args_triggers: calling with None produces introspection output."""
        handle_command(None)
        captured = capsys.readouterr()
        assert "skills" in captured.out.lower() or "Entry Point" in captured.out


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_produces_output(self, capsys):
        """print_help: calling --help produces help text."""
        from aipass.skills.apps.skills import print_help

        print_help()
        captured = capsys.readouterr()
        assert "Usage" in captured.out or "Commands" in captured.out

    def test_print_help_via_command(self, capsys):
        """print_help: handle_command('--help') produces output."""
        handle_command("--help")
        captured = capsys.readouterr()
        assert len(captured.out) > 0


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_print_introspection_produces_output(self, capsys):
        """print_introspection: shows module info."""
        from aipass.skills.apps.skills import print_introspection

        print_introspection()
        captured = capsys.readouterr()
        assert "Entry Point" in captured.out or "skills" in captured.out.lower()

    def test_print_introspection_lists_modules(self, capsys):
        """print_introspection: lists connected modules."""
        from aipass.skills.apps.skills import print_introspection

        print_introspection()
        captured = capsys.readouterr()
        assert "modules/" in captured.out or "discovery" in captured.out.lower()


class TestOutputCapture:
    """Tests using capsys for output_capture verification."""

    def test_output_capture_help_command(self, capsys):
        """output_capture: --help produces non-empty stdout."""
        handle_command("--help")
        captured = capsys.readouterr()
        assert captured.out != ""

    def test_output_capture_version_command(self, capsys):
        """output_capture: --version produces version string."""
        handle_command("--version")
        captured = capsys.readouterr()
        assert "SKILLS" in captured.out or "1.0.0" in captured.out

    def test_output_capture_unknown_command(self, capsys):
        """output_capture: unknown command names itself and points at help."""
        handle_command("bogus_xyz")
        captured = capsys.readouterr()
        # The old assertion ended in `or len(captured.out) > 0`, which passes on
        # any output at all — it could not fail. Pin the actual contract.
        assert "Unknown command" in captured.out
        assert "bogus_xyz" in captured.out
        assert "--help" in captured.out


class TestExitCodes:
    """The process exit code is the only failure signal a caller can script on.

    drone runs a branch command as a subprocess and propagates its return code,
    so a discarded handle_command() result made every failure exit 0.
    """

    def _run(self, *args):
        entry = Path(__file__).resolve().parent.parent / "apps" / "skills.py"
        return subprocess.run(
            [sys.executable, str(entry), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_success_exits_zero(self):
        assert self._run("list").returncode == 0

    def test_help_exits_zero(self):
        assert self._run("--help").returncode == 0

    def test_unknown_skill_exits_nonzero(self):
        result = self._run("info", "definitely_not_a_skill_xyz")
        assert result.returncode != 0

    def test_unknown_command_exits_nonzero(self):
        assert self._run("bogus_command_xyz").returncode != 0

    def test_missing_required_argument_exits_nonzero(self):
        assert self._run("info").returncode != 0

    def test_failed_validate_exits_nonzero(self):
        """`drone @skills validate x && next` must not run `next` on failure."""
        assert self._run("validate", "definitely_not_a_skill_xyz").returncode != 0


class TestRunHelpDoesNotDispatch:
    """`run <skill> --help` must document the skill, not dispatch "--help".

    branch_health and inbox_check treat an unrecognised action as a branch name,
    so the old routing answered `run branch_health --help` with
    "Branch '--help' not found" instead of help.
    """

    def test_run_help_is_not_passed_as_an_action(self):
        with patch("aipass.skills.apps.skills._cmd_run") as mock_run:
            with patch("aipass.skills.apps.skills._cmd_info", return_value=True) as mock_info:
                handle_command("run", ["telegram", "--help"])
        mock_run.assert_not_called()
        mock_info.assert_called_once_with("telegram")

    def test_run_h_short_flag_also_documents(self):
        with patch("aipass.skills.apps.skills._cmd_run") as mock_run:
            with patch("aipass.skills.apps.skills._cmd_info", return_value=True):
                handle_command("run", ["telegram", "-h"])
        mock_run.assert_not_called()

    def test_real_action_still_dispatches(self):
        """The guard must not swallow legitimate actions."""
        with patch("aipass.skills.apps.skills._cmd_run", return_value=True) as mock_run:
            handle_command("run", ["telegram", "status"])
        mock_run.assert_called_once()
        assert mock_run.call_args[0][1] == "status"
