# =================== AIPass ====================
# Name: test_display_resilience.py
# Description: The display consumer must survive an unrenderable event
# Version: 1.2.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/monitor.py and apps/handlers/monitoring/unified_stream.py."""

# Event text is untrusted Rich markup, and one unrenderable event must not kill the display consumer.
# Rendered through the product's own console: a recording mock never renders, so it could not fail.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — handle_command and _run_monitor, covered by tests/test_monitor_module.py
# seedgo: no-test-needed(through_the_command) — _start_threads, _stop_threads, covered by tests/test_monitor_module.py
# seedgo: no-test-needed(through_the_command) — _get_watch_directories, covered by tests/test_monitor_module.py
# seedgo: no-test-needed(through_the_command) — the observer fallback, covered by tests/test_monitor_module.py
# seedgo: no-test-needed(through_the_command) — monitor.py's print_help(), covered by tests/test_help_markup.py
# seedgo: no-test-needed(through_the_command) — print_status's formatting, covered by tests/test_monitoring_handlers.py
# seedgo: no-test-needed(through_the_command) — the rate worker's scan_rates(), covered by tests/test_rate_tracker.py
# seedgo: no-test-needed(constant) — COLORS, SYMBOLS and LEVEL_COLORS, the style tables print_event reads

import io
import threading
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.errors import MarkupError

from aipass.prax.apps.handlers.monitoring import unified_stream
from aipass.prax.apps.handlers.monitoring.branch_scope import parse_scope
from aipass.prax.apps.modules import monitor


@pytest.fixture
def render(monkeypatch, capsys):
    """Run ``call(unified_stream)`` through the product's own console, return what it printed."""
    monkeypatch.setattr(unified_stream, "json_handler", MagicMock())
    monkeypatch.setattr(unified_stream, "logger", MagicMock())

    def _render(call) -> str:
        capsys.readouterr()
        call(unified_stream)
        return capsys.readouterr().out

    return _render


CRASHING_MESSAGE = "PATH resolved to [/usr/bin] for the spawned shell"

EATEN_MESSAGE = "[event_queue] The live monitor display queue is full"


class TestEventTextIsUntrustedMarkup:
    """Whatever a branch logs must render, never raise and never vanish."""

    @pytest.fixture(autouse=True)
    def _keep_render(self, render):
        self._render = render

    def test_closing_tag_in_message_does_not_raise(self):
        """A tailed line containing [/usr/bin] renders instead of killing the render."""
        output = self._render(lambda m: m.print_event("log", "DRONE", CRASHING_MESSAGE, "info"))
        assert "/usr/bin" in output

    def test_closing_tag_keeps_its_brackets(self):
        """The path is shown as written — brackets included, nothing swallowed."""
        output = self._render(lambda m: m.print_event("log", "DRONE", CRASHING_MESSAGE, "info"))
        assert "[/usr/bin]" in output

    def test_lowercase_tag_in_message_survives(self):
        """[event_queue] is a valid-looking Rich tag; it must still reach the screen."""
        output = self._render(lambda m: m.print_event("log", "PRAX", EATEN_MESSAGE, "warning"))
        assert "[event_queue]" in output

    def test_branch_label_still_visible(self):
        """Escaping must not cost the bracketed branch column."""
        output = self._render(lambda m: m.print_event("log", "SEEDGO", "audit complete", "info"))
        assert "[SEEDGO" in output
        assert "audit complete" in output

    def test_lowercase_branch_label_survives(self):
        """A label Rich would read as a tag keeps its brackets (uppercase was luck)."""
        output = self._render(lambda m: m.print_event("log", "commons/feed", "post", "info"))
        assert "COMMONS/FEED" in output

    def test_hook_event_message_is_escaped(self):
        """print_hook_event takes the same untrusted text."""
        output = self._render(lambda m: m.print_hook_event("HOOKS", CRASHING_MESSAGE, "fired"))
        assert "[/usr/bin]" in output

    def test_hook_event_says_which_branch_fired(self):
        """The branch the hook fired in must reach the screen: it tells hook lines apart."""
        output = self._render(lambda m: m.print_hook_event("SEEDGO", "cadence:fired loader=global", "fired"))
        assert "SEEDGO" in output
        assert "cadence:fired loader=global" in output

    def test_command_separator_is_escaped(self):
        """A command string can carry brackets too."""
        output = self._render(lambda m: m.print_command_separator("DRONE", CRASHING_MESSAGE, "DEVPULSE", "PRAX"))
        assert "[/usr/bin]" in output

    def test_command_separator_keeps_attribution(self):
        """Escaping must not cost the CALLER → TARGET line."""
        output = self._render(lambda m: m.print_command_separator("DRONE", "audit", "DEVPULSE", "PRAX"))
        assert "DEVPULSE" in output
        assert "PRAX" in output

    def test_canary_unescaped_message_raises(self):
        """Proof the assertions above can fail: the line interpolated raw into the same markup explodes."""
        output = self._render(lambda m: m.print_event("log", "DRONE", CRASHING_MESSAGE, "info"))
        assert "[/usr/bin]" in output

        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
        with pytest.raises(MarkupError):
            console.print(f"[white]{CRASHING_MESSAGE}[/white]")


@pytest.fixture(autouse=True)
def _monitor_fresh(monkeypatch):
    """monitor.py, bound at the top, with its run state fresh and its logger and relay doubled."""
    monkeypatch.setattr(monitor, "logger", MagicMock())
    monkeypatch.setattr(monitor, "relay_event", MagicMock())
    monkeypatch.setattr(monitor, "_event_queue", None)
    monkeypatch.setattr(monitor, "_stop_event", threading.Event())
    monkeypatch.setattr(monitor, "_render_failures", 0)
    monkeypatch.setattr(monitor, "_last_render_warning", 0.0)


def _import_monitor():
    """The top-bound monitor; _monitor_fresh has reset its state."""
    return monitor


def _event(branch="DRONE"):
    ev = MagicMock()
    ev.event_type = "log"
    ev.branch = branch
    ev.message = CRASHING_MESSAGE
    ev.level = "info"
    return ev


def _queue_of(events, mod):
    """Queue mock that yields each event then stops the worker."""
    remaining = list(events)

    def _dequeue(timeout=0.1):
        if remaining:
            return remaining.pop(0)
        mod._stop_event.set()
        return None

    queue = MagicMock()
    queue.dequeue = _dequeue
    return queue


class TestDisplayWorkerSurvivesBadEvent:
    """A render failure costs one line, never the whole consumer."""

    def _run_worker(self, mod, events, render_side_effect):
        setattr(mod, "_event_queue", _queue_of(events, mod))
        mod._stop_event.clear()
        mod._reset_render_failure_state()
        with patch.object(mod, "_render_event", side_effect=render_side_effect) as render:
            mod._display_worker()
        return render

    def test_worker_keeps_consuming_after_render_error(self):
        """The event AFTER the poison one still reaches the renderer."""
        mod = _import_monitor()
        good = _event("SEEDGO")

        def _side_effect(event):
            if event is not good:
                raise ValueError("closing tag '[/usr/bin]' doesn't match any open tag")

        render = self._run_worker(mod, [_event(), good], _side_effect)
        assert render.call_count == 2

    def test_worker_returns_normally_when_every_event_fails(self):
        """A permanently broken renderer must not propagate: all three tried, the worker leaves by its stop flag."""
        mod = _import_monitor()

        with patch.object(mod, "logger") as log:
            render = self._run_worker(mod, [_event(), _event(), _event()], ValueError("boom"))

        assert render.call_count == 3
        assert log.debug.call_count == 3
        assert mod._stop_event.is_set() is True

    def test_render_failure_is_reported_to_the_operator(self):
        """The failure is logged in plain language, naming the subsystem and impact."""
        mod = _import_monitor()
        with patch.object(mod, "logger") as log:
            self._run_worker(mod, [_event()], ValueError("boom"))
        assert log.error.called
        text = " ".join(str(c) for c in log.error.call_args_list)
        assert "monitor" in text
        assert "ValueError" in text
        assert "on-disk logs" in text

    def test_render_failures_are_rate_limited(self):
        """A storm of bad events reports once: the report lands in a log prax itself tails."""
        mod = _import_monitor()
        with patch.object(mod, "logger") as log:
            self._run_worker(mod, [_event() for _ in range(25)], ValueError("boom"))
        assert log.error.call_count == 1

    def test_failures_keep_accumulating_between_reports(self):
        """Rate-limiting suppresses the line, not the count — the next report owes them."""
        mod = _import_monitor()
        with patch.object(mod, "logger"):
            self._run_worker(mod, [_event() for _ in range(25)], ValueError("boom"))
        # First failure reports immediately (count 1) and resets; 24 are owed.
        assert mod._render_failures == 24

    def test_skipped_count_is_carried_in_the_report(self):
        """The operator is told how many lines the broken renderer cost."""
        mod = _import_monitor()
        mod._reset_render_failure_state()
        setattr(mod, "_render_failures", 24)
        with patch.object(mod, "logger") as log:
            mod._report_render_failures(ValueError("boom"), _event())
        text = " ".join(str(c) for c in log.error.call_args_list)
        assert "24 events" in text


class TestStandaloneRunArgs:
    """`python -m ...monitor run` must mean run-all, not 'branch named run': the Telegram systemd unit launches so."""

    def test_bare_run_is_unscoped(self):
        mod = _import_monitor()
        assert mod._standalone_run_args(["run"], []) == ["run"]

    def test_run_with_branches_keeps_the_scope(self):
        mod = _import_monitor()
        assert mod._standalone_run_args(["run", "seedgo,cli"], []) == ["run", "seedgo,cli"]

    def test_branches_without_run_still_work(self):
        """The documented standalone form `monitor.py seedgo` is unchanged."""
        mod = _import_monitor()
        assert mod._standalone_run_args(["seedgo"], []) == ["run", "seedgo"]

    def test_flags_pass_through(self):
        """`run --relay` reaches _dispatch_run instead of being rejected."""
        mod = _import_monitor()
        assert mod._standalone_run_args(["run"], ["--relay"]) == ["run", "--relay"]

    def test_no_tokens_means_introspection(self):
        mod = _import_monitor()
        assert mod._standalone_run_args([], []) == []

    def test_run_token_does_not_reach_the_scope(self):
        """End to end: the parsed scope of `monitor run` is unscoped."""
        mod = _import_monitor()
        cmd_args = mod._standalone_run_args(["run"], [])
        assert parse_scope(cmd_args[1:]).is_scoped is False

    def test_canary_old_parsing_scoped_to_run(self):
        """Proof this test can fail: the old form asked for a branch called RUN."""
        legacy_scope = parse_scope(["run"])
        assert legacy_scope.is_scoped is True
        assert list(legacy_scope.names) == ["RUN"]


class TestRelaySurvivesConsoleFailure:
    """Console and Telegram are separate sinks; one must not take out the other."""

    def test_relay_runs_even_when_console_render_raises(self):
        """The owner's Telegram feed does not depend on Rich rendering a line."""
        mod = _import_monitor()
        event = _event()
        with patch.object(mod, "_print_event_to_console", side_effect=ValueError("markup")):
            with patch.object(mod, "relay_event") as relay:
                with pytest.raises(ValueError):
                    mod._render_event(event)
        relay.assert_called_once_with(event)

    def test_worker_swallows_that_failure(self):
        """End to end: bad line relayed, error reported, worker still alive."""
        mod = _import_monitor()
        setattr(mod, "_event_queue", _queue_of([_event(), _event("FLOW")], mod))
        mod._stop_event.clear()
        mod._reset_render_failure_state()
        with patch.object(mod, "_print_event_to_console", side_effect=ValueError("markup")):
            with patch.object(mod, "relay_event") as relay:
                mod._display_worker()
        assert relay.call_count == 2
