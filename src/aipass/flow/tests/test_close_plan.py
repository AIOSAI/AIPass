"""Tests for close_plan module -- handle_command routing."""

from unittest.mock import patch


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.modules.close_plan"
# parse_close_command_args is imported *inside* handle_command, not at module
# level, so we must patch it at the handler where it lives.
_PARSER = "aipass.flow.apps.handlers.plan.command_parser"


# ─── Helpers ─────────────────────────────────────────────


def _import_handle_command():
    """Import handle_command inside each test so autouse mocks are active."""
    from aipass.flow.apps.modules.close_plan import handle_command

    return handle_command


def _import_close_plan():
    """Import close_plan orchestrator."""
    from aipass.flow.apps.modules.close_plan import close_plan

    return close_plan


def _import_close_all_plans():
    """Import close_all_plans orchestrator."""
    from aipass.flow.apps.modules.close_plan import close_all_plans

    return close_all_plans


# ═══════════════════════════════════════════════════════════
# 1. Command != "close" -> returns False
# ═══════════════════════════════════════════════════════════


class TestCommandRouting:
    def test_wrong_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("create", []) is False

    def test_unrelated_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("aggregate", ["run"]) is False

    def test_empty_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("", []) is False


# ═══════════════════════════════════════════════════════════
# 2. command == "close" with no args -> introspection
# ═══════════════════════════════════════════════════════════


class TestIntrospection:
    @patch(f"{_MOD}.print_introspection")
    def test_no_args_calls_introspection(self, mock_introspection):
        handle_command = _import_handle_command()
        result = handle_command("close", [])
        assert result is True
        mock_introspection.assert_called_once()

    @patch(f"{_MOD}.print_introspection")
    def test_no_args_does_not_parse(self, mock_introspection):
        """Introspection should not trigger argument parsing."""
        with patch(f"{_PARSER}.parse_close_command_args") as mock_parse:
            handle_command = _import_handle_command()
            result = handle_command("close", [])
            assert result is True  # Command was handled
            mock_parse.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 3. command == "close" with --help -> help
# ═══════════════════════════════════════════════════════════


class TestHelp:
    @patch(f"{_MOD}.print_help")
    def test_help_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_h_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("close", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_help_word(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("close", ["help"])
        assert result is True
        mock_help.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 4. command == "close" with plan number -> calls close_plan
# ═══════════════════════════════════════════════════════════


class TestCloseSinglePlan:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, False, None))
    def test_plan_number_calls_close_plan(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["42"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="42",
            confirm=False,
            all_plans=False,
            dry_run=False,
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, False, None))
    def test_parse_receives_correct_args(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["42"])
        assert result is True  # Command was handled
        mock_parse.assert_called_once_with(["42"])

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("FPLAN-0042", False, False, False, None))
    def test_prefixed_plan_number(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["FPLAN-0042"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="FPLAN-0042",
            confirm=False,
            all_plans=False,
            dry_run=False,
        )


# ═══════════════════════════════════════════════════════════
# 5. command == "close" with --all -> calls close_plan(all_plans=True)
# ═══════════════════════════════════════════════════════════


class TestCloseAllPlans:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, False, True, False, None))
    def test_all_flag_calls_close_plan_with_all(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--all"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=False,
            all_plans=True,
            dry_run=False,
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, True, True, False, None))
    def test_all_with_confirm(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--all", "--confirm"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=True,
            all_plans=True,
            dry_run=False,
        )


# ═══════════════════════════════════════════════════════════
# 6. command == "close" with --dry-run -> passes dry_run flag
# ═══════════════════════════════════════════════════════════


class TestDryRun:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, True, None))
    def test_dry_run_flag(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--dry-run", "42"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="42",
            confirm=False,
            all_plans=False,
            dry_run=True,
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, False, True, True, None))
    def test_dry_run_with_all(self, mock_parse, mock_close):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--all", "--dry-run"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=False,
            all_plans=True,
            dry_run=True,
        )


# ═══════════════════════════════════════════════════════════
# 7. Parse error -> displays usage error, returns True
# ═══════════════════════════════════════════════════════════


class TestParseError:
    @patch(f"{_MOD}.format_delete_usage_error", return_value="Usage error text")
    @patch(f"{_MOD}.close_plan")
    @patch(
        f"{_PARSER}.parse_close_command_args", return_value=(None, False, False, False, "Plan number or --all required")
    )
    def test_parse_error_returns_true(self, mock_parse, mock_close, mock_format):
        """Parse error is still a handled command."""
        handle_command = _import_handle_command()
        result = handle_command("close", ["--unknown-flag"])
        assert result is True
        mock_close.assert_not_called()

    @patch(f"{_MOD}.format_delete_usage_error", return_value="Usage error text")
    @patch(f"{_MOD}.close_plan")
    @patch(
        f"{_PARSER}.parse_close_command_args", return_value=(None, False, False, False, "Plan number or --all required")
    )
    def test_parse_error_shows_usage(self, mock_parse, mock_close, mock_format):
        handle_command = _import_handle_command()
        result = handle_command("close", ["--unknown-flag"])
        assert result is True  # Command was handled (error displayed)
        mock_format.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 8. close_plan orchestrator delegates to close_plan_impl
# ═══════════════════════════════════════════════════════════


class TestClosePlanOrchestrator:
    @patch(f"{_MOD}.close_plan_impl", return_value={"success": True, "messages": []})
    def test_close_plan_impl_success(self, mock_impl):
        close_plan = _import_close_plan()
        result = close_plan(plan_num="42")
        assert result is True
        mock_impl.assert_called_once()

    @patch(f"{_MOD}.close_plan_impl", return_value={"success": False, "messages": []})
    def test_close_plan_impl_failure(self, mock_impl):
        close_plan = _import_close_plan()
        result = close_plan(plan_num="42")
        assert result is False

    @patch(f"{_MOD}.close_plan_impl", return_value=True)
    def test_close_plan_impl_bool_fallback(self, mock_impl):
        """Handler may return a plain bool for backward compatibility."""
        close_plan = _import_close_plan()
        result = close_plan(plan_num="42")
        assert result is True


# ═══════════════════════════════════════════════════════════
# 9. close_all_plans delegates to close_all_plans_impl
# ═══════════════════════════════════════════════════════════


class TestCloseAllOrchestrator:
    @patch(f"{_MOD}.close_all_plans_impl", return_value={"success": True, "messages": []})
    def test_close_all_success(self, mock_impl):
        close_all_plans = _import_close_all_plans()
        result = close_all_plans()
        assert result is True

    @patch(f"{_MOD}.close_all_plans_impl", return_value={"success": False, "messages": []})
    def test_close_all_failure(self, mock_impl):
        close_all_plans = _import_close_all_plans()
        result = close_all_plans()
        assert result is False

    @patch(f"{_MOD}.close_all_plans_impl", return_value=False)
    def test_close_all_bool_fallback(self, mock_impl):
        close_all_plans = _import_close_all_plans()
        result = close_all_plans()
        assert result is False
