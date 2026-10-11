# =================== META ====================
# Name: test_output_routing.py
# Description: Unit tests for output_routing_check
# Version: 1.1.0
# Created: 2026-07-09
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/output_routing_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — APPLIES_TO and AUDIT_SCOPE, the scope the audit reads
# seedgo: no-test-needed(stdlib) — re.compile's matching; the product only composes the patterns
# seedgo: no-test-needed(standard) — the check_completed record json_handler.log_operation writes

import pytest
from unittest.mock import MagicMock

from aipass.seedgo.apps.handlers.aipass_standards import output_routing_check
from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils


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


def _check_line(tmp_path, code: str) -> dict:
    """Run check_module on a one-line product file holding ``code``."""
    f = tmp_path / "subject.py"
    f.write_text(code + "\n", encoding="utf-8")
    return output_routing_check.check_module(str(f))


_ONE_HIT = "1 raw status output(s) on lines 1"
_CLEAN = "All user-facing status output uses @cli helpers"


# ===========================================================================
# 1. Status-print detection, one line at a time, through check_module
# ===========================================================================


class TestIsStatusConsolePrint:
    """Which console.print lines check_module convicts (the _is_status_console_print rule)."""

    def test_red_markup_detected(self, tmp_path):
        """Mutant: check_module skips _scan_file in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        result = _check_line(tmp_path, 'console.print(f"[red]Error: {msg}[/red]")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_bold_red_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[bold red]Failed[/bold red]")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_red_bold_order_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[red bold]Error[/red bold]")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_status_emoji_cross_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("❌ Something failed")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_status_emoji_check_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("✅ Done")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_status_emoji_checkmark_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("✓ Complete")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_status_emoji_cross_mark_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("✗ Failed")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_green_check_pattern_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[green]✓[/green] Done")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_yellow_warning_detected(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[yellow]⚠ Warning: check config[/yellow]")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_err_console_detected(self, tmp_path):
        result = _check_line(tmp_path, 'err_console.print(f"[red]Error[/red]")')
        assert result["passed"] is False
        assert result["checks"][0]["message"] == _ONE_HIT

    def test_plain_console_print_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("Hello world")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_cyan_markup_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'console.print(f"[cyan]Info: {msg}[/cyan]")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_dim_markup_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'console.print(f"[dim]{details}[/dim]")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_table_object_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, "console.print(table)")
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_panel_object_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, "console.print(Panel(title))")
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_no_console_print_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'logger.info("[red]error[/red]")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_green_without_check_emoji_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[green]name[/green]")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_yellow_without_warning_not_flagged(self, tmp_path):
        result = _check_line(tmp_path, 'console.print("[yellow]note[/yellow]")')
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN


# ===========================================================================
# 2. File scanning — docstrings, comments, line numbers, through check_module
# ===========================================================================


class TestScanFile:
    """What the _scan_file pass over a file hands check_module."""

    def test_detects_red_markup(self, tmp_path):
        """Mutant: check_module skips _scan_file in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        f = tmp_path / "subject.py"
        f.write_text('console.print(f"[red]Error: {e}[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is False
        assert result["checks"][0]["message"] == "1 raw status output(s) on lines 1"

    def test_skips_docstrings(self, tmp_path):
        """Mutant: docstring lines scanned in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        f = tmp_path / "subject.py"
        f.write_text(
            '"""\nconsole.print("[red]error[/red]")\n"""\npass\n',
            encoding="utf-8",
        )
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_skips_comments(self, tmp_path):
        """Mutant: comment lines scanned in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        f = tmp_path / "subject.py"
        f.write_text('# console.print("[red]error[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_skips_inline_comment(self, tmp_path):
        """Mutant: inline comment kept in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        f = tmp_path / "subject.py"
        f.write_text('x = 1  # console.print("[red]error[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_detects_multiple_lines(self, tmp_path):
        f = tmp_path / "subject.py"
        f.write_text(
            'x = 1\nconsole.print("[red]a[/red]")\ny = 2\nconsole.print("✅ done")\n',
            encoding="utf-8",
        )
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is False
        assert result["checks"][0]["message"] == "2 raw status output(s) on lines 2, 4"

    def test_clean_file(self, tmp_path):
        f = tmp_path / "subject.py"
        f.write_text('console.print("[cyan]info[/cyan]")\nprint("hello")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["checks"][0]["message"] == _CLEAN

    def test_unreadable_file(self, tmp_path):
        """Mutant: read error swallowed as a clean scan in apps/handlers/aipass_standards/output_routing_check.py — killed."""
        # A directory named like a module exists but cannot be read: the only route
        # check_module has to _scan_file's read error (a missing file stops earlier).
        f = tmp_path / "unreadable.py"
        f.mkdir()
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is False
        assert result["checks"][0]["name"] == "File readable"
        assert result["checks"][0]["message"].startswith("Error reading file: cannot read:")


# ===========================================================================
# 3. check_module — full checker
# ===========================================================================


class TestCheckModule:
    """Tests for check_module."""

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text('from aipass.cli.apps.modules import error\nerror("fail")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["standard"] == "OUTPUT_ROUTING"

    def test_violation_detected(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text('console.print(f"[red]Error: {e}[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_init_py_skipped(self, tmp_path):
        f = tmp_path / "__init__.py"
        f.write_text('console.print("[red]error[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100

    def test_test_file_skipped(self, tmp_path):
        f = tmp_path / "test_something.py"
        f.write_text('console.print("[red]error[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100

    def test_conftest_skipped(self, tmp_path):
        f = tmp_path / "conftest.py"
        f.write_text('console.print("[red]error[/red]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100

    def test_bypass_returns_100(self, tmp_path):
        f = tmp_path / "bypassed.py"
        f.write_text('console.print("[red]error[/red]")\n', encoding="utf-8")
        bypass = [{"standard": "output_routing", "file": str(f)}]
        result = output_routing_check.check_module(str(f), bypass_rules=bypass)
        assert result["passed"] is True
        assert result["score"] == 100

    def test_missing_file(self, tmp_path):
        result = output_routing_check.check_module(str(tmp_path / "no_such.py"))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_line_bypass_all_lines_pass(self, tmp_path):
        f = tmp_path / "partial.py"
        f.write_text(
            'console.print("[red]a[/red]")\nconsole.print("[red]b[/red]")\n',
            encoding="utf-8",
        )
        bypass = [{"standard": "output_routing", "file": "partial.py", "lines": [1, 2]}]
        result = output_routing_check.check_module(str(f), bypass_rules=bypass)
        assert result["passed"] is True

    def test_violation_message_shows_lines(self, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text('console.print("[red]a[/red]")\nconsole.print("✅ b")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert "2 raw" in result["checks"][0]["message"]
        assert "1, 2" in result["checks"][0]["message"]

    def test_more_than_five_violations_truncated(self, tmp_path):
        f = tmp_path / "many.py"
        lines = [f'console.print("[red]err{i}[/red]")\n' for i in range(8)]
        f.write_text("".join(lines), encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert "and 3 more" in result["checks"][0]["message"]


# ===========================================================================
# 4. False-positive avoidance
# ===========================================================================


class TestFalsePositiveAvoidance:
    """Verify that legitimate patterns are NOT flagged."""

    def test_table_print_not_flagged(self, tmp_path):
        f = tmp_path / "tables.py"
        f.write_text("console.print(table)\nconsole.print(Panel(content))\n", encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True

    def test_blue_markup_not_flagged(self, tmp_path):
        f = tmp_path / "blue.py"
        f.write_text('console.print("[blue]Processing...[/blue]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True

    def test_empty_console_print_not_flagged(self, tmp_path):
        f = tmp_path / "blank.py"
        f.write_text('console.print("")\nconsole.print()\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True

    def test_docstring_with_markup_not_flagged(self, tmp_path):
        f = tmp_path / "docs.py"
        content = '"""\nconsole.print("[red]error[/red]")\n"""\ndef foo(): pass\n'
        f.write_text(content, encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True

    def test_green_text_without_emoji_not_flagged(self, tmp_path):
        f = tmp_path / "green.py"
        f.write_text('console.print("[green]branch_name[/green]")\n', encoding="utf-8")
        result = output_routing_check.check_module(str(f))
        assert result["passed"] is True
