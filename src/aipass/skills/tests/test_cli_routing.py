# ===================AIPASS====================
# Name: test_cli_routing.py
# Description: Unit tests for skills.py CLI routing
# Version: 1.1.0
# Created: 2026-03-10
# Modified: 2026-09-27
# Category: skills/tests
# =============================================

"""Tests for apps/skills.py — the entry point's routing, help, introspection and exit codes."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/skills.py parses and carries no unused import
# seedgo: no-test-needed(constant) — the wording of print_help's rows beyond the doors pinned below

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from aipass.skills.apps import skills as entry
from aipass.skills.apps.modules import runner
from aipass.skills.apps.skills import handle_command, print_help, print_introspection


class TestRunExtraArgs:
    """`run <skill> <action> k=v ...` hands the runner a parsed args dict."""

    def _run_with(self, monkeypatch, extra):
        # A recorder stands in for the runner at the edge: the route is the unit.
        seen = {}

        def recorder(name, action=None, args=None):
            seen.update(name=name, action=action, args=args)
            return {"success": True, "output": "", "error": None}

        monkeypatch.setattr(runner, "run_skill", recorder)
        assert handle_command("run", ["some_skill", "act", *extra]) is True
        assert (seen["name"], seen["action"]) == ("some_skill", "act")
        return seen["args"]

    def test_key_value_pairs(self, monkeypatch):
        result = self._run_with(monkeypatch, ["host=localhost", "port=8080"])
        assert result == {"host": "localhost", "port": "8080"}

    def test_positional_args(self, monkeypatch):
        # Mutant killed: positional_idx never incremented (arg1 overwrites arg0).
        result = self._run_with(monkeypatch, ["foo", "bar"])
        assert result == {"arg0": "foo", "arg1": "bar"}

    def test_mixed_args(self, monkeypatch):
        result = self._run_with(monkeypatch, ["foo", "key=val", "bar"])
        assert result == {"arg0": "foo", "key": "val", "arg1": "bar"}

    def test_empty_args(self, monkeypatch):
        result = self._run_with(monkeypatch, [])
        assert result == {}

    def test_value_with_equals_sign(self, monkeypatch):
        """key=value where value itself contains '=' (mutant killed: split("=") unbounded)."""
        result = self._run_with(monkeypatch, ["query=a=b"])
        assert result == {"query": "a=b"}


class TestHandleCommand:
    def test_none_command_shows_introspection(self, capsys):
        # Mutant killed: None routed to print_help() instead of print_introspection().
        result = handle_command(None)
        assert result is True
        out = capsys.readouterr().out
        assert "skills Entry Point" in out
        assert "Usage:" not in out

    def test_help_command(self, capsys):
        # Mutant killed: the help branch calls print_introspection() instead of print_help().
        result = handle_command("--help")
        assert result is True
        assert "drone @skills <command> [args]" in capsys.readouterr().out

    def test_help_alias(self, capsys):
        result = handle_command("help")
        assert result is True
        assert "drone @skills <command> [args]" in capsys.readouterr().out

    def test_h_flag(self, capsys):
        result = handle_command("-h")
        assert result is True
        assert "drone @skills <command> [args]" in capsys.readouterr().out

    def test_version_command(self, capsys):
        result = handle_command("--version")
        assert result is True
        # One version string: the printed line is the module's own constant,
        # never a literal that drifts from the file header.
        assert capsys.readouterr().out.strip() == f"SKILLS v{entry.VERSION}"

    def test_version_short_flag(self, capsys):
        # Mutant killed: -V split off to print a bare VERSION.
        result = handle_command("-V")
        assert result is True
        assert capsys.readouterr().out.strip() == f"SKILLS v{entry.VERSION}"

    def test_unknown_command_returns_false(self):
        result = handle_command("bogus_command_xyz")
        assert result is False

    def test_list_command(self, capsys):
        # Mutant killed: `if not skills` inverted, so list prints "No skills found." and returns True.
        result = handle_command("list")
        assert result is True
        out = capsys.readouterr().out
        assert "skill(s):" in out
        assert "github" in out

    def test_info_missing_args_returns_false(self):
        result = handle_command("info")
        assert result is False

    def test_info_with_valid_skill(self, capsys):
        # Mutant killed: the info branch returns True without calling _cmd_info.
        result = handle_command("info", ["github"])
        assert result is True
        assert "Skill: github" in capsys.readouterr().out

    def test_run_missing_args_returns_false(self):
        result = handle_command("run")
        assert result is False

    def test_run_with_valid_skill(self, capsys):
        # Mutant killed: the run branch returns True without calling _cmd_run.
        result = handle_command("run", ["system_status", "disk"])
        assert result is True
        assert "Disk Usage (" in capsys.readouterr().out

    def test_validate_missing_args_returns_false(self):
        result = handle_command("validate")
        assert result is False

    def test_validate_with_valid_skill(self, capsys):
        # Mutant killed: the validate branch returns True without calling _cmd_validate.
        result = handle_command("validate", ["github"])
        assert result is True
        assert "Skill 'github' - all requirements met." in capsys.readouterr().out

    def test_create_missing_args_returns_false(self):
        result = handle_command("create")
        assert result is False

    def test_create_help_flag_returns_true(self, capsys):
        """create --help shows help instead of treating --help as a skill name."""
        # Mutant killed: the create help guard prints print_help() instead of the create page.
        result = handle_command("create", ["--help"])
        assert result is True
        assert "Skills Create - Scaffold a new skill from a template" in capsys.readouterr().out

    def test_create_help_flag_shows_usage(self, capsys):
        """create --help prints usage text."""
        handle_command("create", ["--help"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert "create" in captured.out.lower()

    def test_create_h_flag_returns_true(self, capsys):
        """create -h shows help."""
        result = handle_command("create", ["-h"])
        assert result is True
        assert "Skills Create - Scaffold a new skill from a template" in capsys.readouterr().out

    def test_create_help_word_returns_true(self, capsys):
        """create help shows help."""
        result = handle_command("create", ["help"])
        assert result is True
        assert "Skills Create - Scaffold a new skill from a template" in capsys.readouterr().out


# ===================================================================
# Missing coverage: no_args, print_help, print_introspection, output_capture
# ===================================================================


class TestNoArgs:
    """Test no_args behavior -- None command triggers introspection."""

    def test_no_args_triggers_introspection(self, capsys):
        """no_args_triggers: calling with None produces introspection output."""
        handle_command(None)
        captured = capsys.readouterr()
        # The old either/or passed on either half; None routes to
        # print_introspection, so pin the banner that proves it did.
        assert "skills Entry Point" in captured.out
        assert "Connected Modules:" in captured.out


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_produces_output(self, capsys):
        """print_help: calling --help produces help text."""
        print_help()
        captured = capsys.readouterr()
        # Both halves of the old `or` were about the same output, so it could
        # not fail. print_help emits both blocks - pin both.
        assert "Usage:" in captured.out
        assert "Commands:" in captured.out
        assert "drone @skills <command> [args]" in captured.out
        # Doors the dispatcher answers that the page did not name until 2026-09-15:
        # a skill's own page, the create flags, and the two --help aliases.
        assert "run <name> --help" in captured.out
        assert "create <name> --help" in captured.out
        assert "--help, -h, help" in captured.out

    def test_print_help_via_command(self, capsys):
        """print_help: handle_command('--help') produces output."""
        handle_command("--help")
        captured = capsys.readouterr()
        assert len(captured.out) > 0


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_print_introspection_produces_output(self, capsys):
        """print_introspection: shows module info."""
        print_introspection()
        captured = capsys.readouterr()
        assert "skills Entry Point" in captured.out
        assert "Run 'drone @skills --help' for usage information" in captured.out

    def test_print_introspection_lists_every_module_on_disk(self, capsys):
        """print_introspection: lists each apps/modules/*.py with its header Description."""
        modules_dir = Path(__file__).resolve().parent.parent / "apps" / "modules"
        print_introspection()
        captured = capsys.readouterr()
        assert "modules/" in captured.out
        on_disk = sorted(p for p in modules_dir.glob("*.py") if p.name != "__init__.py")
        assert len(on_disk) > 0, "no modules found on disk - the oracle would be vacuous"
        for path in on_disk:
            description = next(
                line.split(":", 1)[1].strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("# Description:")
            )
            assert f"{path.name} ({description})" in captured.out, f"introspection does not list {path.name}"
        assert "__init__.py" not in captured.out

    def test_print_introspection_derives_from_the_directory(self, tmp_path, capsys):
        """print_introspection: the listing follows the directory, not a hand-kept list."""
        (tmp_path / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "widget.py").write_text("# Description: Spin widgets\n", encoding="utf-8")
        (tmp_path / "bare.py").write_text('"""No header here."""\n', encoding="utf-8")
        print_introspection(modules_dir=tmp_path)
        captured = capsys.readouterr()
        assert "widget.py (Spin widgets)" in captured.out
        assert "- bare.py\n" in captured.out
        assert "__init__.py" not in captured.out
        assert "discovery.py" not in captured.out


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
        # The banner is built from skills.VERSION; the old `or` passed on either
        # half of it, so a half-broken version line read green. Pinned to the
        # constant, which is also this file's header version.
        assert captured.out.strip() == f"SKILLS v{entry.VERSION}"
        assert entry.VERSION == "1.1.1"

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
            encoding="utf-8",
            timeout=120,
        )

    def test_bare_invocation_exits_zero_with_introspection(self):
        """Bare `drone @skills` is the live self-map (mutant killed: __main__ routes no args to --help)."""
        result = self._run()
        assert result.returncode == 0
        assert "skills Entry Point" in result.stdout

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
