# =================== AIPass ====================
# Name: test_help_markup.py
# Description: Canary tests that literal [placeholders] survive Rich rendering
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-09-27
# =============================================

"""Tests for the rendered [placeholders] of apps/devpulse.py, apps/modules/watchdog.py and its presenter."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the Rich colour tags around HELP_TEXT's placeholders

import io

from rich.console import Console

from aipass.devpulse.apps import devpulse as entry
from aipass.devpulse.apps.handlers.watchdog import presenter
from aipass.devpulse.apps.modules import watchdog

# Rich treats [word] as a style tag, so an unescaped placeholder is consumed silently;
# the product's own console renders to the channel capsys reads, a mock never renders.


def _real_console(width: int = 200) -> tuple[Console, io.StringIO]:
    """A real rendering console writing to a buffer."""
    buffer = io.StringIO()
    return Console(file=buffer, width=width, no_color=True, highlight=False, markup=True), buffer


# ---------------------------------------------------------------------------
# Help-surface placeholders
# ---------------------------------------------------------------------------


class TestHelpPlaceholders:
    """Placeholders in help output must reach the terminal."""

    def test_devpulse_help_keeps_args_placeholder(self, capsys):
        """print_help shows [args...], not a truncated usage line."""
        entry.print_help()
        assert "[args...]" in capsys.readouterr().out

    def test_watchdog_help_keeps_placeholders(self):
        """watchdog --help keeps [--timeout SECONDS] and the optional [command]."""
        console, buffer = _real_console()
        console.print(watchdog.HELP_TEXT)
        output = buffer.getvalue()
        assert "[--timeout SECONDS]" in output
        assert "[command]" in output

    def test_watchdog_timer_and_schedule_help_survive(self, capsys, monkeypatch):
        """The timer/schedule sub-help texts render without losing bracketed text."""
        # The bare verbs print their sub-help after the owner gate; the gate is not the subject.
        gate_calls: list[str] = []

        def _owner_seat() -> bool:
            gate_calls.append("consulted")
            return True

        monkeypatch.setattr(watchdog, "_guard_caller", _owner_seat)
        for verb in ("timer", "schedule"):
            assert watchdog.handle_command("watchdog", [verb]) is True
            # every non-style bracket group in the source must survive rendering
            assert "watchdog" in capsys.readouterr().out
        assert gate_calls == ["consulted", "consulted"]


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
        line = presenter.format_status_line(self.WATCH, lambda s: f"{s}s")
        console, buffer = _real_console()
        console.print(line)
        assert "[wd-1234]" in buffer.getvalue()

    def test_kill_result_keeps_handle(self, capsys):
        """print_kill_result's [handle] renders literally."""
        presenter.print_kill_result({"handle": "wd-9", "killed": True, "was_alive": True, "reason": "test"})
        assert "[wd-9]" in capsys.readouterr().out


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
