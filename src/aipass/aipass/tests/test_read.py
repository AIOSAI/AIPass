# =================== AIPass ====================
# Name: test_read.py
# Description: Tests for aipass read — branch README rendering
# Version: 1.1.0
# Created: 2026-08-07
# Modified: 2026-08-08
# =============================================

"""Tests for read.py — aipass read command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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

    def test_help_flag(self) -> None:
        """--help prints usage and returns True."""
        with patch(f"{_MOD}.console") as mock_con:
            with patch(f"{_MOD}.json_handler"):
                assert handle_command("read", ["--help"]) is True
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "aipass read" in printed

    def test_info_flag(self) -> None:
        """--info prints introspection and returns True."""
        with patch(f"{_MOD}.console") as mock_con:
            with patch(f"{_MOD}.json_handler"):
                assert handle_command("read", ["--info"]) is True
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "read" in printed


# =============================================================================
# TestBranchList — bare invocation
# =============================================================================


class TestBranchList:
    """Bare `aipass read` shows introspection — module identity plus the roster."""

    def test_lists_branches(self) -> None:
        """All branches from list_branches appear in output."""
        with patch(f"{_MOD}.list_branches", return_value=["drone", "hooks"]):
            with patch(f"{_MOD}.console") as mock_con:
                with patch(f"{_MOD}.json_handler"):
                    assert handle_command("read", []) is True
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "drone" in printed
        assert "hooks" in printed

    def test_no_args_shows_introspection(self) -> None:
        """No-args gate reports module identity, per the introspection standard."""
        with patch(f"{_MOD}.list_branches", return_value=["drone"]):
            with patch(f"{_MOD}.console") as mock_con:
                with patch(f"{_MOD}.json_handler"):
                    assert handle_command("read", []) is True
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "Module:" in printed
        assert "Version:" in printed

    def test_roster_is_live_not_cached(self) -> None:
        """The roster comes from list_branches on every call, never a frozen list."""
        with patch(f"{_MOD}.list_branches", return_value=["zeta_brand_new"]):
            with patch(f"{_MOD}.console") as mock_con:
                with patch(f"{_MOD}.json_handler"):
                    handle_command("read", [])
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "zeta_brand_new" in printed


# =============================================================================
# TestRenderReadme — read <branch>
# =============================================================================


class TestRenderReadme:
    """`aipass read <branch>` renders the live README."""

    def test_renders_existing_readme(self, tmp_path: Path) -> None:
        """README content is live-read and rendered."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\nRoutes commands.\n", encoding="utf-8")
        with patch(f"{_MOD}.get_readme_path", return_value=readme):
            with patch(f"{_MOD}.console") as mock_con:
                with patch(f"{_MOD}.json_handler"):
                    assert handle_command("read", ["drone"]) is True
        # Path header printed + a Markdown object rendered
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert str(readme) in printed
        rendered_types = [type(a).__name__ for call in mock_con.print.call_args_list for a in call[0]]
        assert "Markdown" in rendered_types

    def test_at_prefix_stripped(self, tmp_path: Path) -> None:
        """@drone resolves the same as drone."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\n", encoding="utf-8")
        with patch(f"{_MOD}.get_readme_path", return_value=readme) as mock_get:
            with patch(f"{_MOD}.console"):
                with patch(f"{_MOD}.json_handler"):
                    handle_command("read", ["@drone"])
        mock_get.assert_called_once_with("drone")

    def test_unknown_branch_errors_with_available(self) -> None:
        """Unknown branch prints an error plus the available roster."""
        with patch(f"{_MOD}.get_readme_path", return_value=None):
            with patch(f"{_MOD}.list_branches", return_value=["drone", "prax"]):
                with patch(f"{_MOD}.console") as mock_con:
                    with patch(f"{_MOD}.error") as mock_err:
                        with patch(f"{_MOD}.json_handler"):
                            assert handle_command("read", ["nope"]) is True
        err_text = " ".join(str(a) for call in mock_err.call_args_list for a in call[0])
        assert "nope" in err_text
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "drone" in printed

    def test_reads_through_the_handler(self, tmp_path: Path) -> None:
        """The module never touches the filesystem itself — readme_map owns the read."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\n", encoding=_ENCODING)
        with patch(f"{_MOD}.get_readme_path", return_value=readme):
            with patch(f"{_MOD}.read_readme_at", return_value="# Handler\n") as mock_read:
                with patch(f"{_MOD}.console"):
                    with patch(f"{_MOD}.json_handler"):
                        assert handle_command("read", ["drone"]) is True
        mock_read.assert_called_once_with(readme)

    def test_unreadable_file_errors(self, tmp_path: Path) -> None:
        """OSError on read surfaces as an error, not a crash."""
        missing = tmp_path / "gone" / "README.md"
        with patch(f"{_MOD}.get_readme_path", return_value=missing):
            with patch(f"{_MOD}.console"):
                with patch(f"{_MOD}.error") as mock_err:
                    with patch(f"{_MOD}.json_handler"):
                        assert handle_command("read", ["drone"]) is True
        assert mock_err.called
