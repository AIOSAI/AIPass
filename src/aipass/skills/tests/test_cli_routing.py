# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Unit tests for skills.py CLI routing
# Version: 1.2.0
# Created: 2026-03-10
# Modified: 2026-10-24
# Category: skills/tests
# =============================================

"""Tests for apps/skills.py — the entry point's routing, help, introspection and exit codes."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/skills.py parses and carries no unused import
# seedgo: no-test-needed(constant) — the wording of print_help's rows beyond the doors pinned below

import subprocess
import sys
from pathlib import Path

import pytest

from aipass.skills.apps import skills as entry
from aipass.skills.apps.modules import runner
from aipass.skills.apps.modules.switch import read_state
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


class TestNoArgs:
    """Test no_args behavior -- None command triggers introspection."""

    def test_no_args_triggers_introspection(self, capsys):
        """no_args_triggers: calling with None produces introspection output."""
        handle_command(None)
        captured = capsys.readouterr()
        assert "skills Entry Point" in captured.out
        assert "Connected Modules:" in captured.out


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_produces_output(self, capsys):
        """print_help: calling --help produces help text."""
        print_help()
        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert "Commands:" in captured.out
        assert "drone @skills <command> [args]" in captured.out
        # Every door the dispatcher answers must be named on the page.
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
        on_disk = sorted(p for p in modules_dir.glob("*.py") if p.name != "__init__.py" and p.stem.isidentifier())
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
        (tmp_path / "old(disabled).py").write_text("# Description: Parked door\n", encoding="utf-8")
        print_introspection(modules_dir=tmp_path)
        captured = capsys.readouterr()
        assert "widget.py (Spin widgets)" in captured.out
        assert "- bare.py\n" in captured.out
        assert "__init__.py" not in captured.out
        assert "old(disabled).py" not in captured.out
        assert "discovery.py" not in captured.out


class TestOutputCapture:
    """Tests using capsys for output_capture verification."""

    def test_output_capture_help_command(self, capsys):
        """output_capture: --help produces non-empty stdout."""
        handle_command("--help")
        captured = capsys.readouterr()
        assert captured.out != ""

    def test_version_prints_the_version_the_file_header_declares(self, capsys):
        # Pins a shipped drift: --version printed 1.1.1 while the header said 1.1.3.
        header = Path(entry.__file__).read_text(encoding="utf-8")
        declared = next(line.split(":", 1)[1].strip() for line in header.splitlines() if line.startswith("# Version:"))
        handle_command("--version")
        assert capsys.readouterr().out.strip() == f"SKILLS v{declared}"

    def test_output_capture_unknown_command(self, capsys):
        """output_capture: unknown command names itself and points at help."""
        handle_command("bogus_xyz")
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out
        assert "bogus_xyz" in captured.out
        assert "--help" in captured.out


class TestExitCodes:
    """The exit code is the only failure signal a caller can script on (drone propagates it)."""

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
    """`run <skill> --help` documents the skill; it never dispatches "--help" as an action."""

    @pytest.fixture
    def dispatched(self, monkeypatch):
        calls = []

        def recorder(name, action=None, args=None):
            calls.append((name, action))
            return {"success": True, "output": "", "error": None}

        monkeypatch.setattr(runner, "run_skill", recorder)
        return calls

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_a_help_flag_prints_the_skill_md_and_dispatches_nothing(self, capsys, dispatched, flag):
        assert handle_command("run", ["github", flag]) is True
        assert "Skill: github" in capsys.readouterr().out
        assert dispatched == []

    def test_a_real_action_still_dispatches(self, dispatched):
        assert handle_command("run", ["github", "status"]) is True
        assert dispatched == [("github", "status")]

    def test_the_bare_word_help_is_dispatched_as_an_action(self, capsys, dispatched):
        # Pins a shipped defect: drone_commands publishes "help" and the entry showed SKILL.md instead.
        assert handle_command("run", ["drone_commands", "help", "module=flow"]) is True
        assert dispatched == [("drone_commands", "help")]
        assert "Skill: drone_commands" not in capsys.readouterr().out


class TestSkillOutputIsPrintedVerbatim:
    """A skill's output is its own text: Rich must neither eat nor choke on its brackets."""

    def test_bracketed_words_and_a_stray_closing_tag_reach_stdout(self, capsys, monkeypatch):
        # Pins a shipped defect: "[opened]" vanished and "[/b]" raised MarkupError.
        output = "[opened] from @devpulse\nclosing [/b] tag"
        monkeypatch.setattr(
            runner, "run_skill", lambda name, action=None, args=None: {"success": True, "output": output, "error": None}
        )
        assert handle_command("run", ["inbox_check", "skills"]) is True
        assert capsys.readouterr().out == "  [opened] from @devpulse\n  closing [/b] tag\n"


class TestSwitchVerbsHelpWritesNothing:
    """`on`, `off` and `switch` take a help flag as a request for usage, never as a skill name to record."""

    @pytest.mark.parametrize("verb", ["on", "off", "switch"])
    @pytest.mark.parametrize("flag", ["--help", "-h", "help"])
    def test_a_help_flag_prints_the_switch_usage_and_records_no_skill(self, capsys, verb, flag):
        assert handle_command(verb, [flag]) is True
        assert "Skills Switch - Disconnect and reconnect a skill" in capsys.readouterr().out
        assert read_state() == {}

    def test_a_bare_switch_lists_every_skill(self, capsys):
        # The module's old copy printed its introspection here instead of the status.
        assert handle_command("switch", []) is True
        out = capsys.readouterr().out
        assert "github" in out
        assert "switch Module" not in out

    @pytest.mark.parametrize("verb", ["info", "run", "create", "validate", "on", "off"])
    def test_a_verb_missing_its_skill_name_shows_the_module_map_and_fails(self, capsys, verb):
        assert handle_command(verb, []) is False
        out, err = capsys.readouterr()
        assert "Module" in out
        assert "skill name required" in err

    def test_a_skill_name_is_still_recorded(self, capsys):
        assert handle_command("off", ["github"]) is True
        assert read_state()["github"]["enabled"] is False
