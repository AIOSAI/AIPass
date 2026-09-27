# =================== META ====================
# Name: test_checkers_batch6.py
# Description: Unit tests for checker sub-functions in architecture, cli, cli_flags, documentation
# Version: 1.0.2
# Created: 2026-04-25
# Modified: 2026-09-27
# =============================================

"""Tests for the sub-functions of apps/handlers/aipass_standards/architecture_check.py and 3 siblings."""

# Covers architecture, cli, cli_flags and documentation checker sub-functions,
# called directly rather than through check_module.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the four checker modules under test parse and import

from typing import List

import pytest
from unittest.mock import MagicMock

from aipass.seedgo.apps.handlers.aipass_standards import architecture_check
from aipass.seedgo.apps.handlers.aipass_standards import cli_check
from aipass.seedgo.apps.handlers.aipass_standards import cli_flags_check
from aipass.seedgo.apps.handlers.aipass_standards import documentation_check
from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here.

    The bypass tests call the real is_bypassed, which appends to the
    repo-tracked seedgo_json/utils_log.json via the json_handler global in
    its OWN module -- xdist workers racing on that shared file corrupt it
    (JSONDecodeError: Extra data). sys.modules patching never reaches a
    function's globals, so the pin must land on the utils module object.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


# ===========================================================================
# 1. architecture_check sub-functions
# ===========================================================================


# -- check_layer_location ---------------------------------------------------


class TestCheckLayerLocation:
    """Tests for check_layer_location."""

    def test_entry_point_passes(self, tmp_path):
        """Entry point path is recognised as the entry-point layer."""
        result = architecture_check.check_layer_location(
            str(tmp_path / "branch" / "apps" / "branch.py"), True, False, False
        )
        assert result["passed"] is True
        assert "Entry point" in result["message"]

    def test_module_layer_passes(self, tmp_path):
        """Module path is recognised as the module layer."""
        result = architecture_check.check_layer_location(
            str(tmp_path / "branch" / "apps" / "modules" / "foo.py"), False, True, False
        )
        assert result["passed"] is True
        assert "Module layer" in result["message"]

    def test_handler_layer_passes(self, tmp_path):
        """Handler path is recognised as the handler layer."""
        result = architecture_check.check_layer_location(
            str(tmp_path / "branch" / "apps" / "handlers" / "json" / "j.py"), False, False, True
        )
        assert result["passed"] is True
        assert "Handler layer" in result["message"]

    def test_outside_3_layer_fails(self, tmp_path):
        """Path outside the 3-layer structure fails."""
        result = architecture_check.check_layer_location(
            str(tmp_path / "branch" / "random" / "foo.py"), False, False, False
        )
        assert result["passed"] is False
        assert "not in standard 3-layer" in result["message"]


# -- check_file_size (architecture) -----------------------------------------


class TestArchCheckFileSize:
    """Tests for architecture_check.check_file_size."""

    def test_small_file_passes(self):
        """Under 300 lines is perfect."""
        lines: list[str] = ["x"] * 100
        result = architecture_check.check_file_size(lines, "small.py")
        assert result["passed"] is True
        assert "perfect" in result["message"]

    def test_medium_file_passes(self):
        """300-500 lines is good."""
        lines: list[str] = ["x"] * 350
        result = architecture_check.check_file_size(lines, "medium.py")
        assert result["passed"] is True
        assert "good" in result["message"]

    def test_heavy_file_passes(self):
        """500-700 lines is acceptable but heavy."""
        lines: list[str] = ["x"] * 600
        result = architecture_check.check_file_size(lines, "heavy.py")
        assert result["passed"] is True
        assert "getting heavy" in result["message"]

    def test_advisory_file_passes(self):
        """700-1500 lines is advisory — passes but warns."""
        lines: list[str] = ["x"] * 750
        result = architecture_check.check_file_size(lines, "big.py")
        assert result["passed"] is True
        assert "advisory" in result["message"]

    def test_oversized_file_fails(self):
        """1500+ lines hard-fails the size check."""
        lines: list[str] = ["x"] * 1600
        result = architecture_check.check_file_size(lines, "huge.py")
        assert result["passed"] is False
        assert "must split" in result["message"]


# -- check_handler_independence (architecture) --------------------------------


class TestArchHandlerIndependence:
    """Tests for architecture_check.check_handler_independence."""

    def test_clean_handler_passes(self, tmp_path):
        """Handler without parent module imports passes."""
        lines: list[str] = [
            "from aipass.prax import logger",
            "from aipass.cli.apps.modules import display",
            "",
            "def do_work():",
            "    return True",
        ]
        result = architecture_check.check_handler_independence(
            lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_parent_module_import_fails(self, tmp_path):
        """Handler importing from its parent branch module fails."""
        lines: list[str] = [
            "from seedgo.apps.modules.audit import run_audit",
            "",
            "def do_work():",
            "    return True",
        ]
        result = architecture_check.check_handler_independence(
            lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py")
        )
        assert result is not None
        assert result["passed"] is False
        assert "parent module" in result["message"]

    def test_allowed_service_imports_pass(self, tmp_path):
        """Prax and CLI service imports are allowed in handlers."""
        lines: list[str] = [
            "from prax.apps.modules.logger import info",
            "from cli.apps.modules.display import header",
        ]
        result = architecture_check.check_handler_independence(
            lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_import_in_docstring_ignored(self, tmp_path):
        """Imports inside docstrings are not flagged."""
        lines: list[str] = [
            '"""',
            "from seedgo.apps.modules.audit import run_audit",
            '"""',
            "def do_work():",
            "    return True",
        ]
        result = architecture_check.check_handler_independence(
            lines, str(tmp_path / "seedgo" / "apps" / "handlers" / "json" / "j.py")
        )
        assert result is not None
        assert result["passed"] is True


# -- check_domain_organization -----------------------------------------------


class TestCheckDomainOrganization:
    """Tests for check_domain_organization."""

    def test_domain_based_passes(self, tmp_path):
        """Handler in a domain-named folder passes."""
        result = architecture_check.check_domain_organization(
            str(tmp_path / "branch" / "apps" / "handlers" / "json" / "json_handler.py")
        )
        assert result is not None
        assert result["passed"] is True
        assert "json" in result["message"]

    def test_technical_name_fails(self, tmp_path):
        """Handler in a technical-named folder (utils) fails."""
        result = architecture_check.check_domain_organization(
            str(tmp_path / "branch" / "apps" / "handlers" / "utils" / "helper.py")
        )
        assert result is not None
        assert result["passed"] is False
        assert "Technical organization" in result["message"]

    def test_helpers_name_fails(self, tmp_path):
        """Handler in a helpers/ folder fails."""
        result = architecture_check.check_domain_organization(
            str(tmp_path / "branch" / "apps" / "handlers" / "helpers" / "tool.py")
        )
        assert result is not None
        assert result["passed"] is False

    def test_no_handler_domain_detected(self, tmp_path):
        """Path ending at handlers/ with no subdirectory fails detection."""
        result = architecture_check.check_domain_organization(str(tmp_path / "branch" / "apps" / "handlers"))
        assert result is not None
        assert result["passed"] is False
        assert "Could not detect" in result["message"]


# -- check_template_baseline -------------------------------------------------


class TestCheckTemplateBaseline:
    """Tests for check_template_baseline."""

    def test_no_branch_path_detected(self, tmp_path):
        """Path without apps/ cannot resolve a branch."""
        result = architecture_check.check_template_baseline(str(tmp_path / "random" / "file.py"))
        assert len(result) >= 1
        assert result[0]["passed"] is False
        assert "Could not detect branch path" in result[0]["message"]

    def test_missing_passport_skips(self, tmp_path):
        """Branch without passport.json skips template baseline (gitignored)."""
        apps_dir = tmp_path / "mybranch" / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text('"""Entry."""\n', encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        assert result == []

    def test_passport_without_citizen_class(self, tmp_path):
        """Branch with passport.json but no citizen_class fails."""
        apps_dir = tmp_path / "mybranch" / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text('"""Entry."""\n', encoding="utf-8")
        trinity = tmp_path / "mybranch" / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text('{"identity": {}}', encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        assert len(result) >= 1
        assert result[0]["passed"] is False
        assert "citizen_class" in result[0]["message"]

    def test_trinity_files_are_not_scored(self, tmp_path, monkeypatch):
        """Files under .trinity/ are local-only memory — never scored.

        .trinity/ is permanently gitignored, so requiring its contents in a
        clone-facing structural score asks a branch to ship what it must not.
        """
        templates = tmp_path / "templates"
        template = templates / "citizen"
        (template / ".trinity").mkdir(parents=True)
        (template / ".trinity" / "README.md").write_text("memory guide\n", encoding="utf-8")
        (template / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        (template / "apps").mkdir()
        (template / "apps" / "{{BRANCH}}.py").write_text('"""Entry."""\n', encoding="utf-8")
        monkeypatch.setattr(architecture_check, "SPAWN_TEMPLATES_DIR", templates)

        branch = tmp_path / "mybranch"
        apps_dir = branch / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text('"""Entry."""\n', encoding="utf-8")
        trinity = branch / ".trinity"
        trinity.mkdir()
        # Branch deliberately has NO .trinity/README.md — it must not be penalised.
        (trinity / "passport.json").write_text('{"identity": {"citizen_class": "specialist"}}', encoding="utf-8")

        result = architecture_check.check_template_baseline(str(entry))
        names = [c["name"] for c in result]

        assert not any(".trinity/README.md" in n for n in names)
        assert not any(".trinity/passport.json" in n for n in names)
        assert all(c["passed"] for c in result), [c for c in result if not c["passed"]]

    def test_skipped_baseline_announced_on_info_channel(self, tmp_path):
        """A baseline that cannot run says so — it never vanishes silently."""
        branch = tmp_path / "mybranch"
        (branch / "apps").mkdir(parents=True)

        lines = architecture_check.check_branch_info(str(branch))
        assert len(lines) == 1
        assert "passport.json" in lines[0]
        assert "emplate baseline" in lines[0]

    def test_info_channel_silent_when_passport_present(self, tmp_path):
        """Nothing to announce when the baseline can actually run."""
        branch = tmp_path / "mybranch"
        (branch / "apps").mkdir(parents=True)
        trinity = branch / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text('{"identity": {"citizen_class": "specialist"}}', encoding="utf-8")

        assert architecture_check.check_branch_info(str(branch)) == []


# ===========================================================================
# 2. cli_check sub-functions
# ===========================================================================


# -- check_handler_separation ------------------------------------------------


class TestCheckHandlerSeparation:
    """Tests for check_handler_separation."""

    def test_clean_handler_passes(self):
        """Handler with no console output passes."""
        content = "def compute():\n    return 42\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is True
        assert "No console output" in result["message"]

    def test_console_print_fails(self):
        """Handler with console.print() fails."""
        content = "def show():\n    console.print('hello')\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is False
        assert "console.print()" in result["message"]

    def test_bare_print_fails(self):
        """Handler with bare print() fails."""
        content = "def show():\n    print('hello')\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is False
        assert "print()" in result["message"]

    def test_cli_import_fails(self):
        """Handler importing CLI services fails separation check."""
        content = "from aipass.cli.apps.modules.display import header\ndef show():\n    pass\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is False
        assert "CLI services" in result["message"]

    def test_print_in_main_block_ignored(self):
        """Print inside if __name__ block is allowed."""
        content = "def compute():\n    return 42\nif __name__ == '__main__':\n    print('test output')\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is True

    def test_console_print_in_string_ignored(self):
        """Console.print inside a string literal is not flagged."""
        content = "msg = 'use console.print() for output'\n"
        result = cli_check.check_handler_separation(content)
        assert result["passed"] is True


# -- check_cli_imports -------------------------------------------------------


class TestCheckCliImports:
    """Tests for check_cli_imports."""

    def test_has_cli_imports_passes(self, tmp_path):
        """Module with CLI service imports passes."""
        content = "from aipass.cli.apps.modules.display import header\n"
        result = cli_check.check_cli_imports(content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py"))
        assert result is not None
        assert result["passed"] is True

    def test_cli_branch_exempt(self, tmp_path):
        """CLI branch itself is exempt from this check."""
        content = "from .display import header\n"
        result = cli_check.check_cli_imports(content, str(tmp_path / "cli" / "apps" / "modules" / "something.py"))
        assert result is not None
        assert result["passed"] is True
        assert "CLI branch exempt" in result["message"]

    def test_output_without_cli_imports_fails(self, tmp_path):
        """Module with output but no CLI imports fails."""
        content = "print('hello world')\n"
        result = cli_check.check_cli_imports(content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py"))
        assert result is not None
        assert result["passed"] is False
        assert "missing CLI service imports" in result["message"]

    def test_no_output_at_all_passes(self, tmp_path):
        """Module with no output at all passes."""
        content = "def compute():\n    return 42\n"
        result = cli_check.check_cli_imports(content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py"))
        assert result is not None
        assert result["passed"] is True
        assert "No CLI output needed" in result["message"]

    def test_shortcut_import_passes(self, tmp_path):
        """Shortcut import via cli __init__ passes."""
        content = "from aipass.cli import header\n"
        result = cli_check.check_cli_imports(content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py"))
        assert result is not None
        assert result["passed"] is True


# -- check_print_usage -------------------------------------------------------


class TestCheckPrintUsage:
    """Tests for check_print_usage."""

    def test_console_print_passes(self, tmp_path):
        """File using console.print passes."""
        content = "console.print('hello')\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is not None
        assert result["passed"] is True

    def test_bare_print_fails(self, tmp_path):
        """Bare print() statement fails."""
        content = "print('hello')\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is not None
        assert result["passed"] is False
        assert "print() statements" in result["message"]

    def test_parser_print_help_fails(self, tmp_path):
        """parser.print_help() usage fails."""
        content = "parser.print_help()\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is not None
        assert result["passed"] is False
        assert "parser.print_help()" in result["message"]

    def test_format_help_fails(self, tmp_path):
        """console.print(parser.format_help()) fails — plain argparse text."""
        content = "console.print(parser.format_help())\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is not None
        assert result["passed"] is False
        assert ".format_help()" in result["message"]

    def test_format_help_in_comment_ignored(self, tmp_path):
        """.format_help() inside a comment is not flagged."""
        content = "# parser.format_help() should not be used\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is None

    def test_sys_stdout_write_fails(self, tmp_path):
        """sys.stdout.write() usage fails."""
        content = "import sys\nsys.stdout.write('hello')\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is not None
        assert result["passed"] is False
        assert "sys.stdout" in result["message"]

    def test_print_in_main_block_ignored(self, tmp_path):
        """Print inside if __name__ block returns None (no violation)."""
        content = "if __name__ == '__main__':\n    print('test')\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is None

    def test_no_output_returns_none(self, tmp_path):
        """File with no output returns None."""
        content = "x = 42\n"
        lines = _lines(content)
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"))
        assert result is None

    def test_bypass_rule_skips_line(self, tmp_path):
        """Bypassed print line is not flagged."""
        content = "print('hello')\n"
        lines = _lines(content)
        bypass = [{"standard": "cli", "file": "module.py", "lines": [1]}]
        result = cli_check.check_print_usage(content, lines, str(tmp_path / "module.py"), bypass_rules=bypass)
        assert result is None


# -- check_help_flag ---------------------------------------------------------


class TestCheckHelpFlag:
    """Tests for check_help_flag."""

    def test_argparse_with_help_passes(self):
        """Module with argparse and help/h flags passes."""
        content = "import argparse\nparser = argparse.ArgumentParser()\n--help\n-h\n"
        result = cli_check.check_help_flag(content)
        assert result is not None
        assert result["passed"] is True

    def test_print_help_function_passes(self):
        """Module with def print_help passes."""
        content = "def print_help():\n    pass\n"
        result = cli_check.check_help_flag(content)
        assert result is not None
        assert result["passed"] is True

    def test_executable_without_help_fails(self):
        """Executable module without --help fails."""
        content = "if __name__ == '__main__':\n    main()\n"
        result = cli_check.check_help_flag(content)
        assert result is not None
        assert result["passed"] is False
        assert "--help flag not implemented" in result["message"]

    def test_non_executable_returns_none(self):
        """Non-executable module returns None (not applicable)."""
        content = "def compute():\n    return 42\n"
        result = cli_check.check_help_flag(content)
        assert result is None


# -- check_duplicate_display_functions ----------------------------------------


class TestCheckDuplicateDisplayFunctions:
    """Tests for check_duplicate_display_functions."""

    def test_no_duplicates_passes(self, tmp_path):
        """Module without CLI display function duplicates passes."""
        content = "def compute():\n    return 42\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_duplicate_header_fails(self, tmp_path):
        """Module defining its own header() fails."""
        content = "def header(title):\n    print(title)\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py")
        )
        assert result is not None
        assert result["passed"] is False
        assert "header" in result["message"]

    def test_duplicate_error_and_warning_fails(self, tmp_path):
        """Module defining error() and warning() fails."""
        content = "def error(msg):\n    pass\ndef warning(msg):\n    pass\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py")
        )
        assert result is not None
        assert result["passed"] is False
        assert "error" in result["message"]

    # -- Method vs module-level function (reported by @trigger) --------------
    # The check used to substring-match "def error(" over raw source, so any
    # class exposing a logger API tripped it.

    def test_logger_class_methods_are_not_display_duplicates(self, tmp_path):
        """class TrailLogger: def error(...) is a logger API, not a cli.display copy."""
        content = (
            "class TrailLogger:\n"
            "    def error(self, message, **fields):\n        pass\n"
            "    def warning(self, message, **fields):\n        pass\n"
            "    def info(self, message, **fields):\n        pass\n"
        )
        result = cli_check.check_duplicate_display_functions(content, str(tmp_path / "trigger" / "apps" / "config.py"))
        assert result is not None
        assert result["passed"] is True

    def test_module_level_duplicate_still_caught_next_to_a_logger_class(self, tmp_path):
        """Narrowing to module level must not blind the check to a real duplicate."""
        content = "class TrailLogger:\n    def info(self, m):\n        pass\n\ndef success(msg):\n    print(msg)\n"
        result = cli_check.check_duplicate_display_functions(content, str(tmp_path / "trigger" / "apps" / "config.py"))
        assert result is not None
        assert result["passed"] is False
        assert "success" in result["message"]

    def test_def_inside_string_literal_is_not_a_definition(self, tmp_path):
        """Help text quoting "def error(" is not a definition."""
        content = 'HELP = """\n  def error(msg)\n"""\n'
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_nested_def_is_not_module_level(self, tmp_path):
        """A closure named info() is local, not a module-level display helper."""
        content = "def outer():\n    def info(m):\n        pass\n    return info\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "seedgo" / "apps" / "modules" / "audit.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_async_module_level_duplicate_is_caught(self, tmp_path):
        """async def error() at module level is still a duplicate."""
        result = cli_check.check_duplicate_display_functions(
            "async def error(m):\n    pass\n", str(tmp_path / "seedgo" / "apps" / "modules" / "a.py")
        )
        assert result is not None
        assert result["passed"] is False

    def test_unparseable_file_does_not_crash(self, tmp_path):
        """A syntax error degrades to no-finding rather than raising."""
        result = cli_check.check_duplicate_display_functions(
            "def broken(:\n", str(tmp_path / "seedgo" / "apps" / "modules" / "a.py")
        )
        assert result is not None
        assert result["passed"] is True

    def test_cli_branch_exempt(self, tmp_path):
        """CLI branch is exempt (it defines these functions)."""
        content = "def header(title):\n    print(title)\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "cli" / "apps" / "modules" / "display.py")
        )
        assert result is None

    def test_prax_logger_exempt(self, tmp_path):
        """Prax logger module is exempt (it is the logging system)."""
        content = "def error(msg):\n    pass\n"
        result = cli_check.check_duplicate_display_functions(
            content, str(tmp_path / "prax" / "apps" / "modules" / "logger" / "log.py")
        )
        assert result is None


# ===========================================================================
# 3. cli_flags_check sub-functions
# ===========================================================================


# -- check_version_flag ------------------------------------------------------


class TestCheckVersionFlag:
    """Tests for check_version_flag."""

    def test_version_flag_found_passes(self, tmp_path):
        """Entry point with '--version' string passes."""
        lines: list[str] = [
            "def main():",
            "    if '--version' in args:",
            "        print(VERSION)",
        ]
        result = cli_flags_check.check_version_flag(lines, str(tmp_path / "branch" / "apps" / "branch.py"), None)
        assert result["passed"] is True
        assert "version flag" in result["message"].lower()

    def test_short_version_flag_passes(self, tmp_path):
        """Entry point with '-V' string passes."""
        lines: list[str] = [
            "def main():",
            "    if '-V' in args:",
            "        print(VERSION)",
        ]
        result = cli_flags_check.check_version_flag(lines, str(tmp_path / "branch" / "apps" / "branch.py"), None)
        assert result["passed"] is True

    def test_no_version_flag_fails(self, tmp_path):
        """Entry point without any version flag handling fails."""
        lines: list[str] = [
            "def main():",
            "    print('hello')",
        ]
        result = cli_flags_check.check_version_flag(lines, str(tmp_path / "branch" / "apps" / "branch.py"), None)
        assert result["passed"] is False
        assert "missing --version" in result["message"].lower()

    def test_version_in_docstring_ignored(self, tmp_path):
        """Version flag mentioned only in a docstring does not count."""
        lines: list[str] = [
            '"""',
            "Supports --version flag",
            '"""',
            "def main():",
            "    pass",
        ]
        result = cli_flags_check.check_version_flag(lines, str(tmp_path / "branch" / "apps" / "branch.py"), None)
        assert result["passed"] is False

    def test_bypassed_passes(self, tmp_path):
        """Bypassed entry point passes regardless."""
        lines: list[str] = ["def main():", "    pass"]
        bypass = [{"standard": "cli_flags", "file": "branch.py"}]
        result = cli_flags_check.check_version_flag(lines, str(tmp_path / "branch" / "apps" / "branch.py"), bypass)
        assert result["passed"] is True
        assert "Bypassed" in result["message"]


# ===========================================================================
# 4. documentation_check sub-functions
# ===========================================================================


# -- check_module_docstring --------------------------------------------------


class TestCheckModuleDocstring:
    """Tests for check_module_docstring."""

    def test_docstring_present_passes(self):
        """File with a module-level docstring passes."""
        lines: list[str] = [
            "# META block",
            "",
            '"""Module docstring."""',
            "",
            "def foo():",
        ]
        result = documentation_check.check_module_docstring(lines)
        assert result["passed"] is True

    def test_docstring_missing_fails(self):
        """File without a docstring in the first 30 lines fails."""
        lines: list[str] = [
            "# Just a comment",
            "import os",
            "import sys",
            "def foo():",
            "    pass",
        ] + ["# more code"] * 30
        result = documentation_check.check_module_docstring(lines)
        assert result["passed"] is False
        assert "Missing module-level docstring" in result["message"]

    def test_single_quote_docstring_passes(self):
        """Single-quote triple-quote docstring is accepted."""
        lines: list[str] = ["'''Module docstring.'''", "", "def foo():"]
        result = documentation_check.check_module_docstring(lines)
        assert result["passed"] is True

    def test_docstring_after_meta_block_passes(self):
        """Docstring after META header block is accepted."""
        lines: list[str] = [
            "# ========= META =========",
            "# Name: foo.py",
            "# ========================",
            "",
            '"""',
            "Multi-line docstring.",
            '"""',
        ]
        result = documentation_check.check_module_docstring(lines)
        assert result["passed"] is True


# -- check_function_docstrings -----------------------------------------------


class TestCheckFunctionDocstrings:
    """Tests for check_function_docstrings."""

    def test_all_public_documented_passes(self):
        """All public functions with docstrings passes."""
        content = 'def foo():\n    """Does foo."""\n    pass\ndef bar():\n    """Does bar."""\n    pass\n'
        lines = _lines(content)
        result = documentation_check.check_function_docstrings(content, lines)
        assert result["passed"] is True
        assert "2 public functions" in result["message"]

    def test_missing_docstring_fails(self):
        """Public function without docstring fails."""
        content = "def foo():\n    pass\n"
        lines = _lines(content)
        result = documentation_check.check_function_docstrings(content, lines)
        assert result["passed"] is False
        assert "foo" in result["message"]

    def test_private_functions_skipped(self):
        """Private functions (starting with _) are not checked."""
        content = "def _private_helper():\n    pass\n"
        lines = _lines(content)
        result = documentation_check.check_function_docstrings(content, lines)
        assert result["passed"] is True
        assert "No public functions" in result["message"]

    def test_no_functions_passes(self):
        """File with no functions passes vacuously."""
        content = "x = 42\ny = 43\n"
        lines = _lines(content)
        result = documentation_check.check_function_docstrings(content, lines)
        assert result["passed"] is True

    def test_multiline_signature_docstring_found(self):
        """Docstring after a multi-line function signature is detected."""
        content = (
            'def compute(\n    arg1: str,\n    arg2: int,\n) -> bool:\n    """Compute something."""\n    return True\n'
        )
        lines = _lines(content)
        result = documentation_check.check_function_docstrings(content, lines)
        assert result["passed"] is True
