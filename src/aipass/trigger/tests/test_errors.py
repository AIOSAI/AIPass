# =================== AIPass ====================
# Name: test_errors.py
# Description: Unit tests for the errors module (error registry management CLI)
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/errors.py: the errors command routing and its report_error re-export."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — what the registry stores and returns, in tests/test_error_registry.py
# seedgo: no-test-needed(covered_elsewhere) — how report_error fingerprints and dispatches, in tests/test_error_reporter.py

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from aipass.cli.apps.modules import display
from aipass.trigger.apps.handlers import error_reporter
from aipass.trigger.apps.modules import errors

# Module-level dict populated by the autouse fixture each test.
_shared_mocks: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# The edge — autouse fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _registry_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap what the real errors module reaches outside through, and nothing else.

    The module under test, rich and the cli console are all real; output is read
    off capsys. Replaced on the errors module are the registry reads and writes
    (the live trigger_json/error_registry.json and its circuit breaker), the
    source-fix email the suppress route sends, the prax logger, and
    json_handler.log_operation.
    """
    mock_logger = MagicMock()
    mock_log_operation = MagicMock()
    monkeypatch.setattr(errors, "logger", mock_logger)
    monkeypatch.setattr(errors.json_handler, "log_operation", mock_log_operation)

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
    mock_purge_stale = MagicMock(return_value=0)
    mock_send_fix_email = MagicMock(return_value=False)

    monkeypatch.setattr(errors, "query", mock_query)
    monkeypatch.setattr(errors, "get_entry", mock_get_entry)
    monkeypatch.setattr(errors, "update_status", mock_update_status)
    monkeypatch.setattr(errors, "clear_resolved", mock_clear_resolved)
    monkeypatch.setattr(errors, "get_stats", mock_get_stats)
    monkeypatch.setattr(errors, "get_circuit_breaker_status", mock_get_cb_status)
    monkeypatch.setattr(errors, "circuit_breaker_reset", mock_cb_reset)
    monkeypatch.setattr(errors, "update_source_fix_status", mock_update_fix_status)
    monkeypatch.setattr(errors, "purge_stale", mock_purge_stale)
    monkeypatch.setattr(errors, "_send_source_fix_email", mock_send_fix_email)

    # Expose mocks to tests via the module-level dict
    _shared_mocks.clear()
    _shared_mocks.update(
        {
            "logger": mock_logger,
            "log_operation": mock_log_operation,
            "query": mock_query,
            "get_entry": mock_get_entry,
            "update_status": mock_update_status,
            "clear_resolved": mock_clear_resolved,
            "get_stats": mock_get_stats,
            "get_cb_status": mock_get_cb_status,
            "cb_reset": mock_cb_reset,
            "update_fix_status": mock_update_fix_status,
            "purge_stale": mock_purge_stale,
            "send_fix_email": mock_send_fix_email,
        }
    )


def _mocks() -> dict[str, Any]:
    """Shorthand accessor for the shared mock dict."""
    return _shared_mocks


def _has_line(text: str, *parts: str) -> bool:
    """True when one printed line carries every part."""
    return any(all(part in line for part in parts) for line in text.splitlines())


def _row_cells(out: str, row_id: str) -> list[str]:
    """The cells of the rendered table row whose first cell is *row_id*."""
    for line in out.splitlines():
        cells = [cell.strip() for cell in line.split("│")[1:-1]]
        if cells and cells[0] == row_id:
            return cells
    raise AssertionError(f"no table row {row_id!r} in:\n{out}")


# ---------------------------------------------------------------------------
# handle_command — "list" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandList:
    """Tests for the 'list' subcommand."""

    def test_list_empty_registry(self, capsys: pytest.CaptureFixture[str]) -> None:
        """list with no errors prints a 'no errors' message."""
        mocks = _mocks()
        mocks["query"].return_value = []

        result = errors.handle_command("errors", ["list"])

        assert result is True
        mocks["query"].assert_called_once()
        assert "No errors in registry" in capsys.readouterr().out

    def test_list_with_entries_renders_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        """list with entries calls query and prints a Rich table with correct data."""
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

        result = errors.handle_command("errors", ["list"])

        assert result is True
        mocks["query"].assert_called_once()
        out = capsys.readouterr().out

        # The table's title
        assert "Error Registry" in out, "Table title should contain 'Error Registry'"

        # The one row, cell by cell
        cells = _row_cells(out, "e001")
        assert cells[1] == "abc123de"  # fingerprint[:8]
        assert cells[2] == "ImportError"  # error_type
        assert cells[3] == "FLOW"  # component
        assert cells[4] == "3"  # count (as string)

        # Verify summary line with entry count was printed
        assert "1 error(s)" in out, "Expected '1 error(s)' in list summary output"

        mocks["log_operation"].assert_called_with(
            "error_command",
            {"subcommand": "list"},
        )

    def test_list_passes_filters_to_query(self) -> None:
        """list --status=new --component=FLOW passes filters through."""
        mocks = _mocks()
        mocks["query"].return_value = []

        errors.handle_command("errors", ["list", "--status=new", "--component=FLOW", "--severity=high"])

        mocks["query"].assert_called_once_with(
            status="new",
            component="FLOW",
            severity="high",
            limit=50,
        )

    def test_list_custom_limit(self) -> None:
        """list --limit=10 passes the limit to query."""
        mocks = _mocks()
        mocks["query"].return_value = []

        errors.handle_command("errors", ["list", "--limit=10"])

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

    def test_stats_displays_statistics(self, capsys: pytest.CaptureFixture[str]) -> None:
        """stats calls get_stats and get_circuit_breaker_status and prints specific values."""
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

        result = errors.handle_command("errors", ["stats"])

        assert result is True
        mocks["get_stats"].assert_called_once()
        mocks["get_cb_status"].assert_called_once()

        out = capsys.readouterr().out

        # Verify heading
        assert "Error Registry Statistics" in out, "Expected 'Error Registry Statistics' heading in output"

        # Verify total errors value printed
        assert _has_line(out, "Total errors", "5"), "Expected 'Total errors' line with value 5 in stats output"

        # Verify circuit breaker section is included
        assert "Circuit Breaker" in out, "Expected 'Circuit Breaker' section in stats output"

        # Verify cooldown value printed
        assert _has_line(out, "Cooldown", "300"), "Expected cooldown '300s' in stats output"

    def test_stats_logs_operation(self) -> None:
        """stats logs the operation via json_handler."""
        mocks = _mocks()

        errors.handle_command("errors", ["stats"])

        mocks["log_operation"].assert_called_with(
            "error_command",
            {"subcommand": "stats"},
        )


# ---------------------------------------------------------------------------
# handle_command — "circuit-breaker" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandCircuitBreaker:
    """Tests for the 'circuit-breaker' subcommand."""

    def test_circuit_breaker_shows_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        """circuit-breaker without args shows current circuit breaker state with all fields."""
        mocks = _mocks()
        mocks["get_cb_status"].return_value = {
            "state": "closed",
            "opened_at": 0,
            "cooldown_seconds": 300,
            "recent_error_count": 0,
            "summary_sent": False,
        }

        result = errors.handle_command("errors", ["circuit-breaker"])

        assert result is True
        mocks["get_cb_status"].assert_called()

        out = capsys.readouterr().out

        # Verify heading
        assert "Circuit Breaker Status" in out, "Expected 'Circuit Breaker Status' heading in output"

        # Verify state value (closed) is displayed
        assert _has_line(out, "State", "closed"), "Expected State line with 'closed' in output"

        # Verify cooldown value
        assert _has_line(out, "Cooldown", "300"), "Expected Cooldown line with '300' in output"

        # Verify recent errors value
        assert _has_line(out, "Recent errors", "0"), "Expected Recent errors line with '0' in output"

        # Verify summary_sent field
        assert _has_line(out, "Summary sent", "False"), "Expected Summary sent line with 'False' in output"

        # Verify closed-state normal operation message
        assert "Normal operation" in out, "Expected 'Normal operation' message for closed state"

    def test_circuit_breaker_open_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        """circuit-breaker displays open-state details with remaining time."""
        mocks = _mocks()
        mocks["get_cb_status"].return_value = {
            "state": "open",
            "opened_at": time.time() - 60,
            "cooldown_seconds": 300,
            "recent_error_count": 12,
            "summary_sent": True,
        }

        result = errors.handle_command("errors", ["circuit-breaker"])

        assert result is True
        assert "paused" in capsys.readouterr().err.lower(), "Expected 'paused' in error() output"

    def test_circuit_breaker_reset(self, capsys: pytest.CaptureFixture[str]) -> None:
        """circuit-breaker reset calls reset and confirms CLOSED state in output."""
        mocks = _mocks()

        result = errors.handle_command("errors", ["circuit-breaker", "reset"])

        assert result is True
        mocks["cb_reset"].assert_called_once()
        out = capsys.readouterr().out

        # Verify reset confirmation message was printed
        assert "Circuit breaker reset to CLOSED" in out, "Expected 'Circuit breaker reset to CLOSED' confirmation"

        # Verify dispatch allowed message
        assert "dispatch" in out.lower(), "Expected dispatch status message after reset"


# ---------------------------------------------------------------------------
# handle_command — "--help" / "help"
# ---------------------------------------------------------------------------


class TestHandleCommandHelp:
    """Tests for help display."""

    def test_help_flag_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help triggers the help display with panel, sections, and commands."""
        result = errors.handle_command("errors", ["--help"])

        assert result is True
        out = capsys.readouterr().out

        # print_help opens with a Panel carrying the title text
        assert "Error Registry - Medic v2 Error Management" in out, "Expected Panel with 'Error Registry' title"

        # print_help uses console.rule for section headers — a rule line carries the name
        assert _has_line(out, "─", "USAGE"), "Expected USAGE rule section"
        assert _has_line(out, "─", "COMMANDS"), "Expected COMMANDS rule section"
        assert _has_line(out, "─", "EXAMPLES"), "Expected EXAMPLES rule section"

        # Verify command names appear in help output
        assert _has_line(out, "list", "List tracked errors"), "Expected 'list' command in help"
        assert _has_line(out, "resolve", "Mark error as resolved"), "Expected 'resolve' command in help"
        assert _has_line(out, "stats", "Summary statistics"), "Expected 'stats' command in help"

    def test_h_flag_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """-h triggers the help display."""
        result = errors.handle_command("errors", ["-h"])

        assert result is True
        assert _has_line(capsys.readouterr().out, "─", "COMMANDS"), "-h must print the COMMANDS section"

    def test_help_subcommand_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'help' as subcommand triggers help display."""
        result = errors.handle_command("errors", ["help"])

        assert result is True
        assert _has_line(capsys.readouterr().out, "─", "COMMANDS"), "help must print the COMMANDS section"


# ---------------------------------------------------------------------------
# handle_command — no args (introspection)
# ---------------------------------------------------------------------------


class TestHandleCommandIntrospection:
    """Tests for introspection display (no arguments)."""

    def test_no_args_shows_introspection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Calling handle_command with empty args shows module introspection with handler details."""
        result = errors.handle_command("errors", [])

        assert result is True
        out = capsys.readouterr().out

        # Verify module name heading
        assert "errors Module" in out, "Expected 'errors Module' heading in introspection output"

        # Verify description line
        assert "error registry management" in out.lower(), "Expected module description in introspection output"

        # Verify handler listing
        assert "Connected Handlers" in out, "Expected 'Connected Handlers' section in introspection output"

        # Verify specific handler names appear
        assert "error_registry.py" in out, "Expected 'error_registry.py' handler in introspection"
        assert "error_reporter.py" in out, "Expected 'error_reporter.py' handler in introspection"


# ---------------------------------------------------------------------------
# handle_command — wrong command name
# ---------------------------------------------------------------------------


class TestHandleCommandWrongModule:
    """Tests for command name mismatch."""

    def test_wrong_command_returns_false(self) -> None:
        """handle_command returns False when command is not 'errors'."""
        result = errors.handle_command("medic", ["list"])

        assert result is False


# ---------------------------------------------------------------------------
# handle_command — unknown subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandUnknown:
    """Tests for unknown subcommands."""

    def test_unknown_subcommand_refuses_rather_than_reporting_handled(self, capsys: pytest.CaptureFixture[str]) -> None:
        """`errors foobar` returns False so the entry point can exit non-zero.

        This test used to assert the opposite: the module printed its own
        "Unknown subcommand: foobar" and returned True, which told trigger.py
        the command had been handled — so a refusal exited 0 and no caller
        could branch on it (the owner's standing ruling, FPLAN-0492). Returning
        False routes the refusal through the ONE gate, which names the whole
        invocation and exits 1.
        Mutant run 2026-09-27: handle_command calling error("Unknown subcommand")
        before its return False reddens this.
        """
        result = errors.handle_command("errors", ["foobar"])

        assert result is False
        # The module must NOT print its own refusal — the gate owns the message.
        assert capsys.readouterr().err == ""
        assert display.command_failed() is False


# ---------------------------------------------------------------------------
# report_error — public API
# ---------------------------------------------------------------------------


class TestReportError:
    """Tests for the report_error public API re-export."""

    def test_report_error_delegates_to_reporter(self) -> None:
        """report_error is the function from error_reporter.

        Drone calls errors.report_error; what it reaches must be the reporter's
        own function, not a copy or a wrapper that could drift from it. How the
        reporter fingerprints and dispatches is tests/test_error_reporter.py's.
        """
        assert errors.report_error is error_reporter.report_error


# ---------------------------------------------------------------------------
# handle_command — "resolve" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandResolve:
    """Tests for the 'resolve' subcommand."""

    def test_resolve_marks_error_resolved(self, capsys: pytest.CaptureFixture[str]) -> None:
        """resolve <id> looks up the entry and updates status with correct fingerprint."""
        mocks = _mocks()
        mocks["get_entry"].return_value = {
            "id": "e001",
            "fingerprint": "abc123def456abc123def456abc123def456abc1",
            "error_type": "ImportError",
            "component": "FLOW",
            "status": "new",
        }

        result = errors.handle_command("errors", ["resolve", "e001"])

        assert result is True
        mocks["update_status"].assert_called_once()
        update_call = mocks["update_status"].call_args

        # Verify fingerprint (first positional arg) comes from the entry, not the CLI arg
        assert update_call[0][0] == "abc123def456abc123def456abc123def456abc1", (
            "Expected update_status to be called with the full fingerprint from the entry"
        )
        assert update_call[0][1] == "resolved"

        # Verify confirmation message was routed through success() — its ✅ line on stdout
        out = capsys.readouterr().out
        assert _has_line(out, "✅", "Resolved", "e001"), "Expected 'Resolved' confirmation with error ID from success()"

    def test_resolve_no_id_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        """resolve with no ID prints a usage hint."""
        result = errors.handle_command("errors", ["resolve"])

        assert result is True
        assert "missing" in capsys.readouterr().err.lower(), "Expected 'missing' in error() output"


# ---------------------------------------------------------------------------
# handle_command — "unsuppress" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandUnsuppress:
    """Tests for the 'unsuppress' subcommand (compass #219)."""

    def test_unsuppress_restores_status_to_new(self, capsys: pytest.CaptureFixture[str]) -> None:
        """unsuppress <id> sets a suppressed entry back to 'new' so dispatch resumes."""
        mocks = _mocks()
        mocks["get_entry"].return_value = {
            "id": "e001",
            "fingerprint": "abc123def456abc123def456abc123def456abc1",
            "error_type": "ImportError",
            "component": "FLOW",
            "status": "suppressed",
            "suppress_reason": "known noise",
        }

        result = errors.handle_command("errors", ["unsuppress", "e001"])

        assert result is True
        mocks["update_status"].assert_called_once()
        update_call = mocks["update_status"].call_args
        assert update_call[0][0] == "abc123def456abc123def456abc123def456abc1"
        assert update_call[0][1] == "new"

        # No reason passed — the original suppress_reason survives as history
        assert len(update_call[0]) == 2

        out = capsys.readouterr().out
        assert _has_line(out, "✅", "Unsuppressed", "e001"), "Expected 'Unsuppressed' confirmation from success()"

    def test_unsuppress_noop_when_not_suppressed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """unsuppress on a non-suppressed entry changes nothing and says so."""
        mocks = _mocks()
        mocks["get_entry"].return_value = {
            "id": "e002",
            "fingerprint": "def456abc123def456abc123def456abc123def4",
            "status": "new",
        }

        result = errors.handle_command("errors", ["unsuppress", "e002"])

        assert result is True
        mocks["update_status"].assert_not_called()
        assert "not suppressed" in capsys.readouterr().out, "Expected 'not suppressed' notice"

    def test_unsuppress_no_id_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        """unsuppress with no ID prints a usage hint."""
        result = errors.handle_command("errors", ["unsuppress"])

        assert result is True
        assert "missing" in capsys.readouterr().err.lower(), "Expected 'missing' in error() output"

    def test_unsuppress_unknown_id_reports_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """unsuppress on an unknown ID reports not found without touching status."""
        mocks = _mocks()
        mocks["get_entry"].return_value = None
        mocks["query"].return_value = []

        result = errors.handle_command("errors", ["unsuppress", "nope"])

        assert result is True
        mocks["update_status"].assert_not_called()
        assert "not found" in capsys.readouterr().err.lower(), "Expected 'not found' in error() output"

    def test_stats_shows_silenced_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        """stats surfaces how many fingerprints are currently silenced."""
        mocks = _mocks()
        mocks["get_stats"].return_value = {
            "total": 7,
            "by_status": {"new": 5, "suppressed": 2},
            "by_component": {},
            "by_severity": {},
        }

        errors.handle_command("errors", ["stats"])

        assert _has_line(capsys.readouterr().out, "Silenced", "2"), "Expected a 'Silenced' count line in stats output"


# ---------------------------------------------------------------------------
# handle_command — "clear-resolved" subcommand
# ---------------------------------------------------------------------------


class TestHandleCommandClearResolved:
    """Tests for the 'clear-resolved' subcommand."""

    def test_clear_resolved_default_days(self) -> None:
        """clear-resolved with no args uses default 7 days."""
        mocks = _mocks()
        mocks["clear_resolved"].return_value = 3

        result = errors.handle_command("errors", ["clear-resolved"])

        assert result is True
        mocks["clear_resolved"].assert_called_once_with(days=7)

    def test_clear_resolved_custom_days(self) -> None:
        """clear-resolved --days=14 passes the custom days value."""
        mocks = _mocks()
        mocks["clear_resolved"].return_value = 0

        errors.handle_command("errors", ["clear-resolved", "--days=14"])

        mocks["clear_resolved"].assert_called_once_with(days=14)

    def test_clear_resolved_failure_reports_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """clear-resolved reports a failed clear (-1) through error(), not as "nothing to clear".

        Red first 2026-09-27 against _cmd_clear_resolved with no removed < 0 branch.
        """
        mocks = _mocks()
        mocks["clear_resolved"].return_value = -1

        assert errors.handle_command("errors", ["clear-resolved"]) is True

        captured = capsys.readouterr()
        assert captured.err.count("❌") == 1
        assert _has_line(captured.err, "❌", "clear")
        assert display.command_failed() is True
        assert "no resolved" not in captured.out.lower()

    def test_purge_failure_reports_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """purge reports a failed purge (-1) through error(), never as "Purged -1 entries".

        Red first 2026-09-27 against _cmd_purge with no removed < 0 branch.
        """
        mocks = _mocks()
        mocks["purge_stale"].return_value = -1

        assert errors.handle_command("errors", ["purge"]) is True

        captured = capsys.readouterr()
        assert captured.err.count("❌") == 1
        assert _has_line(captured.err, "❌", "purge")
        assert display.command_failed() is True
        assert "Purged -1" not in captured.out

    def test_clear_resolved_none_removed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """clear-resolved prints dim message when nothing was removed."""
        mocks = _mocks()
        mocks["clear_resolved"].return_value = 0

        errors.handle_command("errors", ["clear-resolved"])

        assert "no resolved" in capsys.readouterr().out.lower(), "Expected 'no resolved' message when nothing cleared"


# ---------------------------------------------------------------------------
# --key=value flags and the Last Seen cell, through the list command
# ---------------------------------------------------------------------------


class TestArgsAndTimeThroughList:
    """--key=value parsing and the Last Seen cell, read off the list command."""

    @staticmethod
    def _last_seen_cell(capsys: pytest.CaptureFixture[str], last_seen: str) -> str:
        """Run `errors list` over one entry and return the Last Seen cell it rendered."""
        mocks = _mocks()
        mocks["query"].return_value = [{"id": "e001", "fingerprint": "abc123def456", "last_seen": last_seen}]
        errors.handle_command("errors", ["list"])
        return _row_cells(capsys.readouterr().out, "e001")[7]

    def test_list_parses_key_value_flags(self) -> None:
        """--key=value pairs reach query with the dashes stripped; a bare word is ignored.

        Mutant run 2026-09-27: _parse_args keeps the leading dashes (no lstrip) -> red.
        """
        errors.handle_command("errors", ["list", "--status=new", "--limit=10", "positional"])

        _mocks()["query"].assert_called_once_with(status="new", component=None, severity=None, limit=10)

    def test_list_with_no_flags_uses_defaults(self) -> None:
        """No flags parse to nothing: no filters and the default limit of 50.

        Mutant run 2026-09-27: _cmd_list default limit "50" -> "20" -> red.
        """
        errors.handle_command("errors", ["list"])

        _mocks()["query"].assert_called_once_with(status=None, component=None, severity=None, limit=50)

    def test_last_seen_trims_iso_with_fractional(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'2026-03-20T10:00:00.123456' renders as '2026-03-20 10:00:00'.

        Mutant run 2026-09-27: _fmt_time returns iso unchanged -> red.
        """
        assert self._last_seen_cell(capsys, "2026-03-20T10:00:00.123456") == "2026-03-20 10:00:00"

    def test_last_seen_trims_iso_without_fractional(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ISO without fractional seconds still loses its T.

        Mutant run 2026-09-27: _fmt_time returns iso unchanged -> red.
        """
        assert self._last_seen_cell(capsys, "2026-03-20T10:00:00") == "2026-03-20 10:00:00"

    def test_last_seen_passthrough_plain(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A non-ISO string renders unchanged.

        Mutant run 2026-09-27: _fmt_time's last return iso -> iso.upper() -> red.
        """
        assert self._last_seen_cell(capsys, "yesterday") == "yesterday"

    def test_last_seen_empty_string(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An empty last_seen renders as an empty cell.

        Mutant run 2026-09-27: _fmt_time's last return iso -> iso or "?" -> red.
        """
        assert self._last_seen_cell(capsys, "") == ""

    def test_last_seen_date_only_passthrough(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A date with no T or dot falls through unchanged.

        Mutant run 2026-09-27: _fmt_time's last return iso -> iso.replace("-", "/") -> red.
        """
        assert self._last_seen_cell(capsys, "2026-03-20") == "2026-03-20"


# ---------------------------------------------------------------------------
# Contract gap: query() result structure
# ---------------------------------------------------------------------------


class TestQueryResultStructure:
    """Tests verifying query result structure flows correctly through list command."""

    def test_query_result_keys_rendered_in_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        """query() results with expected keys are rendered correctly in the table.

        Mutant run 2026-09-27: _cmd_list fingerprint [:8] -> [:9] reddens this.
        """
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

        result = errors.handle_command("errors", ["list"])

        assert result is True

        # Verify the table row contains all key fields from the query result
        row_cells = _row_cells(capsys.readouterr().out, "e042")

        assert row_cells[1] == "deadbeef"  # fingerprint[:8]
        assert row_cells[2] == "ValueError"  # error_type
        assert row_cells[3] == "API"  # component
        assert row_cells[4] == "7"  # count as string


# ---------------------------------------------------------------------------
# Contract gap: handle_command with None args
# ---------------------------------------------------------------------------


class TestHandleCommandNoneArgs:
    """Tests for edge-case None args input."""

    def test_handle_command_none_args_shows_introspection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """handle_command('errors', None) — None args treated as falsy, shows introspection."""
        # None is falsy like [], so `if not args` branch triggers introspection
        none_as_list: Any = None
        result = errors.handle_command("errors", none_as_list)

        assert result is True
        # Introspection should have printed module name
        assert "errors Module" in capsys.readouterr().out, "Expected introspection output when args is None"


# ---------------------------------------------------------------------------
# help_flag_safety canary — a help flag ANYWHERE explains, never executes
# ---------------------------------------------------------------------------


class TestHelpFlagSafety:
    """A help flag past position 0 must describe, never run the subcommand."""

    def test_help_flag_after_subcommand_does_not_run_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`errors list --help` must not execute the list query.

        `list` is the read-only probe. The route target is mocked, so a
        missing gate surfaces as a call that should not have happened.
        """
        ran = MagicMock()
        monkeypatch.setattr(errors, "_cmd_list", ran)
        printed = MagicMock()
        monkeypatch.setattr(errors, "print_help", printed)

        result = errors.handle_command("errors", ["list", "--help"])

        assert result is True
        printed.assert_called_once()
        ran.assert_not_called()

    def test_short_flag_after_subcommand_and_operand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`errors list --branch api -h` — the flag is last, still explains."""
        ran = MagicMock()
        monkeypatch.setattr(errors, "_cmd_list", ran)
        printed = MagicMock()
        monkeypatch.setattr(errors, "print_help", printed)

        result = errors.handle_command("errors", ["list", "--branch", "api", "-h"])

        assert result is True
        printed.assert_called_once()
        ran.assert_not_called()

    def test_bare_word_help_as_an_operand_is_not_a_help_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`errors suppress <id> help` — a reason, not a request for the manual."""
        ran = MagicMock()
        monkeypatch.setattr(errors, "_cmd_suppress", ran)
        printed = MagicMock()
        monkeypatch.setattr(errors, "print_help", printed)

        errors.handle_command("errors", ["suppress", "abc123", "help"])

        # handle_command returns the subcommand's own result here, so the
        # proof is the call itself: the reason text was not read as a flag.
        ran.assert_called_once()
        assert ran.call_args[0][1] == ["abc123", "help"]
        printed.assert_not_called()
