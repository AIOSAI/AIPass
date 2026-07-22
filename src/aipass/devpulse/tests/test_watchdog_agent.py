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
import sys
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
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
    return branch_path


def _write_lock(branch_path: Path, pid: int) -> Path:
    """Write a fake .dispatch.lock and return its path."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_data = {"pid": pid, "timestamp": "2026-04-14T00:00:00", "branch": str(branch_path)}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    return lock_file


def _agent_only_sleep(side_effect):
    """Wrap a sleep side-effect so ONLY calls from the agent module fire it.

    Patching agent_handler.time.sleep mutates the GLOBAL time module — any
    daemon thread sleeping during the patch window (prax logger spawns three on
    first log) would run the side effect concurrently with the main thread,
    e.g. re-truncating the bounce file mid-read in _classify_exit. Foreign
    callers get a real 1ms sleep instead. Same guard as _fake_clock_sleep.
    """
    agent_file = Path(agent_handler.__file__).resolve()
    real_sleep = time.sleep

    def fake_sleep(_seconds):
        caller = Path(sys._getframe(1).f_code.co_filename).resolve()
        if caller != agent_file:
            real_sleep(0.001)
            return
        side_effect()
        real_sleep(0.01)

    return fake_sleep


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
    assert result["agent_state"] == "completed_silent"
    assert result["exit_code"] == 0


def test_watch_agent_completed_via_lock_removal(monkeypatch, tmp_path):
    """Lock present at start, then removed -> wake with state=completed_silent (no sent messages)."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    monkeypatch.setattr(
        agent_handler.time,
        "sleep",
        _agent_only_sleep(lambda: lock_file.unlink(missing_ok=True)),
    )

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["woke"] is True
    assert result["agent_state"] == "completed_silent"
    assert result["exit_code"] == 0


def test_watch_agent_completed_replied_via_sent_folder(monkeypatch, tmp_path):
    """Lock removed + sent message after dispatch -> completed_replied."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    sent_dir = branch_path / ".ai_mail.local" / "sent"
    sent_dir.mkdir(parents=True, exist_ok=True)
    sent_msg = {"to": "@devpulse", "from": "@fakebranch", "subject": "Done", "timestamp": "2026-04-14 00:01:00"}
    (sent_dir / "reply.json").write_text(json.dumps(sent_msg), encoding="utf-8")

    monkeypatch.setattr(
        agent_handler.time,
        "sleep",
        _agent_only_sleep(lambda: lock_file.unlink(missing_ok=True)),
    )

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["woke"] is True
    assert result["agent_state"] == "completed_replied"
    assert result["exit_code"] == 0


def test_watch_agent_crashed_via_bounce_file(monkeypatch, tmp_path):
    """Lock removed AND bounce file present -> wake with state=crashed."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    bounce_file = branch_path / ".ai_mail.local" / "last_bounce.json"
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    def crash_exit():
        """Drop a bounce file then remove the lock to simulate crash exit."""
        bounce_file.write_text(json.dumps({"exit_code": 1, "reason": "test"}), encoding="utf-8")
        lock_file.unlink(missing_ok=True)

    monkeypatch.setattr(agent_handler.time, "sleep", _agent_only_sleep(crash_exit))

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["woke"] is True
    assert result["agent_state"] == "crashed"
    assert result["exit_code"] == 1


def test_watch_agent_timeout(monkeypatch, tmp_path):
    """Lock never removed and PID stays alive -> timeout."""
    branch_path = _build_fake_branch(tmp_path)
    _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: True)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=1, poll_interval=0.05)

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

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["woke"] is True
    assert result["agent_state"] == "crashed"


def test_watch_agent_return_keys():
    """Every code path must return all expected keys (Phase 4 adds ``handle``)."""
    expected = {
        "woke",
        "reason",
        "elapsed",
        "agent_state",
        "exit_code",
        "agent_id",
        "handle",
    }
    # Use the not-found path for a fast invocation
    result = agent_handler.watch_agent("@__definitely_not_a_branch__", timeout_seconds=1)
    assert set(result.keys()) == expected


# ─────────────────────────────────────────────────────────────────────────────
# #634 — in-flight tool detection + stall surfaced to stdout
# ─────────────────────────────────────────────────────────────────────────────


def _write_jsonl(projects_dir: Path, *lines: dict, name: str = "session.jsonl") -> Path:
    """Write JSONL entries (one dict per line) into a projects dir."""
    projects_dir.mkdir(parents=True, exist_ok=True)
    f = projects_dir / name
    f.write_text("".join(json.dumps(ln) + "\n" for ln in lines), encoding="utf-8")
    return f


def test_last_entry_is_inflight_tool_true_for_assistant_tool_use(tmp_path):
    """Last line = assistant message with a tool_use block → in-flight tool call."""
    proj = tmp_path / "proj"
    _write_jsonl(
        proj,
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "Bash", "input": {}}]},
        },
    )
    assert agent_handler._last_entry_is_inflight_tool(proj) is True


def test_last_entry_is_inflight_tool_false_for_text_and_results(tmp_path):
    """Assistant text-only, a returned tool_result, malformed, and empty all → False."""
    proj = tmp_path / "proj"

    _write_jsonl(
        proj, {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}
    )
    assert agent_handler._last_entry_is_inflight_tool(proj) is False

    _write_jsonl(
        proj,
        {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
        },
    )
    assert agent_handler._last_entry_is_inflight_tool(proj) is False

    (proj / "session.jsonl").write_text("{not valid json\n", encoding="utf-8")
    assert agent_handler._last_entry_is_inflight_tool(proj) is False

    # Nonexistent dir and empty dir → False.
    assert agent_handler._last_entry_is_inflight_tool(tmp_path / "nope") is False
    (tmp_path / "empty").mkdir()
    assert agent_handler._last_entry_is_inflight_tool(tmp_path / "empty") is False


def test_last_entry_is_inflight_tool_picks_newest_file(tmp_path):
    """With multiple JSONLs, only the most-recently-modified one decides."""
    proj = tmp_path / "proj"
    old = _write_jsonl(
        proj,
        {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}]}},
        name="old.jsonl",
    )
    new = _write_jsonl(
        proj,
        {"message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
        name="new.jsonl",
    )
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    assert agent_handler._last_entry_is_inflight_tool(proj) is False  # newest = text-only

    os.utime(old, (3, 3))  # old is now newest and holds the tool_use
    assert agent_handler._last_entry_is_inflight_tool(proj) is True


def test_stalltracker_reports_stall_after_threshold(monkeypatch, capsys):
    """No activity past STALL_THRESHOLD → a [watchdog.stall] line on stdout."""
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: False)
    t = agent_handler.StallTracker("@x", Path("/nope"), {}, now=0.0, pid=123)

    t.observe(now=60.0)  # below threshold
    assert "[watchdog.stall]" not in capsys.readouterr().out
    assert t.stall_reported is False

    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD)  # at threshold
    assert "[watchdog.stall]" in capsys.readouterr().out
    assert t.stall_reported is True


def test_stalltracker_inflight_tool_prevents_stall(monkeypatch, capsys):
    """An in-flight tool call resets the idle timer every tick → never a stall."""
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: True)
    t = agent_handler.StallTracker("@x", Path("/nope"), {}, now=0.0, pid=123)

    for now in (120.0, 240.0, 360.0, 480.0):
        t.observe(now=now)

    out = capsys.readouterr().out
    assert "[watchdog.stall]" not in out
    assert t.stall_reported is False


def test_stalltracker_long_tool_advisory(monkeypatch, capsys):
    """One tool call held in-flight past LONG_TOOL_THRESHOLD → advisory, not a stall."""
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: True)
    t = agent_handler.StallTracker("@x", Path("/nope"), {}, now=0.0, pid=123)

    t.observe(now=0.0)  # first in-flight tick → anchors in_flight_since
    t.observe(now=agent_handler.StallTracker.LONG_TOOL_THRESHOLD)
    out = capsys.readouterr().out
    assert "[watchdog.longtool]" in out
    assert "[watchdog.stall]" not in out
    assert t.long_tool_reported is True


def test_stalltracker_resume_clears_stall(monkeypatch, capsys):
    """After a stall, real activity emits [watchdog.resumed] and clears the flag."""
    signals = {"size": False}
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: signals["size"])
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_snapshot_jsonl_sizes", lambda *a, **kw: {})
    t = agent_handler.StallTracker("@x", Path("/nope"), {}, now=0.0, pid=123)

    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD)  # stall
    assert "[watchdog.stall]" in capsys.readouterr().out
    assert t.stall_reported is True

    signals["size"] = True  # activity resumes
    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD + 5)
    out = capsys.readouterr().out
    assert "[watchdog.resumed]" in out
    assert t.stall_reported is False


def _fake_clock_sleep(agent_module, monkeypatch, lock_file, unlink_at=200.0, step=60.0):
    """Patch monotonic + sleep with a fake clock that advances `step`s per sleep
    and unlinks the dispatch lock once the clock passes `unlink_at` (loop exit).

    THREAD-SCOPED (S300): ``agent_module.time`` is the shared stdlib module, so
    patching ``time.sleep`` is process-global — background daemon threads (prax
    logger spawns three on first log) also hit the fake and would race the
    clock forward, unlinking the lock before ``watch_agent`` even reads it
    (flaked exactly so: 'no active lock' + uptime-sized elapsed). Only sleeps
    called FROM the agent module advance the clock; foreign callers get a tiny
    real sleep so they don't spin hot.
    """
    clock = {"t": 0.0}
    agent_file = Path(agent_module.__file__).resolve()
    real_sleep = time.sleep
    monkeypatch.setattr(agent_module.time, "monotonic", lambda: clock["t"])

    def fake_sleep(_seconds):
        """Advance the fake clock for agent-module callers only."""
        caller = Path(sys._getframe(1).f_code.co_filename).resolve()
        if caller != agent_file:
            real_sleep(0.001)  # background thread — keep it off the fake clock
            return
        clock["t"] += step
        if clock["t"] >= unlink_at:
            lock_file.unlink(missing_ok=True)

    monkeypatch.setattr(agent_module.time, "sleep", fake_sleep)


def test_watch_agent_surfaces_stall_to_stdout(monkeypatch, tmp_path, capsys):
    """End-to-end: a genuine stall reaches STDOUT so the Monitor wrapper relays it."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: False)
    # Lock must outlive STALL_THRESHOLD (300s) or the watch completes stall-free.
    _fake_clock_sleep(agent_handler, monkeypatch, lock_file, unlink_at=400.0)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=100000, poll_interval=0.01)
    out = capsys.readouterr().out
    assert "[watchdog.stall]" in out
    assert result["woke"] is True


def test_watch_agent_inflight_tool_no_false_stall(monkeypatch, tmp_path, capsys):
    """End-to-end: a long in-flight tool call must NOT surface a stall (#634 part 1)."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(agent_handler, "_has_jsonl_activity", lambda *a, **kw: False)
    monkeypatch.setattr(agent_handler, "_last_entry_is_inflight_tool", lambda *a, **kw: True)
    _fake_clock_sleep(agent_handler, monkeypatch, lock_file)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=100000, poll_interval=0.01)
    out = capsys.readouterr().out
    assert "[watchdog.stall]" not in out
    assert result["woke"] is True


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
        ["drone", "@ai_mail", "dispatch", "@drone", "Watchdog ping test", "Reply with OK then exit."],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert dispatch.returncode == 0, f"dispatch failed: {dispatch.stderr}"

    result = agent_handler.watch_agent("@drone", timeout_seconds=300, poll_interval=2.0)
    assert result["woke"] is True
    assert result["agent_state"] in ("completed_replied", "completed_silent", "crashed")


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("WATCHDOG_INTEGRATION") != "1",
    reason="Set WATCHDOG_INTEGRATION=1 to run live dispatch tests",
)
def test_watch_agent_live_dispatch_timeout_path():
    """Dispatch a real agent with a very short watchdog timeout; verify timeout state."""
    import subprocess

    subprocess.run(
        ["drone", "@ai_mail", "dispatch", "@drone", "Long watchdog test", "Wait at least 30 seconds then reply."],
        capture_output=True,
        text=True,
        timeout=60,
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
