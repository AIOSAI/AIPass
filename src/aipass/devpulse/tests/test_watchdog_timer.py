# =================== AIPass ====================
# Name: test_watchdog_timer.py
# Description: Tests for the watchdog timer handler + router integration
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for watchdog timer handler (Phase 2, FPLAN-0186)."""

import json
import sys
import time
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import timer as timer_handler
from aipass.devpulse.apps.modules import watchdog as wd_mod


# ─────────────────────────────────────────────────────────────────────────────
# parse_duration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30s", 30),
        ("5m", 300),
        ("2h", 7200),
        ("1h30m", 5400),
        ("45", 45),
        ("0s", 0),
        ("120", 120),
        ("1h1m1s", 3661),
    ],
)
def test_parse_duration_valid(text, expected):
    assert timer_handler.parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "abc",
        "",
        "   ",
        "-5m",
        "5x",
        "5m5",
        "hm",
    ],
)
def test_parse_duration_invalid(text):
    with pytest.raises(ValueError):
        timer_handler.parse_duration(text)


def test_parse_duration_none_raises():
    with pytest.raises(ValueError):
        timer_handler.parse_duration(None)  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# format_human
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (1, "1s"),
        (59, "59s"),
        (60, "1m 00s"),
        (125, "2m 05s"),
        (3600, "1h 0m 00s"),
        (5400, "1h 30m 00s"),
        (3725, "1h 2m 05s"),
        (0, "0s"),
    ],
)
def test_format_human(seconds, expected):
    assert timer_handler.format_human(seconds) == expected


def test_format_human_rejects_negative():
    with pytest.raises(ValueError):
        timer_handler.format_human(-1)


# ─────────────────────────────────────────────────────────────────────────────
# wake_in
# ─────────────────────────────────────────────────────────────────────────────


def test_wake_in_short_duration():
    """Very short wake-in returns the expected shape and elapsed is in the ballpark."""
    started = time.monotonic()
    result = timer_handler.wake_in("1s")
    elapsed_real = time.monotonic() - started

    assert result["woke"] is True
    assert result["state"] == "woke"
    assert result["reason"] == "timer fired"
    assert result["duration"] == "1s"
    assert 1 <= result["elapsed"] <= 3
    assert elapsed_real < 3


# ─────────────────────────────────────────────────────────────────────────────
# timer_start / timer_stop
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "watchdog_timers.json"


def test_timer_start_then_stop(store_path):
    start = timer_handler.timer_start("phase-a", storage_path=store_path)
    assert start["state"] == "started"
    assert start["name"] == "phase-a"
    assert "started_at" in start

    time.sleep(1.1)

    stop = timer_handler.timer_stop("phase-a", storage_path=store_path)
    assert stop["state"] == "stopped"
    assert stop["name"] == "phase-a"
    assert stop["elapsed_seconds"] >= 1
    assert stop["human"].endswith("s")
    assert "stopped_at" in stop

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert "phase-a" not in raw["active"]
    assert len(raw["history"]) == 1
    assert raw["history"][0]["name"] == "phase-a"


def test_timer_start_duplicate_returns_error(store_path):
    timer_handler.timer_start("dup", storage_path=store_path)
    second = timer_handler.timer_start("dup", storage_path=store_path)
    assert second["state"] == "error"
    assert "already running" in second["reason"]


def test_timer_stop_without_start_returns_error(store_path):
    result = timer_handler.timer_stop("ghost", storage_path=store_path)
    assert result["state"] == "error"
    assert "not running" in result["reason"]


def test_timer_start_empty_name(store_path):
    result = timer_handler.timer_start("   ", storage_path=store_path)
    assert result["state"] == "error"


# ─────────────────────────────────────────────────────────────────────────────
# timer_list
# ─────────────────────────────────────────────────────────────────────────────


def test_timer_list_mixes_active_and_history(store_path):
    timer_handler.timer_start("alpha", storage_path=store_path)
    timer_handler.timer_start("beta", storage_path=store_path)
    time.sleep(1.1)
    timer_handler.timer_stop("beta", storage_path=store_path)

    snapshot = timer_handler.timer_list(storage_path=store_path)
    active_names = [a["name"] for a in snapshot["active"]]
    history_names = [h["name"] for h in snapshot["history"]]

    assert "alpha" in active_names
    assert "beta" not in active_names
    assert "beta" in history_names

    alpha_entry = next(a for a in snapshot["active"] if a["name"] == "alpha")
    assert alpha_entry["elapsed_so_far_seconds"] >= 0
    assert "human" in alpha_entry


def test_timer_list_empty_store(store_path):
    snapshot = timer_handler.timer_list(storage_path=store_path)
    assert snapshot == {"active": [], "history": []}


# ─────────────────────────────────────────────────────────────────────────────
# timer_report
# ─────────────────────────────────────────────────────────────────────────────


def test_timer_report_contains_sections(store_path):
    timer_handler.timer_start("reporting", storage_path=store_path)
    time.sleep(1.1)
    timer_handler.timer_stop("reporting", storage_path=store_path)
    timer_handler.timer_start("still-active", storage_path=store_path)

    report = timer_handler.timer_report(storage_path=store_path)
    assert "Watchdog Timer Report" in report
    assert "Active:" in report
    assert "History" in report
    assert "reporting" in report
    assert "still-active" in report
    assert "Total tracked" in report


# ─────────────────────────────────────────────────────────────────────────────
# Persistence + atomic writes
# ─────────────────────────────────────────────────────────────────────────────


def test_persistence_across_reloads(store_path):
    timer_handler.timer_start("persistent", storage_path=store_path)

    raw_after_start = json.loads(store_path.read_text(encoding="utf-8"))
    assert "persistent" in raw_after_start["active"]

    time.sleep(1.1)
    stop_result = timer_handler.timer_stop("persistent", storage_path=store_path)
    assert stop_result["state"] == "stopped"

    raw_after_stop = json.loads(store_path.read_text(encoding="utf-8"))
    assert "persistent" not in raw_after_stop["active"]
    assert any(h["name"] == "persistent" for h in raw_after_stop["history"])


def test_atomic_write_cleans_up_tmp(store_path):
    timer_handler.timer_start("atomic", storage_path=store_path)
    tmp_sibling = store_path.with_suffix(store_path.suffix + ".tmp")
    assert not tmp_sibling.exists()
    timer_handler.timer_stop("atomic", storage_path=store_path)
    assert not tmp_sibling.exists()


def test_concurrent_timers_independent(store_path):
    timer_handler.timer_start("t1", storage_path=store_path)
    timer_handler.timer_start("t2", storage_path=store_path)
    timer_handler.timer_stop("t1", storage_path=store_path)

    snapshot = timer_handler.timer_list(storage_path=store_path)
    active_names = [a["name"] for a in snapshot["active"]]
    assert active_names == ["t2"]
    assert [h["name"] for h in snapshot["history"]] == ["t1"]


# ─────────────────────────────────────────────────────────────────────────────
# Router integration
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _bypass_caller_guard():
    """Force _guard_caller pass so router tests don't depend on cwd."""
    with patch.object(wd_mod, "_guard_caller", return_value=True):
        yield


def _fake_timer_module(**overrides):
    """Build a fake handler module with the public surface the router calls."""
    fake = type(sys)("fake_timer_mod")
    fake.calls = []

    def wake_in(duration):
        fake.calls.append(("wake_in", duration))
        return overrides.get(
            "wake_in",
            {
                "woke": True,
                "reason": "timer fired",
                "elapsed": 1,
                "duration": duration,
                "state": "woke",
            },
        )

    def timer_start(name, storage_path=None):
        fake.calls.append(("timer_start", name))
        return overrides.get(
            "timer_start",
            {
                "name": name,
                "started_at": "now",
                "state": "started",
            },
        )

    def timer_stop(name, storage_path=None):
        fake.calls.append(("timer_stop", name))
        return overrides.get(
            "timer_stop",
            {
                "name": name,
                "elapsed_seconds": 12,
                "human": "12s",
                "state": "stopped",
            },
        )

    def timer_list(storage_path=None):
        fake.calls.append(("timer_list",))
        return overrides.get("timer_list", {"active": [], "history": []})

    def timer_report(storage_path=None):
        fake.calls.append(("timer_report",))
        return overrides.get("timer_report", "report body")

    fake.wake_in = wake_in
    fake.timer_start = timer_start
    fake.timer_stop = timer_stop
    fake.timer_list = timer_list
    fake.timer_report = timer_report
    return fake


def test_router_timer_wake_in(_bypass_caller_guard, capsys):
    fake = _fake_timer_module()
    with patch("importlib.import_module", return_value=fake):
        result = wd_mod.handle_command("watchdog", ["timer", "1s"])
    assert result is True
    assert ("wake_in", "1s") in fake.calls


def test_router_timer_start(_bypass_caller_guard):
    fake = _fake_timer_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["timer", "start", "build-phase-3"])
    assert ("timer_start", "build-phase-3") in fake.calls


def test_router_timer_stop(_bypass_caller_guard):
    fake = _fake_timer_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["timer", "stop", "build-phase-3"])
    assert ("timer_stop", "build-phase-3") in fake.calls


def test_router_timer_list(_bypass_caller_guard):
    fake = _fake_timer_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["timer", "list"])
    assert ("timer_list",) in fake.calls


def test_router_timer_report(_bypass_caller_guard, capsys):
    fake = _fake_timer_module()
    with patch("importlib.import_module", return_value=fake):
        wd_mod.handle_command("watchdog", ["timer", "report"])
    assert ("timer_report",) in fake.calls
    captured = capsys.readouterr()
    assert "report body" in (captured.out + captured.err)


def test_router_timer_help(_bypass_caller_guard, capsys):
    result = wd_mod.handle_command("watchdog", ["timer", "--help"])
    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "timer" in combined.lower()


def test_router_timer_invalid_duration(_bypass_caller_guard, capsys):
    """Invalid duration from wake_in surfaces as a clean error via the router."""
    fake = type(sys)("fake_timer_mod")

    def wake_in(duration):
        raise ValueError(f"bad duration: {duration}")

    fake.wake_in = wake_in
    fake.timer_start = lambda *a, **kw: {}
    fake.timer_stop = lambda *a, **kw: {}
    fake.timer_list = lambda *a, **kw: {}
    fake.timer_report = lambda *a, **kw: ""

    with patch("importlib.import_module", return_value=fake):
        result = wd_mod.handle_command("watchdog", ["timer", "notaduration"])

    assert result is True
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "invalid" in combined.lower()
