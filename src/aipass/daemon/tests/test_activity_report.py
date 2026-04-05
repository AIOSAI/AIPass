# =================== AIPass ====================
# Name: test_activity_report.py
# Description: Tests for the activity_report CLI module
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for the activity_report CLI module (apps/modules/activity_report.py)."""

from unittest.mock import patch, MagicMock

MODULE = "aipass.daemon.apps.modules.activity_report"


# =============================================
# handle_command -- routing basics
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestHandleCommandRouting:
    """Tests for handle_command routing and unknown commands."""

    def test_unknown_command_returns_false(self, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        assert handle_command("not_a_real_command", []) is False

    def test_activity_no_args_calls_generate(self, _log, _err, mock_con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="report") as mock_gen:
            result = handle_command("activity", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24.0, verbosity="normal")
        mock_con.print.assert_called_with("report")

    def test_activity_help_shows_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report") as mock_gen:
            result = handle_command("activity", ["--help"])

        assert result is True
        mock_gen.assert_not_called()
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("ACTIVITY" in c for c in calls)

    def test_activity_hours_48(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="report") as mock_gen:
            result = handle_command("activity", ["--hours", "48"])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=48.0, verbosity="normal")


# =============================================
# handle_command -- activity-report
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestActivityReportCommand:
    """Tests for 'activity-report' command."""

    def test_activity_report_no_args(self, _log, _err, _con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="detailed") as mock_gen:
            result = handle_command("activity-report", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24.0, verbosity="detailed")

    def test_activity_report_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report") as mock_gen:
            result = handle_command("activity-report", ["--help"])

        assert result is True
        mock_gen.assert_not_called()
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("ACTIVITY-REPORT" in c for c in calls)

    def test_activity_report_json(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.get_json_report", return_value={"branches": []}) as mock_json:
            result = handle_command("activity-report", ["--json"])

        assert result is True
        mock_json.assert_called_once_with(24.0)

    def test_activity_report_json_short_flag(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.get_json_report", return_value={}) as mock_json:
            result = handle_command("activity-report", ["-j"])

        assert result is True
        mock_json.assert_called_once()


# =============================================
# handle_command -- activity_report alias
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestActivityReportAlias:
    """Tests for 'activity_report' underscore alias."""

    def test_activity_report_alias_works(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="r") as mock_gen:
            result = handle_command("activity_report", [])

        assert result is True
        mock_gen.assert_called_once()

    def test_activity_report_alias_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("activity_report", ["--help"])
        assert result is True
        # Shows introspection (module info)
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("activity_report Module" in c for c in calls)


# =============================================
# handle_command -- branch-health
# =============================================

@patch(f"{MODULE}.json_handler")
@patch(f"{MODULE}.console")
@patch(f"{MODULE}.error")
@patch(f"{MODULE}.logger")
class TestBranchHealthCommand:
    """Tests for 'branch-health' command."""

    def test_branch_health_no_args(self, _log, _err, _con, mock_jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_activity_report", return_value="all") as mock_gen:
            result = handle_command("branch-health", [])

        assert result is True
        mock_gen.assert_called_once_with(since_hours=24, verbosity="normal")

    def test_branch_health_help(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("branch-health", ["--help"])
        assert result is True
        calls = [str(c) for c in mock_con.print.call_args_list]
        assert any("BRANCH-HEALTH" in c for c in calls)

    def test_branch_health_with_branch(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="DRONE report") as mock_br:
            result = handle_command("branch-health", ["DRONE"])

        assert result is True
        mock_br.assert_called_once_with("DRONE", since_hours=24.0)

    def test_branch_health_with_branch_and_hours(self, _log, _err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        with patch(f"{MODULE}.generate_branch_report", return_value="report") as mock_br:
            result = handle_command("branch-health", ["DRONE", "--hours", "48"])

        assert result is True
        mock_br.assert_called_once_with("DRONE", since_hours=48.0)

    def test_branch_health_only_flags_shows_error(self, _log, mock_err, mock_con, _jh):
        from aipass.daemon.apps.modules.activity_report import handle_command

        result = handle_command("branch-health", ["--hours", "48"])
        assert result is True
        mock_err.assert_called()


# =============================================
# _parse_hours_arg
# =============================================

@patch(f"{MODULE}.logger")
class TestParseHoursArg:
    """Tests for _parse_hours_arg helper."""

    def test_hours_flag(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg(["--hours", "48"]) == 48.0

    def test_short_flag(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg(["-t", "12"]) == 12.0

    def test_no_flag_returns_default(self, _log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        assert _parse_hours_arg([]) == 24.0

    def test_invalid_value_returns_default(self, mock_log):
        from aipass.daemon.apps.modules.activity_report import _parse_hours_arg

        result = _parse_hours_arg(["--hours", "abc"])
        assert result == 24.0
        mock_log.warning.assert_called()


# =============================================
# _extract_branch_name
# =============================================

class TestExtractBranchName:
    """Tests for _extract_branch_name helper."""

    def test_branch_with_flags(self):
        from aipass.daemon.apps.modules.activity_report import _extract_branch_name

        assert _extract_branch_name(["DRONE", "--hours", "48"]) == "DRONE"

    def test_only_flags_returns_none(self):
        from aipass.daemon.apps.modules.activity_report import _extract_branch_name

        assert _extract_branch_name(["--hours", "48"]) is None
