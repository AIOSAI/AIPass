# ===================AIPASS====================
# META DATA HEADER
# Name: test_cli_routing.py - Unit tests for skills.py CLI routing
# Date: 2026-03-10
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills entry point CLI routing."""

import sys
from pathlib import Path
skills_root = Path(__file__).resolve().parent.parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))

from skills.apps.skills import handle_command, _parse_extra_args


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
        from skills.apps.skills import print_help
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
        from skills.apps.skills import print_introspection
        print_introspection()
        captured = capsys.readouterr()
        assert "Entry Point" in captured.out or "skills" in captured.out.lower()

    def test_print_introspection_lists_modules(self, capsys):
        """print_introspection: lists connected modules."""
        from skills.apps.skills import print_introspection
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
        """output_capture: unknown command produces output."""
        handle_command("bogus_xyz")
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out or "unknown" in captured.out.lower() or len(captured.out) > 0
