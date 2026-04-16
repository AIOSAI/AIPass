# =================== AIPass ====================
# Name: test_watchdog_registry.py
# Description: Tests for the watchdog watch registry (Phase 4, FPLAN-0186)
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for watchdog registry — register/deregister/list/kill (Phase 4)."""

import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry


@pytest.fixture
def store_path(tmp_path):
    """Fresh, isolated registry file per test — never touches real .trinity/."""
    return tmp_path / "watchdog_active.json"


# ─────────────────────────────────────────────────────────────────────────────
# register / deregister
# ─────────────────────────────────────────────────────────────────────────────


def test_register_creates_entry_and_returns_handle(store_path):
    handle = watch_registry.register(
        "agent",
        metadata={"agent_id": "@drone", "timeout_seconds": 1800},
        storage_path=store_path,
    )
    assert handle.startswith("agent-")
    assert len(handle) > len("agent-")

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert len(raw["watches"]) == 1
    entry = raw["watches"][0]
    assert entry["handle"] == handle
    assert entry["type"] == "agent"
    assert entry["pid"] == os.getpid()
    assert entry["metadata"]["agent_id"] == "@drone"
    assert "started_at" in entry
    assert "started_epoch" in entry


def test_register_multiple_watches(store_path):
    h1 = watch_registry.register("agent", {"agent_id": "@drone"}, storage_path=store_path)
    h2 = watch_registry.register("timer", {"duration": "5m"}, storage_path=store_path)
    h3 = watch_registry.register("schedule", {"scheduled_for": "02:00"}, storage_path=store_path)

    handles = {h1, h2, h3}
    assert len(handles) == 3
    assert h1.startswith("agent-")
    assert h2.startswith("timer-")
    assert h3.startswith("schedule-")

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["watches"]) == 3
    stored = {w["handle"] for w in raw["watches"]}
    assert stored == handles


def test_register_rejects_empty_watch_type(store_path):
    with pytest.raises(ValueError):
        watch_registry.register("", storage_path=store_path)
    with pytest.raises(ValueError):
        watch_registry.register("   ", storage_path=store_path)


def test_deregister_removes_entry(store_path):
    handle = watch_registry.register("timer", {"duration": "1s"}, storage_path=store_path)
    removed = watch_registry.deregister(handle, storage_path=store_path)
    assert removed is True

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["watches"] == []


def test_deregister_nonexistent_returns_false(store_path):
    # Empty store
    assert watch_registry.deregister("ghost-abcdef", storage_path=store_path) is False

    # Non-empty store, wrong handle
    watch_registry.register("timer", {"duration": "1s"}, storage_path=store_path)
    assert watch_registry.deregister("ghost-abcdef", storage_path=store_path) is False


def test_deregister_only_removes_target(store_path):
    h1 = watch_registry.register("agent", {}, storage_path=store_path)
    h2 = watch_registry.register("timer", {}, storage_path=store_path)

    watch_registry.deregister(h1, storage_path=store_path)
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert [w["handle"] for w in raw["watches"]] == [h2]


# ─────────────────────────────────────────────────────────────────────────────
# list_active
# ─────────────────────────────────────────────────────────────────────────────


def test_list_active_empty(store_path):
    assert watch_registry.list_active(storage_path=store_path) == []


def test_list_active_returns_all_with_elapsed(store_path):
    watch_registry.register("agent", {"agent_id": "@drone"}, storage_path=store_path)
    watch_registry.register("timer", {"duration": "5m"}, storage_path=store_path)
    time.sleep(0.05)

    active = watch_registry.list_active(storage_path=store_path, prune_stale=False)
    assert len(active) == 2
    for entry in active:
        assert "elapsed_seconds" in entry
        assert entry["elapsed_seconds"] >= 0


def test_list_active_prunes_stale_by_default(store_path):
    watch_registry.register("timer", {}, storage_path=store_path)
    watch_registry.register("schedule", {}, storage_path=store_path)

    # Force every pid to look dead.
    with patch.object(watch_registry, "is_pid_alive", return_value=False):
        active = watch_registry.list_active(storage_path=store_path, prune_stale=True)

    assert active == []
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["watches"] == []  # pruned from disk too


def test_list_active_keeps_stale_when_prune_false(store_path):
    watch_registry.register("timer", {}, storage_path=store_path)

    with patch.object(watch_registry, "is_pid_alive", return_value=False):
        active = watch_registry.list_active(storage_path=store_path, prune_stale=False)

    assert len(active) == 1
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["watches"]) == 1  # still on disk


def test_list_active_selective_prune(store_path):
    """Only entries with dead pids should be pruned."""
    h_alive = watch_registry.register("agent", {"label": "alive"}, storage_path=store_path)
    h_dead = watch_registry.register("agent", {"label": "dead"}, storage_path=store_path)

    # Patch the dead entry's pid on disk to something definitely unused.
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    for watch in raw["watches"]:
        if watch["handle"] == h_dead:
            watch["pid"] = 999999
    store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    active = watch_registry.list_active(storage_path=store_path, prune_stale=True)
    surviving_handles = {a["handle"] for a in active}
    assert h_alive in surviving_handles
    assert h_dead not in surviving_handles


# ─────────────────────────────────────────────────────────────────────────────
# is_pid_alive
# ─────────────────────────────────────────────────────────────────────────────


def test_is_pid_alive_current_process():
    assert watch_registry.is_pid_alive(os.getpid()) is True


def test_is_pid_alive_impossible_pid():
    # 999999 is well above typical kernel.pid_max default — unlikely to exist.
    assert watch_registry.is_pid_alive(999999) is False


def test_is_pid_alive_rejects_invalid_input():
    assert watch_registry.is_pid_alive(-1) is False
    assert watch_registry.is_pid_alive(0) is False
    # Non-int input can't be used by os.kill — handled defensively.
    assert watch_registry.is_pid_alive("1234") is False  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# kill_watch / kill_all
# ─────────────────────────────────────────────────────────────────────────────


def test_kill_watch_handle_not_found(store_path):
    result = watch_registry.kill_watch("ghost-abcdef", storage_path=store_path)
    assert result == {
        "handle": "ghost-abcdef",
        "killed": False,
        "was_alive": False,
        "reason": "handle not found",
    }


def test_kill_watch_already_dead_pid(store_path):
    """Handle for a dead pid should still be deregistered cleanly."""
    handle = watch_registry.register("timer", {}, storage_path=store_path)
    # Point the entry at a dead pid without touching the current pid of this test.
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    raw["watches"][0]["pid"] = 999999
    store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    result = watch_registry.kill_watch(handle, storage_path=store_path)
    assert result["killed"] is True
    assert result["was_alive"] is False

    # Deregistered
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["watches"] == []


def test_kill_watch_happy_path(store_path):
    """Spawn a sleep subprocess, register it, kill via registry — verify dead."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Manually install an entry pointing at the subprocess pid so kill_watch
        # targets it instead of this test's own pid.
        handle = watch_registry.register("timer", {"duration": "30s"}, storage_path=store_path)
        raw = json.loads(store_path.read_text(encoding="utf-8"))
        for watch in raw["watches"]:
            if watch["handle"] == handle:
                watch["pid"] = proc.pid
        store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        result = watch_registry.kill_watch(handle, storage_path=store_path)
        assert result["handle"] == handle
        assert result["was_alive"] is True
        assert result["killed"] is True

        # Subprocess should have exited (wait briefly in case SIGTERM is still
        # in flight on a slow CI box).
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_kill_all_multiple_watches(store_path):
    h1 = watch_registry.register("timer", {}, storage_path=store_path)
    h2 = watch_registry.register("schedule", {}, storage_path=store_path)
    # Point both at dead pids so kill_all completes fast and doesn't touch real processes.
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    for watch in raw["watches"]:
        watch["pid"] = 999999
    store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    results = watch_registry.kill_all(storage_path=store_path)
    handles = {r["handle"] for r in results}
    assert handles == {h1, h2}
    assert all(r["killed"] for r in results)

    raw_after = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw_after["watches"] == []


def test_kill_all_empty(store_path):
    assert watch_registry.kill_all(storage_path=store_path) == []


# ─────────────────────────────────────────────────────────────────────────────
# Atomic write + concurrency sanity
# ─────────────────────────────────────────────────────────────────────────────


def test_atomic_write_leaves_no_tmp(store_path):
    watch_registry.register("timer", {}, storage_path=store_path)
    tmp_sibling = store_path.with_suffix(store_path.suffix + ".tmp")
    assert not tmp_sibling.exists()


def test_sequential_register_deregister_preserves_entries(store_path):
    """Sanity test for read-modify-write: many ops in a row don't lose data."""
    handles = [watch_registry.register("timer", {"i": i}, storage_path=store_path) for i in range(10)]
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["watches"]) == 10

    # Remove every other one.
    for handle in handles[::2]:
        assert watch_registry.deregister(handle, storage_path=store_path) is True

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["watches"]) == 5
    surviving = {w["handle"] for w in raw["watches"]}
    assert surviving == set(handles[1::2])


def test_full_cycle_integration(store_path):
    """register -> list -> deregister end to end."""
    h = watch_registry.register("agent", {"agent_id": "@drone"}, storage_path=store_path)

    active = watch_registry.list_active(storage_path=store_path, prune_stale=False)
    assert len(active) == 1
    assert active[0]["handle"] == h
    assert active[0]["metadata"]["agent_id"] == "@drone"

    assert watch_registry.deregister(h, storage_path=store_path) is True
    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


# ─────────────────────────────────────────────────────────────────────────────
# Handler integration — each handler registers at start, deregisters on exit
# ─────────────────────────────────────────────────────────────────────────────


def test_agent_handler_registers_and_deregisters(store_path, monkeypatch):
    """watch_agent registers on entry and deregisters in finally (even on early return)."""
    from aipass.devpulse.apps.handlers.watchdog import agent as agent_handler

    # Force the handler's default storage path to our tmp file so register
    # lands in the right place.
    monkeypatch.setattr(watch_registry, "_default_storage_path", lambda: store_path)

    # @__definitely_not_a_branch__ hits the early "not found" return —
    # exercises the deregister-in-finally path with minimal work.
    result = agent_handler.watch_agent("@__definitely_not_a_branch__", timeout_seconds=1)
    assert "handle" in result
    assert result["handle"].startswith("agent-")

    # Registry should be empty after the call.
    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_timer_wake_in_registers_and_deregisters(store_path, monkeypatch):
    """wake_in with a short duration registers then deregisters."""
    from aipass.devpulse.apps.handlers.watchdog import timer as timer_handler

    monkeypatch.setattr(watch_registry, "_default_storage_path", lambda: store_path)

    # Take a peek mid-flight by patching time.sleep to snapshot the registry.
    snapshots: list[list] = []
    real_sleep = time.sleep

    def spy_sleep(duration):
        """Capture the registry state while the timer is mid-wait."""
        snapshots.append(watch_registry.list_active(storage_path=store_path, prune_stale=False))
        real_sleep(duration)

    with patch("aipass.devpulse.apps.handlers.watchdog.timer.time.sleep", spy_sleep):
        result = timer_handler.wake_in("1s")

    assert result["state"] == "woke"
    assert "handle" in result

    # Mid-flight snapshot must have seen the entry.
    assert any(any(w["handle"].startswith("timer-") for w in snap) for snap in snapshots), (
        "timer handler never registered mid-wait"
    )

    # After wake_in returns, the registry must be empty.
    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_schedule_wake_at_registers_and_deregisters(store_path, monkeypatch):
    """wake_at with a tiny relative delay registers then deregisters."""
    from aipass.devpulse.apps.handlers.watchdog import schedule as schedule_handler

    monkeypatch.setattr(watch_registry, "_default_storage_path", lambda: store_path)

    # Fast-forward clock so wake_at returns immediately without real waiting.
    from datetime import datetime, timedelta

    start = datetime(2026, 4, 14, 12, 0, 0)
    calls = {"n": 0}

    def fake_now():
        """Returns ``start`` once then jumps 10s forward to trip the break."""
        calls["n"] += 1
        if calls["n"] == 1:
            return start
        return start + timedelta(seconds=10)

    result = schedule_handler.wake_at("+5s", now_fn=fake_now)

    assert result["state"] == "woke"
    assert "handle" in result

    # Registry cleaned up.
    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_handler_deregisters_on_exception(store_path, monkeypatch):
    """If a handler raises mid-wait, the finally block must still deregister."""
    from aipass.devpulse.apps.handlers.watchdog import timer as timer_handler

    monkeypatch.setattr(watch_registry, "_default_storage_path", lambda: store_path)

    # Make time.sleep raise after the register call.
    def exploding_sleep(duration):
        """Simulate a KeyboardInterrupt / cancellation mid-sleep."""
        raise RuntimeError("boom")

    with patch("aipass.devpulse.apps.handlers.watchdog.timer.time.sleep", exploding_sleep):
        with pytest.raises(RuntimeError, match="boom"):
            timer_handler.wake_in("5s")

    # Even though wake_in raised, the finally block must have deregistered.
    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []
