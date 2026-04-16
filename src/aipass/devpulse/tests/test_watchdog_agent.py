# =================== AIPass ====================
# Name: test_watchdog_agent.py
# Description: Tests for the watchdog agent handler
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

"""Tests for watch_agent (Phase 1, FPLAN-0186).

Mock-heavy unit tests verify the return-shape branches:
  - completed (clean exit)
  - crashed (bounce file present)
  - timeout
  - agent not found

Integration tests are marked with @pytest.mark.integration and require
a live ai_mail dispatch flow. They're skipped by default in CI.
"""

import json
import os
import time
from pathlib import Path

import pytest

from aipass.devpulse.apps.handlers.watchdog import agent as agent_handler


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_fake_branch(tmp_path: Path, branch_name: str = "fakebranch") -> Path:
    """Create a fake branch dir with .ai_mail.local and a registry pointing at it."""
    branch_path = tmp_path / branch_name
    (branch_path / ".ai_mail.local").mkdir(parents=True)

    registry = {
        "branches": [
            {"email": f"@{branch_name}", "path": str(branch_path)},
        ]
    }
    (tmp_path / "AIPASS_REGISTRY.json").write_text(
        json.dumps(registry), encoding='utf-8'
    )
    return branch_path


def _write_lock(branch_path: Path, pid: int) -> Path:
    """Write a fake .dispatch.lock and return its path."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_data = {"pid": pid, "timestamp": "2026-04-14T00:00:00", "branch": str(branch_path)}
    lock_file.write_text(json.dumps(lock_data), encoding='utf-8')
    return lock_file


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — return shape per branch
# ─────────────────────────────────────────────────────────────────────────────


def test_watch_agent_branch_not_found(monkeypatch, tmp_path):
    """Missing branch returns immediately with timeout state and 'agent not found'."""
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: None)
    result = agent_handler.watch_agent("@nonexistent", timeout_seconds=5)

    assert result["woke"] is False
    assert result["agent_state"] == "timeout"
    assert "not found" in result["reason"].lower()
    assert result["agent_id"] == "@nonexistent"
    assert result["exit_code"] is None


def test_watch_agent_no_active_lock(monkeypatch, tmp_path):
    """No lock file -> agent already idle, returns completed immediately."""
    _build_fake_branch(tmp_path)
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5)

    assert result["woke"] is True
    assert result["agent_state"] == "completed"
    assert result["exit_code"] == 0


def test_watch_agent_completed_via_lock_removal(monkeypatch, tmp_path):
    """Lock present at start, then removed -> wake with state=completed."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    call_count = {"n": 0}
    real_sleep = time.sleep

    def fake_sleep(seconds):
        """Remove the lock on the second poll cycle to simulate clean exit."""
        call_count["n"] += 1
        if call_count["n"] >= 1:
            lock_file.unlink(missing_ok=True)
        real_sleep(0.01)

    monkeypatch.setattr(agent_handler.time, "sleep", fake_sleep)

    result = agent_handler.watch_agent(
        "@fakebranch", timeout_seconds=5, poll_interval=0.01
    )

    assert result["woke"] is True
    assert result["agent_state"] == "completed"
    assert result["exit_code"] == 0
    assert "clean" in result["reason"].lower() or "finished" in result["reason"].lower()


def test_watch_agent_crashed_via_bounce_file(monkeypatch, tmp_path):
    """Lock removed AND bounce file present -> wake with state=crashed."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    bounce_file = branch_path / ".ai_mail.local" / "last_bounce.json"
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    real_sleep = time.sleep

    def fake_sleep(seconds):
        """Drop a bounce file then remove the lock to simulate crash exit."""
        bounce_file.write_text(json.dumps({"exit_code": 1, "reason": "test"}), encoding='utf-8')
        lock_file.unlink(missing_ok=True)
        real_sleep(0.01)

    monkeypatch.setattr(agent_handler.time, "sleep", fake_sleep)

    result = agent_handler.watch_agent(
        "@fakebranch", timeout_seconds=5, poll_interval=0.01
    )

    assert result["woke"] is True
    assert result["agent_state"] == "crashed"
    assert result["exit_code"] == 1


def test_watch_agent_timeout(monkeypatch, tmp_path):
    """Lock never removed and PID stays alive -> timeout."""
    branch_path = _build_fake_branch(tmp_path)
    _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: True)

    result = agent_handler.watch_agent(
        "@fakebranch", timeout_seconds=1, poll_interval=0.05
    )

    assert result["woke"] is False
    assert result["agent_state"] == "timeout"
    assert result["exit_code"] is None
    assert result["elapsed"] >= 1


def test_watch_agent_pid_dead_treated_as_crash(monkeypatch, tmp_path):
    """Lock present but monitor PID dead -> crash exit."""
    branch_path = _build_fake_branch(tmp_path)
    _write_lock(branch_path, pid=999999)
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: False)

    result = agent_handler.watch_agent(
        "@fakebranch", timeout_seconds=5, poll_interval=0.01
    )

    assert result["woke"] is True
    assert result["agent_state"] == "crashed"


def test_watch_agent_return_keys():
    """Every code path must return all expected keys (Phase 4 adds ``handle``)."""
    expected = {
        "woke", "reason", "elapsed", "agent_state",
        "exit_code", "agent_id", "handle",
    }
    # Use the not-found path for a fast invocation
    result = agent_handler.watch_agent("@__definitely_not_a_branch__", timeout_seconds=1)
    assert set(result.keys()) == expected


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests (require live ai_mail dispatch — skipped by default)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("WATCHDOG_INTEGRATION") != "1",
    reason="Set WATCHDOG_INTEGRATION=1 to run live dispatch tests",
)
def test_watch_agent_live_dispatch_completes():
    """Dispatch a real tiny agent and verify watchdog wakes on completion.

    Skipped unless WATCHDOG_INTEGRATION=1 is set. Slow and depends on
    a working drone / ai_mail / agent runtime.
    """
    import subprocess

    dispatch = subprocess.run(
        ["drone", "@ai_mail", "dispatch", "@drone",
         "Watchdog ping test", "Reply with OK then exit."],
        capture_output=True, text=True, timeout=60,
    )
    assert dispatch.returncode == 0, f"dispatch failed: {dispatch.stderr}"

    result = agent_handler.watch_agent("@drone", timeout_seconds=300, poll_interval=2.0)
    assert result["woke"] is True
    assert result["agent_state"] in ("completed", "crashed")


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("WATCHDOG_INTEGRATION") != "1",
    reason="Set WATCHDOG_INTEGRATION=1 to run live dispatch tests",
)
def test_watch_agent_live_dispatch_timeout_path():
    """Dispatch a real agent with a very short watchdog timeout; verify timeout state."""
    import subprocess

    subprocess.run(
        ["drone", "@ai_mail", "dispatch", "@drone",
         "Long watchdog test", "Wait at least 30 seconds then reply."],
        capture_output=True, text=True, timeout=60,
    )

    result = agent_handler.watch_agent("@drone", timeout_seconds=2, poll_interval=0.5)
    assert result["agent_state"] == "timeout"


@pytest.mark.integration
def test_watch_agent_crash_path_skipped():
    """Crash-path integration test — skipped.

    Cheaply triggering a real agent crash mid-task would require either
    crafting a malformed dispatch (risk: corrupting the ai_mail flow) or
    SIGKILLing a live monitor (risk: leaving stale locks). The unit test
    test_watch_agent_crashed_via_bounce_file already covers the bounce-file
    branch via the same code path the monitor uses.
    """
    pytest.skip("Crash path covered by unit test test_watch_agent_crashed_via_bounce_file")
