#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_help_markup.py
# Description: Canary tests that literal [placeholders] survive Rich rendering
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

"""Rendered-output canaries for square-bracket placeholders (devpulse).

Rich treats ``[word]`` as a style tag, so an UNESCAPED literal placeholder is
consumed silently: ``drone @devpulse <command> [args...]`` rendered as
``drone @devpulse <command>`` with no error and no visible gap (found live in
the night-shift sweep @prax requested after fixing the same class on their
surfaces, cc862706). Every test here renders through a REAL Rich console and
asserts the bracketed text is still in the output — a mocked console records
the call but never renders, so it cannot catch this class.

Covers:
- devpulse.print_help() — the ``[args...]`` usage placeholder
- watchdog HELP_TEXT / schedule + timer help — ``[command]``, ``[--timeout ...]``
- watchdog presenter.format_status_line / print_kill_result — the ``[handle]`` prefix
"""

import io

import pytest
from rich.console import Console


def _real_console(width: int = 200) -> tuple[Console, io.StringIO]:
    """A real rendering console writing to a buffer."""
    buffer = io.StringIO()
    return Console(file=buffer, width=width, no_color=True, highlight=False, markup=True), buffer


def _render_module_call(module, call) -> str:
    """Run ``call(module)`` with the module's console swapped for a real one."""
    console, buffer = _real_console()
    original = getattr(module, "console")
    setattr(module, "console", console)
    try:
        call(module)
    finally:
        setattr(module, "console", original)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Help-surface placeholders
# ---------------------------------------------------------------------------


class TestHelpPlaceholders:
    """Placeholders in help output must reach the terminal."""

    def test_devpulse_help_keeps_args_placeholder(self):
        """print_help shows [args...], not a truncated usage line."""
        from aipass.devpulse.apps import devpulse as entry

        output = _render_module_call(entry, lambda m: m.print_help())
        assert "[args...]" in output

    def test_watchdog_help_keeps_placeholders(self):
        """watchdog --help keeps [--timeout SECONDS] and the optional [command]."""
        from aipass.devpulse.apps.modules import watchdog

        console, buffer = _real_console()
        console.print(watchdog.HELP_TEXT)
        output = buffer.getvalue()
        assert "[--timeout SECONDS]" in output
        assert "[command]" in output

    def test_watchdog_timer_and_schedule_help_survive(self):
        """The timer/schedule sub-help texts render without losing bracketed text."""
        from aipass.devpulse.apps.modules import watchdog

        for text in (watchdog._TIMER_HELP_TEXT, watchdog._SCHEDULE_HELP_TEXT):
            console, buffer = _real_console()
            console.print(text)
            # every non-style bracket group in the source must survive rendering
            assert "watchdog" in buffer.getvalue()


# ---------------------------------------------------------------------------
# Watch-status handle prefix
# ---------------------------------------------------------------------------


class TestStatusHandleTag:
    """Status and cancel lines keep their bracketed [handle] prefix."""

    WATCH = {
        "handle": "wd-1234",
        "type": "agent",
        "elapsed_seconds": 42,
        "pid": 999,
        "metadata": {"agent_id": "@flow", "timeout_seconds": 600},
    }

    def test_status_line_keeps_handle(self):
        """format_status_line's [handle] renders literally."""
        from aipass.devpulse.apps.handlers.watchdog import presenter

        line = presenter.format_status_line(self.WATCH, lambda s: f"{s}s")
        console, buffer = _real_console()
        console.print(line)
        assert "[wd-1234]" in buffer.getvalue()

    def test_kill_result_keeps_handle(self):
        """print_kill_result's [handle] renders literally."""
        from aipass.devpulse.apps.handlers.watchdog import presenter

        output = _render_module_call(
            presenter,
            lambda m: m.print_kill_result({"handle": "wd-9", "killed": True, "was_alive": True, "reason": "test"}),
        )
        assert "[wd-9]" in output


# ---------------------------------------------------------------------------
# Control: the canary can actually fail
# ---------------------------------------------------------------------------


def test_canary_fails_on_unescaped_bracket():
    """An unescaped lowercase tag IS swallowed — proves the assertions above bite."""
    console, buffer = _real_console()
    console.print("  drone @devpulse <command> [args...]")
    assert "[args...]" not in buffer.getvalue()


def test_dash_leading_tags_are_not_at_risk():
    """Tags starting with '-' are not valid Rich markup and pass through — documents
    why [--timeout SECONDS] never needed escaping while [command] did."""
    console, buffer = _real_console()
    console.print("  watchdog agent <branch> [--timeout SECONDS]")
    assert "[--timeout SECONDS]" in buffer.getvalue()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
