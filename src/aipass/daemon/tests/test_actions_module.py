# =================== AIPass ====================
# Name: test_actions_module.py
# Description: Tests for the actions CLI module
# Version: 1.0.0
# Created: 2026-04-02
# Modified: 2026-04-02
# =============================================

"""Tests for the actions CLI module (apps/modules/actions.py)."""

from datetime import datetime, timedelta
from unittest.mock import patch

MODULE = "aipass.daemon.apps.modules.actions"


# =============================================
# FIXTURES
# =============================================

def _make_action(
    action_id: str = "0001",
    name: str = "test_action",
    enabled: bool = True,
    schedule_type: str = "daily",
    time: str = "08:00",
    action_type: str = "schedule",
    target_branch: str = "@seedgo",
    interval_minutes: int | None = None,
    due_date: str | None = None,
    prompt: str = "Run tests",
) -> dict:
    """Build a sample action dict for tests."""
    action: dict = {
        "id": action_id,
        "name": name,
        "enabled": enabled,
        "schedule_type": schedule_type,
        "time": time,
        "type": action_type,
        "target_branch": target_branch,
        "prompt": prompt,
        "created": "2026-03-01T00:00:00",
        "last_run": None,
    }
    if interval_minutes is not None:
        action["interval_minutes"] = interval_minutes
    if due_date is not None:
        action["due_date"] = due_date
    return action


# =============================================
# handle_command — routing
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestHandleCommand:
    """Tests for handle_command routing."""

    def test_wrong_command_returns_false(self, _err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("not_actions", []) is False

    def test_no_args_shows_introspection(self, _err, mock_console, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        result = handle_command("actions", [])
        assert result is True
        # introspection prints "actions Module"
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("actions Module" in c for c in calls)

    def test_help_flag(self, _err, mock_console, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["--help"]) is True
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("USAGE" in c for c in calls)

    def test_help_word(self, _err, mock_console, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["help"]) is True

    @patch(f"{MODULE}.list_actions", return_value=[])
    @patch(f"{MODULE}.next_due_str", return_value="--")
    def test_list_subcommand(self, _nds, _la, _err, mock_console, mock_jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["list"]) is True
        mock_jh.log_operation.assert_called_once()

    @patch(f"{MODULE}.migrate_plugins", return_value=2)
    @patch(f"{MODULE}.list_actions", return_value=[])
    @patch(f"{MODULE}.next_due_str", return_value="--")
    def test_migrate_subcommand(self, _nds, _la, mock_migrate, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["migrate"]) is True
        mock_migrate.assert_called_once()

    @patch(f"{MODULE}.get_action")
    @patch(f"{MODULE}.delete_action")
    def test_delete_with_valid_id(self, mock_del, mock_get, _err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        mock_get.return_value = _make_action()
        assert handle_command("actions", ["delete", "0001"]) is True
        mock_del.assert_called_once_with("0001")

    def test_delete_missing_id(self, mock_err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["delete"]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.create_action")
    @patch(f"{MODULE}._parse_date", return_value="2026-04-09")
    def test_set_reminder_valid(self, _pd, mock_create, _err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        mock_create.return_value = _make_action(action_id="0099")
        assert handle_command("actions", ["set", "reminder", "7d", "Check PR"]) is True
        mock_create.assert_called_once()

    @patch(f"{MODULE}.create_action")
    @patch(f"{MODULE}._parse_date", return_value="2026-04-09")
    def test_set_schedule_valid(self, _pd, mock_create, _err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        mock_create.return_value = _make_action(action_id="0088")
        assert handle_command(
            "actions", ["set", "schedule", "@seedgo", "Run audit", "daily", "04:00"]
        ) is True
        mock_create.assert_called_once()

    @patch(f"{MODULE}.get_action")
    @patch(f"{MODULE}.next_due_str", return_value="--")
    def test_action_id_routes(self, _nds, mock_get, _err, _con, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        mock_get.return_value = _make_action(action_id="0003")
        assert handle_command("actions", ["0003", "info"]) is True
        mock_get.assert_called_with("0003")

    def test_unknown_subcommand(self, mock_err, mock_console, _jh):
        from aipass.daemon.apps.modules.actions import handle_command

        assert handle_command("actions", ["foobar"]) is True
        mock_err.assert_called()


# =============================================
# _handle_toggle
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestHandleToggle:

    @patch(f"{MODULE}.toggle_action")
    @patch(f"{MODULE}.get_action")
    def test_enable_success(self, mock_get, mock_toggle, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_toggle

        mock_get.return_value = _make_action()
        assert _handle_toggle("0001", True) is True
        mock_toggle.assert_called_once_with("0001", True)

    @patch(f"{MODULE}.toggle_action")
    @patch(f"{MODULE}.get_action")
    def test_disable_success(self, mock_get, mock_toggle, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_toggle

        mock_get.return_value = _make_action()
        assert _handle_toggle("0001", False) is True
        mock_toggle.assert_called_once_with("0001", False)

    @patch(f"{MODULE}.get_action", return_value=None)
    def test_not_found(self, _get, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_toggle

        assert _handle_toggle("9999", True) is True
        mock_err.assert_called()


# =============================================
# _handle_info
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestHandleInfo:

    @patch(f"{MODULE}.next_due_str", return_value="--")
    @patch(f"{MODULE}.get_action")
    def test_info_success(self, mock_get, _nds, _err, mock_console):
        from aipass.daemon.apps.modules.actions import _handle_info

        mock_get.return_value = _make_action()
        assert _handle_info("0001") is True
        # Should print detail header containing the action name
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("test_action" in c for c in calls)

    @patch(f"{MODULE}.get_action", return_value=None)
    def test_info_not_found(self, _get, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_info

        assert _handle_info("9999") is True
        mock_err.assert_called()


# =============================================
# _handle_set_reminder
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestHandleSetReminder:

    def test_missing_args(self, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_reminder

        assert _handle_set_reminder(["7d"]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.create_action")
    @patch(f"{MODULE}._parse_date", return_value="2026-04-09")
    def test_with_to_flag(self, _pd, mock_create, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_reminder

        mock_create.return_value = _make_action(action_id="0050")
        assert _handle_set_reminder(["7d", "Follow up", "--to", "@flow"]) is True
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["target_branch"] == "@flow"

    @patch(f"{MODULE}._parse_date", return_value="")
    def test_invalid_date(self, _pd, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_reminder

        assert _handle_set_reminder(["xyz", "Some msg"]) is True
        mock_err.assert_called()


# =============================================
# _handle_set_schedule
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
@patch(f"{MODULE}.logger")
class TestHandleSetSchedule:

    def test_invalid_type(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        assert _handle_set_schedule(["@branch", "prompt", "weekly"]) is True
        mock_err.assert_called()

    def test_missing_time_arg(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        assert _handle_set_schedule(["@branch", "prompt", "daily"]) is True
        mock_err.assert_called()

    def test_interval_non_numeric(self, _log, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        assert _handle_set_schedule(["@b", "prompt", "interval", "abc"]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.create_action")
    def test_daily_success(self, mock_create, _log, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        mock_create.return_value = _make_action(action_id="0070")
        assert _handle_set_schedule(["@seedgo", "Run audit", "daily", "04:00"]) is True
        kw = mock_create.call_args[1]
        assert kw["schedule_type"] == "daily"
        assert kw["time"] == "04:00"

    @patch(f"{MODULE}.create_action")
    def test_hourly_success(self, mock_create, _log, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        mock_create.return_value = _make_action(action_id="0071")
        assert _handle_set_schedule(["@flow", "Check plans", "hourly", "30"]) is True
        kw = mock_create.call_args[1]
        assert kw["schedule_type"] == "hourly"

    @patch(f"{MODULE}.create_action")
    def test_interval_success(self, mock_create, _log, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_set_schedule

        mock_create.return_value = _make_action(action_id="0072")
        assert _handle_set_schedule(["@vera", "Heartbeat", "interval", "240"]) is True
        kw = mock_create.call_args[1]
        assert kw["interval_minutes"] == 240


# =============================================
# _handle_delete
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestHandleDelete:

    def test_no_args(self, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_delete

        assert _handle_delete([]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.get_action", return_value=None)
    def test_not_found(self, _get, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _handle_delete

        assert _handle_delete(["9999"]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.delete_action")
    @patch(f"{MODULE}.get_action")
    def test_success(self, mock_get, mock_del, _err, _con):
        from aipass.daemon.apps.modules.actions import _handle_delete

        mock_get.return_value = _make_action(action_id="0005")
        assert _handle_delete(["0005"]) is True
        mock_del.assert_called_once_with("0005")


# =============================================
# _parse_date
# =============================================

@patch(f"{MODULE}.logger")
class TestParseDate:

    def test_relative_days(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        result = _parse_date("7d")
        expected = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert result == expected

    def test_relative_weeks(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        result = _parse_date("2w")
        expected = (datetime.now() + timedelta(weeks=2)).strftime("%Y-%m-%d")
        assert result == expected

    def test_iso_format(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        assert _parse_date("2026-04-15") == "2026-04-15"

    def test_invalid_format(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        assert _parse_date("not-a-date") == ""

    def test_invalid_relative_day(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        assert _parse_date("xd") == ""

    def test_invalid_relative_week(self, _log):
        from aipass.daemon.apps.modules.actions import _parse_date

        assert _parse_date("xw") == ""


# =============================================
# _format_schedule
# =============================================

class TestFormatSchedule:

    def test_daily(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "daily", "time": "08:00"}) == "daily @ 08:00"

    def test_hourly(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "hourly", "time": "30"}) == "hourly @ :30"

    def test_interval_minutes(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "interval", "interval_minutes": 45}) == "every 45m"

    def test_interval_hours(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "interval", "interval_minutes": 120}) == "every 2h"

    def test_once(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "once", "due_date": "2026-04-10"}) == "once: 2026-04-10"

    def test_unknown_type(self):
        from aipass.daemon.apps.modules.actions import _format_schedule

        assert _format_schedule({"schedule_type": "custom"}) == "custom"


# =============================================
# _route_set_subcommand / _route_action_id
# =============================================

@patch(f"{MODULE}.console")
@patch(f"{MODULE}.cli_error")
class TestRouting:

    def test_route_set_too_few_args(self, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _route_set_subcommand

        assert _route_set_subcommand(["set"]) is True
        mock_err.assert_called()

    def test_route_set_unknown_type(self, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _route_set_subcommand

        assert _route_set_subcommand(["set", "bogus"]) is True
        mock_err.assert_called()

    @patch(f"{MODULE}.get_action", return_value=None)
    def test_route_action_id_no_sub_defaults_to_info(self, mock_get, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _route_action_id

        assert _route_action_id("0001", ["0001"]) is True
        mock_get.assert_called_with("0001")

    @patch(f"{MODULE}.get_action")
    @patch(f"{MODULE}.toggle_action")
    def test_route_action_id_on(self, mock_toggle, mock_get, _err, _con):
        from aipass.daemon.apps.modules.actions import _route_action_id

        mock_get.return_value = _make_action()
        assert _route_action_id("0001", ["0001", "on"]) is True
        mock_toggle.assert_called_once_with("0001", True)

    def test_route_action_id_unknown_sub(self, mock_err, _con):
        from aipass.daemon.apps.modules.actions import _route_action_id

        assert _route_action_id("0001", ["0001", "banana"]) is True
        mock_err.assert_called()
