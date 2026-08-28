"""Tests for seedgo checker sub-functions -- batch 6 (architecture, cli, cli_flags, documentation)."""

# =================== META ====================
# Name: test_checkers_batch6.py
# Description: Unit tests for checker sub-functions in architecture, cli, cli_flags, documentation
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

from typing import List

import pytest
from unittest.mock import MagicMock


def _lines(text: str) -> List[str]:
    """Split text into lines, widening LiteralString to str for pyright."""
    return text.split("\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.json.json_handler",
        json_mod,
    )

    # -- bypass handler (used by architecture_check + cli_check) -------------
    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as _real_is_bypassed

    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = _real_is_bypassed
    bypass_pkg.utils = bypass_utils
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.utils",
        bypass_utils,
    )

    # Force re-imports so checkers pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.architecture_check",
        "aipass.seedgo.apps.handlers.aipass_standards.cli_check",
        "aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check",
        "aipass.seedgo.apps.handlers.aipass_standards.documentation_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# 1. architecture_check sub-functions
# ===========================================================================


# -- check_layer_location ---------------------------------------------------


class TestCheckLayerLocation:
    """Tests for check_layer_location."""

    def test_entry_point_passes(self):
        """Entry point path is recognised as the entry-point layer."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_layer_location,
        )

        result = check_layer_location("/branch/apps/branch.py", True, False, False)
        assert result["passed"] is True
        assert "Entry point" in result["message"]

    def test_module_layer_passes(self):
        """Module path is recognised as the module layer."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_layer_location,
        )

        result = check_layer_location("/branch/apps/modules/foo.py", False, True, False)
        assert result["passed"] is True
        assert "Module layer" in result["message"]

    def test_handler_layer_passes(self):
        """Handler path is recognised as the handler layer."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_layer_location,
        )

        result = check_layer_location("/branch/apps/handlers/json/j.py", False, False, True)
        assert result["passed"] is True
        assert "Handler layer" in result["message"]

    def test_outside_3_layer_fails(self):
        """Path outside the 3-layer structure fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_layer_location,
        )

        result = check_layer_location("/branch/random/foo.py", False, False, False)
        assert result["passed"] is False
        assert "not in standard 3-layer" in result["message"]


# -- check_file_size (architecture) -----------------------------------------


class TestArchCheckFileSize:
    """Tests for architecture_check.check_file_size."""

    def test_small_file_passes(self):
        """Under 300 lines is perfect."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 100
        result = check_file_size(lines, "small.py")
        assert result["passed"] is True
        assert "perfect" in result["message"]

    def test_medium_file_passes(self):
        """300-500 lines is good."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 350
        result = check_file_size(lines, "medium.py")
        assert result["passed"] is True
        assert "good" in result["message"]

    def test_heavy_file_passes(self):
        """500-700 lines is acceptable but heavy."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 600
        result = check_file_size(lines, "heavy.py")
        assert result["passed"] is True
        assert "getting heavy" in result["message"]

    def test_advisory_file_passes(self):
        """700-1500 lines is advisory — passes but warns."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 750
        result = check_file_size(lines, "big.py")
        assert result["passed"] is True
        assert "advisory" in result["message"]

    def test_oversized_file_fails(self):
        """1500+ lines hard-fails the size check."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_file_size,
        )

        lines: list[str] = ["x"] * 1600
        result = check_file_size(lines, "huge.py")
        assert result["passed"] is False
        assert "must split" in result["message"]


# -- check_handler_independence (architecture) --------------------------------


class TestArchHandlerIndependence:
    """Tests for architecture_check.check_handler_independence."""

    def test_clean_handler_passes(self):
        """Handler without parent module imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines: list[str] = [
            "from aipass.prax import logger",
            "from aipass.cli.apps.modules import display",
            "",
            "def do_work():",
            "    return True",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True

    def test_parent_module_import_fails(self):
        """Handler importing from its parent branch module fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines: list[str] = [
            "from seedgo.apps.modules.audit import run_audit",
            "",
            "def do_work():",
            "    return True",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is False
        assert "parent module" in result["message"]

    def test_allowed_service_imports_pass(self):
        """Prax and CLI service imports are allowed in handlers."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines: list[str] = [
            "from prax.apps.modules.logger import info",
            "from cli.apps.modules.display import header",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True

    def test_import_in_docstring_ignored(self):
        """Imports inside docstrings are not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_handler_independence,
        )

        lines: list[str] = [
            '"""',
            "from seedgo.apps.modules.audit import run_audit",
            '"""',
            "def do_work():",
            "    return True",
        ]
        result = check_handler_independence(lines, "/seedgo/apps/handlers/json/j.py")
        assert result is not None
        assert result["passed"] is True


# -- check_domain_organization -----------------------------------------------


class TestCheckDomainOrganization:
    """Tests for check_domain_organization."""

    def test_domain_based_passes(self):
        """Handler in a domain-named folder passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/json/json_handler.py")
        assert result is not None
        assert result["passed"] is True
        assert "json" in result["message"]

    def test_technical_name_fails(self):
        """Handler in a technical-named folder (utils) fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/utils/helper.py")
        assert result is not None
        assert result["passed"] is False
        assert "Technical organization" in result["message"]

    def test_helpers_name_fails(self):
        """Handler in a helpers/ folder fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers/helpers/tool.py")
        assert result is not None
        assert result["passed"] is False

    def test_no_handler_domain_detected(self):
        """Path ending at handlers/ with no subdirectory fails detection."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_domain_organization,
        )

        result = check_domain_organization("/branch/apps/handlers")
        assert result is not None
        assert result["passed"] is False
        assert "Could not detect" in result["message"]


# -- check_template_baseline -------------------------------------------------


class TestCheckTemplateBaseline:
    """Tests for check_template_baseline."""

    def test_no_branch_path_detected(self):
        """Path without apps/ cannot resolve a branch."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_template_baseline,
        )

        result = check_template_baseline("/random/file.py")
        assert len(result) >= 1
        assert result[0]["passed"] is False
        assert "Could not detect branch path" in result[0]["message"]

    def test_missing_passport_skips(self, tmp_path):
        """Branch without passport.json skips template baseline (gitignored)."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_template_baseline,
        )

        apps_dir = tmp_path / "mybranch" / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text('"""Entry."""\n', encoding="utf-8")

        result = check_template_baseline(str(entry))
        assert result == []

    def test_passport_without_citizen_class(self, tmp_path):
        """Branch with passport.json but no citizen_class fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.architecture_check import (
            check_template_baseline,
        )

        apps_dir = tmp_path / "mybranch" / "apps"
        apps_dir.mkdir(parents=True)
        entry = apps_dir / "mybranch.py"
        entry.write_text('"""Entry."""\n', encoding="utf-8")
        trinity = tmp_path / "mybranch" / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text('{"identity": {}}', encoding="utf-8")

        result = check_template_baseline(str(entry))
        assert len(result) >= 1
        assert result[0]["passed"] is False
        assert "citizen_class" in result[0]["message"]

    def test_trinity_files_are_not_scored(self, tmp_path, monkeypatch):
        """Files under .trinity/ are local-only memory — never scored.

        .trinity/ is permanently gitignored, so requiring its contents in a
        clone-facing structural score asks a branch to ship what it must not.
        """
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

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
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

        branch = tmp_path / "mybranch"
        (branch / "apps").mkdir(parents=True)

        lines = architecture_check.check_branch_info(str(branch))
        assert len(lines) == 1
        assert "passport.json" in lines[0]
        assert "emplate baseline" in lines[0]

    def test_info_channel_silent_when_passport_present(self, tmp_path):
        """Nothing to announce when the baseline can actually run."""
        from aipass.seedgo.apps.handlers.aipass_standards import architecture_check

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
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "def compute():\n    return 42\n"
        result = check_handler_separation(content)
        assert result["passed"] is True
        assert "No console output" in result["message"]

    def test_console_print_fails(self):
        """Handler with console.print() fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "def show():\n    console.print('hello')\n"
        result = check_handler_separation(content)
        assert result["passed"] is False
        assert "console.print()" in result["message"]

    def test_bare_print_fails(self):
        """Handler with bare print() fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "def show():\n    print('hello')\n"
        result = check_handler_separation(content)
        assert result["passed"] is False
        assert "print()" in result["message"]

    def test_cli_import_fails(self):
        """Handler importing CLI services fails separation check."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "from aipass.cli.apps.modules.display import header\ndef show():\n    pass\n"
        result = check_handler_separation(content)
        assert result["passed"] is False
        assert "CLI services" in result["message"]

    def test_print_in_main_block_ignored(self):
        """Print inside if __name__ block is allowed."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "def compute():\n    return 42\nif __name__ == '__main__':\n    print('test output')\n"
        result = check_handler_separation(content)
        assert result["passed"] is True

    def test_console_print_in_string_ignored(self):
        """Console.print inside a string literal is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_handler_separation,
        )

        content = "msg = 'use console.print() for output'\n"
        result = check_handler_separation(content)
        assert result["passed"] is True


# -- check_cli_imports -------------------------------------------------------


class TestCheckCliImports:
    """Tests for check_cli_imports."""

    def test_has_cli_imports_passes(self):
        """Module with CLI service imports passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_cli_imports,
        )

        content = "from aipass.cli.apps.modules.display import header\n"
        result = check_cli_imports(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True

    def test_cli_branch_exempt(self):
        """CLI branch itself is exempt from this check."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_cli_imports,
        )

        content = "from .display import header\n"
        result = check_cli_imports(content, "/cli/apps/modules/something.py")
        assert result is not None
        assert result["passed"] is True
        assert "CLI branch exempt" in result["message"]

    def test_output_without_cli_imports_fails(self):
        """Module with output but no CLI imports fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_cli_imports,
        )

        content = "print('hello world')\n"
        result = check_cli_imports(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is False
        assert "missing CLI service imports" in result["message"]

    def test_no_output_at_all_passes(self):
        """Module with no output at all passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_cli_imports,
        )

        content = "def compute():\n    return 42\n"
        result = check_cli_imports(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True
        assert "No CLI output needed" in result["message"]

    def test_shortcut_import_passes(self):
        """Shortcut import via cli __init__ passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_cli_imports,
        )

        content = "from aipass.cli import header\n"
        result = check_cli_imports(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True


# -- check_print_usage -------------------------------------------------------


class TestCheckPrintUsage:
    """Tests for check_print_usage."""

    def test_console_print_passes(self):
        """File using console.print passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "console.print('hello')\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is True

    def test_bare_print_fails(self):
        """Bare print() statement fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "print('hello')\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert "print() statements" in result["message"]

    def test_parser_print_help_fails(self):
        """parser.print_help() usage fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "parser.print_help()\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert "parser.print_help()" in result["message"]

    def test_format_help_fails(self):
        """console.print(parser.format_help()) fails — plain argparse text."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "console.print(parser.format_help())\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert ".format_help()" in result["message"]

    def test_format_help_in_comment_ignored(self):
        """.format_help() inside a comment is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "# parser.format_help() should not be used\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is None

    def test_sys_stdout_write_fails(self):
        """sys.stdout.write() usage fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "import sys\nsys.stdout.write('hello')\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is not None
        assert result["passed"] is False
        assert "sys.stdout" in result["message"]

    def test_print_in_main_block_ignored(self):
        """Print inside if __name__ block returns None (no violation)."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "if __name__ == '__main__':\n    print('test')\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is None

    def test_no_output_returns_none(self):
        """File with no output returns None."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "x = 42\n"
        lines = _lines(content)
        result = check_print_usage(content, lines, "/module.py")
        assert result is None

    def test_bypass_rule_skips_line(self):
        """Bypassed print line is not flagged."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_print_usage,
        )

        content = "print('hello')\n"
        lines = _lines(content)
        bypass = [{"standard": "cli", "file": "module.py", "lines": [1]}]
        result = check_print_usage(content, lines, "/module.py", bypass_rules=bypass)
        assert result is None


# -- check_help_flag ---------------------------------------------------------


class TestCheckHelpFlag:
    """Tests for check_help_flag."""

    def test_argparse_with_help_passes(self):
        """Module with argparse and help/h flags passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_help_flag,
        )

        content = "import argparse\nparser = argparse.ArgumentParser()\n--help\n-h\n"
        result = check_help_flag(content)
        assert result is not None
        assert result["passed"] is True

    def test_print_help_function_passes(self):
        """Module with def print_help passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_help_flag,
        )

        content = "def print_help():\n    pass\n"
        result = check_help_flag(content)
        assert result is not None
        assert result["passed"] is True

    def test_executable_without_help_fails(self):
        """Executable module without --help fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_help_flag,
        )

        content = "if __name__ == '__main__':\n    main()\n"
        result = check_help_flag(content)
        assert result is not None
        assert result["passed"] is False
        assert "--help flag not implemented" in result["message"]

    def test_non_executable_returns_none(self):
        """Non-executable module returns None (not applicable)."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_help_flag,
        )

        content = "def compute():\n    return 42\n"
        result = check_help_flag(content)
        assert result is None


# -- check_duplicate_display_functions ----------------------------------------


class TestCheckDuplicateDisplayFunctions:
    """Tests for check_duplicate_display_functions."""

    def test_no_duplicates_passes(self):
        """Module without CLI display function duplicates passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def compute():\n    return 42\n"
        result = check_duplicate_display_functions(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True

    def test_duplicate_header_fails(self):
        """Module defining its own header() fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def header(title):\n    print(title)\n"
        result = check_duplicate_display_functions(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is False
        assert "header" in result["message"]

    def test_duplicate_error_and_warning_fails(self):
        """Module defining error() and warning() fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def error(msg):\n    pass\ndef warning(msg):\n    pass\n"
        result = check_duplicate_display_functions(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is False
        assert "error" in result["message"]

    # -- Method vs module-level function (reported by @trigger) --------------
    # The check used to substring-match "def error(" over raw source, so any
    # class exposing a logger API tripped it.

    def test_logger_class_methods_are_not_display_duplicates(self):
        """class TrailLogger: def error(...) is a logger API, not a cli.display copy."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = (
            "class TrailLogger:\n"
            "    def error(self, message, **fields):\n        pass\n"
            "    def warning(self, message, **fields):\n        pass\n"
            "    def info(self, message, **fields):\n        pass\n"
        )
        result = check_duplicate_display_functions(content, "/trigger/apps/config.py")
        assert result is not None
        assert result["passed"] is True

    def test_module_level_duplicate_still_caught_next_to_a_logger_class(self):
        """Narrowing to module level must not blind the check to a real duplicate."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "class TrailLogger:\n    def info(self, m):\n        pass\n\ndef success(msg):\n    print(msg)\n"
        result = check_duplicate_display_functions(content, "/trigger/apps/config.py")
        assert result is not None
        assert result["passed"] is False
        assert "success" in result["message"]

    def test_def_inside_string_literal_is_not_a_definition(self):
        """Help text quoting "def error(" is not a definition."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = 'HELP = """\n  def error(msg)\n"""\n'
        result = check_duplicate_display_functions(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True

    def test_nested_def_is_not_module_level(self):
        """A closure named info() is local, not a module-level display helper."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def outer():\n    def info(m):\n        pass\n    return info\n"
        result = check_duplicate_display_functions(content, "/seedgo/apps/modules/audit.py")
        assert result is not None
        assert result["passed"] is True

    def test_async_module_level_duplicate_is_caught(self):
        """async def error() at module level is still a duplicate."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        result = check_duplicate_display_functions("async def error(m):\n    pass\n", "/seedgo/apps/modules/a.py")
        assert result is not None
        assert result["passed"] is False

    def test_unparseable_file_does_not_crash(self):
        """A syntax error degrades to no-finding rather than raising."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        result = check_duplicate_display_functions("def broken(:\n", "/seedgo/apps/modules/a.py")
        assert result is not None
        assert result["passed"] is True

    def test_cli_branch_exempt(self):
        """CLI branch is exempt (it defines these functions)."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def header(title):\n    print(title)\n"
        result = check_duplicate_display_functions(content, "/cli/apps/modules/display.py")
        assert result is None

    def test_prax_logger_exempt(self):
        """Prax logger module is exempt (it is the logging system)."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_check import (
            check_duplicate_display_functions,
        )

        content = "def error(msg):\n    pass\n"
        result = check_duplicate_display_functions(content, "/prax/apps/modules/logger/log.py")
        assert result is None


# ===========================================================================
# 3. cli_flags_check sub-functions
# ===========================================================================


# -- check_version_flag ------------------------------------------------------


class TestCheckVersionFlag:
    """Tests for check_version_flag."""

    def test_version_flag_found_passes(self):
        """Entry point with '--version' string passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
            check_version_flag,
        )

        lines: list[str] = [
            "def main():",
            "    if '--version' in args:",
            "        print(VERSION)",
        ]
        result = check_version_flag(lines, "/branch/apps/branch.py", None)
        assert result["passed"] is True
        assert "version flag" in result["message"].lower()

    def test_short_version_flag_passes(self):
        """Entry point with '-V' string passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
            check_version_flag,
        )

        lines: list[str] = [
            "def main():",
            "    if '-V' in args:",
            "        print(VERSION)",
        ]
        result = check_version_flag(lines, "/branch/apps/branch.py", None)
        assert result["passed"] is True

    def test_no_version_flag_fails(self):
        """Entry point without any version flag handling fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
            check_version_flag,
        )

        lines: list[str] = [
            "def main():",
            "    print('hello')",
        ]
        result = check_version_flag(lines, "/branch/apps/branch.py", None)
        assert result["passed"] is False
        assert "missing --version" in result["message"].lower()

    def test_version_in_docstring_ignored(self):
        """Version flag mentioned only in a docstring does not count."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
            check_version_flag,
        )

        lines: list[str] = [
            '"""',
            "Supports --version flag",
            '"""',
            "def main():",
            "    pass",
        ]
        result = check_version_flag(lines, "/branch/apps/branch.py", None)
        assert result["passed"] is False

    def test_bypassed_passes(self):
        """Bypassed entry point passes regardless."""
        from aipass.seedgo.apps.handlers.aipass_standards.cli_flags_check import (
            check_version_flag,
        )

        lines: list[str] = ["def main():", "    pass"]
        bypass = [{"standard": "cli_flags", "file": "branch.py"}]
        result = check_version_flag(lines, "/branch/apps/branch.py", bypass)
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
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_module_docstring,
        )

        lines: list[str] = [
            "# META block",
            "",
            '"""Module docstring."""',
            "",
            "def foo():",
        ]
        result = check_module_docstring(lines)
        assert result["passed"] is True

    def test_docstring_missing_fails(self):
        """File without a docstring in the first 30 lines fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_module_docstring,
        )

        lines: list[str] = [
            "# Just a comment",
            "import os",
            "import sys",
            "def foo():",
            "    pass",
        ] + ["# more code"] * 30
        result = check_module_docstring(lines)
        assert result["passed"] is False
        assert "Missing module-level docstring" in result["message"]

    def test_single_quote_docstring_passes(self):
        """Single-quote triple-quote docstring is accepted."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_module_docstring,
        )

        lines: list[str] = ["'''Module docstring.'''", "", "def foo():"]
        result = check_module_docstring(lines)
        assert result["passed"] is True

    def test_docstring_after_meta_block_passes(self):
        """Docstring after META header block is accepted."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_module_docstring,
        )

        lines: list[str] = [
            "# ========= META =========",
            "# Name: foo.py",
            "# ========================",
            "",
            '"""',
            "Multi-line docstring.",
            '"""',
        ]
        result = check_module_docstring(lines)
        assert result["passed"] is True


# -- check_function_docstrings -----------------------------------------------


class TestCheckFunctionDocstrings:
    """Tests for check_function_docstrings."""

    def test_all_public_documented_passes(self):
        """All public functions with docstrings passes."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_function_docstrings,
        )

        content = 'def foo():\n    """Does foo."""\n    pass\ndef bar():\n    """Does bar."""\n    pass\n'
        lines = _lines(content)
        result = check_function_docstrings(content, lines)
        assert result["passed"] is True
        assert "2 public functions" in result["message"]

    def test_missing_docstring_fails(self):
        """Public function without docstring fails."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_function_docstrings,
        )

        content = "def foo():\n    pass\n"
        lines = _lines(content)
        result = check_function_docstrings(content, lines)
        assert result["passed"] is False
        assert "foo" in result["message"]

    def test_private_functions_skipped(self):
        """Private functions (starting with _) are not checked."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_function_docstrings,
        )

        content = "def _private_helper():\n    pass\n"
        lines = _lines(content)
        result = check_function_docstrings(content, lines)
        assert result["passed"] is True
        assert "No public functions" in result["message"]

    def test_no_functions_passes(self):
        """File with no functions passes vacuously."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_function_docstrings,
        )

        content = "x = 42\ny = 43\n"
        lines = _lines(content)
        result = check_function_docstrings(content, lines)
        assert result["passed"] is True

    def test_multiline_signature_docstring_found(self):
        """Docstring after a multi-line function signature is detected."""
        from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import (
            check_function_docstrings,
        )

        content = (
            'def compute(\n    arg1: str,\n    arg2: int,\n) -> bool:\n    """Compute something."""\n    return True\n'
        )
        lines = _lines(content)
        result = check_function_docstrings(content, lines)
        assert result["passed"] is True
