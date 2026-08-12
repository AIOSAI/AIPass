#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_display_resilience.py
# Description: The display consumer must survive an unrenderable event
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Regression cover for the 2026-08-11 Mission Control consumer death.

A tailed log line containing ``[/usr/bin]`` reached ``print_event``, which
interpolated it raw into a Rich markup string. Rich read it as a closing tag,
raised ``MarkupError``, and the exception escaped ``_display_worker`` — killing
the only consumer of the display queue for the life of the process. The queue
then sat permanently full, ``event_queue`` warned every 30s for ~20 hours, and
the Telegram relay (fed from the same code path) went silent.

Two independent defects, covered separately here:

1. Event text is UNTRUSTED markup. Log lines carry ``[/usr/bin]`` (raises) and
   ``[event_queue]`` (silently eaten). Every dynamic value must be escaped.
2. One unrenderable event must not kill the consumer. Even with (1) fixed, the
   loop has to survive whatever the next producer sends.

Rendering goes through a REAL Rich console — the shared conftest installs a
MagicMock console that records the call but never renders, so it cannot fail
on either defect.
"""

import importlib
import io
import sys
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console


# ---------------------------------------------------------------------------
# Real-console rendering helper
# ---------------------------------------------------------------------------


def _render(call):
    """Run ``call(unified_stream)`` against a real Rich console, return output."""
    module = importlib.import_module("aipass.prax.apps.handlers.monitoring.unified_stream")
    buffer = io.StringIO()
    real_console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
    original = getattr(module, "console")
    setattr(module, "console", real_console)
    try:
        call(module)
    finally:
        setattr(module, "console", original)
    return buffer.getvalue()


# The exact line that killed the live monitor (service log, 2026-08-11 11:29:04).
CRASHING_MESSAGE = "PATH resolved to [/usr/bin] for the spawned shell"

# The prax operator warning whose own subsystem tag Rich was eating on screen.
EATEN_MESSAGE = "[event_queue] The live monitor display queue is full"


# ---------------------------------------------------------------------------
# Defect 1 — event text is untrusted markup
# ---------------------------------------------------------------------------


class TestEventTextIsUntrustedMarkup:
    """Whatever a branch logs must render, never raise and never vanish."""

    def test_closing_tag_in_message_does_not_raise(self):
        """A tailed line containing [/usr/bin] renders instead of killing the render."""
        output = _render(lambda m: m.print_event("log", "DRONE", CRASHING_MESSAGE, "info"))
        assert "/usr/bin" in output

    def test_closing_tag_keeps_its_brackets(self):
        """The path is shown as written — brackets included, nothing swallowed."""
        output = _render(lambda m: m.print_event("log", "DRONE", CRASHING_MESSAGE, "info"))
        assert "[/usr/bin]" in output

    def test_lowercase_tag_in_message_survives(self):
        """[event_queue] is a valid-looking Rich tag; it must still reach the screen."""
        output = _render(lambda m: m.print_event("log", "PRAX", EATEN_MESSAGE, "warning"))
        assert "[event_queue]" in output

    def test_branch_label_still_visible(self):
        """Escaping must not cost the bracketed branch column."""
        output = _render(lambda m: m.print_event("log", "SEEDGO", "audit complete", "info"))
        assert "[SEEDGO" in output
        assert "audit complete" in output

    def test_lowercase_branch_label_survives(self):
        """A label Rich would read as a tag keeps its brackets (uppercase was luck)."""
        output = _render(lambda m: m.print_event("log", "commons/feed", "post", "info"))
        assert "COMMONS/FEED" in output

    def test_hook_event_message_is_escaped(self):
        """print_hook_event takes the same untrusted text."""
        output = _render(lambda m: m.print_hook_event("HOOKS", CRASHING_MESSAGE, "fired"))
        assert "[/usr/bin]" in output

    def test_command_separator_is_escaped(self):
        """A command string can carry brackets too."""
        output = _render(lambda m: m.print_command_separator("DRONE", CRASHING_MESSAGE, "DEVPULSE", "PRAX"))
        assert "[/usr/bin]" in output

    def test_command_separator_keeps_attribution(self):
        """Escaping must not cost the CALLER → TARGET line."""
        output = _render(lambda m: m.print_command_separator("DRONE", "audit", "DEVPULSE", "PRAX"))
        assert "DEVPULSE" in output
        assert "PRAX" in output

    def test_canary_unescaped_message_raises(self):
        """Proof the assertions above can fail: raw interpolation still explodes."""
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
        with pytest.raises(Exception):
            console.print(f"[white]{CRASHING_MESSAGE}[/white]")

    def test_canary_unescaped_lowercase_tag_is_eaten(self):
        """Proof the [event_queue] assertion can fail: raw interpolation swallows it."""
        buffer = io.StringIO()
        console = Console(file=buffer, width=200, no_color=True, highlight=False, markup=True)
        console.print(f"[white]{EATEN_MESSAGE}[/white]")
        assert "[event_queue]" not in buffer.getvalue()


# ---------------------------------------------------------------------------
# Defect 2 — one bad event must not kill the consumer
# ---------------------------------------------------------------------------

_MONITORING_MOCKS = (
    "aipass.prax.apps.handlers.monitoring",
    "aipass.prax.apps.handlers.monitoring.event_queue",
    "aipass.prax.apps.handlers.monitoring.filesystem_handler",
    "aipass.prax.apps.handlers.monitoring.log_watcher",
    "aipass.prax.apps.handlers.monitoring.unified_stream",
    "aipass.prax.apps.handlers.monitoring.module_tracker",
    "aipass.prax.apps.handlers.monitoring.branch_detector",
    "aipass.prax.apps.handlers.monitoring.interactive_filter",
    "aipass.prax.apps.handlers.monitoring.monitoring_filters",
    "aipass.prax.apps.handlers.monitoring.file_watcher_integration",
    "aipass.prax.apps.handlers.monitoring.telegram_relay",
    "aipass.prax.apps.handlers.monitoring.pid_cache",
    "aipass.prax.apps.handlers.monitoring.instance_lock",
)


def _import_monitor():
    """Import (or reload) monitor.py with all monitoring handlers mocked."""
    fresh = {name: MagicMock() for name in _MONITORING_MOCKS}
    with patch.dict(sys.modules, fresh):
        if "aipass.prax.apps.modules.monitor" in sys.modules:
            return importlib.reload(sys.modules["aipass.prax.apps.modules.monitor"])
        return importlib.import_module("aipass.prax.apps.modules.monitor")


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
        """A permanently broken renderer must not propagate out of the thread."""
        mod = _import_monitor()
        self._run_worker(mod, [_event(), _event(), _event()], ValueError("boom"))

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
        """A storm of bad events reports once, not once per event.

        The report lands in a log prax itself tails, so per-event logging would
        turn a broken renderer into a self-feeding firehose (same reasoning as
        the queue-full warning).
        """
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
    """`python -m ...monitor run` must mean run-all, not 'branch named run'.

    The systemd unit that carries Patrick's Telegram feed launches exactly that
    way. Before launch-time scoping the stray 'run' was parsed and discarded;
    once the scope became real it selected a branch nobody has, so a restart
    would have brought the service up watching — and relaying — nothing.
    """

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
        from aipass.prax.apps.handlers.monitoring.branch_scope import parse_scope

        mod = _import_monitor()
        cmd_args = mod._standalone_run_args(["run"], [])
        assert parse_scope(cmd_args[1:]).is_scoped is False

    def test_canary_old_parsing_scoped_to_run(self):
        """Proof this test can fail: the old form asked for a branch called RUN."""
        from aipass.prax.apps.handlers.monitoring.branch_scope import parse_scope

        legacy_scope = parse_scope(["run"])
        assert legacy_scope.is_scoped is True
        assert list(legacy_scope.names) == ["RUN"]


class TestRelaySurvivesConsoleFailure:
    """Console and Telegram are separate sinks; one must not take out the other."""

    def test_relay_runs_even_when_console_render_raises(self):
        """Patrick's Telegram feed does not depend on Rich rendering a line."""
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
