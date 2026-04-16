# =================== AIPass ====================
# Name: test_scan.py
# Description: Tests for branch command scanning
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Tests for branch command scanning.

Covers handler-layer functions (scan_help_output, scan_module_files,
scan_branch) and the orchestration module (scan.handle_command, scan.scan).
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.scanning.scanner import (
    scan_branch,
    scan_help_output,
    scan_module_files,
)
from aipass.drone.apps.handlers.scanning.formatters import (
    format_no_commands,
    format_scan_results,
)


# =============================================================================
# scan_help_output tests
# =============================================================================


class TestScanHelpOutput:
    """Tests for scan_help_output()."""

    def test_returns_commands_from_help(self, temp_test_dir: Path) -> None:
        """Should parse commands from --help output."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"Usage: mybranch\n\nCommands:\n  audit       Run an audit\n  list        List items\n\n"
        mock_result.stderr = b""

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            return_value=mock_result,
        ):
            result = scan_help_output(str(temp_test_dir), "mybranch")

        assert len(result) == 2
        names = [c["name"] for c in result]
        assert "audit" in names
        assert "list" in names
        assert all(c["source"] == "help" for c in result)

    def test_extracts_descriptions(self, temp_test_dir: Path) -> None:
        """Should extract descriptions alongside command names."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b"Commands:\n  deploy      Deploy to production\n\n"
        mock_result.stderr = b""

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            return_value=mock_result,
        ):
            result = scan_help_output(str(temp_test_dir), "mybranch")

        assert result[0]["description"] == "Deploy to production"

    def test_returns_empty_when_no_entry_point(self, temp_test_dir: Path) -> None:
        """Should return empty list when no entry point exists."""
        result = scan_help_output(str(temp_test_dir), "nonexistent")
        assert result == []

    def test_returns_empty_on_timeout(self, temp_test_dir: Path) -> None:
        """Should return empty list when subprocess times out."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "slow.py").write_text("# entry", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="test", timeout=10),
        ):
            result = scan_help_output(str(temp_test_dir), "slow")

        assert result == []

    def test_returns_empty_on_oserror(self, temp_test_dir: Path) -> None:
        """Should return empty list on OSError."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "broken.py").write_text("# entry", encoding="utf-8")

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            side_effect=OSError("No such file"),
        ):
            result = scan_help_output(str(temp_test_dir), "broken")

        assert result == []

    def test_falls_back_to_stderr(self, temp_test_dir: Path) -> None:
        """Should parse stderr when stdout is empty."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.stdout = b""
        mock_result.stderr = b"Commands:\n  check    Run checks\n\n"

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            return_value=mock_result,
        ):
            result = scan_help_output(str(temp_test_dir), "mybranch")

        assert len(result) == 1
        assert result[0]["name"] == "check"


# =============================================================================
# scan_module_files tests
# =============================================================================


class TestScanModuleFiles:
    """Tests for scan_module_files()."""

    def test_finds_modules_with_handle_command(self, temp_test_dir: Path) -> None:
        """Should find .py files that define handle_command()."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "alpha.py").write_text(
            '"""Alpha module."""\ndef handle_command(command=None, args=None): pass\n',
            encoding="utf-8",
        )
        (modules_dir / "beta.py").write_text(
            '"""Beta module."""\ndef handle_command(command=None, args=None): pass\n',
            encoding="utf-8",
        )

        result = scan_module_files(str(temp_test_dir))

        assert len(result) == 2
        names = [c["name"] for c in result]
        assert "alpha" in names
        assert "beta" in names
        assert all(c["source"] == "module" for c in result)

    def test_skips_files_without_handle_command(self, temp_test_dir: Path) -> None:
        """Should skip modules that do not define handle_command()."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "utility.py").write_text(
            "def helper(): pass\n",
            encoding="utf-8",
        )

        result = scan_module_files(str(temp_test_dir))

        assert result == []

    def test_skips_init_and_main(self, temp_test_dir: Path) -> None:
        """Should exclude __init__.py and __main__.py."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "__init__.py").write_text(
            "def handle_command(): pass\n",
            encoding="utf-8",
        )
        (modules_dir / "__main__.py").write_text(
            "def handle_command(): pass\n",
            encoding="utf-8",
        )
        (modules_dir / "real.py").write_text(
            '"""Real module."""\ndef handle_command(command=None, args=None): pass\n',
            encoding="utf-8",
        )

        result = scan_module_files(str(temp_test_dir))

        names = [c["name"] for c in result]
        assert "__init__" not in names
        assert "__main__" not in names
        assert "real" in names

    def test_returns_empty_when_no_modules_dir(self, temp_test_dir: Path) -> None:
        """Should return empty list when apps/modules/ does not exist."""
        result = scan_module_files(str(temp_test_dir))
        assert result == []

    def test_extracts_module_description(self, temp_test_dir: Path) -> None:
        """Should extract the first line of the module docstring."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        (modules_dir / "config.py").write_text(
            '"""Configuration management for the branch."""\ndef handle_command(command=None, args=None): pass\n',
            encoding="utf-8",
        )

        result = scan_module_files(str(temp_test_dir))

        assert len(result) == 1
        assert result[0]["description"] == "Configuration management for the branch."

    def test_results_are_sorted(self, temp_test_dir: Path) -> None:
        """Results should be sorted alphabetically by module name."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        for name in ["zebra", "apple", "mango"]:
            (modules_dir / f"{name}.py").write_text(
                f'"""{name} module."""\ndef handle_command(): pass\n',
                encoding="utf-8",
            )

        result = scan_module_files(str(temp_test_dir))

        names = [c["name"] for c in result]
        assert names == sorted(names)


# =============================================================================
# scan_branch tests
# =============================================================================


class TestScanBranch:
    """Tests for scan_branch()."""

    def test_merges_help_and_module_results(self, temp_test_dir: Path) -> None:
        """Should combine help and module results, deduplicating by name."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        modules_dir = apps_dir / "modules"
        modules_dir.mkdir()
        (modules_dir / "extra.py").write_text(
            '"""Extra module."""\ndef handle_command(): pass\n',
            encoding="utf-8",
        )

        mock_result = MagicMock()
        mock_result.stdout = b"Commands:\n  audit    Run audit\n\n"
        mock_result.stderr = b""

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            return_value=mock_result,
        ):
            result = scan_branch(str(temp_test_dir), "mybranch")

        names = [c["name"] for c in result]
        assert "audit" in names
        assert "extra" in names

    def test_help_wins_on_duplicate(self, temp_test_dir: Path) -> None:
        """When a command appears in both help and module, help source should win."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir(parents=True)
        (apps_dir / "mybranch.py").write_text("# entry", encoding="utf-8")

        modules_dir = apps_dir / "modules"
        modules_dir.mkdir()
        # Module named "audit" -- same as a help command
        (modules_dir / "audit.py").write_text(
            '"""Audit module."""\ndef handle_command(): pass\n',
            encoding="utf-8",
        )

        mock_result = MagicMock()
        mock_result.stdout = b"Commands:\n  audit    Run audit from help\n\n"
        mock_result.stderr = b""

        with patch(
            "aipass.drone.apps.handlers.scanning.scanner.subprocess.run",
            return_value=mock_result,
        ):
            result = scan_branch(str(temp_test_dir), "mybranch")

        audit_cmds = [c for c in result if c["name"] == "audit"]
        assert len(audit_cmds) == 1
        assert audit_cmds[0]["source"] == "help"

    def test_returns_empty_when_nothing_found(self, temp_test_dir: Path) -> None:
        """Should return empty list when no commands found anywhere."""
        result = scan_branch(str(temp_test_dir), "empty")
        assert result == []

    def test_results_sorted_by_name(self, temp_test_dir: Path) -> None:
        """Results should be sorted alphabetically."""
        modules_dir = temp_test_dir / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        for name in ["zebra", "apple"]:
            (modules_dir / f"{name}.py").write_text(
                f'"""{name}."""\ndef handle_command(): pass\n',
                encoding="utf-8",
            )

        result = scan_branch(str(temp_test_dir), "test")

        names = [c["name"] for c in result]
        assert names == sorted(names)


# =============================================================================
# format_scan_results tests
# =============================================================================


class TestFormatScanResults:
    """Tests for format_scan_results()."""

    def test_produces_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should produce console output with command names."""
        commands = [
            {"name": "audit", "description": "Run audit", "source": "help"},
            {"name": "list", "description": "List items", "source": "module"},
        ]
        format_scan_results("testbranch", commands)

        captured = capsys.readouterr()
        assert "audit" in captured.out
        assert "list" in captured.out
        assert "@testbranch" in captured.out
        assert "command" in captured.out and "discovered" in captured.out

    def test_adds_at_prefix_if_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should add @ prefix for display when missing."""
        format_scan_results("mybranch", [{"name": "x", "description": "", "source": "help"}])

        captured = capsys.readouterr()
        assert "@mybranch" in captured.out

    def test_preserves_at_prefix(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should not double the @ prefix."""
        format_scan_results("@mybranch", [{"name": "x", "description": "", "source": "help"}])

        captured = capsys.readouterr()
        assert "@mybranch" in captured.out
        assert "@@mybranch" not in captured.out


# =============================================================================
# format_no_commands tests
# =============================================================================


class TestFormatNoCommands:
    """Tests for format_no_commands()."""

    def test_produces_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should produce informational console output."""
        format_no_commands("emptybranch")

        captured = capsys.readouterr()
        assert "No commands discovered" in captured.out
        assert "@emptybranch" in captured.out

    def test_adds_at_prefix_if_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should add @ prefix for display."""
        format_no_commands("mybranch")

        captured = capsys.readouterr()
        assert "@mybranch" in captured.out


# =============================================================================
# scan module handle_command tests
# =============================================================================


class TestScanHandleCommand:
    """Tests for scan.handle_command() routing."""

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_routes_to_scan(self, mock_scan: MagicMock) -> None:
        """Should call scan() with the target argument."""
        from aipass.drone.apps.modules.scan import handle_command

        mock_scan.return_value = [{"name": "x", "description": "", "source": "help"}]

        result = handle_command(command=None, args=["@testbranch"])

        assert result is True
        mock_scan.assert_called_once_with("@testbranch")

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_returns_false_when_scan_fails(self, mock_scan: MagicMock) -> None:
        """Should return False when scan returns None (resolution failure)."""
        from aipass.drone.apps.modules.scan import handle_command

        mock_scan.return_value = None

        result = handle_command(command=None, args=["@nonexistent"])

        assert result is False

    def test_no_args_shows_introspection(self) -> None:
        """Should call print_introspection when command is None and no args."""
        from aipass.drone.apps.modules.scan import handle_command

        with patch("aipass.drone.apps.modules.scan.print_introspection") as mock_intro:
            result = handle_command(command=None, args=None)

        assert result is True
        mock_intro.assert_called_once()

    def test_empty_args_returns_false(self) -> None:
        """Should return False when command is given but no args."""
        from aipass.drone.apps.modules.scan import handle_command

        result = handle_command(command="scan", args=[])

        assert result is False


# =============================================================================
# scan module scan() tests
# =============================================================================


class TestScanFunction:
    """Tests for scan.scan() orchestration."""

    @patch("aipass.drone.apps.modules.scan.resolve_branch")
    @patch("aipass.drone.apps.modules.scan.scan_branch")
    @patch("aipass.drone.apps.modules.scan.format_scan_results")
    def test_resolves_and_scans(
        self,
        mock_format: MagicMock,
        mock_scan_branch: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        """Should resolve target, scan, format, and return results."""
        from aipass.drone.apps.modules.scan import scan

        mock_resolve.return_value = "/fake/path"
        mock_scan_branch.return_value = [
            {"name": "audit", "description": "Run audit", "source": "help"},
        ]

        result = scan("@testbranch")

        mock_resolve.assert_called_once_with("@testbranch")
        mock_scan_branch.assert_called_once_with("/fake/path", "testbranch")
        mock_format.assert_called_once()
        assert result is not None
        assert len(result) == 1

    @patch("aipass.drone.apps.modules.scan.resolve_branch")
    @patch("aipass.drone.apps.modules.scan.scan_branch")
    @patch("aipass.drone.apps.modules.scan.format_no_commands")
    def test_shows_no_commands_message(
        self,
        mock_format_none: MagicMock,
        mock_scan_branch: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        """Should display no-commands message when scan finds nothing."""
        from aipass.drone.apps.modules.scan import scan

        mock_resolve.return_value = "/fake/path"
        mock_scan_branch.return_value = []

        result = scan("@emptybranch")

        mock_format_none.assert_called_once()
        assert result is not None  # Empty list, not None
        assert len(result) == 0

    @patch("aipass.drone.apps.modules.scan.resolve_branch", side_effect=Exception("not found"))
    def test_returns_none_on_resolution_failure(self, mock_resolve: MagicMock) -> None:
        """Should return None when branch resolution fails."""
        from aipass.drone.apps.modules.scan import scan

        result = scan("@nonexistent")

        assert result is None
