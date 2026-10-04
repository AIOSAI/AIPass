# =================== AIPass ====================
# Name: test_close_plan.py
# Description: Tests for apps/modules/close_plan.py -- handle_command routing
# Version: 1.0.1
# Created: 2026-03-24
# Modified: 2026-10-04
# =============================================

"""Tests for apps/modules/close_plan.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that close_plan.py parses and imports
# seedgo: no-test-needed(constant) — print_introspection's and print_help's literal banner text

import pytest
from unittest.mock import patch

from aipass.flow.apps.handlers.plan.confirmation import confirm_plan_deletion
from aipass.flow.apps.modules.close_plan import close_all_plans, close_plan, handle_command

# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.modules.close_plan"
# parse_close_command_args is imported *inside* handle_command, not at module
# level, so we must patch it at the handler where it lives.
_PARSER = "aipass.flow.apps.handlers.plan.command_parser"


# ═══════════════════════════════════════════════════════════
# 1. Command != "close" -> returns False
# ═══════════════════════════════════════════════════════════


class TestCommandRouting:
    def test_wrong_command_returns_false(self):
        assert handle_command("create", []) is False

    def test_unrelated_command_returns_false(self):
        assert handle_command("aggregate", ["run"]) is False

    def test_empty_command_returns_false(self):
        assert handle_command("", []) is False


# ═══════════════════════════════════════════════════════════
# 2. command == "close" with no args -> introspection
# ═══════════════════════════════════════════════════════════


class TestIntrospection:
    @patch(f"{_MOD}.print_introspection")
    def test_no_args_calls_introspection(self, mock_introspection):
        result = handle_command("close", [])
        assert result is True
        mock_introspection.assert_called_once()

    @patch(f"{_MOD}.print_introspection")
    def test_no_args_does_not_parse(self, mock_introspection):
        """Introspection should not trigger argument parsing."""
        with patch(f"{_PARSER}.parse_close_command_args") as mock_parse:
            result = handle_command("close", [])
            assert result is True  # Command was handled
            mock_parse.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 3. command == "close" with --help -> help
# ═══════════════════════════════════════════════════════════


class TestHelp:
    @patch(f"{_MOD}.print_help")
    def test_help_flag(self, mock_help):
        result = handle_command("close", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_h_flag(self, mock_help):
        result = handle_command("close", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_help_word(self, mock_help):
        result = handle_command("close", ["help"])
        assert result is True
        mock_help.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 4. command == "close" with plan number -> calls close_plan
# ═══════════════════════════════════════════════════════════


class TestCloseSinglePlan:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, False, [], None))
    def test_plan_number_calls_close_plan(self, mock_parse, mock_close):
        result = handle_command("close", ["42"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="42",
            confirm=False,
            all_plans=False,
            dry_run=False,
            exclude_types=[],
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, False, [], None))
    def test_parse_receives_correct_args(self, mock_parse, mock_close):
        result = handle_command("close", ["42"])
        assert result is True  # Command was handled
        mock_parse.assert_called_once_with(["42"])

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("FPLAN-0042", False, False, False, [], None))
    def test_prefixed_plan_number(self, mock_parse, mock_close):
        result = handle_command("close", ["FPLAN-0042"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="FPLAN-0042",
            confirm=False,
            all_plans=False,
            dry_run=False,
            exclude_types=[],
        )


# ═══════════════════════════════════════════════════════════
# 5. command == "close" with --all -> calls close_plan(all_plans=True)
# ═══════════════════════════════════════════════════════════


class TestCloseAllPlans:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, False, True, False, [], None))
    def test_all_flag_calls_close_plan_with_all(self, mock_parse, mock_close):
        result = handle_command("close", ["--all"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=False,
            all_plans=True,
            dry_run=False,
            exclude_types=[],
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, True, True, False, [], None))
    def test_all_with_confirm(self, mock_parse, mock_close):
        result = handle_command("close", ["--all", "--confirm"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=True,
            all_plans=True,
            dry_run=False,
            exclude_types=[],
        )


# ═══════════════════════════════════════════════════════════
# 6. command == "close" with --dry-run -> passes dry_run flag
# ═══════════════════════════════════════════════════════════


class TestDryRun:
    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=("42", False, False, True, [], None))
    def test_dry_run_flag(self, mock_parse, mock_close):
        result = handle_command("close", ["--dry-run", "42"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num="42",
            confirm=False,
            all_plans=False,
            dry_run=True,
            exclude_types=[],
        )

    @patch(f"{_MOD}.close_plan")
    @patch(f"{_PARSER}.parse_close_command_args", return_value=(None, False, True, True, [], None))
    def test_dry_run_with_all(self, mock_parse, mock_close):
        result = handle_command("close", ["--all", "--dry-run"])
        assert result is True
        mock_close.assert_called_once_with(
            plan_num=None,
            confirm=False,
            all_plans=True,
            dry_run=True,
            exclude_types=[],
        )


# ═══════════════════════════════════════════════════════════
# 7. Parse error -> displays usage error, returns True
# ═══════════════════════════════════════════════════════════


class TestParseError:
    @patch(f"{_MOD}.format_delete_usage_error", return_value="Usage error text")
    @patch(f"{_MOD}.close_plan")
    @patch(
        f"{_PARSER}.parse_close_command_args",
        return_value=(None, False, False, False, [], "Plan number or --all required"),
    )
    def test_parse_error_exits_non_zero_without_closing_anything(self, mock_parse, mock_close, mock_format):
        """A refused close FAILS.

        Was pinned as "still a handled command" returning True, which flow.py
        turns into exit 0 — so `drone @flow close not_a_plan && next_step` ran
        the next step as if a plan had closed (ruling 2026-09-07). Handled and
        succeeded are different answers; the refusal itself was always correct.
        """
        with pytest.raises(SystemExit) as exit_info:
            handle_command("close", ["--unknown-flag"])
        assert exit_info.value.code == 1
        mock_close.assert_not_called()

    @patch(f"{_MOD}.error_display")
    @patch(f"{_MOD}.close_plan")
    @patch(
        f"{_PARSER}.parse_close_command_args",
        return_value=(None, False, False, False, [], "Unknown plan type(s): APLNA. Registered: APLAN, FPLAN"),
    )
    def test_parse_error_prints_the_parsers_own_reason(self, mock_parse, mock_close, mock_error):
        """The specific reason reaches the operator, not a fixed usage block.

        The generic block said "ERROR: Plan number required / Usage: delete
        <plan_number>" for EVERY parse failure -- wrong verb, and a false
        diagnosis printed under a true refusal.
        """
        with pytest.raises(SystemExit) as exit_info:
            handle_command("close", ["--all", "--exclude-type", "APLNA"])
        assert exit_info.value.code == 1  # Handled, refused, and it says so
        mock_error.assert_called_once_with("Unknown plan type(s): APLNA. Registered: APLAN, FPLAN")

    @patch(f"{_MOD}.format_delete_usage_error", return_value="Usage error text")
    @patch(f"{_MOD}.close_plan")
    @patch(
        f"{_PARSER}.parse_close_command_args",
        return_value=(None, False, False, False, [], "Plan number or --all required"),
    )
    def test_parse_error_does_not_print_the_misleading_usage_block(self, mock_parse, mock_close, mock_format):
        with pytest.raises(SystemExit):
            handle_command("close", ["--unknown-flag"])
        mock_format.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 8. close_plan orchestrator delegates to close_plan_impl
# ═══════════════════════════════════════════════════════════


class TestClosePlanOrchestrator:
    @patch(f"{_MOD}.close_plan_impl", return_value={"success": True, "messages": []})
    def test_close_plan_impl_success(self, mock_impl):
        result = close_plan(plan_num="42")
        assert result is True
        mock_impl.assert_called_once()

    @patch(f"{_MOD}.close_plan_impl", return_value={"success": False, "messages": []})
    def test_close_plan_impl_failure(self, mock_impl):
        result = close_plan(plan_num="42")
        assert result is False

    @patch(f"{_MOD}.close_plan_impl", return_value=True)
    def test_close_plan_impl_bool_fallback(self, mock_impl):
        """Handler may return a plain bool for backward compatibility."""
        result = close_plan(plan_num="42")
        assert result is True


# ═══════════════════════════════════════════════════════════
# 9. close_all_plans delegates to close_all_plans_impl
# ═══════════════════════════════════════════════════════════


class TestCloseAllOrchestrator:
    @patch(f"{_MOD}.close_all_plans_impl", return_value={"success": True, "messages": []})
    def test_close_all_success(self, mock_impl):
        result = close_all_plans()
        assert result is True

    @patch(f"{_MOD}.close_all_plans_impl", return_value={"success": False, "messages": []})
    def test_close_all_failure(self, mock_impl):
        result = close_all_plans()
        assert result is False

    @patch(f"{_MOD}.close_all_plans_impl", return_value=False)
    def test_close_all_bool_fallback(self, mock_impl):
        result = close_all_plans()
        assert result is False


# ═══════════════════════════════════════════════════════════
# 10. --confirm: the prompt close_plan hands to close_plan_impl
# ═══════════════════════════════════════════════════════════


class _Terminal:
    """Stands in for the TTY question and the prompt; records what the product asked."""

    def __init__(self, tty: bool, answers: list[str | None]):
        self.tty = tty
        self.answers = answers
        self.tty_checks = 0
        self.prompts: list[str] = []

    def isatty(self) -> bool:
        self.tty_checks += 1
        return self.tty

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if answer is None:
            raise EOFError
        return answer


class TestConfirmPlanDeletion:
    def test_input_that_ends_before_an_answer_is_not_a_yes(self):
        """Shipped defect: EOF at the --confirm prompt answered True and closed the plan."""
        term = _Terminal(tty=True, answers=[None])
        assert confirm_plan_deletion("0042", ask=term.ask, interactive=term.isatty) is None
        assert term.prompts == ["Close FPLAN-0042? (yes/no): "]

    def test_yes_confirms_and_no_cancels_at_a_tty(self):
        term = _Terminal(tty=True, answers=[" Y ", "no"])
        assert confirm_plan_deletion("0042", ask=term.ask, interactive=term.isatty) is True
        assert confirm_plan_deletion("0042", ask=term.ask, interactive=term.isatty) is False
        assert term.prompts == ["Close FPLAN-0042? (yes/no): "] * 2
        assert term.tty_checks == 2

    def test_no_tty_confirms_without_asking(self):
        term = _Terminal(tty=False, answers=[])
        assert confirm_plan_deletion("0042", ask=term.ask, interactive=term.isatty) is True
        assert term.prompts == []
        assert term.tty_checks == 1
