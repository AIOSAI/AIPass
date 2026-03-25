"""Tests for aggregate_central module -- handle_command routing and orchestration."""

from unittest.mock import MagicMock, patch

import pytest


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.modules.aggregate_central"


# ─── Helpers ─────────────────────────────────────────────

def _import_handle_command():
    """Import handle_command inside each test so autouse mocks are active."""
    from aipass.flow.apps.modules.aggregate_central import handle_command
    return handle_command


def _import_aggregate_central():
    """Import aggregate_central orchestrator."""
    from aipass.flow.apps.modules.aggregate_central import aggregate_central
    return aggregate_central


# ═══════════════════════════════════════════════════════════
# 1. Command != "aggregate" -> returns False
# ═══════════════════════════════════════════════════════════

class TestCommandRouting:

    def test_wrong_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("create", []) is False

    def test_unrelated_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("close", ["42"]) is False

    def test_empty_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("", []) is False


# ═══════════════════════════════════════════════════════════
# 2. command == "aggregate" with no args -> introspection
# ═══════════════════════════════════════════════════════════

class TestIntrospection:

    @patch(f"{_MOD}.print_introspection")
    def test_no_args_calls_introspection(self, mock_introspection):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", [])
        assert result is True
        mock_introspection.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 3. command == "aggregate" with --help -> help
# ═══════════════════════════════════════════════════════════

class TestHelp:

    @patch(f"{_MOD}.print_help")
    def test_help_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_h_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_help_word(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["help"])
        assert result is True
        mock_help.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 4. command == "aggregate" with ["run"] -> calls aggregate_central(heal=True)
# ═══════════════════════════════════════════════════════════

class TestRunCommand:

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_run_calls_aggregate_with_heal(self, mock_aggregate):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["run"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=True)

    @patch(f"{_MOD}.aggregate_central", return_value=False)
    def test_run_returns_false_on_failure(self, mock_aggregate):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["run"])
        assert result is False

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_heal_flag_explicit(self, mock_aggregate):
        """Explicit --heal flag should still pass heal=True."""
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["run", "--heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=True)


# ═══════════════════════════════════════════════════════════
# 5. command == "aggregate" with ["--no-heal"] -> calls aggregate_central(heal=False)
# ═══════════════════════════════════════════════════════════

class TestNoHealFlag:

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_no_heal_flag(self, mock_aggregate):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["--no-heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=False)

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    def test_no_heal_with_run(self, mock_aggregate):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["run", "--no-heal"])
        assert result is True
        mock_aggregate.assert_called_once_with(heal=False)


# ═══════════════════════════════════════════════════════════
# 6. aggregate_central orchestrator delegates to aggregate_central_impl
# ═══════════════════════════════════════════════════════════

class TestAggregateCentralOrchestrator:

    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_impl_success_returns_true(self, mock_impl):
        aggregate_central = _import_aggregate_central()
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
        aggregate_central = _import_aggregate_central()
        result = aggregate_central(heal=True)
        assert result is False

    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_heal_false_passed_to_impl(self, mock_impl):
        aggregate_central = _import_aggregate_central()
        result = aggregate_central(heal=False)
        assert result is True  # Impl succeeded
        call_kwargs = mock_impl.call_args[1]
        assert call_kwargs["heal"] is False

    @patch(f"{_MOD}.aggregate_central_impl", return_value=True)
    def test_default_heal_is_true(self, mock_impl):
        aggregate_central = _import_aggregate_central()
        result = aggregate_central()
        assert result is True  # Impl succeeded
        call_kwargs = mock_impl.call_args[1]
        assert call_kwargs["heal"] is True


# ═══════════════════════════════════════════════════════════
# 7. json_handler.log_operation is called on valid commands
# ═══════════════════════════════════════════════════════════

class TestOperationLogging:

    @patch(f"{_MOD}.aggregate_central", return_value=True)
    @patch(f"{_MOD}.json_handler")
    def test_logs_operation(self, mock_jh, mock_aggregate):
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["run"])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_called_once_with(
            "central_aggregated",
            {"command": "aggregate", "args": ["run"]},
        )

    @patch(f"{_MOD}.print_introspection")
    @patch(f"{_MOD}.json_handler")
    def test_no_logging_on_introspection(self, mock_jh, mock_introspection):
        """Introspection (no args) should not log an operation."""
        handle_command = _import_handle_command()
        result = handle_command("aggregate", [])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_not_called()

    @patch(f"{_MOD}.print_help")
    @patch(f"{_MOD}.json_handler")
    def test_no_logging_on_help(self, mock_jh, mock_help):
        """Help should not log an operation."""
        handle_command = _import_handle_command()
        result = handle_command("aggregate", ["--help"])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_not_called()
