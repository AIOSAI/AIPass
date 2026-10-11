# =================== AIPass ====================
# Name: test_list_plans.py
# Description: Unit tests for apps/modules/list_plans.py
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/list_plans.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that list_plans.py parses and imports
# seedgo: no-test-needed(constant) — print_introspection's and print_help's literal banner text

import pytest
from unittest.mock import patch

from aipass.flow.apps.modules.list_plans import handle_command, list_plans

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
        assert handle_command("create", []) is False
        assert handle_command("close", ["open"]) is False
        assert handle_command("", []) is False

    def test_no_args_calls_introspection(self):
        """command == 'list' with no args should call print_introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            result = handle_command("list", [])

            mock_intro.assert_called_once()
            assert result is True

    @pytest.mark.parametrize("help_flag", ["--help", "-h", "help"])
    def test_help_flags_call_print_help(self, help_flag: str):
        """Help flags (--help, -h, help) should call print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            result = handle_command("list", [help_flag])

            mock_help.assert_called_once()
            assert result is True

    def test_filter_open(self):
        """'list open' should call list_plans with filter_type='open'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            result = handle_command("list", ["open"])

            mock_lp.assert_called_once_with("open")
            assert result is True

    def test_filter_closed(self):
        """'list closed' should call list_plans with filter_type='closed'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            result = handle_command("list", ["closed"])

            mock_lp.assert_called_once_with("closed")
            assert result is True

    def test_filter_all(self):
        """'list all' should call list_plans with filter_type='all'."""
        with patch(f"{_MOD}.list_plans") as mock_lp:
            result = handle_command("list", ["all"])

            mock_lp.assert_called_once_with("all")
            assert result is True

    def test_unknown_filter_is_refused_by_name_and_exits_non_zero(self, capsys: pytest.CaptureFixture[str]):
        """An unknown filter FAILS — it does not quietly become 'open'.

        Was pinned the other way ("defaults to open with a warning") until the
        2026-09-07 ruling: listing the open plans because the caller misspelled
        "closed" answers a question nobody asked, and exit 0 tells a script it
        got what it asked for. The listing must NOT run — that assertion is
        what catches a silent return of the default.
        Mutant: error(exc.message, suggestion=exc.usage) -> print(exc.message) reddens this.
        """
        with (
            patch(f"{_MOD}.list_plans") as mock_lp,
            patch(f"{_MOD}.error") as mock_error,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("list", ["garbage"])

        assert exit_info.value.code == 1
        mock_error.assert_called_once()
        assert "garbage" in mock_error.call_args[0][0]
        mock_lp.assert_not_called()
        # The refusal is the error line alone: nothing reaches stdout.
        assert capsys.readouterr().out == ""

    def test_a_trailing_argument_after_a_valid_filter_is_refused(self, capsys: pytest.CaptureFixture[str]):
        """`list open <typo>` reads nothing after the filter, so it refuses too.

        Mutant: error(exc.message, suggestion=exc.usage) -> print(exc.message) reddens this.
        """
        with (
            patch(f"{_MOD}.list_plans") as mock_lp,
            patch(f"{_MOD}.error") as mock_error,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("list", ["open", "stray_token"])

        assert exit_info.value.code == 1
        assert "stray_token" in mock_error.call_args[0][0]
        mock_lp.assert_not_called()
        assert capsys.readouterr().out == ""

    def test_json_handler_called_on_filter_commands(self):
        """json_handler.log_operation should be called for filter commands."""
        with patch(f"{_MOD}.list_plans", autospec=True), patch(f"{_MOD}.json_handler", spec=True) as mock_jh:
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

    def test_success_displays_formatted_output(self, capsys: pytest.CaptureFixture[str]):
        """Successful impl result should display formatted_list and formatted_stats.

        Mutant: console.print(result["formatted_stats"]) -> pass reddens this.
        """
        mock_result = {
            "success": True,
            "empty": False,
            "formatted_list": "[bold]Plan list output[/bold]",
            "formatted_stats": "[dim]3 plans total[/dim]",
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result) as mock_impl:
            result = list_plans("open")

            assert result is True
            mock_impl.assert_called_once()
        # Both formatted outputs reach stdout, list first, markup rendered away.
        out, _err = capsys.readouterr()
        assert out == "Plan list output\n3 plans total\n"

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
            patch(f"{_MOD}.load_registry", autospec=True) as mock_lr,
            patch(f"{_MOD}.get_registry_statistics") as mock_gs,
            patch(f"{_MOD}.format_plans_list") as mock_fpl,
            patch(f"{_MOD}.format_statistics_summary") as mock_fss,
        ):
            list_plans("closed")

            mock_impl.assert_called_once_with(
                filter_type="closed",
                load_registry=mock_lr,
                get_registry_statistics=mock_gs,
                format_plans_list=mock_fpl,
                format_statistics_summary=mock_fss,
            )

    def test_broken_pipe_during_display_does_not_crash(self, capsys: pytest.CaptureFixture[str]):
        """BrokenPipeError during console.print should be caught gracefully.

        The real console raises it while rendering the list, as it would on a
        closed pipe. Mutant: except BrokenPipeError: -> except KeyError: (the
        display one) reddens this.
        """

        class _ClosedPipeRenderable:
            def __rich__(self):
                raise BrokenPipeError("pipe closed")

        mock_result = {
            "success": True,
            "empty": False,
            "formatted_list": _ClosedPipeRenderable(),
            "formatted_stats": "stats",
            "filter_type": "open",
        }

        with patch(f"{_MOD}.list_plans_impl", return_value=mock_result):
            # Should not raise
            result = list_plans("open")
            assert result is True
        # The pipe broke on the first line, so the stats line is never attempted.
        out, _err = capsys.readouterr()
        assert out == ""

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

            # Should not raise
            result = list_plans("open")
            assert result is False
