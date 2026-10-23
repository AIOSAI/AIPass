# =================== AIPass ====================
# Name: test_watchdog_registry.py
# Description: Tests for the watchdog watch registry (Phase 4, FPLAN-0186)
# Version: 1.4.1
# Created: 2026-04-14
# Modified: 2026-10-22
# =============================================

"""Tests for apps/handlers/watchdog/registry.py and the handlers that register through it."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/watchdog/registry.py parses and imports
# seedgo: no-test-needed(documentation) — that register, deregister, list_active and kill_watch carry docstrings

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers import file_lock
from aipass.devpulse.apps.handlers.watchdog import agent as agent_handler
from aipass.devpulse.apps.handlers.watchdog import registry as reg
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry
from aipass.devpulse.apps.handlers.watchdog import schedule as schedule_handler
from aipass.devpulse.apps.handlers.watchdog import timer as tmr
from aipass.devpulse.apps.handlers.watchdog import timer as watch_timer


@pytest.fixture
def store_path(tmp_path):
    """Fresh, isolated registry file per test — never touches real .trinity/."""
    return tmp_path / "watchdog_active.json"


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
    assert watch_registry.deregister("ghost-abcdef", storage_path=store_path) is False

    watch_registry.register("timer", {"duration": "1s"}, storage_path=store_path)
    assert watch_registry.deregister("ghost-abcdef", storage_path=store_path) is False


def test_deregister_only_removes_target(store_path):
    h1 = watch_registry.register("agent", {}, storage_path=store_path)
    h2 = watch_registry.register("timer", {}, storage_path=store_path)

    watch_registry.deregister(h1, storage_path=store_path)
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert [w["handle"] for w in raw["watches"]] == [h2]


def test_list_active_empty(store_path):
    assert watch_registry.list_active(storage_path=store_path) == []


def test_list_active_returns_all_with_elapsed(store_path):
    watch_registry.register("agent", {"agent_id": "@drone"}, storage_path=store_path)
    watch_registry.register("timer", {"duration": "5m"}, storage_path=store_path)

    active = watch_registry.list_active(storage_path=store_path, prune_stale=False)
    assert len(active) == 2
    for entry in active:
        assert "elapsed_seconds" in entry
        assert entry["elapsed_seconds"] >= 0


def test_list_active_prunes_stale_by_default(store_path):
    watch_registry.register("timer", {}, storage_path=store_path)
    watch_registry.register("schedule", {}, storage_path=store_path)

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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.kill sig-0)")
def test_list_active_selective_prune(store_path):
    """Only entries with dead pids should be pruned."""
    h_alive = watch_registry.register("agent", {"label": "alive"}, storage_path=store_path)
    h_dead = watch_registry.register("agent", {"label": "dead"}, storage_path=store_path)

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    for watch in raw["watches"]:
        if watch["handle"] == h_dead:
            watch["pid"] = 999999
    store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    active = watch_registry.list_active(storage_path=store_path, prune_stale=True)
    surviving_handles = {a["handle"] for a in active}
    assert h_alive in surviving_handles
    assert h_dead not in surviving_handles


def test_is_pid_alive_current_process():
    assert watch_registry.is_pid_alive(os.getpid()) is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.kill sig-0)")
def test_is_pid_alive_impossible_pid():
    assert watch_registry.is_pid_alive(999999) is False


def test_is_pid_alive_rejects_invalid_input():
    assert watch_registry.is_pid_alive(-1) is False
    assert watch_registry.is_pid_alive(0) is False
    assert watch_registry.is_pid_alive("1234") is False  # type: ignore[arg-type]


# os.kill(pid, 0) SUCCEEDS for a zombie, so off Linux only ps can say a pid is a corpse.
# These pretend darwin here, with subprocess.run answering in real `ps -o state=` shape.


def _fake_ps(stdout: str, argv_seen: list | None = None):
    """A subprocess.run stand-in that prints ``stdout`` and records its argv."""

    def _run(argv, **kwargs):
        if argv_seen is not None:
            argv_seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return _run


def test_is_zombie_off_linux_reads_the_ps_state(monkeypatch, pretend_platform):
    argv_seen: list = []
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_ps("Z+\n", argv_seen))

    assert watch_registry.is_zombie(4242) is True
    assert argv_seen == [["ps", "-o", "state=", "-p", "4242"]]


def test_a_running_state_off_linux_is_not_a_zombie(monkeypatch, pretend_platform):
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_ps("S\n"))

    assert watch_registry.is_zombie(4242) is False


def test_is_zombie_off_linux_is_false_when_ps_cannot_run(monkeypatch, pretend_platform):
    pretend_platform(watch_registry, "darwin")

    def _explode(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "ps")

    monkeypatch.setattr(subprocess, "run", _explode)
    assert watch_registry.is_zombie(4242) is False


def test_a_zombie_is_not_alive_off_linux(monkeypatch, pretend_platform):
    """This pid answers os.kill(pid, 0); the ps state is the ONLY thing that can say it is a corpse."""
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_ps("Z+\n"))

    assert watch_registry.is_pid_alive(os.getpid()) is False


def test_a_live_pid_off_linux_is_still_alive(monkeypatch, pretend_platform):
    """The other half: the portable probe must not bury the living."""
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_ps("S+\n"))

    assert watch_registry.is_pid_alive(os.getpid()) is True


def test_a_zombie_watch_is_pruned_off_linux(store_path, monkeypatch, pretend_platform):
    """A zombie watch must not stay listed forever; runs on every host, as the lock reads fcntl, not the platform."""
    watch_registry.register("agent", {"label": "reaped"}, storage_path=store_path)
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_ps("Z+\n"))

    assert watch_registry.list_active(storage_path=store_path, prune_stale=True) == []


def test_the_lock_is_a_no_op_where_fcntl_is_absent(store_path, monkeypatch, pretend_platform):
    """The lock reads the fcntl binding, not sys.platform: pretended darwin without fcntl neither imports nor locks."""
    monkeypatch.setattr(file_lock, "fcntl", None)
    pretend_platform(watch_registry, "darwin")

    handle = watch_registry.register("agent", {"label": "unlocked"}, storage_path=store_path)

    assert handle.startswith("agent-")
    assert store_path.exists()
    assert not store_path.with_suffix(store_path.suffix + ".lock").exists()


def test_kill_watch_handle_not_found(store_path):
    result = watch_registry.kill_watch("ghost-abcdef", storage_path=store_path)
    assert result == {
        "handle": "ghost-abcdef",
        "killed": False,
        "was_alive": False,
        "reason": "handle not found",
    }


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.kill sig-0)")
def test_kill_watch_already_dead_pid(store_path):
    """Handle for a dead pid should still be deregistered cleanly."""
    handle = watch_registry.register("timer", {}, storage_path=store_path)
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    raw["watches"][0]["pid"] = 999999
    store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    result = watch_registry.kill_watch(handle, storage_path=store_path)
    assert result["killed"] is True
    assert result["was_alive"] is False

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["watches"] == []


def test_kill_watch_happy_path(store_path):
    """Spawn a sleep subprocess, register it, kill via registry — verify dead."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
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

        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only signal semantics (SIG_IGN)")
def test_kill_watch_reports_failure_when_pid_survives_sigterm(store_path):
    """A pid that ignores SIGTERM must come back killed=False, not a KILLED lie; the handle is still freed."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('armed', flush=True); time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == b"armed"  # SIG_IGN installed before we fire

        handle = watch_registry.register("timer", {"duration": "30s"}, storage_path=store_path)
        raw = json.loads(store_path.read_text(encoding="utf-8"))
        for watch in raw["watches"]:
            if watch["handle"] == handle:
                watch["pid"] = proc.pid
        store_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        result = watch_registry.kill_watch(handle, storage_path=store_path)
        assert result["was_alive"] is True
        assert result["killed"] is False
        assert "still alive" in result["reason"]

        raw = json.loads(store_path.read_text(encoding="utf-8"))
        assert raw["watches"] == []
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.kill sig-0)")
def test_kill_all_multiple_watches(store_path):
    h1 = watch_registry.register("timer", {}, storage_path=store_path)
    h2 = watch_registry.register("schedule", {}, storage_path=store_path)
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


def test_atomic_write_leaves_no_tmp(store_path):
    watch_registry.register("timer", {}, storage_path=store_path)
    tmp_sibling = store_path.with_suffix(store_path.suffix + ".tmp")
    assert not tmp_sibling.exists()


def test_sequential_register_deregister_preserves_entries(store_path):
    """Sanity test for read-modify-write: many ops in a row don't lose data."""
    handles = [watch_registry.register("timer", {"i": i}, storage_path=store_path) for i in range(10)]
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["watches"]) == 10

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


def test_agent_handler_registers_and_deregisters(store_path, monkeypatch):
    """watch_agent registers on entry and deregisters in finally (even on early return)."""
    monkeypatch.setattr(watch_registry, "default_storage_path", lambda: store_path)

    result = agent_handler.watch_agent("@__definitely_not_a_branch__", timeout_seconds=1)
    assert "handle" in result
    assert result["handle"].startswith("agent-")

    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_timer_wake_in_registers_and_deregisters(store_path, monkeypatch):
    """wake_in with a short duration registers then deregisters; mutant 'register skipped' reddens it."""
    monkeypatch.setattr(watch_registry, "default_storage_path", lambda: store_path)

    outcome: dict = {}
    waker = threading.Thread(target=lambda: outcome.update(result=watch_timer.wake_in("1s")))
    snapshots: list[list] = []
    waker.start()
    deadline = time.monotonic() + 30
    while waker.is_alive() and time.monotonic() < deadline:
        snapshots.append(watch_registry.list_active(storage_path=store_path, prune_stale=False))
        waker.join(timeout=0.01)
    waker.join(timeout=30)
    result = outcome["result"]

    assert result["state"] == "woke"
    assert "handle" in result

    assert any(any(w["handle"].startswith("timer-") for w in snap) for snap in snapshots), (
        "timer handler never registered mid-wait"
    )

    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_schedule_wake_at_registers_and_deregisters(store_path, monkeypatch):
    """wake_at with a tiny relative delay registers then deregisters."""
    monkeypatch.setattr(watch_registry, "default_storage_path", lambda: store_path)

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

    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_handler_deregisters_on_exception(store_path, monkeypatch):
    """If a handler raises mid-wait, the finally block must still deregister."""
    monkeypatch.setattr(watch_registry, "default_storage_path", lambda: store_path)

    def exploding_sleep(duration):
        """Simulate a KeyboardInterrupt / cancellation mid-sleep."""
        raise RuntimeError("boom")

    # Only timer's own ``time`` name is swapped: patching time.sleep is process-wide.
    monkeypatch.setattr(
        watch_timer, "time", SimpleNamespace(sleep=exploding_sleep, monotonic=time.monotonic, time=time.time)
    )
    with pytest.raises(RuntimeError, match="boom"):
        watch_timer.wake_in("5s")

    assert watch_registry.list_active(storage_path=store_path, prune_stale=False) == []


def test_a_call_that_names_no_store_writes_the_sealed_tmp_store(tmp_path):
    """conftest's sealed_watchdog_store: a test's default store is its own tmp_path, never the seat's."""
    handle = watch_registry.register("agent", {"agent_id": "@seal-probe"})
    started = watch_timer.timer_start("seal-probe")

    sealed = tmp_path / "_sealed_watchdog"
    watches = json.loads((sealed / "watchdog_active.json").read_text(encoding="utf-8"))["watches"]
    timers = json.loads((sealed / "watchdog_timers.json").read_text(encoding="utf-8"))["active"]
    assert [watch["handle"] for watch in watches] == [handle]
    assert list(timers) == ["seal-probe"]
    assert timers["seal-probe"]["started_at"] == started["started_at"]


@pytest.mark.live_default_store
class TestTheDefaultStoreNeverLandsAtTheCallersFeet:
    """The store is package state, derived from __file__: a cwd answer plants .watchdog/ in the tree."""

    def test_the_default_path_ignores_cwd_entirely(self, tmp_path, monkeypatch):
        """From a marker-less cwd the default must NOT be under that cwd."""
        monkeypatch.chdir(tmp_path)
        for mod in (reg, tmr):
            default = mod.default_storage_path()
            assert not default.is_relative_to(tmp_path), (
                f"the default store landed at the caller's feet — the cwd fallback is back: {default}"
            )

    def test_the_default_path_lives_inside_the_package(self, tmp_path, monkeypatch):
        """The store resolves next to the code that owns it, from anywhere."""
        monkeypatch.chdir(tmp_path)
        package_root = Path(reg.__file__).resolve().parents[3]
        assert package_root.name == "devpulse", (
            f"the layout assumption this test rests on moved — re-derive parents[N]: {package_root}"
        )
        assert reg.default_storage_path() == (package_root / ".watchdog" / "watchdog_active.json")
        assert tmr.default_storage_path() == (package_root / ".watchdog" / "watchdog_timers.json")
