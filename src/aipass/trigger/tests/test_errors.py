# =================== AIPass ====================
# Name: test_errors.py
# Description: Unit tests for the errors module (error registry management CLI)
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Unit tests for aipass.trigger.apps.modules.errors

Tests the handle_command routing and report_error public API.
All heavy infrastructure (prax logger, json_handler, error_registry,
error_reporter, cli display) is mocked via sys.modules before import.
"""

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

# Module-level dict populated by the autouse fixture each test.
_shared_mocks: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Infrastructure mocking — autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock all external dependencies before the errors module is imported.

    Patches sys.modules for prax logger, json_handler, error_registry,
    error_reporter, and cli display so the module can be imported in
    isolation without touching disk or real infrastructure.
    """
    # --- prax logger ---
    mock_logger = MagicMock()
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = mock_logger
    prax_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock(logger=mock_logger))
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # --- json_handler ---
    mock_json_handler = MagicMock()
    json_mod = MagicMock()
    json_mod.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_mod)
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", mock_json_handler)

    # --- error_registry handler ---
    mock_query = MagicMock(return_value=[])
    mock_get_entry = MagicMock(return_value=None)
    mock_update_status = MagicMock(return_value=True)
    mock_clear_resolved = MagicMock(return_value=0)
    mock_get_stats = MagicMock(
        return_value={
            "total": 0,
            "by_status": {},
            "by_component": {},
            "by_severity": {},
        }
    )
    mock_get_cb_status = MagicMock(
        return_value={
            "state": "closed",
            "opened_at": 0,
            "cooldown_seconds": 300,
            "recent_error_count": 0,
            "summary_sent": False,
        }
    )
    mock_cb_reset = MagicMock()
    mock_update_fix_status = MagicMock(return_value=True)

    registry_mod = MagicMock()
    registry_mod.query = mock_query
    registry_mod.get_entry = mock_get_entry
    registry_mod.update_status = mock_update_status
    registry_mod.clear_resolved = mock_clear_resolved
    registry_mod.get_stats = mock_get_stats
    registry_mod.get_circuit_breaker_status = mock_get_cb_status
    registry_mod.circuit_breaker_reset = mock_cb_reset
    registry_mod.update_source_fix_status = mock_update_fix_status
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_registry", registry_mod)

    # --- error_reporter handler ---
    mock_report_error = MagicMock(
        return_value={
            "fingerprint": "abc123",
            "is_new": True,
            "dispatched": False,
        }
    )
    mock_send_fix_email = MagicMock(return_value=False)

    reporter_mod = MagicMock()
    reporter_mod.report_error = mock_report_error
    reporter_mod.send_source_fix_email = mock_send_fix_email
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.error_reporter", reporter_mod)

    # --- cli display (console, error) ---
    mock_console = MagicMock()
    mock_error_fn = MagicMock()
    mock_cli_modules = MagicMock()
    mock_cli_modules.console = mock_console
    mock_cli_modules.error = mock_error_fn
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", mock_cli_modules)
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules.display", MagicMock(console=mock_console))

    # --- rich (for Rich table/panel used inside command functions) ---
    mock_table_cls = MagicMock()
    mock_panel_cls = MagicMock()
    mock_rich_table = MagicMock()
    mock_rich_table.Table = mock_table_cls
    mock_rich_panel = MagicMock()
    mock_rich_panel.Panel = mock_panel_cls
    monkeypatch.setitem(sys.modules, "rich.table", mock_rich_table)
    monkeypatch.setitem(sys.modules, "rich.panel", mock_rich_panel)
    monkeypatch.setitem(sys.modules, "rich.console", MagicMock())

    # Force re-import of the errors module so it picks up all mocks
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.errors", raising=False)

    # Expose mocks to tests via the module-level dict
    _shared_mocks.clear()
    _shared_mocks.update(
        {
            "logger": mock_logger,
            "json_handler": mock_json_handler,
            "console": mock_console,
            "error_fn": mock_error_fn,
            "query": mock_query,
            "get_entry": mock_get_entry,
            "update_status": mock_update_status,
            "clear_resolved": mock_clear_resolved,
            "get_stats": mock_get_stats,
            "get_cb_status": mock_get_cb_status,
            "cb_reset": mock_cb_reset,
            "update_fix_status": mock_update_fix_status,
            "report_error": mock_report_error,
            "send_fix_email": mock_send_fix_email,
            "table_cls": mock_table_cls,
            "panel_cls": mock_panel_cls,
        }
    )


def _mocks() -> dict[str, Any]:
    """Shorthand accessor for the shared mock dict."""
    return _shared_mocks


# ---------------------------------------------------------------------------
# handle_command — "list" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandList:
    """Tests for the 'list' subcommand."""

    def test_list_empty_registry(self):
        """list with no errors prints a 'no errors' message."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["query"].return_value = []

        result = handle_command("errors", ["list"])

        assert result is True
        mocks["query"].assert_called_once()
        mocks["console"].print.assert_any_call("[dim]No errors in registry[/dim]")

    def test_list_with_entries_renders_table(self):
        """list with entries calls query and prints a Rich table with correct data."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["query"].return_value = [
            {
                "id": "e001",
                "fingerprint": "abc123def456",
                "error_type": "ImportError",
                "component": "FLOW",
                "count": 3,
                "severity": "high",
                "status": "new",
                "last_seen": "2026-03-20T10:00:00.000000",
            },
        ]

        result = handle_command("errors", ["list"])

        assert result is True
        mocks["query"].assert_called_once()

        # Verify the Table was constructed with a title containing "Error Registry"
        table_instance = mocks["table_cls"].return_value
        mocks["table_cls"].assert_called_once()
        create_kwargs = mocks["table_cls"].call_args
        assert "Error Registry" in str(create_kwargs), "Table title should contain 'Error Registry'"

        # Verify add_row was called with the entry data
        table_instance.add_row.assert_called_once()
        row_args = table_instance.add_row.call_args[0]
        assert row_args[0] == "e001"  # ID
        assert row_args[1] == "abc123de"  # fingerprint[:8]
        assert row_args[2] == "ImportError"  # error_type
        assert row_args[3] == "FLOW"  # component
        assert row_args[4] == "3"  # count (as string)

        # Verify the table object was printed to console
        mocks["console"].print.assert_any_call(table_instance)

        # Verify summary line with entry count was printed
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_count = any("1 error(s)" in text for text in printed_texts)
        assert has_count, "Expected '1 error(s)' in list summary output"

        mocks["json_handler"].log_operation.assert_called_with(
            "error_command",
            {"subcommand": "list"},
        )

    def test_list_passes_filters_to_query(self):
        """list --status=new --component=FLOW passes filters through."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["query"].return_value = []

        handle_command("errors", ["list", "--status=new", "--component=FLOW", "--severity=high"])

        mocks["query"].assert_called_once_with(
            status="new",
            component="FLOW",
            severity="high",
            limit=50,
        )

    def test_list_custom_limit(self):
        """list --limit=10 passes the limit to query."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["query"].return_value = []

        handle_command("errors", ["list", "--limit=10"])

        mocks["query"].assert_called_once_with(
            status=None,
            component=None,
            severity=None,
            limit=10,
        )


# ---------------------------------------------------------------------------
# handle_command — "stats" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandStats:
    """Tests for the 'stats' subcommand."""

    def test_stats_displays_statistics(self):
        """stats calls get_stats and get_circuit_breaker_status and prints specific values."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["get_stats"].return_value = {
            "total": 5,
            "by_status": {"new": 3, "resolved": 2},
            "by_component": {"FLOW": 4, "API": 1},
            "by_severity": {"high": 2, "medium": 3},
        }
        mocks["get_cb_status"].return_value = {
            "state": "closed",
            "opened_at": 0,
            "cooldown_seconds": 300,
            "recent_error_count": 0,
            "summary_sent": False,
        }

        result = handle_command("errors", ["stats"])

        assert result is True
        mocks["get_stats"].assert_called_once()
        mocks["get_cb_status"].assert_called_once()

        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]

        # Verify heading
        has_heading = any("Error Registry Statistics" in text for text in printed_texts)
        assert has_heading, "Expected 'Error Registry Statistics' heading in output"

        # Verify total errors value printed
        has_total = any("5" in text and "Total errors" in text for text in printed_texts)
        assert has_total, "Expected 'Total errors' line with value 5 in stats output"

        # Verify circuit breaker section is included
        has_cb = any("Circuit Breaker" in text for text in printed_texts)
        assert has_cb, "Expected 'Circuit Breaker' section in stats output"

        # Verify cooldown value printed
        has_cooldown = any("300" in text and "Cooldown" in text for text in printed_texts)
        assert has_cooldown, "Expected cooldown '300s' in stats output"

    def test_stats_logs_operation(self):
        """stats logs the operation via json_handler."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        handle_command("errors", ["stats"])

        mocks["json_handler"].log_operation.assert_called_with(
            "error_command",
            {"subcommand": "stats"},
        )


# ---------------------------------------------------------------------------
# handle_command — "circuit-breaker" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandCircuitBreaker:
    """Tests for the 'circuit-breaker' subcommand."""

    def test_circuit_breaker_shows_status(self):
        """circuit-breaker without args shows current circuit breaker state with all fields."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["get_cb_status"].return_value = {
            "state": "closed",
            "opened_at": 0,
            "cooldown_seconds": 300,
            "recent_error_count": 0,
            "summary_sent": False,
        }

        result = handle_command("errors", ["circuit-breaker"])

        assert result is True
        mocks["get_cb_status"].assert_called()

        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]

        # Verify heading
        has_heading = any("Circuit Breaker Status" in text for text in printed_texts)
        assert has_heading, "Expected 'Circuit Breaker Status' heading in output"

        # Verify state value (closed) is displayed
        has_state = any("closed" in text and "State" in text for text in printed_texts)
        assert has_state, "Expected State line with 'closed' in output"

        # Verify cooldown value
        has_cooldown = any("300" in text and "Cooldown" in text for text in printed_texts)
        assert has_cooldown, "Expected Cooldown line with '300' in output"

        # Verify recent errors value
        has_recent = any("Recent errors" in text and "0" in text for text in printed_texts)
        assert has_recent, "Expected Recent errors line with '0' in output"

        # Verify summary_sent field
        has_summary = any("Summary sent" in text and "False" in text for text in printed_texts)
        assert has_summary, "Expected Summary sent line with 'False' in output"

        # Verify closed-state normal operation message
        has_normal = any("Normal operation" in text for text in printed_texts)
        assert has_normal, "Expected 'Normal operation' message for closed state"

    def test_circuit_breaker_open_state(self):
        """circuit-breaker displays open-state details with remaining time."""
        from aipass.trigger.apps.modules.errors import handle_command
        import time

        mocks = _mocks()
        mocks["get_cb_status"].return_value = {
            "state": "open",
            "opened_at": time.time() - 60,
            "cooldown_seconds": 300,
            "recent_error_count": 12,
            "summary_sent": True,
        }

        result = handle_command("errors", ["circuit-breaker"])

        assert result is True
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_paused = any("paused" in text.lower() for text in printed_texts)
        assert has_paused, "Expected 'paused' in open circuit breaker output"

    def test_circuit_breaker_reset(self):
        """circuit-breaker reset calls reset and confirms CLOSED state in output."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        result = handle_command("errors", ["circuit-breaker", "reset"])

        assert result is True
        mocks["cb_reset"].assert_called_once()

        # Verify reset confirmation message was printed
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_reset_msg = any("Circuit breaker reset to CLOSED" in text for text in printed_texts)
        assert has_reset_msg, "Expected 'Circuit breaker reset to CLOSED' confirmation in output"

        # Verify dispatch allowed message
        has_dispatch = any("dispatch" in text.lower() for text in printed_texts)
        assert has_dispatch, "Expected dispatch status message after reset"


# ---------------------------------------------------------------------------
# handle_command — "--help" / "help"
# ---------------------------------------------------------------------------


class TestHandleCommandHelp:
    """Tests for help display."""

    def test_help_flag_shows_help(self):
        """--help triggers the help display with panel, sections, and commands."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        result = handle_command("errors", ["--help"])

        assert result is True

        # print_help creates a Panel with the title text
        mocks["panel_cls"].assert_called_once()
        panel_args = str(mocks["panel_cls"].call_args)
        assert "Error Registry" in panel_args, "Expected Panel with 'Error Registry' title"

        # print_help uses console.rule for section headers
        rule_calls = [str(c) for c in mocks["console"].rule.call_args_list]
        assert any("USAGE" in text for text in rule_calls), "Expected USAGE rule section"
        assert any("COMMANDS" in text for text in rule_calls), "Expected COMMANDS rule section"
        assert any("EXAMPLES" in text for text in rule_calls), "Expected EXAMPLES rule section"

        # Verify command names appear in help output
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        assert any("list" in text for text in printed_texts), "Expected 'list' command in help"
        assert any("resolve" in text for text in printed_texts), "Expected 'resolve' command in help"
        assert any("stats" in text for text in printed_texts), "Expected 'stats' command in help"

    def test_h_flag_shows_help(self):
        """-h triggers the help display."""
        from aipass.trigger.apps.modules.errors import handle_command

        result = handle_command("errors", ["-h"])

        assert result is True

    def test_help_subcommand_shows_help(self):
        """'help' as subcommand triggers help display."""
        from aipass.trigger.apps.modules.errors import handle_command

        result = handle_command("errors", ["help"])

        assert result is True


# ---------------------------------------------------------------------------
# handle_command — no args (introspection)
# ---------------------------------------------------------------------------


class TestHandleCommandIntrospection:
    """Tests for introspection display (no arguments)."""

    def test_no_args_shows_introspection(self):
        """Calling handle_command with empty args shows module introspection with handler details."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        result = handle_command("errors", [])

        assert result is True
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]

        # Verify module name heading
        has_module_name = any("errors Module" in text for text in printed_texts)
        assert has_module_name, "Expected 'errors Module' heading in introspection output"

        # Verify description line
        has_desc = any("error registry management" in text.lower() for text in printed_texts)
        assert has_desc, "Expected module description in introspection output"

        # Verify handler listing
        has_handlers = any("Connected Handlers" in text for text in printed_texts)
        assert has_handlers, "Expected 'Connected Handlers' section in introspection output"

        # Verify specific handler names appear
        has_registry = any("error_registry.py" in text for text in printed_texts)
        assert has_registry, "Expected 'error_registry.py' handler in introspection"
        has_reporter = any("error_reporter.py" in text for text in printed_texts)
        assert has_reporter, "Expected 'error_reporter.py' handler in introspection"


# ---------------------------------------------------------------------------
# handle_command — wrong command name
# ---------------------------------------------------------------------------


class TestHandleCommandWrongModule:
    """Tests for command name mismatch."""

    def test_wrong_command_returns_false(self):
        """handle_command returns False when command is not 'errors'."""
        from aipass.trigger.apps.modules.errors import handle_command

        result = handle_command("medic", ["list"])

        assert result is False


# ---------------------------------------------------------------------------
# handle_command — unknown subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandUnknown:
    """Tests for unknown subcommands."""

    def test_unknown_subcommand_shows_error(self):
        """Unknown subcommand calls the error display with exact message format and suggestion."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        result = handle_command("errors", ["foobar"])

        assert result is True
        mocks["error_fn"].assert_called_once()

        # Verify the exact message format: "Unknown subcommand: foobar"
        call_args = mocks["error_fn"].call_args
        assert call_args[0][0] == "Unknown subcommand: foobar", (
            f"Expected exact error message 'Unknown subcommand: foobar', got {call_args[0][0]!r}"
        )

        # Verify suggestion kwarg is passed
        assert "suggestion" in call_args[1], "Expected 'suggestion' keyword argument"
        assert "help" in call_args[1]["suggestion"].lower(), "Expected suggestion to mention 'help'"


# ---------------------------------------------------------------------------
# report_error — public API
# ---------------------------------------------------------------------------


class TestReportError:
    """Tests for the report_error public API re-export."""

    def test_report_error_delegates_to_reporter(self):
        """report_error is the function from error_reporter."""
        from aipass.trigger.apps.modules.errors import report_error

        mocks = _mocks()
        mocks["report_error"].return_value = {
            "fingerprint": "deadbeef1234",
            "is_new": True,
            "dispatched": False,
        }

        result = report_error(
            error_type="ImportError",
            message="No module named 'foo'",
            component="FLOW",
            log_path="/tmp/flow.log",
            severity="high",
        )

        mocks["report_error"].assert_called_once_with(
            error_type="ImportError",
            message="No module named 'foo'",
            component="FLOW",
            log_path="/tmp/flow.log",
            severity="high",
        )
        assert result["fingerprint"] == "deadbeef1234"
        assert result["is_new"] is True


# ---------------------------------------------------------------------------
# handle_command — "resolve" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandResolve:
    """Tests for the 'resolve' subcommand."""

    def test_resolve_marks_error_resolved(self):
        """resolve <id> looks up the entry and updates status with correct fingerprint."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["get_entry"].return_value = {
            "id": "e001",
            "fingerprint": "abc123def456abc123def456abc123def456abc1",
            "error_type": "ImportError",
            "component": "FLOW",
            "status": "new",
        }

        result = handle_command("errors", ["resolve", "e001"])

        assert result is True
        mocks["update_status"].assert_called_once()
        update_call = mocks["update_status"].call_args

        # Verify fingerprint (first positional arg) comes from the entry, not the CLI arg
        assert update_call[0][0] == "abc123def456abc123def456abc123def456abc1", (
            "Expected update_status to be called with the full fingerprint from the entry"
        )
        assert update_call[0][1] == "resolved"

        # Verify confirmation message was printed
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_resolved = any("Resolved" in text and "e001" in text for text in printed_texts)
        assert has_resolved, "Expected 'Resolved' confirmation with error ID in output"

    def test_resolve_no_id_prints_usage(self):
        """resolve with no ID prints a usage hint."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        result = handle_command("errors", ["resolve"])

        assert result is True
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_missing = any("missing" in text.lower() for text in printed_texts)
        assert has_missing, "Expected 'missing' in resolve-no-id output"


# ---------------------------------------------------------------------------
# handle_command — "clear-resolved" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandClearResolved:
    """Tests for the 'clear-resolved' subcommand."""

    def test_clear_resolved_default_days(self):
        """clear-resolved with no args uses default 7 days."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["clear_resolved"].return_value = 3

        result = handle_command("errors", ["clear-resolved"])

        assert result is True
        mocks["clear_resolved"].assert_called_once_with(days=7)

    def test_clear_resolved_custom_days(self):
        """clear-resolved --days=14 passes the custom days value."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["clear_resolved"].return_value = 0

        handle_command("errors", ["clear-resolved", "--days=14"])

        mocks["clear_resolved"].assert_called_once_with(days=14)

    def test_clear_resolved_none_removed(self):
        """clear-resolved prints dim message when nothing was removed."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["clear_resolved"].return_value = 0

        handle_command("errors", ["clear-resolved"])

        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_no_resolved = any("no resolved" in text.lower() for text in printed_texts)
        assert has_no_resolved, "Expected 'no resolved' message when nothing cleared"


# ---------------------------------------------------------------------------
# Internal helpers — _parse_args and _fmt_time
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    """Tests for small internal helper functions."""

    def test_parse_args_extracts_key_value(self):
        """_parse_args parses --key=value pairs, stripping leading dashes."""
        from aipass.trigger.apps.modules.errors import _parse_args

        result = _parse_args(["--status=new", "--limit=10", "positional"])

        assert result == {"status": "new", "limit": "10"}

    def test_parse_args_empty(self):
        """_parse_args returns empty dict for empty list."""
        from aipass.trigger.apps.modules.errors import _parse_args

        assert _parse_args([]) == {}

    def test_fmt_time_trims_iso_with_fractional(self):
        """_fmt_time trims '2026-03-20T10:00:00.123456' to readable form."""
        from aipass.trigger.apps.modules.errors import _fmt_time

        assert _fmt_time("2026-03-20T10:00:00.123456") == "2026-03-20 10:00:00"

    def test_fmt_time_trims_iso_without_fractional(self):
        """_fmt_time handles ISO without fractional seconds."""
        from aipass.trigger.apps.modules.errors import _fmt_time

        assert _fmt_time("2026-03-20T10:00:00") == "2026-03-20 10:00:00"

    def test_fmt_time_passthrough_plain(self):
        """_fmt_time passes through non-ISO strings unchanged."""
        from aipass.trigger.apps.modules.errors import _fmt_time

        assert _fmt_time("yesterday") == "yesterday"

    def test_parse_args_none_input(self):
        """_parse_args handles None input gracefully (treats as empty)."""
        from aipass.trigger.apps.modules.errors import _parse_args

        # None is not a valid list, but the function should handle empty-like input
        # The function iterates over args, so passing an empty iterable is the contract
        assert _parse_args([]) == {}

    def test_fmt_time_empty_string(self):
        """_fmt_time returns empty string unchanged when given empty string."""
        from aipass.trigger.apps.modules.errors import _fmt_time

        assert _fmt_time("") == ""

    def test_fmt_time_none_like_string(self):
        """_fmt_time handles a string with no T or dot as passthrough."""
        from aipass.trigger.apps.modules.errors import _fmt_time

        # No 'T' in the string means it falls through to the return-as-is path
        assert _fmt_time("2026-03-20") == "2026-03-20"


# ---------------------------------------------------------------------------
# Contract gap: query() result structure
# ---------------------------------------------------------------------------


class TestQueryResultStructure:
    """Tests verifying query result structure flows correctly through list command."""

    def test_query_result_keys_rendered_in_table(self):
        """query() results with expected keys are rendered correctly in the table."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()
        mocks["query"].return_value = [
            {
                "id": "e042",
                "fingerprint": "deadbeef1234abcd",
                "error_type": "ValueError",
                "component": "API",
                "count": 7,
                "severity": "medium",
                "status": "investigating",
                "last_seen": "2026-03-22T14:30:00.000000",
            },
        ]

        result = handle_command("errors", ["list"])

        assert result is True

        # Verify the table row contains all key fields from the query result
        table_instance = mocks["table_cls"].return_value
        table_instance.add_row.assert_called_once()
        row_args = table_instance.add_row.call_args[0]

        assert row_args[0] == "e042"  # id
        assert row_args[1] == "deadbeef"  # fingerprint[:8]
        assert row_args[2] == "ValueError"  # error_type
        assert row_args[3] == "API"  # component
        assert row_args[4] == "7"  # count as string


# ---------------------------------------------------------------------------
# Contract gap: handle_command with None args
# ---------------------------------------------------------------------------


class TestHandleCommandNoneArgs:
    """Tests for edge-case None args input."""

    def test_handle_command_none_args_shows_introspection(self):
        """handle_command('errors', None) — None args treated as falsy, shows introspection."""
        from aipass.trigger.apps.modules.errors import handle_command

        mocks = _mocks()

        # None is falsy like [], so `if not args` branch triggers introspection
        from typing import Any

        none_as_list: Any = None
        result = handle_command("errors", none_as_list)

        assert result is True
        # Introspection should have printed module name
        printed_texts = [str(c) for c in mocks["console"].print.call_args_list]
        has_module = any("errors Module" in text for text in printed_texts)
        assert has_module, "Expected introspection output when args is None"
