# =================== AIPass ====================
# Name: test_usage_tracker.py
# Description: Tests for usage tracker module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-10-05
# =============================================

"""Tests for apps/modules/usage_tracker.py, API usage monitoring orchestration."""

# Tests for usage_tracker.py -- API usage monitoring orchestration.
#
# Tests:
# - handle_command routing for all subcommands
# - Help gate, introspection gate, unknown command
# - show_stats / show_session with data and without
# - show_caller_usage with data, no data, and missing args
# - cleanup_data success/failure, default/custom days

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the aggregation handler's sums; tests/test_aggregation.py
# seedgo: no-test-needed(covered_elsewhere) — the cleanup handler's file pruning; tests/test_cleanup.py
# seedgo: no-test-needed(covered_elsewhere) — the tracking handler's storage; tests/test_tracking.py

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.modules import usage_tracker
from aipass.api.apps.modules.usage_tracker import handle_command
from aipass.api.apps.modules.usage_tracker import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection

# All external dependencies are patched at the module level so no
# live I/O or network access is needed.

PATCH_ROOT = "aipass.api.apps.modules.usage_tracker"
# cleanup_data imports the bus inside the function, so the name it reads is the bus's home.
TRIGGER_HOME = "aipass.trigger.apps.modules.core.trigger"

# Generation timestamps far on either side of any retention window.
_LONG_AGO = "2000-01-01T00:00:00"
_FAR_AHEAD = "2999-12-31T00:00:00"


def _usage_store(tmp_path: Path, generations: dict) -> Path:
    """Write a usage store under tmp_path in the shape cleanup_old_data reads, and return its path."""
    store = tmp_path / "usage_tracker_data.json"
    store.write_text(json.dumps({"data": {"generation_tracking": generations}}), encoding="utf-8")
    return store


def _generations_on_disk(store: Path) -> dict:
    """The generation_tracking map as it stands on disk now."""
    return json.loads(store.read_text(encoding="utf-8"))["data"]["generation_tracking"]


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


@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_returns_false_for_unknown(mock_jh, mock_header):
    """Unknown commands must return False without logging."""
    result = usage_tracker.handle_command("unknown", [])

    assert result is False
    mock_jh.log_operation.assert_not_called()


@patch(f"{PATCH_ROOT}.track_usage")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_routes_track(mock_jh, mock_header, mock_track):
    """'track' with args should call track_usage(args)."""
    result = usage_tracker.handle_command("track", ["my_app"])

    assert result is True
    mock_track.assert_called_once_with(["my_app"])


@patch(f"{PATCH_ROOT}.show_stats")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_routes_stats_standalone(mock_jh, mock_header, mock_show):
    """'stats' is standalone -- routes before introspection gate, no args needed."""
    result = usage_tracker.handle_command("stats", [])

    assert result is True
    mock_show.assert_called_once()


@patch(f"{PATCH_ROOT}.show_session")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_routes_session_standalone(mock_jh, mock_header, mock_show):
    """'session' is standalone -- routes before introspection gate, no args needed."""
    result = usage_tracker.handle_command("session", [])

    assert result is True
    mock_show.assert_called_once()


@patch(f"{PATCH_ROOT}.show_caller_usage")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_routes_caller_usage(mock_jh, mock_header, mock_show):
    """'caller-usage' with args routes to show_caller_usage."""
    result = usage_tracker.handle_command("caller-usage", ["my_app"])

    assert result is True
    mock_show.assert_called_once_with(["my_app"])


@patch(f"{PATCH_ROOT}.cleanup_data")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_routes_cleanup(mock_jh, mock_header, mock_cleanup):
    """'cleanup' with args routes to cleanup_data."""
    result = usage_tracker.handle_command("cleanup", ["60"])

    assert result is True
    mock_cleanup.assert_called_once_with(["60"])


@patch(f"{PATCH_ROOT}.print_help")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_help_gate(mock_jh, mock_header, mock_help):
    """--help flag triggers print_help and returns True."""
    result = usage_tracker.handle_command("track", ["--help"])

    assert result is True
    mock_help.assert_called_once()
    # log_operation should NOT be called when help is shown
    mock_jh.log_operation.assert_not_called()


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_track_no_args_executes(mock_jh, mock_header, mock_error):
    """'track' with empty args should execute (show error), not show introspection."""
    result = usage_tracker.handle_command("track", [])

    assert result is True
    mock_error.assert_called()
    assert "Generation ID required" in mock_error.call_args[0][0]


@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
def test_handle_command_logs_operation(mock_jh, mock_header, tmp_path, monkeypatch, capsys):
    """handle_command should call json_handler.log_operation for valid commands."""
    # stats reads the usage store; hand it one under tmp_path, never the real api_json (api, fleet green leg 3).
    # Aggregation's own json_handler is stubbed too, so nothing real is written either.
    store = '{"data": {"usage_by_caller": {"tmp_caller": {"requests": 7, "total_tokens": 4321}}}}'
    (tmp_path / usage_tracker.aggregation.DATA_FILE).write_text(store, encoding="utf-8")
    monkeypatch.setattr(usage_tracker.aggregation, "API_JSON_DIR", tmp_path)
    agg_jh = MagicMock()
    monkeypatch.setattr(usage_tracker.aggregation, "json_handler", agg_jh)

    usage_tracker.handle_command("stats", [])

    mock_jh.log_operation.assert_called_once_with("usage_stats", {"command": "stats"})
    agg_jh.log_operation.assert_called_once_with("get_overall_stats", {"total_requests": 7})
    out = capsys.readouterr().out
    assert "Total Requests: 7" in out, "stats read the tmp_path store, not the real one"
    assert "Total Tokens: 4321" in out


# =============================================
# show_stats
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_stats_with_data(mock_agg, mock_header, mock_warning, capsys):
    """show_stats prints stats when aggregation returns data."""
    mock_agg.get_overall_stats.return_value = {
        "total_requests": 42,
        "total_cost": 0.123456,
        "total_tokens": 9001,
        "callers": 3,
        "models_used": ["anthropic/claude-3.5-sonnet"],
    }

    usage_tracker.show_stats()

    mock_header.assert_called_once_with("Usage Statistics")
    # Verify the data values appear in console output
    output = capsys.readouterr().out
    assert "42" in output
    assert "9001" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_stats_no_data(mock_agg, mock_header, mock_warning, capsys):
    """show_stats shows warning when no data available."""
    mock_agg.get_overall_stats.return_value = {}

    usage_tracker.show_stats()

    mock_warning.assert_called_once_with("No usage data available")
    # Verify no stat data was printed to console
    # Header and warning are stand-ins, so only the spacer after the header reaches stdout (api, fleet green leg 3).
    # Mutant that reddens it: any row printed on the no-data path.
    assert capsys.readouterr() == ("\n", ""), "No stat rows should be printed when data is empty"


# =============================================
# show_session
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_session_with_data(mock_agg, mock_header, mock_warning, capsys):
    """show_session prints session data when available."""
    mock_agg.get_session_summary.return_value = {
        "total_requests": 10,
        "total_cost": 0.05,
        "total_tokens": 3000,
    }

    usage_tracker.show_session()

    mock_header.assert_called_once_with("Session Summary")
    output = capsys.readouterr().out
    assert "10" in output
    assert "3000" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_session_no_data(mock_agg, mock_header, mock_warning, capsys):
    """show_session shows warning when no session data."""
    mock_agg.get_session_summary.return_value = {}

    usage_tracker.show_session()

    mock_warning.assert_called_once_with("No session data available")
    # Verify no session stat data was printed to console
    assert capsys.readouterr() == ("\n", ""), "No session rows should be printed when data is empty"


# =============================================
# show_caller_usage
# =============================================


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_caller_usage_with_data(mock_agg, mock_header, mock_warning, capsys):
    """show_caller_usage prints caller data when available."""
    mock_agg.get_caller_usage.return_value = {
        "requests": 5,
        "total_cost": 0.01,
        "total_tokens": 1500,
    }

    usage_tracker.show_caller_usage(["my_app"])

    mock_agg.get_caller_usage.assert_called_once_with("my_app")
    mock_header.assert_called_once_with("Usage for Caller: my_app")
    output = capsys.readouterr().out
    assert "5" in output
    assert "1500" in output
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_caller_usage_no_data(mock_agg, mock_header, mock_warning, capsys):
    """show_caller_usage shows warning when no data found."""
    mock_agg.get_caller_usage.return_value = {}

    usage_tracker.show_caller_usage(["ghost_caller"])

    mock_warning.assert_called_once_with("No usage data found for caller: ghost_caller")
    # Verify no usage data rows were printed to console
    assert capsys.readouterr() == ("\n", ""), "No usage rows should be printed when data is empty"


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
def test_show_caller_usage_no_args(mock_agg, mock_header, mock_error):
    """show_caller_usage calls error() when called with empty args."""
    usage_tracker.show_caller_usage([])

    mock_error.assert_called_once_with("Caller name required")
    mock_agg.get_caller_usage.assert_not_called()


# =============================================
# cleanup_data
# =============================================


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.header")
@patch(TRIGGER_HOME)
def test_cleanup_success(mock_trigger, mock_header, mock_success, mock_error, tmp_path):
    """Through the real cleanup handler: the old entry leaves the store on disk and the count is printed.

    The store is handed through the data_path seam, under tmp_path, where a patch
    of pathlib.Path on the module used to steer it (api, fleet green leg 13).
    """
    store = _usage_store(tmp_path, {"gen-old": {"timestamp": _LONG_AGO}, "gen-recent": {"timestamp": _FAR_AHEAD}})

    usage_tracker.cleanup_data(["45"], data_path=store)

    assert _generations_on_disk(store) == {"gen-recent": {"timestamp": _FAR_AHEAD}}
    mock_success.assert_called_once_with("Cleaned up 1 entries older than 45 days")
    mock_error.assert_not_called()
    mock_trigger.fire.assert_called_once_with("usage_data_cleaned", days=45, data_path=str(store))


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.header")
def test_cleanup_nothing_to_clean(mock_header, mock_success, mock_warning, tmp_path):
    """Through the real cleanup handler: nothing old leaves the store byte-equal and says so."""
    store = _usage_store(tmp_path, {"gen-recent": {"timestamp": _FAR_AHEAD}})
    before = store.read_bytes()

    usage_tracker.cleanup_data(["30"], data_path=store)

    assert store.read_bytes() == before
    mock_success.assert_called_once_with("Nothing to clean — no entries older than 30 days")
    mock_warning.assert_not_called()


@patch(f"{PATCH_ROOT}.warning")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.header")
def test_cleanup_without_a_store_warns_and_writes_nothing(mock_header, mock_success, mock_warning, tmp_path):
    """Through the real cleanup handler: no store means the warning, no success, no file made.

    (api, fleet green leg 13)
    """
    store = tmp_path / "usage_tracker_data.json"

    usage_tracker.cleanup_data(["30"], data_path=store)

    mock_warning.assert_called_once_with("No usage data file found — nothing to clean")
    mock_success.assert_not_called()
    assert not store.exists()


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup", autospec=True)
@patch(TRIGGER_HOME)
def test_cleanup_default_30_days(mock_trigger, mock_cleanup_handler, mock_header, mock_success, mock_error, tmp_path):
    """Orchestration alone, cleanup patched: no args means 30 days, handed to the handler with the store."""
    mock_cleanup_handler.cleanup_old_data.return_value = 3
    store = _usage_store(tmp_path, {})

    usage_tracker.cleanup_data([], data_path=store)

    mock_header.assert_called_once_with("Cleanup Old Data (retain 30 days)")
    mock_cleanup_handler.cleanup_old_data.assert_called_once_with(store, 30)
    mock_success.assert_called_once_with("Cleaned up 3 entries older than 30 days")
    mock_trigger.fire.assert_called_once_with("usage_data_cleaned", days=30, data_path=str(store))


@patch(f"{PATCH_ROOT}.error")
@patch(f"{PATCH_ROOT}.success")
@patch(f"{PATCH_ROOT}.header")
@patch(f"{PATCH_ROOT}.cleanup", autospec=True)
@patch(TRIGGER_HOME)
def test_cleanup_custom_days(mock_trigger, mock_cleanup_handler, mock_header, mock_success, mock_error, tmp_path):
    """Orchestration alone, cleanup patched: the days argument reaches the handler."""
    mock_cleanup_handler.cleanup_old_data.return_value = 7
    store = _usage_store(tmp_path, {})

    usage_tracker.cleanup_data(["90"], data_path=store)

    mock_header.assert_called_once_with("Cleanup Old Data (retain 90 days)")
    mock_cleanup_handler.cleanup_old_data.assert_called_once_with(store, 90)
    mock_success.assert_called_once_with("Cleaned up 7 entries older than 90 days")
    mock_trigger.fire.assert_called_once_with("usage_data_cleaned", days=90, data_path=str(store))


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{PATCH_ROOT}.aggregation", autospec=True)
@patch(f"{PATCH_ROOT}.json_handler", autospec=True)
@patch(f"{PATCH_ROOT}.header")
def test_handle_command_propagates_exception(mock_header, mock_jh, mock_agg):
    """handle_command re-raises exceptions from downstream handlers."""
    mock_agg.get_overall_stats.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        usage_tracker.handle_command("stats", [])


class TestTrailingHelpDoesNotExecute:
    """A help flag must explain the verb, never run it.

    The entry-point guard in api.py only inspects the first arg after the
    command, so `cleanup 30 --help` reaches this module with args[0] == "30".
    Before the fix that parsed 30 as a retention window and ran a real,
    data-deleting cleanup.
    """

    def test_cleanup_with_days_and_trailing_help_shows_help(self):
        """`cleanup 30 --help` prints help instead of deleting usage data."""
        with patch(f"{PATCH_ROOT}.print_help") as mock_help, patch(f"{PATCH_ROOT}.cleanup_data") as mock_cleanup:
            assert handle_command("cleanup", ["30", "--help"]) is True

        mock_cleanup.assert_not_called()
        mock_help.assert_called_once()

    def test_track_with_id_and_trailing_help_shows_help(self):
        """`track <gen_id> --help` prints help instead of tracking."""
        with patch(f"{PATCH_ROOT}.print_help") as mock_help, patch(f"{PATCH_ROOT}.track_usage") as mock_track:
            assert handle_command("track", ["gen-123", "-h"]) is True

        mock_track.assert_not_called()
        mock_help.assert_called_once()

    def test_caller_usage_with_name_and_trailing_help_shows_help(self):
        """`caller-usage flow --help` prints help instead of querying."""
        with patch(f"{PATCH_ROOT}.print_help") as mock_help, patch(f"{PATCH_ROOT}.show_caller_usage") as mock_show:
            assert handle_command("caller-usage", ["flow", "--help"]) is True

        mock_show.assert_not_called()
        mock_help.assert_called_once()

    def test_bare_help_in_value_position_is_data(self):
        """`track <id> help` names a caller — only `--help`/`-h` are flags.

        Bare `help` keeps its meaning in the first position (`cleanup help`),
        so the anywhere-scan is limited to the unambiguous flag spellings.
        """
        with patch(f"{PATCH_ROOT}.print_help") as mock_help, patch(f"{PATCH_ROOT}.track_usage") as mock_track:
            assert handle_command("track", ["gen-123", "help"]) is True

        mock_track.assert_called_once_with(["gen-123", "help"])
        mock_help.assert_not_called()

    def test_bare_help_first_position_still_shows_help(self):
        """`cleanup help` keeps working — existing alias, unchanged."""
        with patch(f"{PATCH_ROOT}.print_help") as mock_help, patch(f"{PATCH_ROOT}.cleanup_data") as mock_cleanup:
            assert handle_command("cleanup", ["help"]) is True

        mock_cleanup.assert_not_called()
        mock_help.assert_called_once()
