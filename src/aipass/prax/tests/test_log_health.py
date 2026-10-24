# =================== AIPass ====================
# Name: test_log_health.py
# Description: Tests for the log-health command module
# Version: 1.1.0
# Created: 2026-08-13
# Modified: 2026-10-23
# =============================================

"""Tests for apps/modules/log_health.py."""

# A snapshot with no recent samples must name its cause, not read as a quiet fleet. Rendered
# through the product's own console: a recording mock never renders, so it could not fail.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(help_flag_safety) — -h routing to print_help, covered by tests/test_help_flag_safety.py
# seedgo: no-test-needed(introspection) — print_introspection's no-args self-map, covered by that row
# seedgo: no-test-needed(through_the_command) — scan_rates and get_snapshot, covered by tests/test_rate_tracker.py
# seedgo: no-test-needed(trigger) — _get_event_callback's lookup of trigger.fire, covered by that row
# seedgo: no-test-needed(json_structure) — the log_health_executed record written through json_handler.log_operation

from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.apps.modules import log_health


@pytest.fixture
def render(monkeypatch, capsys):
    """Call ``call(log_health)`` through the product's own console and return what it printed."""
    monkeypatch.setattr(log_health, "logger", MagicMock())
    monkeypatch.setattr(log_health, "json_handler", MagicMock())

    def _render(call) -> str:
        capsys.readouterr()
        call(log_health)
        return capsys.readouterr().out

    return _render


def _row(logs_dir, name="prax_monitor.log", rate=0.0, age=None, branch="PRAX"):
    """Build one get_snapshot()/scan_rates() result row, its path under ``logs_dir``."""
    return {
        "file": name,
        "path": str(logs_dir / name),
        "size_kb": 12.5,
        "rate_lines_per_min": rate,
        "age_seconds": age,
        "warning_sustained": 0,
        "critical_sustained": 0,
        "severity": None,
        "branch": branch,
    }


class TestSnapshotStaleness:
    """A snapshot with nothing recent must not read as a quiet system."""

    @pytest.fixture(autouse=True)
    def _keep_render(self, render):
        self._render = render

    def test_no_recent_samples_is_reported_not_shown_as_idle(self, tmp_path):
        """All-zero snapshot names its cause instead of implying every file is idle."""
        rows = [_row(tmp_path, name=f"branch_{i}.log") for i in range(5)]
        output = self._render(lambda m: m._display_rates(rows, is_scan=False))

        assert "No recent measurements" in output
        assert "log-health scan" in output

    def test_fresh_samples_report_their_age(self, tmp_path):
        """A snapshot backed by recent samples says how old the newest one is."""
        rows = [_row(tmp_path, rate=7.5, age=12.0)]
        output = self._render(lambda m: m._display_rates(rows, is_scan=False))

        assert "Newest sample: 12s ago" in output
        assert "No recent measurements" not in output

    def test_scan_output_never_carries_the_staleness_notice(self, tmp_path):
        """A scan measures right now, so the notice would be a lie on that path."""
        rows = [_row(tmp_path, name=f"branch_{i}.log") for i in range(5)]
        output = self._render(lambda m: m._display_rates(rows, is_scan=True))

        assert "No recent measurements" not in output

    def test_empty_snapshot_keeps_its_own_message(self):
        """Nothing tracked at all is a different state from nothing recent."""
        output = self._render(lambda m: m._display_rates([], is_scan=False))

        assert "No log files tracked yet" in output
        assert "No recent measurements" not in output

    def test_active_rows_still_render_with_branch_tag(self, tmp_path):
        """The staleness work must not disturb normal active-file rows."""
        rows = [_row(tmp_path, rate=42.0, age=3.0)]
        output = self._render(lambda m: m._display_rates(rows, is_scan=False))

        assert "prax_monitor.log" in output
        assert "42.0 lines/min" in output
        assert "[PRAX]" in output


class TestRouting:
    """handle_command dispatches the documented subcommands."""

    def test_rejects_other_commands(self):
        """Only 'log-health' is handled."""
        assert log_health.handle_command("monitor", ["run"]) is False

    def test_unknown_subcommand_reports_and_shows_help(self):
        """A bogus subcommand is refused by name and never reported as handled (True would exit 0)."""
        with pytest.raises(UnknownArgument) as refusal:
            log_health.handle_command("log-health", ["bogus"])

        assert refusal.value.verb == "log-health"
        assert refusal.value.token == "bogus"


def test_a_trailing_argument_after_scan_is_refused():
    """`scan --dry-run` is refused by name, not run as a scan."""
    with pytest.raises(UnknownArgument) as refusal:
        log_health.handle_command("log-health", ["scan", "--dry-run"])
    assert refusal.value.token == "--dry-run"


def test_a_trigger_that_raises_oserror_on_import_is_no_callback(monkeypatch):
    """trigger's cwd guard raises OSError at import; log-health still runs without a callback."""
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith("aipass.trigger"):
            raise OSError("no readable cwd")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(log_health, "logger", MagicMock())
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert log_health._get_event_callback() is None
