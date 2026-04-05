# =================== AIPass ====================
# Name: test_wakeup_ops.py
# Description: Tests for the wakeup_ops facade module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for the wakeup_ops facade module (apps/modules/wakeup_ops.py)."""

from unittest.mock import patch

MODULE = "aipass.daemon.apps.modules.wakeup_ops"


# =============================================
# handle_command — routing
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.logger")
class TestHandleCommand:
    """Tests for handle_command routing."""

    def test_wrong_command_returns_false(self, _log, _con, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        assert handle_command("not-wakeup-ops", []) is False

    def test_no_args_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        result = handle_command("wakeup-ops", [])
        assert result is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("wakeup_ops Module" in c for c in calls)

    def test_help_flag_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        assert handle_command("wakeup-ops", ["--help"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("wakeup_ops Module" in c for c in calls)

    def test_h_flag_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        assert handle_command("wakeup-ops", ["-h"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("wakeup_ops Module" in c for c in calls)

    def test_help_word_shows_introspection(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        assert handle_command("wakeup-ops", ["help"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("wakeup_ops Module" in c for c in calls)

    def test_status_arg_shows_info(self, _log, mock_console, mock_jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        assert handle_command("wakeup-ops", ["status"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Wakeup Ops" in c for c in calls)

    def test_status_calls_log_operation(self, _log, _con, mock_jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        handle_command("wakeup-ops", ["status"])
        mock_jh.log_operation.assert_called_once_with("wakeup_ops_status")

    def test_status_prints_notifications_archived(self, _log, mock_console, _jh):
        from aipass.daemon.apps.modules.wakeup_ops import handle_command

        handle_command("wakeup-ops", ["status"])
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Notifications" in c for c in calls)


# =============================================
# print_introspection
# =============================================

@patch(f"{MODULE}.console")
class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_prints_module_header(self, mock_console):
        from aipass.daemon.apps.modules.wakeup_ops import print_introspection

        print_introspection()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("wakeup_ops Module" in c for c in calls)
