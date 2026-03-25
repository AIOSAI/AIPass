# =================== AIPass ====================
# Name: test_core.py
# Description: Unit tests for trigger event bus core module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Unit tests for aipass.trigger.apps.modules.core — Trigger event bus."""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure so the module loads in isolation."""
    import sys

    mock_logger = MagicMock()
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger

    # Prax logger (imported at module level as `logger`)
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # json_handler used by handle_command
    json_mod = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json",
        MagicMock(json_handler=json_mod),
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json.json_handler",
        json_mod,
    )

    # Registry setup_handlers (called by _ensure_initialized)
    registry_mod = MagicMock()
    registry_mod.setup_handlers = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.events",
        MagicMock(registry=registry_mod),
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.events.registry",
        registry_mod,
    )

    # Force re-import so the module picks up mocks
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.modules.core", raising=False)


@pytest.fixture()
def trigger_cls():
    """Import and return a clean Trigger class after mocking.

    Resets all class-level state so tests are fully isolated.
    """
    from aipass.trigger.apps.modules.core import Trigger

    # Reset mutable class state between tests
    Trigger._handlers = {}
    Trigger._history = []
    Trigger._initialized = False
    Trigger._firing = False
    Trigger._deferred_queue = []
    Trigger._draining_deferred = False
    Trigger._log_watcher_started = False
    return Trigger


# ---------------------------------------------------------------------------
# Tests -- on() registration
# ---------------------------------------------------------------------------

def test_on_registers_handler(trigger_cls):
    """on() stores the handler in _handlers under the given event key."""
    handler = MagicMock()
    trigger_cls.on("deploy", handler)

    assert "deploy" in trigger_cls._handlers
    assert handler in trigger_cls._handlers["deploy"]


def test_on_multiple_events(trigger_cls):
    """on() can register handlers for different event names independently."""
    h1 = MagicMock()
    h2 = MagicMock()
    trigger_cls.on("build", h1)
    trigger_cls.on("test", h2)

    assert len(trigger_cls._handlers) == 2
    assert h1 in trigger_cls._handlers["build"]
    assert h2 in trigger_cls._handlers["test"]


# ---------------------------------------------------------------------------
# Tests -- fire()
# ---------------------------------------------------------------------------

def test_fire_calls_registered_handler(trigger_cls):
    """fire() invokes every handler registered for that event."""
    handler = MagicMock()
    trigger_cls.on("deploy", handler)

    trigger_cls.fire("deploy")

    handler.assert_called_once()


def test_fire_no_handlers_does_not_error(trigger_cls):
    """fire() on an event with zero handlers completes without raising."""
    result = trigger_cls.fire("nonexistent_event")
    assert result is None


def test_fire_passes_data_kwargs(trigger_cls):
    """fire() forwards **data to each handler, plus the fire_event callback."""
    received = {}

    def capture_handler(**kwargs):
        received.update(kwargs)

    trigger_cls.on("deploy", capture_handler)
    trigger_cls.fire("deploy", branch="main", status="success")

    assert received["branch"] == "main"
    assert received["status"] == "success"
    assert callable(received["fire_event"])


def test_fire_injects_fire_event_callback(trigger_cls):
    """fire() always injects a fire_event key that is Trigger.fire."""
    received_kwargs = {}

    def spy(**kwargs):
        received_kwargs.update(kwargs)

    trigger_cls.on("ping", spy)
    trigger_cls.fire("ping")

    assert "fire_event" in received_kwargs
    assert callable(received_kwargs["fire_event"])
    # Verify the callback resolves to Trigger.fire by checking its __name__
    # (bound classmethod creates a new wrapper each access, so identity
    # comparison does not work; qualname is stable)
    callback = received_kwargs["fire_event"]
    assert getattr(callback, "__qualname__", "") == "Trigger.fire"


def test_fire_multiple_handlers_same_event(trigger_cls):
    """fire() calls every handler registered for the same event."""
    h1 = MagicMock()
    h2 = MagicMock()
    h3 = MagicMock()

    trigger_cls.on("build", h1)
    trigger_cls.on("build", h2)
    trigger_cls.on("build", h3)

    trigger_cls.fire("build")

    h1.assert_called_once()
    h2.assert_called_once()
    h3.assert_called_once()


def test_fire_handler_exception_does_not_block_others(trigger_cls):
    """If one handler raises, remaining handlers still execute."""
    call_order = []

    def exploding_handler(**kwargs):
        call_order.append("h1")
        raise ValueError("boom")

    def safe_handler(**kwargs):
        call_order.append("h2")

    trigger_cls.on("fail_event", exploding_handler)
    trigger_cls.on("fail_event", safe_handler)

    trigger_cls.fire("fail_event")

    assert call_order == ["h1", "h2"], "Both handlers must be called despite h1 raising"


# ---------------------------------------------------------------------------
# Tests -- off() unregistration
# ---------------------------------------------------------------------------

def test_off_removes_handler(trigger_cls):
    """off() removes a previously registered handler so it no longer fires."""
    handler = MagicMock()
    trigger_cls.on("deploy", handler)
    trigger_cls.off("deploy", handler)

    trigger_cls.fire("deploy")

    handler.assert_not_called()


def test_off_unregistered_handler_no_error(trigger_cls):
    """off() for a handler that was never registered does not raise."""
    handler = MagicMock()
    handlers_before = dict(trigger_cls._handlers)
    result = trigger_cls.off("nonexistent_event", handler)
    assert result is None
    assert trigger_cls._handlers == handlers_before


def test_off_unregistered_handler_on_existing_event(trigger_cls):
    """off() for a handler not in an existing event list does not raise."""
    h1 = MagicMock()
    h2 = MagicMock()
    trigger_cls.on("deploy", h1)

    # h2 was never registered for "deploy"
    trigger_cls.off("deploy", h2)

    # h1 should still be there
    assert h1 in trigger_cls._handlers["deploy"]


def test_off_only_removes_target_handler(trigger_cls):
    """off() removes only the specified handler, leaving others intact."""
    h1 = MagicMock()
    h2 = MagicMock()
    trigger_cls.on("build", h1)
    trigger_cls.on("build", h2)

    trigger_cls.off("build", h1)

    trigger_cls.fire("build")
    h1.assert_not_called()
    h2.assert_called_once()


# ---------------------------------------------------------------------------
# Tests -- status()
# ---------------------------------------------------------------------------

def test_status_empty(trigger_cls):
    """status() returns empty dict when no handlers are registered."""
    result = trigger_cls.status()
    assert result == {}


def test_status_counts_handlers(trigger_cls):
    """status() returns a dict mapping event names to handler counts."""
    trigger_cls.on("deploy", MagicMock())
    trigger_cls.on("deploy", MagicMock())
    trigger_cls.on("test", MagicMock())

    result = trigger_cls.status()

    assert result["deploy"] == 2
    assert result["test"] == 1
    assert len(result) == 2


def test_status_returns_dict(trigger_cls):
    """status() return type is a plain dict."""
    trigger_cls.on("x", MagicMock())
    result = trigger_cls.status()
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Tests -- edge cases
# ---------------------------------------------------------------------------

def test_duplicate_handler_registration(trigger_cls):
    """on() with the same handler twice registers it twice (both fire)."""
    call_count = 0

    def counting_handler(**kwargs):
        nonlocal call_count
        call_count += 1

    trigger_cls.on("dup", counting_handler)
    trigger_cls.on("dup", counting_handler)

    trigger_cls.fire("dup")

    assert call_count == 2


def test_off_duplicate_removes_one(trigger_cls):
    """off() removes only one instance of a duplicate-registered handler."""
    call_count = 0

    def counting_handler(**kwargs):
        nonlocal call_count
        call_count += 1

    trigger_cls.on("dup", counting_handler)
    trigger_cls.on("dup", counting_handler)
    trigger_cls.off("dup", counting_handler)

    trigger_cls.fire("dup")

    # One copy was removed, one remains
    assert call_count == 1


def test_deferred_queue_for_nested_fire(trigger_cls):
    """Events fired inside a handler are deferred and processed after."""
    order = []

    def handler_a(**kwargs):
        order.append("a_start")
        # This fire happens while _firing is True, so it gets deferred
        trigger_cls.fire("event_b")
        order.append("a_end")

    def handler_b(**kwargs):
        order.append("b")

    trigger_cls.on("event_a", handler_a)
    trigger_cls.on("event_b", handler_b)

    trigger_cls.fire("event_a")

    # handler_a runs fully first, then deferred event_b fires handler_b
    assert order == ["a_start", "a_end", "b"]


def test_firing_flag_resets_after_exception(trigger_cls):
    """_firing flag resets even if a handler raises, so bus stays usable."""
    trigger_cls.on("bad", MagicMock(side_effect=RuntimeError("fail")))

    trigger_cls.fire("bad")

    assert trigger_cls._firing is False


def test_fire_event_callback_is_functional(trigger_cls):
    """The fire_event callback injected into data actually fires events."""
    result = []

    def first_handler(fire_event, **kwargs):
        fire_event("second_event", origin="first")

    def second_handler(**kwargs):
        result.append(kwargs.get("origin"))

    trigger_cls.on("first_event", first_handler)
    trigger_cls.on("second_event", second_handler)

    trigger_cls.fire("first_event")

    assert result == ["first"]


def test_fire_only_triggers_matching_event(trigger_cls):
    """fire() does not invoke handlers registered under different events."""
    h_deploy = MagicMock()
    h_test = MagicMock()
    trigger_cls.on("deploy", h_deploy)
    trigger_cls.on("test", h_test)

    trigger_cls.fire("deploy")

    h_deploy.assert_called_once()
    h_test.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- contract gaps
# ---------------------------------------------------------------------------

def test_fire_none_event_name(trigger_cls):
    """fire(None) handles None event gracefully -- no handlers match, returns None."""
    from typing import Any
    none_event: Any = None
    result = trigger_cls.fire(none_event)
    assert result is None


def test_fire_empty_string_event(trigger_cls):
    """fire('') with empty string event fires without error (no handlers match)."""
    handler = MagicMock()
    trigger_cls.on("", handler)

    result = trigger_cls.fire("")

    handler.assert_called_once()
    assert result is None


def test_on_none_handler(trigger_cls):
    """on('event', None) registers None as a handler; fire raises on call."""
    trigger_cls.on("event", None)

    assert None in trigger_cls._handlers["event"]
    # Firing should not propagate the error (Trigger catches handler exceptions)
    trigger_cls.fire("event")


def test_fire_return_type_is_none(trigger_cls):
    """fire() always returns None."""
    handler = MagicMock()
    trigger_cls.on("deploy", handler)

    result = trigger_cls.fire("deploy")
    assert result is None


def test_on_return_type_is_none(trigger_cls):
    """on() returns None."""
    result = trigger_cls.on("deploy", MagicMock())
    assert result is None


def test_off_return_type_is_none(trigger_cls):
    """off() returns None."""
    handler = MagicMock()
    trigger_cls.on("deploy", handler)
    result = trigger_cls.off("deploy", handler)
    assert result is None


def test_fire_event_kwarg_always_overwritten(trigger_cls):
    """fire_event kwarg passed by caller is always overwritten with Trigger.fire."""
    received_kwargs = {}

    def spy(**kwargs):
        received_kwargs.update(kwargs)

    trigger_cls.on("event", spy)

    # Caller tries to inject a custom fire_event
    trigger_cls.fire("event", fire_event="custom_value")

    callback = received_kwargs["fire_event"]
    assert callback != "custom_value"
    assert callable(callback)
    assert getattr(callback, "__qualname__", "") == "Trigger.fire"
