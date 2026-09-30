# =================== AIPass ====================
# Name: test_aggregate_central.py
# Description: Tests for the aggregate command - routing, heal flags, card sweep
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/aggregate_central.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports
# seedgo: no-test-needed(help_text) — the wording of print_help and print_introspection

from unittest.mock import patch

import pytest

from aipass.flow.apps.modules.aggregate_central import aggregate_central, handle_command


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.modules.aggregate_central"


# ═══════════════════════════════════════════════════════════
# 1. Command != "aggregate" -> returns False
# ═══════════════════════════════════════════════════════════


class TestCommandRouting:
    def test_wrong_command_returns_false(self):
        assert handle_command("create", []) is False

    def test_unrelated_command_returns_false(self):
        assert handle_command("close", ["42"]) is False

    def test_empty_command_returns_false(self):
        assert handle_command("", []) is False


# ═══════════════════════════════════════════════════════════
# 2. command == "aggregate" with no args -> introspection
# ═══════════════════════════════════════════════════════════


class TestNoArgs:
    @patch(f"{_MOD}.print_introspection")
    def test_no_args_calls_introspection(self, mock_intro):
        """No args should show introspection."""
        result = handle_command("aggregate", [])
        assert result is True
        mock_intro.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 3. command == "aggregate" with --help -> help
# ═══════════════════════════════════════════════════════════


class TestHelp:
    @patch(f"{_MOD}.print_help")
    def test_help_flag(self, mock_help):
        result = handle_command("aggregate", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_h_flag(self, mock_help):
        result = handle_command("aggregate", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_help_word(self, mock_help):
        result = handle_command("aggregate", ["help"])
        assert result is True
        mock_help.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 4. command == "aggregate" with ["run"] -> calls aggregate_central(heal=True)
# ═══════════════════════════════════════════════════════════


class TestRunCommand:
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_run_calls_aggregate_with_heal(self, mock_aggregate):
        result = handle_command("aggregate", ["--heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=True)

    @patch(f"{_MOD}.aggregate_central", return_value=False)
    def test_run_returns_false_on_failure(self, mock_aggregate):
        result = handle_command("aggregate", ["--heal"])
        assert result is False

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_no_heal_wins_over_an_explicit_heal(self, mock_aggregate):
        """Heal auto-closes rows in branch registries, so asking for both runs the safe one.
        Mutant: if "--no-heal" in args: -> if "--no-heal" in args and "--heal" not in args: reddens this."""
        result = handle_command("aggregate", ["--heal", "--no-heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=False)


# ═══════════════════════════════════════════════════════════
# 5. command == "aggregate" with ["--no-heal"] -> calls aggregate_central(heal=False)
# ═══════════════════════════════════════════════════════════


class TestNoHealFlag:
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_no_heal_flag(self, mock_aggregate):
        result = handle_command("aggregate", ["--no-heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=False)

    @patch(f"{_MOD}.push_flow_to_all_branch_dashboards", return_value={"pushed": 1, "skipped": 0, "failed": 0})
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_no_heal_holds_when_the_card_sweep_rides_along(self, mock_aggregate, sweep):
        """The sweep flag must not reset the heal choice; the sweep is stubbed, it writes every card.
        Mutant: heal = False -> heal = "--sweep-cards" in args reddens this."""
        result = handle_command("aggregate", ["--sweep-cards", "--no-heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=False)
        sweep.assert_called_once_with()


# ═══════════════════════════════════════════════════════════
# 6. aggregate_central orchestrator delegates to aggregate_central_impl
# ═══════════════════════════════════════════════════════════


class TestAggregateCentralOrchestrator:
    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_impl_success_returns_true(self, mock_impl):
        result = aggregate_central(heal=True)
        assert result is True
        mock_impl.assert_called_once()
        # Verify heal and path args are passed through
        call_kwargs = mock_impl.call_args[1]
        assert call_kwargs["heal"] is True
        assert "central_file" in call_kwargs
        assert "central_dir" in call_kwargs

    @patch(f"{_MOD}.aggregate_central_impl", return_value=False)
    def test_impl_failure_returns_false(self, mock_impl):
        result = aggregate_central(heal=True)
        assert result is False

    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_heal_false_passed_to_impl(self, mock_impl):
        result = aggregate_central(heal=False)
        assert result is True  # Impl succeeded
        call_kwargs = mock_impl.call_args[1]
        assert call_kwargs["heal"] is False

    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_default_heal_is_true(self, mock_impl):
        result = aggregate_central()
        assert result is True  # Impl succeeded
        call_kwargs = mock_impl.call_args[1]
        assert call_kwargs["heal"] is True


# ═══════════════════════════════════════════════════════════
# 7. json_handler.log_operation is called on valid commands
# ═══════════════════════════════════════════════════════════


class TestOperationLogging:
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    @patch(f"{_MOD}.json_handler", spec=True)
    def test_logs_operation(self, mock_jh, mock_aggregate):
        result = handle_command("aggregate", ["--heal"])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_called_once_with(
            "central_aggregated",
            {"command": "aggregate", "args": ["--heal"]},
        )

    @patch(f"{_MOD}.print_introspection")
    @patch(f"{_MOD}.json_handler", spec=True)
    def test_no_logging_on_introspection(self, mock_jh, mock_intro):
        """Introspection (no args) should not log an operation."""
        result = handle_command("aggregate", [])
        assert result is True
        mock_jh.log_operation.assert_not_called()

    @patch(f"{_MOD}.print_help")
    @patch(f"{_MOD}.json_handler", spec=True)
    def test_no_logging_on_help(self, mock_jh, mock_help):
        """Help should not log an operation."""
        result = handle_command("aggregate", ["--help"])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 9. --sweep-cards re-pushes every branch card, and its failures fail the command
# ═══════════════════════════════════════════════════════════


class TestSweepCardsFlag:
    """The sweep writes every branch's dashboard, so each test stubs it first.

    Mutant run 2026-09-27: deleting the `if "--sweep-cards" in args:` block reddens
    the first and third tests here."""

    @patch(f"{_MOD}.push_flow_to_all_branch_dashboards", return_value={"pushed": 3, "skipped": 1, "failed": 0})
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_sweep_cards_pushes_every_card_and_reports_the_counts(
        self, _agg, sweep, capsys: pytest.CaptureFixture[str]
    ):
        assert handle_command("aggregate", ["--sweep-cards"]) is True
        sweep.assert_called_once_with()
        out, _err = capsys.readouterr()
        assert "3 pushed, 1 skipped (no dashboard), 0 failed" in out

    @patch(f"{_MOD}.push_flow_to_all_branch_dashboards")
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_without_the_flag_no_card_is_pushed(self, _agg, sweep):
        assert handle_command("aggregate", ["--heal"]) is True
        sweep.assert_not_called()

    @patch(f"{_MOD}.push_flow_to_all_branch_dashboards", return_value={"pushed": 2, "skipped": 0, "failed": 1})
    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_a_failed_card_push_fails_the_command(self, _agg, _sweep):
        assert handle_command("aggregate", ["--sweep-cards"]) is False
