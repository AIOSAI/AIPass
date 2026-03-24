# =================== AIPass ====================
# Name: test_usage_tracker.py
# Description: Tests for usage tracker module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for usage_tracker.py -- API usage monitoring orchestration.

Tests:
- handle_command routing for all subcommands
- Help gate, introspection gate, unknown command
- show_stats / show_session with data and without
- show_caller_usage with data, no data, and missing args
- cleanup_data success/failure, default/custom days
"""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from aipass.api.apps.modules.usage_tracker import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection

# All external dependencies are patched at the module level so no
# live I/O or network access is needed.

PATCH_ROOT = "aipass.api.apps.modules.usage_tracker"


# =============================================
# Helpers
# =============================================


def _base_patches():
    """Return the list of patch targets shared by most tests."""
    return [
        f"{PATCH_ROOT}.console",
        f"{PATCH_ROOT}.header",
        f"{PATCH_ROOT}.success",
        f"{PATCH_ROOT}.error",
        f"{PATCH_ROOT}.warning",
        f"{PATCH_ROOT}.json_handler",
        f"{PATCH_ROOT}.tracking",
        f"{PATCH_ROOT}.aggregation",
        f"{PATCH_ROOT}.cleanup",
    ]


# =============================================
# handle_command -- routing & gates
# =============================================


@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_returns_false_for_unknown(mock_jh, mock_header, mock_console):
    """Unknown commands must return False without logging."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("unknown", [])

    assert result is False
    mock_jh.log_operation.assert_not_called()


@patch(f"{PATCH_ROOT}.track_usage")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_routes_track(mock_jh, mock_header, mock_console, mock_track):
    """'track' with args should call track_usage(args)."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("track", ["my_app"])

    assert result is True
    mock_track.assert_called_once_with(["my_app"])


@patch(f"{PATCH_ROOT}.show_stats")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_routes_stats_standalone(mock_jh, mock_header, mock_console, mock_show):
    """'stats' is standalone -- routes before introspection gate, no args needed."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("stats", [])

    assert result is True
    mock_show.assert_called_once()


@patch(f"{PATCH_ROOT}.show_session")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_routes_session_standalone(mock_jh, mock_header, mock_console, mock_show):
    """'session' is standalone -- routes before introspection gate, no args needed."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("session", [])

    assert result is True
    mock_show.assert_called_once()


@patch(f"{PATCH_ROOT}.show_caller_usage")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_routes_caller_usage(mock_jh, mock_header, mock_console, mock_show):
    """'caller-usage' with args routes to show_caller_usage."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("caller-usage", ["my_app"])

    assert result is True
    mock_show.assert_called_once_with(["my_app"])


@patch(f"{PATCH_ROOT}.cleanup_data")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_routes_cleanup(mock_jh, mock_header, mock_console, mock_cleanup):
    """'cleanup' with args routes to cleanup_data."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("cleanup", ["60"])

    assert result is True
    mock_cleanup.assert_called_once_with(["60"])


@patch(f"{PATCH_ROOT}.print_help")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_help_gate(mock_jh, mock_header, mock_console, mock_help):
    """--help flag triggers print_help and returns True."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("track", ["--help"])

    assert result is True
    mock_help.assert_called_once()
    # log_operation should NOT be called when help is shown
    mock_jh.log_operation.assert_not_called()


@patch(f"{PATCH_ROOT}.print_introspection")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_introspection_gate(mock_jh, mock_header, mock_console, mock_intro):
    """'track' with empty args triggers introspection gate."""
    from aipass.api.apps.modules import usage_tracker

    result = usage_tracker.handle_command("track", [])

    assert result is True
    mock_intro.assert_called_once()


@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler")
def test_handle_command_logs_operation(mock_jh, mock_header, mock_console):
    """handle_command should call json_handler.log_operation for valid commands."""
    from aipass.api.apps.modules import usage_tracker

    usage_tracker.handle_command("stats", [])

    mock_jh.log_operation.assert_called_once_with(
        "usage_stats", {"command": "stats"}
    )


# =============================================
# show_stats
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_stats_with_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_stats prints stats when aggregation returns data."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_session_summary.return_value = {
        "total_requests": 42,
        "total_cost": 0.123456,
        "total_tokens": 9001,
    }

    usage_tracker.show_stats()

    mock_header.assert_called_once_with("Usage Statistics")
    # Verify the data values appear in console output
    calls = [str(c) for c in mock_console.print.call_args_list]
    output = " ".join(calls)
    assert "42" in output
    assert "9001" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_stats_no_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_stats shows warning when no data available."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_session_summary.return_value = {}

    usage_tracker.show_stats()

    mock_warning.assert_called_once_with("No usage data available")
    # Verify no stat data was printed to console
    stat_calls = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "Total Requests" in c.args[0]
    ]
    assert len(stat_calls) == 0, "No stat rows should be printed when data is empty"


# =============================================
# show_session
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_session_with_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_session prints session data when available."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_session_summary.return_value = {
        "total_requests": 10,
        "total_cost": 0.05,
        "total_tokens": 3000,
    }

    usage_tracker.show_session()

    mock_header.assert_called_once_with("Session Summary")
    calls = [str(c) for c in mock_console.print.call_args_list]
    output = " ".join(calls)
    assert "10" in output
    assert "3000" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_session_no_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_session shows warning when no session data."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_session_summary.return_value = {}

    usage_tracker.show_session()

    mock_warning.assert_called_once_with("No session data available")
    # Verify no session stat data was printed to console
    stat_calls = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "Session Requests" in c.args[0]
    ]
    assert len(stat_calls) == 0, "No session rows should be printed when data is empty"


# =============================================
# show_caller_usage
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_caller_usage_with_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_caller_usage prints caller data when available."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_caller_usage.return_value = {
        "requests": 5,
        "total_cost": 0.01,
        "total_tokens": 1500,
    }

    usage_tracker.show_caller_usage(["my_app"])

    mock_agg.get_caller_usage.assert_called_once_with("my_app")
    mock_header.assert_called_once_with("Usage for Caller: my_app")
    calls = [str(c) for c in mock_console.print.call_args_list]
    output = " ".join(calls)
    assert "5" in output
    assert "1500" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_caller_usage_no_data(mock_agg, mock_header, mock_console, mock_warning):
    """show_caller_usage shows warning when no data found."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_caller_usage.return_value = {}

    usage_tracker.show_caller_usage(["ghost_caller"])

    mock_warning.assert_called_once_with("No usage data found for caller: ghost_caller")
    # Verify no usage data rows were printed to console
    usage_calls = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "Requests" in c.args[0]
    ]
    assert len(usage_calls) == 0, "No usage rows should be printed when data is empty"


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation")
def test_show_caller_usage_no_args(mock_agg, mock_header, mock_console, mock_error):
    """show_caller_usage calls error() when called with empty args."""
    from aipass.api.apps.modules import usage_tracker

    usage_tracker.show_caller_usage([])

    mock_error.assert_called_once_with("Caller name required")
    mock_agg.get_caller_usage.assert_not_called()


# =============================================
# cleanup_data
# =============================================


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup")
def test_cleanup_success(mock_cleanup_handler, mock_header, mock_console, mock_success, mock_error):
    """cleanup_data calls success() when handler returns truthy."""
    from aipass.api.apps.modules import usage_tracker

    mock_cleanup_handler.cleanup_old_data.return_value = True

    with patch(f"{PATCH_ROOT}.Path") as mock_path_cls:
        mock_path_cls.__file__ = MagicMock()
        # Let Path(__file__).resolve().parent chain work
        mock_resolved = MagicMock()
        mock_path_cls.return_value.resolve.return_value.parent.parent.parent.__truediv__ = MagicMock()

        # Simpler approach: just let the real Path work -- it resolves against
        # the actual source file, but cleanup_old_data is mocked anyway.
        pass

    # Call directly without patching Path -- cleanup handler is mocked
    usage_tracker.cleanup_data(["45"])

    mock_cleanup_handler.cleanup_old_data.assert_called_once()
    mock_success.assert_called_once_with("Cleaned up data older than 45 days")
    mock_error.assert_not_called()


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup")
def test_cleanup_failure(mock_cleanup_handler, mock_header, mock_console, mock_success, mock_error):
    """cleanup_data calls error() when handler returns falsy."""
    from aipass.api.apps.modules import usage_tracker

    mock_cleanup_handler.cleanup_old_data.return_value = False

    usage_tracker.cleanup_data(["30"])

    mock_cleanup_handler.cleanup_old_data.assert_called_once()
    mock_error.assert_called_once_with("Cleanup failed")
    mock_success.assert_not_called()


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup")
def test_cleanup_default_30_days(mock_cleanup_handler, mock_header, mock_console, mock_success, mock_error):
    """cleanup_data defaults to 30 days when no args provided."""
    from aipass.api.apps.modules import usage_tracker

    mock_cleanup_handler.cleanup_old_data.return_value = True

    usage_tracker.cleanup_data([])

    # Verify the header shows 30 days
    mock_header.assert_called_once_with("Cleanup Old Data (retain 30 days)")
    # Verify cleanup_old_data was called with days=30
    args, kwargs = mock_cleanup_handler.cleanup_old_data.call_args
    assert args[1] == 30
    mock_success.assert_called_once_with("Cleaned up data older than 30 days")


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.console")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup")
def test_cleanup_custom_days(mock_cleanup_handler, mock_header, mock_console, mock_success, mock_error):
    """cleanup_data parses custom days from args."""
    from aipass.api.apps.modules import usage_tracker

    mock_cleanup_handler.cleanup_old_data.return_value = True

    usage_tracker.cleanup_data(["90"])

    mock_header.assert_called_once_with("Cleanup Old Data (retain 90 days)")
    args, kwargs = mock_cleanup_handler.cleanup_old_data.call_args
    assert args[1] == 90
    mock_success.assert_called_once_with("Cleaned up data older than 90 days")


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{PATCH_ROOT}.aggregation")
@patch(f"{PATCH_ROOT}.json_handler")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.console")
def test_handle_command_propagates_exception(mock_console, mock_header, mock_jh, mock_agg):
    """handle_command re-raises exceptions from downstream handlers."""
    from aipass.api.apps.modules import usage_tracker

    mock_agg.get_session_summary.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        usage_tracker.handle_command("stats", [])
