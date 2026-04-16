# =================== AIPass ====================
# Name: test_watchdog_schedule.py
# Description: Tests for the watchdog schedule handler + router integration
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for watchdog schedule handler (Phase 3, FPLAN-0186)."""

import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import schedule as schedule_handler
from aipass.devpulse.apps.modules import watchdog as wd_mod


# ─────────────────────────────────────────────────────────────────────────────
# parse_schedule — wall-clock
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fixed_now():
    # 2026-04-14 10:00:00 — any 02:00 target is "past", any 14:30 is "future".
    return datetime(2026, 4, 14, 10, 0, 0)


def test_parse_schedule_future_same_day(fixed_now):
    target = schedule_handler.parse_schedule("14:30", now=fixed_now)
    assert target == datetime(2026, 4, 14, 14, 30, 0)


def test_parse_schedule_past_rolls_to_tomorrow(fixed_now):
    target = schedule_handler.parse_schedule("02:00", now=fixed_now)
    assert target == datetime(2026, 4, 15, 2, 0, 0)


def test_parse_schedule_with_seconds(fixed_now):
    target = schedule_handler.parse_schedule("14:30:15", now=fixed_now)
    assert target == datetime(2026, 4, 14, 14, 30, 15)


def test_parse_schedule_midnight_rolls_tomorrow(fixed_now):
    # 00:00 is strictly before 10:00 today -> tomorrow.
    target = schedule_handler.parse_schedule("00:00", now=fixed_now)
    assert target == datetime(2026, 4, 15, 0, 0, 0)


def test_parse_schedule_end_of_day_same_day(fixed_now):
    target = schedule_handler.parse_schedule("23:59", now=fixed_now)
    assert target == datetime(2026, 4, 14, 23, 59, 0)


def test_parse_schedule_equal_to_now_rolls_tomorrow(fixed_now):
    # Target equal to now is "past" by policy — rolls forward so a caller
    # who says "wake at 10:00" at 10:00 sharp gets tomorrow, not "now".
    target = schedule_handler.parse_schedule("10:00", now=fixed_now)
    assert target == datetime(2026, 4, 15, 10, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# parse_schedule — relative
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,delta_seconds",
    [
        ("+30m", 1800),
        ("+1h", 3600),
        ("+45s", 45),
        ("+1h30m", 5400),
        ("+2h", 7200),
    ],
)
def test_parse_schedule_relative(fixed_now, text, delta_seconds):
    target = schedule_handler.parse_schedule(text, now=fixed_now)
    assert target == fixed_now + timedelta(seconds=delta_seconds)


# ─────────────────────────────────────────────────────────────────────────────
# parse_schedule — invalid
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "25:00",
        "12:60",
        "-5m",
        "+xyz",
        "+",
        "14:30:99",
    ],
)
def test_parse_schedule_invalid(text):
    with pytest.raises(ValueError):
        schedule_handler.parse_schedule(text, now=datetime(2026, 4, 14, 10, 0, 0))


def test_parse_schedule_none_raises():
    with pytest.raises(ValueError):
        schedule_handler.parse_schedule(None)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# format_wait
# ─────────────────────────────────────────────────────────────────────────────


def test_format_wait_hours_and_minutes():
    now = datetime(2026, 4, 14, 10, 0, 0)
    target = now + timedelta(hours=2, minutes=15)
    assert schedule_handler.format_wait(target, now) == "in 2h 15m"


def test_format_wait_minutes_only():
    now = datetime(2026, 4, 14, 10, 0, 0)
    target = now + timedelta(minutes=5)
    assert schedule_handler.format_wait(target, now) == "in 5m"


def test_format_wait_seconds():
    now = datetime(2026, 4, 14, 10, 0, 0)
    target = now + timedelta(seconds=45)
    assert schedule_handler.format_wait(target, now) == "in 45s"


def test_format_wait_overdue():
    now = datetime(2026, 4, 14, 10, 0, 0)
    target = now - timedelta(minutes=3)
    assert schedule_handler.format_wait(target, now) == "overdue by 3m"


def test_format_wait_zero():
    now = datetime(2026, 4, 14, 10, 0, 0)
    assert schedule_handler.format_wait(now, now) == "in 0s"


# ─────────────────────────────────────────────────────────────────────────────
# wake_at — injected clock
# ─────────────────────────────────────────────────────────────────────────────


class _FakeClock:
    """Clock that advances by a fixed delta on every call."""

    def __init__(self, start: datetime, step_seconds: float = 2.0):
        self.current = start
        self.step = timedelta(seconds=step_seconds)

    def __call__(self) -> datetime:
        value = self.current
        self.current = self.current + self.step
        return value


def test_wake_at_relative_with_injected_clock():
    start = datetime(2026, 4, 14, 10, 0, 0)
    clock = _FakeClock(start, step_seconds=10.0)

    with patch.object(schedule_handler.time, "sleep", return_value=None):
        result = schedule_handler.wake_at("+30s", now_fn=clock)

    assert result["woke"] is True
    assert result["state"] == "woke"
    assert result["reason"] == "schedule fired"
    assert result["command"] is None
    assert result["command_exit_code"] is None
    assert result["command_stdout"] is None
    assert result["command_stderr"] is None
    assert result["scheduled_for"] == (start + timedelta(seconds=30)).isoformat()
    assert result["elapsed"] >= 30


def test_wake_at_wall_clock_with_injected_clock():
    start = datetime(2026, 4, 14, 10, 0, 0)
    clock = _FakeClock(start, step_seconds=60.0)

    with patch.object(schedule_handler.time, "sleep", return_value=None):
        result = schedule_handler.wake_at("10:05", now_fn=clock)

    assert result["scheduled_for"] == datetime(2026, 4, 14, 10, 5, 0).isoformat()
    assert result["elapsed"] >= 300


def test_wake_at_real_short_relative():
    """Use a real 1s sleep to verify wake_at actually returns without mocking."""
    result = schedule_handler.wake_at("+1s")
    assert result["woke"] is True
    assert result["elapsed"] >= 1
    assert result["command"] is None


# ─────────────────────────────────────────────────────────────────────────────
# wake_at — command execution
# ─────────────────────────────────────────────────────────────────────────────


def test_wake_at_runs_echo_command():
    start = datetime(2026, 4, 14, 10, 0, 0)
    clock = _FakeClock(start, step_seconds=5.0)

    with patch.object(schedule_handler.time, "sleep", return_value=None):
        result = schedule_handler.wake_at("+1s", command="echo hello", now_fn=clock)

    assert result["command"] == "echo hello"
    assert result["command_exit_code"] == 0
    assert "hello" in (result["command_stdout"] or "")


def test_wake_at_failing_command_no_exception():
    start = datetime(2026, 4, 14, 10, 0, 0)
    clock = _FakeClock(start, step_seconds=5.0)

    with patch.object(schedule_handler.time, "sleep", return_value=None):
        result = schedule_handler.wake_at("+1s", command="false", now_fn=clock)

    assert result["command"] == "false"
    assert result["command_exit_code"] != 0


def test_wake_at_nonexistent_command():
    start = datetime(2026, 4, 14, 10, 0, 0)
    clock = _FakeClock(start, step_seconds=5.0)

    with patch.object(schedule_handler.time, "sleep", return_value=None):
        result = schedule_handler.wake_at(
            "+1s",
            command="this-command-does-not-exist-xyz-123",
            now_fn=clock,
        )

    # shell=True routes through /bin/sh which reports 127 for not-found.
    assert result["command_exit_code"] != 0
    assert result["command"] == "this-command-does-not-exist-xyz-123"


# ─────────────────────────────────────────────────────────────────────────────
# Chunked sleep
# ─────────────────────────────────────────────────────────────────────────────


def test_wake_at_sleeps_in_chunks():
    """Long waits should call time.sleep repeatedly, never once with a big value."""
    start = datetime(2026, 4, 14, 10, 0, 0)
    # Real-time clock — no advancement per call — so wake_at relies on sleep.
    # We fake sleep to advance our synthetic clock instead.
    state = {"now": start}

    def fake_clock():
        return state["now"]

    def fake_sleep(seconds):
        state["now"] = state["now"] + timedelta(seconds=seconds)

    with patch.object(schedule_handler.time, "sleep", side_effect=fake_sleep) as sleep_mock:
        schedule_handler.wake_at("+30s", now_fn=fake_clock)

    # Each chunk is capped at _SLEEP_CHUNK_SECONDS (5.0) so 30s -> >= 6 calls.
    max_chunk = schedule_handler._SLEEP_CHUNK_SECONDS
    assert sleep_mock.call_count >= 6
    for call in sleep_mock.call_args_list:
        (value,) = call.args
        assert value <= max_chunk + 0.0001


# ─────────────────────────────────────────────────────────────────────────────
# Router integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _bypass_caller_guard():
    with patch.object(wd_mod, "_guard_caller", return_value=True):
        yield


def _fake_schedule_module(**overrides):
    """Build a fake schedule module with the public surface the router calls."""
    fake = type(sys)("fake_schedule_mod")
    fake.calls = []

    def wake_at(time_str, command=None, now_fn=None):
        fake.calls.append(("wake_at", time_str, command))
        return overrides.get(
            "wake_at",
            {
                "woke": True,
                "reason": "schedule fired",
                "elapsed": 0,
                "scheduled_for": "2026-04-14T10:00:00",
                "state": "woke",
                "command": command,
                "command_exit_code": 0 if command else None,
                "command_stdout": "hi\n" if command else None,
                "command_stderr": "" if command else None,
            },
        )

    fake.wake_at = wake_at
    return fake


def test_router_schedule_wall_clock(_bypass_caller_guard):
    fake = _fake_schedule_module()
    with patch("importlib.import_module", return_value=fake):
        result = wd_mod.handle_command("watchdog", ["schedule", "02:00"])
    assert result is True
    assert ("wake_at", "02:00", None) in fake.calls


def test_router_schedule_relative(_bypass_caller_guard):
    fake = _fake_schedule_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["schedule", "+30m"])
    assert ("wake_at", "+30m", None) in fake.calls


def test_router_schedule_with_command(_bypass_caller_guard):
    fake = _fake_schedule_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["schedule", "02:00", "drone @git status"])
    assert ("wake_at", "02:00", "drone @git status") in fake.calls


def test_router_schedule_help(_bypass_caller_guard, capsys):
    result = wd_mod.handle_command("watchdog", ["schedule", "--help"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "schedule" in combined.lower()


def test_router_schedule_empty_shows_help(_bypass_caller_guard, capsys):
    # Without a positional time, the subhandler prints help rather than erroring.
    result = wd_mod.handle_command("watchdog", ["schedule"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "schedule" in combined.lower()


def test_router_schedule_invalid_time(_bypass_caller_guard, capsys):
    """ValueError from wake_at surfaces as a clean router error."""
    fake = type(sys)("fake_schedule_mod")

    def wake_at(time_str, command=None, now_fn=None):
        raise ValueError(f"bad schedule: {time_str}")

    fake.wake_at = wake_at

    with patch("importlib.import_module", return_value=fake):
        result = wd_mod.handle_command("watchdog", ["schedule", "notatime"])

    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "invalid" in combined.lower()
