# =================== AIPass ====================
# Name: test_list_plans.py
# Description: Unit tests for apps/modules/list_plans.py
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for the list_plans module -- command routing and orchestration."""

import pytest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Module-level patch targets (patch where used, not where defined)
# ---------------------------------------------------------------------------

_MOD = "aipass.flow.apps.modules.list_plans"


# ---------------------------------------------------------------------------
# handle_command routing tests
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    """Verify handle_command routes to the correct function for each input."""

    def test_wrong_command_returns_false(self):
        """command != 'list' should return False immediately."""
        from aipass.flow.apps.modules.list_plans import handle_command

        assert handle_command("create", []) is False
        assert handle_command("close", ["open"]) is False
        assert handle_command("", []) is False

    def test_no_args_calls_introspection(self):
        """command == 'list' with no args should call print_introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", [])

            mock_intro.assert_called_once()
            assert result is True

    @pytest.mark.parametrize("help_flag", ["--help", "-h", "help"])
    def test_help_flags_call_print_help(self, help_flag: str):
        """Help flags (--help, -h, help) should call print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", [help_flag])

            mock_help.assert_called_once()
            assert result is True

    def test_filter_open(self):
        """'list open' should call list_plans with filter_type='open'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", ["open"])

            mock_lp.assert_called_once_with("open")
            assert result is True

    def test_filter_closed(self):
        """'list closed' should call list_plans with filter_type='closed'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", ["closed"])

            mock_lp.assert_called_once_with("closed")
            assert result is True

    def test_filter_all(self):
        """'list all' should call list_plans with filter_type='all'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", ["all"])

            mock_lp.assert_called_once_with("all")
            assert result is True

    def test_unknown_filter_defaults_to_open_with_warning(self):
        """Unknown filter arg should default to 'open' and emit a warning."""
        with patch(f"{_MOD}.list_plans") as mock_lp, patch(f"{_MOD}.warning") as mock_warn, patch(f"{_MOD}.console"):
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", ["garbage"])

            mock_warn.assert_called_once()
            assert "garbage" in mock_warn.call_args[0][0]
            mock_lp.assert_called_once_with("open")
            assert result is True

    def test_json_handler_called_on_filter_commands(self):
        """json_handler.log_operation should be called for filter commands."""
        with patch(f"{_MOD}.list_plans"), patch(f"{_MOD}.json_handler") as mock_jh:
            from aipass.flow.apps.modules.list_plans import handle_command

            result = handle_command("list", ["open"])

            assert result is True  # Command was handled
            mock_jh.log_operation.assert_called_once_with(
                "plans_listed",
                {"command": "list", "args": ["open"]},
            )


# ---------------------------------------------------------------------------
# list_plans orchestrator tests
# ---------------------------------------------------------------------------


class TestListPlansOrchestrator:
    """Verify list_plans delegates to list_plans_impl and displays results."""

    def test_success_displays_formatted_output(self):
        """Successful impl result should display formatted_list and formatted_stats."""
        mock_result = {
            "success": True,
            "empty": False,
            "formatted_list": "[bold]Plan list output[/bold]",
            "formatted_stats": "[dim]3 plans total[/dim]",
            "filter_type": "open",
        }

        with (
            patch(f"{_MOD}.list_plans_impl", return_value=mock_result) as mock_impl,
            patch(f"{_MOD}.console") as mock_console,
        ):
            from aipass.flow.apps.modules.list_plans import list_plans

            result = list_plans("open")

            assert result is True
            mock_impl.assert_called_once()
            # Verify both formatted outputs are printed
            calls = mock_console.print.call_args_list
            assert any("[bold]Plan list output[/bold]" in str(c) for c in calls)
            assert any("[dim]3 plans total[/dim]" in str(c) for c in calls)

    def test_empty_result_shows_warning(self):
        """Empty + success result should display a warning."""
        mock_result = {
            "success": True,
            "empty": True,
            "formatted_list": "",
            "formatted_stats": "",
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result), patch(f"{_MOD}.warning") as mock_warn:
            from aipass.flow.apps.modules.list_plans import list_plans

            result = list_plans("all")

            assert result is True
            mock_warn.assert_called_once_with("No plans found in registry")

    def test_error_result_displays_error(self):
        """Failed impl result should display the error message."""
        mock_result = {
            "success": False,
            "error": "Registry file not found",
            "formatted_list": "",
            "formatted_stats": "",
            "empty": True,
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result), patch(f"{_MOD}.error") as mock_error:
            from aipass.flow.apps.modules.list_plans import list_plans

            result = list_plans("open")

            assert result is False
            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("ERROR:")

    def test_error_result_without_message_shows_unknown(self):
        """Failed impl result without error key should show 'Unknown error'."""
        mock_result = {
            "success": False,
            "formatted_list": "",
            "formatted_stats": "",
            "empty": True,
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result), patch(f"{_MOD}.error") as mock_error:
            from aipass.flow.apps.modules.list_plans import list_plans

            result = list_plans("open")

            assert result is False
            assert "Unknown error" in mock_error.call_args[0][0]

    def test_impl_receives_injected_dependencies(self):
        """list_plans_impl should receive all handler functions as kwargs."""
        mock_result = {
            "success": True,
            "empty": True,
            "formatted_list": "",
            "formatted_stats": "",
            "filter_type": "open",
        }

        with (
            patch(f"{_MOD}.list_plans_impl", return_value=mock_result) as mock_impl,
            patch(f"{_MOD}.load_registry") as mock_lr,
            patch(f"{_MOD}.get_registry_statistics") as mock_gs,
            patch(f"{_MOD}.format_plans_list") as mock_fpl,
            patch(f"{_MOD}.format_statistics_summary") as mock_fss,
        ):
            from aipass.flow.apps.modules.list_plans import list_plans

            list_plans("closed")

            mock_impl.assert_called_once_with(
                filter_type="closed",
                load_registry=mock_lr,
                get_registry_statistics=mock_gs,
                format_plans_list=mock_fpl,
                format_statistics_summary=mock_fss,
            )

    def test_broken_pipe_during_display_does_not_crash(self):
        """BrokenPipeError during console.print should be caught gracefully."""
        mock_result = {
            "success": True,
            "empty": False,
            "formatted_list": "output",
            "formatted_stats": "stats",
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result), patch(f"{_MOD}.console") as mock_console:
            mock_console.print.side_effect = BrokenPipeError("pipe closed")

            from aipass.flow.apps.modules.list_plans import list_plans

            # Should not raise
            result = list_plans("open")
            assert result is True

    def test_broken_pipe_during_error_display_does_not_crash(self):
        """BrokenPipeError during error display should be caught."""
        mock_result = {
            "success": False,
            "error": "something broke",
            "formatted_list": "",
            "formatted_stats": "",
            "empty": True,
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result), patch(f"{_MOD}.error") as mock_error:
            mock_error.side_effect = BrokenPipeError("pipe closed")

            from aipass.flow.apps.modules.list_plans import list_plans

            # Should not raise
            result = list_plans("open")
            assert result is False
