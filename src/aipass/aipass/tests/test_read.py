# =================== AIPass ====================
# Name: test_read.py
# Description: Tests for aipass read — branch README rendering
# Version: 1.3.1
# Created: 2026-08-07
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/read.py — aipass read command."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — get_readme_path, list_branches and read_readme_at's
# seedgo: no-test-needed(covered_elsewhere) — own behavior; see tests/test_readme_map.py

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.aipass.apps.modules.read import COMMAND, handle_command

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"

_MOD = "aipass.aipass.apps.modules.read"


# =============================================================================
# TestHandleCommand — routing
# =============================================================================


class TestHandleCommandRouting:
    """Routing contract of handle_command."""

    def test_ignores_other_commands(self) -> None:
        """Returns False for commands it does not own."""
        assert handle_command("doctor", []) is False

    def test_command_constant(self) -> None:
        """COMMAND is 'read'."""
        assert COMMAND == "read"

    def test_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: help usage line not printed -> red."""
        with patch(f"{_MOD}.json_handler", autospec=True):
            assert handle_command("read", ["--help"]) is True
        out, _err = capsys.readouterr()
        assert "aipass read <branch>" in out

    def test_info_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: Module line not printed -> red."""
        with patch(f"{_MOD}.json_handler", autospec=True):
            assert handle_command("read", ["--info"]) is True
        out, _err = capsys.readouterr()
        assert "Module:" in out


# =============================================================================
# TestBranchList — bare invocation
# =============================================================================


class TestBranchList:
    """Bare `aipass read` shows introspection — module identity plus the roster."""

    def test_lists_branches(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: branch loop prints nothing -> red."""
        with patch(f"{_MOD}.list_branches", return_value=["drone", "hooks"]):
            with patch(f"{_MOD}.json_handler", autospec=True):
                assert handle_command("read", []) is True
        out, _err = capsys.readouterr()
        assert "  drone" in out
        assert "  hooks" in out

    def test_no_args_shows_introspection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No-args gate reports module identity, per the introspection standard.

        Mutant: no-args routes to branch list only -> red.
        """
        with patch(f"{_MOD}.list_branches", return_value=["drone"]):
            with patch(f"{_MOD}.json_handler", autospec=True):
                assert handle_command("read", []) is True
        out, _err = capsys.readouterr()
        assert "Module:" in out
        assert "Version:" in out

    def test_roster_is_live_not_cached(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: roster is a frozen list -> red."""
        with patch(f"{_MOD}.list_branches", return_value=["zeta_brand_new"]):
            with patch(f"{_MOD}.json_handler", autospec=True):
                handle_command("read", [])
        out, _err = capsys.readouterr()
        assert "zeta_brand_new" in out


# =============================================================================
# TestRenderReadme — read <branch>
# =============================================================================


class TestRenderReadme:
    """`aipass read <branch>` renders the live README."""

    def test_renders_existing_readme(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """README content is live-read and rendered.

        Mutant: Markdown body not printed -> red.
        """
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\nRoutes commands.\n", encoding="utf-8")
        with patch(f"{_MOD}.get_readme_path", return_value=readme):
            with patch(f"{_MOD}.json_handler", autospec=True):
                assert handle_command("read", ["drone"]) is True
        out, _err = capsys.readouterr()
        assert "README.md" in out
        assert "Routes commands." in out
        assert "# Drone" not in out

    def test_at_prefix_stripped(self, tmp_path: Path) -> None:
        """@drone resolves the same as drone."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\n", encoding="utf-8")
        with patch(f"{_MOD}.get_readme_path", return_value=readme) as mock_get:
            with patch(f"{_MOD}.json_handler", autospec=True):
                handle_command("read", ["@drone"])
        mock_get.assert_called_once_with("drone")

    def test_unknown_branch_errors_with_available(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: Available roster line dropped -> red."""
        with patch(f"{_MOD}.get_readme_path", return_value=None):
            with patch(f"{_MOD}.list_branches", return_value=["drone", "prax"]):
                with patch(f"{_MOD}.json_handler", autospec=True):
                    assert handle_command("read", ["nope"]) is True
        out, err = capsys.readouterr()
        assert "No README found for branch 'nope'" in err
        assert "Available: drone, prax" in out

    def test_reads_through_the_handler(self, tmp_path: Path) -> None:
        """The module never touches the filesystem itself — readme_map owns the read."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\n", encoding=_ENCODING)
        with patch(f"{_MOD}.get_readme_path", return_value=readme):
            with patch(f"{_MOD}.read_readme_at", return_value="# Handler\n") as mock_read:
                with patch(f"{_MOD}.json_handler", autospec=True):
                    assert handle_command("read", ["drone"]) is True
        mock_read.assert_called_once_with(readme)

    def test_unreadable_file_errors(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """OSError on read surfaces as an error, not a crash.

        Mutant: OSError swallowed silently -> red.
        """
        missing = tmp_path / "gone" / "README.md"
        with patch(f"{_MOD}.get_readme_path", return_value=missing):
            with patch(f"{_MOD}.json_handler", autospec=True):
                assert handle_command("read", ["drone"]) is True
        _out, err = capsys.readouterr()
        assert "Could not read" in err
