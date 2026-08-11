#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_help_markup.py
# Description: Canary tests that literal [placeholders] survive Rich rendering
# Version: 1.0.0
# Created: 2026-08-10
# Modified: 2026-08-10
# =============================================

"""Rendered-output canaries for square-bracket placeholders.

Rich treats ``[word]`` as a style tag, so an UNESCAPED literal placeholder is
consumed silently: ``drone @prax monitor run [branches]`` renders as
``drone @prax monitor run`` with no error and no visible gap. Every test here
renders through a REAL Rich console (not the MagicMock the shared conftest
installs) and asserts the bracketed text is still in the output — a mocked
console records the call but never renders, so it cannot catch this class.

Covers:
- monitor.print_help() — the ``[branches]`` argument placeholder
- prax.print_help() — the ``[options]`` usage placeholder
- log_health._display_rates() — the ``[branch]`` attribution tag on every row
"""

import importlib
import io

import pytest
from rich.console import Console


def _render(module_path: str, call):
    """Call ``call(module)`` with a real Rich console and return the output text."""
    module = importlib.import_module(module_path)
    buffer = io.StringIO()
    real_console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
    original = getattr(module, "console")
    setattr(module, "console", real_console)
    try:
        call(module)
    finally:
        setattr(module, "console", original)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Help-surface placeholders
# ---------------------------------------------------------------------------


class TestHelpPlaceholders:
    """Placeholders in --help output must reach the terminal."""

    def test_monitor_help_keeps_branches_placeholder(self):
        """monitor --help shows [branches], not a truncated 'monitor run'."""
        output = _render("aipass.prax.apps.modules.monitor", lambda m: m.print_help())
        assert "[branches]" in output

    def test_prax_help_keeps_options_placeholder(self):
        """prax --help shows the [options] usage placeholder."""
        output = _render("aipass.prax.apps.prax", lambda m: m.print_help())
        assert "[options]" in output

    def test_monitor_help_documents_commons_feed(self):
        """Commons feed mode is discoverable from --help (devpulse 62dcd0cc)."""
        output = _render("aipass.prax.apps.modules.monitor", lambda m: m.print_help())
        assert "monitor run commons" in output

    def test_monitor_help_does_not_advertise_mission_control_filter(self):
        """_handle_interactive_cmd dispatches only help/status — no bare 'filter' claim."""
        output = _render("aipass.prax.apps.modules.monitor", lambda m: m.print_help())
        for line in output.splitlines():
            if line.strip().startswith("filter"):
                pytest.fail(f"help advertises an unhandled Mission Control command: {line.strip()}")


# ---------------------------------------------------------------------------
# log-health branch attribution
# ---------------------------------------------------------------------------


class TestLogHealthBranchTag:
    """Every log-health row carries a visible [branch] tag."""

    ROWS = [
        {
            "file": "prax_monitor.log",
            "rate_lines_per_min": 910,
            "size_kb": 44,
            "branch": "prax",
            "severity": "critical",
        },
        {
            "file": "seedgo_audit.log",
            "rate_lines_per_min": 12,
            "size_kb": 8,
            "branch": "seedgo",
            "severity": None,
        },
        {
            "file": "cli_drone.log",
            "rate_lines_per_min": 0,
            "size_kb": 2,
            "branch": "cli",
            "severity": None,
        },
    ]

    @pytest.mark.parametrize("branch", ["prax", "seedgo", "cli"])
    def test_branch_tag_survives_rendering(self, branch):
        """Flagged, active and idle rows all keep their bracketed branch name."""
        output = _render(
            "aipass.prax.apps.modules.log_health",
            lambda m: m._display_rates(list(self.ROWS), is_scan=True),
        )
        assert f"[{branch}]" in output

    def test_canary_fails_on_unescaped_bracket(self):
        """The assertion above can actually fail — an unescaped tag is swallowed."""
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
        console.print("  cli_drone.log: 2 KB [cli]")
        assert "[cli]" not in buffer.getvalue()
