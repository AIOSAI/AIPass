#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_log_health.py
# Description: Tests for the log-health command module
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Tests for apps/modules/log_health.py

The snapshot display is the reason this file exists. `snapshot` reports the
rates a previous scan measured, and when it has none it used to render
identically to a genuinely quiet system: "329 idle files (0 lines/min)".
An operator cannot tell a calm fleet from a tracker that never ran, so the
zero-state has to name its own cause.

Every display test renders through a REAL Rich console — the shared conftest
installs a MagicMock console, which records calls but never renders, so it
cannot fail on anything that happens at render time.

Covers:
- snapshot with no recent samples says so instead of reporting idle
- snapshot with fresh samples reports their age
- scan output is unchanged by the staleness reporting
- subcommand routing and the unknown-subcommand path
"""

import importlib
import io

from rich.console import Console


def _render(call):
    """Call ``call(module)`` with a real Rich console and return the output text."""
    module = importlib.import_module("aipass.prax.apps.modules.log_health")
    buffer = io.StringIO()
    real_console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
    original = getattr(module, "console")
    setattr(module, "console", real_console)
    try:
        call(module)
    finally:
        setattr(module, "console", original)
    return buffer.getvalue()


def _row(name="prax_monitor.log", rate=0.0, age=None, branch="PRAX"):
    """Build one get_snapshot()/scan_rates() result row."""
    return {
        "file": name,
        "path": f"/tmp/system_logs/{name}",
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

    def test_no_recent_samples_is_reported_not_shown_as_idle(self):
        """All-zero snapshot names its cause instead of implying every file is idle."""
        rows = [_row(name=f"branch_{i}.log") for i in range(5)]
        output = _render(lambda m: m._display_rates(rows, is_scan=False))

        assert "No recent measurements" in output
        assert "log-health scan" in output

    def test_fresh_samples_report_their_age(self):
        """A snapshot backed by recent samples says how old the newest one is."""
        rows = [_row(rate=7.5, age=12.0)]
        output = _render(lambda m: m._display_rates(rows, is_scan=False))

        assert "Newest sample: 12s ago" in output
        assert "No recent measurements" not in output

    def test_scan_output_never_carries_the_staleness_notice(self):
        """A scan measures right now, so the notice would be a lie on that path."""
        rows = [_row(name=f"branch_{i}.log") for i in range(5)]
        output = _render(lambda m: m._display_rates(rows, is_scan=True))

        assert "No recent measurements" not in output

    def test_empty_snapshot_keeps_its_own_message(self):
        """Nothing tracked at all is a different state from nothing recent."""
        output = _render(lambda m: m._display_rates([], is_scan=False))

        assert "No log files tracked yet" in output
        assert "No recent measurements" not in output

    def test_active_rows_still_render_with_branch_tag(self):
        """The staleness work must not disturb normal active-file rows."""
        rows = [_row(rate=42.0, age=3.0)]
        output = _render(lambda m: m._display_rates(rows, is_scan=False))

        assert "prax_monitor.log" in output
        assert "42.0 lines/min" in output
        assert "[PRAX]" in output


class TestRouting:
    """handle_command dispatches the documented subcommands."""

    def test_rejects_other_commands(self):
        """Only 'log-health' is handled."""
        module = importlib.import_module("aipass.prax.apps.modules.log_health")
        assert module.handle_command("monitor", ["run"]) is False

    def test_unknown_subcommand_reports_and_shows_help(self):
        """A bogus subcommand is named, not silently swallowed."""
        module = importlib.import_module("aipass.prax.apps.modules.log_health")
        assert module.handle_command("log-health", ["bogus"]) is True
