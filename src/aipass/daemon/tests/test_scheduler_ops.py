# =================== AIPass ====================
# Name: test_scheduler_ops.py
# Description: Tests for the scheduler_ops facade module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for the scheduler_ops facade module (apps/modules/scheduler_ops.py)."""

from unittest.mock import patch

MODULE = "aipass.daemon.apps.modules.scheduler_ops"


# =============================================
# handle_command — routing
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.logger")
class TestHandleCommand:
    """Tests for handle_command routing."""

    def test_wrong_command_returns_false(self, _log, _con, _jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        assert handle_command("not-scheduler-ops", []) is False

    def test_no_args_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        result = handle_command("scheduler-ops", [])
        assert result is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("scheduler_ops Module" in c for c in calls)

    def test_help_flag_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        assert handle_command("scheduler-ops", ["--help"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("scheduler_ops Module" in c for c in calls)

    def test_h_flag_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        assert handle_command("scheduler-ops", ["-h"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("scheduler_ops Module" in c for c in calls)

    def test_help_word_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        assert handle_command("scheduler-ops", ["help"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("scheduler_ops Module" in c for c in calls)

    def test_status_arg_shows_registry_info(self, _log, mock_console, mock_jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        assert handle_command("scheduler-ops", ["status"]) is True
        mock_jh.log_operation.assert_called_once_with("scheduler_ops_status")
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Scheduler Ops" in c for c in calls)

    def test_status_prints_task_registry_availability(self, _log, mock_console, mock_jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        handle_command("scheduler-ops", ["status"])
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Task registry" in c for c in calls)

    def test_status_prints_action_registry_availability(self, _log, mock_console, mock_jh):
        from aipass.daemon.apps.modules.scheduler_ops import handle_command

        handle_command("scheduler-ops", ["status"])
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Action registry" in c for c in calls)


# =============================================
# Module-level availability flags
# =============================================

class TestRegistryAvailability:
    """Verify that registry imports succeed in the test environment."""

    def test_task_registry_available(self):
        from aipass.daemon.apps.modules.scheduler_ops import TASK_REGISTRY_AVAILABLE

        assert TASK_REGISTRY_AVAILABLE is True

    def test_action_registry_available(self):
        from aipass.daemon.apps.modules.scheduler_ops import ACTION_REGISTRY_AVAILABLE

        assert ACTION_REGISTRY_AVAILABLE is True


# =============================================
# print_introspection
# =============================================

@patch(f"{MODULE}.console")
class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_prints_module_header(self, mock_console):
        from aipass.daemon.apps.modules.scheduler_ops import print_introspection

        print_introspection()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("scheduler_ops Module" in c for c in calls)
