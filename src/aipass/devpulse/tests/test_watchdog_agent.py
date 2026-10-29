# =================== AIPass ====================
# Name: test_watchdog_agent.py
# Description: Tests for the watchdog agent handler
# Version: 1.7.0
# Created: 2026-04-14
# Modified: 2026-10-29
# =============================================

"""Tests for apps/handlers/watchdog/agent.py: watch_agent, TranscriptScanner and StallTracker."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/watchdog/agent.py parses and imports
# seedgo: no-test-needed(documentation) — that watch_agent, TranscriptScanner and StallTracker carry docstrings
# seedgo: no-test-needed(constant) — STALL_THRESHOLD, LONG_TOOL_THRESHOLD and REFRESH_INTERVAL values

import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from aipass.devpulse.apps.handlers.watchdog import agent as agent_handler
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry


@pytest.fixture(autouse=True)
def _hermetic_watch_store(tmp_path, monkeypatch):
    """Every watch_agent call registers a handle via the DEFAULT store path.

    Module-local, not conftest: the registry pin tests measure default_storage_path itself.
    """
    monkeypatch.setattr(
        watch_registry,
        "default_storage_path",
        lambda: tmp_path / "watchdog_active.json",
    )


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


def _pin_home(monkeypatch, home: Path, caller_cwd: str = "") -> None:
    """Point the resolver's external roots (caller cwd, ~/Projects) at test-owned places.

    Through the environment Path.home() reads (HOME on POSIX, USERPROFILE on Windows).
    """
    monkeypatch.setenv("AIPASS_CALLER_CWD", caller_cwd)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


def _mark_resolved(branch_dir: Path) -> None:
    """Leave a bounce (exit_code 7) in ``branch_dir`` only, so watch_agent's
    ('crashed', 7) answer names the directory the resolver chose."""
    (branch_dir / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
    (branch_dir / ".ai_mail.local" / "last_bounce.json").write_text(json.dumps({"exit_code": 7}), encoding="utf-8")


def _exit_during_first_poll(monkeypatch, side_effect):
    """Run ``side_effect`` (the agent exiting) inside the watch loop's first poll tick.

    A class seam, not time.sleep: the stdlib sleep is process-wide and races the logger's threads.
    """

    def tick_and_exit(self, now):
        side_effect()
        return False

    monkeypatch.setattr(agent_handler.TranscriptScanner, "tick", tick_and_exit)


def test_watch_agent_branch_not_found(monkeypatch, tmp_path):
    """Missing branch returns immediately with timeout state and 'agent not found'."""
    asked: list = []
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: asked.append(a) or None)
    result = agent_handler.watch_agent("@nonexistent", timeout_seconds=5)

    assert asked == [()]
    assert result["woke"] is False
    assert result["agent_state"] == "timeout"
    assert "not found" in result["reason"].lower()
    assert result["agent_id"] == "@nonexistent"
    assert result["exit_code"] is None


def test_resolve_branch_path_finds_projects_citizen(monkeypatch, tmp_path):
    """A projects/* citizen resolves via the in-repo project registry sweep.

    The whole world is pinned to tmp_path, so the real tree can neither save nor break this.
    """
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    branch_dir = tmp_path / "projects" / "baud" / "src" / "baud" / "baud"
    branch_dir.mkdir(parents=True)
    project_registry = {"branches": [{"name": "BAUD", "email": "@baud", "path": "src/baud/baud"}]}
    (tmp_path / "projects" / "baud" / "BAUD_REGISTRY.json").write_text(json.dumps(project_registry), encoding="utf-8")
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    _pin_home(monkeypatch, tmp_path / "nohome")
    _mark_resolved(branch_dir)

    result = agent_handler.watch_agent("@baud", timeout_seconds=5)
    assert (result["agent_state"], result["exit_code"]) == ("crashed", 7)


def test_resolve_branch_path_local_wins_over_projects(monkeypatch, tmp_path):
    """A name in BOTH registries resolves to the main-registry branch — local always wins."""
    local_dir = tmp_path / "src" / "aipass" / "twin"
    local_dir.mkdir(parents=True)
    (tmp_path / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"branches": [{"email": "@twin", "path": str(local_dir)}]}), encoding="utf-8"
    )
    shadow_dir = tmp_path / "projects" / "twin" / "home"
    shadow_dir.mkdir(parents=True)
    (tmp_path / "projects" / "twin" / "TWIN_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "TWIN", "email": "@twin", "path": "home"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    _pin_home(monkeypatch, tmp_path / "nohome")
    _mark_resolved(local_dir)

    result = agent_handler.watch_agent("@twin", timeout_seconds=5)
    assert (result["agent_state"], result["exit_code"]) == ("crashed", 7)


def test_an_unreadable_main_registry_never_hands_over_a_projects_namesake(monkeypatch, tmp_path):
    """The main registry exists but cannot be read: refuse, never watch a namesake."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
    shadow_dir = tmp_path / "projects" / "twin" / "home"
    shadow_dir.mkdir(parents=True)
    (tmp_path / "projects" / "twin" / "TWIN_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "TWIN", "email": "@twin", "path": "home"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    _pin_home(monkeypatch, tmp_path / "nohome")
    _mark_resolved(shadow_dir)

    result = agent_handler.watch_agent("@twin", timeout_seconds=5)
    assert (result["woke"], result["agent_state"], result["exit_code"]) == (False, "timeout", None)
    assert "unreadable" in result["reason"]


def test_an_unreadable_lock_is_a_held_lock(monkeypatch, tmp_path):
    """A lock that exists but cannot be parsed is a dispatch in flight, not an idle agent."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    lock_file.write_text('{"pid": 12', encoding="utf-8")
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    ticks: list = []

    def exit_on_first_tick():
        ticks.append(1)
        lock_file.unlink()

    _exit_during_first_poll(monkeypatch, exit_on_first_tick)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)
    assert ticks == [1]
    assert result["reason"].endswith("(lock removed)")


def test_an_unreadable_tail_is_in_flight_and_never_cached(tmp_path):
    """A transcript that cannot be read is no verdict: in flight now, read again on the next ask."""
    transcript = tmp_path / "a.jsonl"
    transcript.write_text("x\n", encoding="utf-8")
    scanner = agent_handler.TranscriptScanner(tmp_path, now=0.0)
    scanner.tick(1.0)
    seen_ns = os.stat(transcript).st_mtime_ns
    transcript.unlink()
    transcript.mkdir()  # stat still answers, the read raises, on every platform
    assert scanner.last_entry_inflight() is True
    transcript.rmdir()
    transcript.write_text("x\n", encoding="utf-8")
    os.utime(transcript, ns=(seen_ns, seen_ns))  # same cache key: a cached failure would still read in flight
    assert scanner.last_entry_inflight() is False


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

    _exit_during_first_poll(monkeypatch, lambda: lock_file.unlink(missing_ok=True))

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

    _exit_during_first_poll(monkeypatch, lambda: lock_file.unlink(missing_ok=True))

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
        bounce_file.write_text(
            json.dumps({"exit_code": 1, "reason": "test", "timestamp": "2026-04-14T00:00:05"}), encoding="utf-8"
        )
        lock_file.unlink(missing_ok=True)

    _exit_during_first_poll(monkeypatch, crash_exit)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["woke"] is True
    assert result["agent_state"] == "crashed"
    assert result["exit_code"] == 1


def test_watch_agent_timeout(monkeypatch, tmp_path):
    """Lock never removed and PID stays alive -> timeout."""
    branch_path = _build_fake_branch(tmp_path)
    _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: pid == os.getpid())

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
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: pid != 999999)

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
    result = agent_handler.watch_agent("@__definitely_not_a_branch__", timeout_seconds=1)
    assert set(result.keys()) == expected


def _write_jsonl(projects_dir: Path, *lines: dict, name: str = "session.jsonl") -> Path:
    """Write JSONL entries (one dict per line) into a projects dir."""
    projects_dir.mkdir(parents=True, exist_ok=True)
    f = projects_dir / name
    f.write_text("".join(json.dumps(ln) + "\n" for ln in lines), encoding="utf-8")
    return f


def _lines(*entries: dict) -> list[str]:
    """JSON-encode entries as raw transcript lines."""
    return [json.dumps(e) for e in entries]


def _scanner_verdict(projects_dir: Path, lines: list[str]) -> bool:
    """The in-flight verdict a TranscriptScanner gives for one transcript holding ``lines``."""
    projects_dir.mkdir(parents=True)
    (projects_dir / "session.jsonl").write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
    scanner = agent_handler.TranscriptScanner(projects_dir, now=0.0)
    scanner.tick(1.0)
    return scanner.last_entry_inflight()


def test_inflight_from_lines_true_for_assistant_tool_use(tmp_path):
    """Last line = assistant message with a tool_use block → in-flight tool call."""
    assert (
        _scanner_verdict(
            tmp_path / "proj",
            _lines(
                {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "a", "name": "Bash", "input": {}}],
                    },
                },
            ),
        )
        is True
    )


def test_inflight_from_lines_false_for_text_results_malformed_empty(tmp_path):
    """Assistant text-only, a returned tool_result, malformed, and empty all → False."""
    assert (
        _scanner_verdict(
            tmp_path / "text",
            _lines({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "d"}]}}),
        )
        is False
    )
    assert (
        _scanner_verdict(
            tmp_path / "result",
            _lines(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}],
                    },
                }
            ),
        )
        is False
    )
    assert _scanner_verdict(tmp_path / "malformed", ["{not valid json"]) is False
    assert _scanner_verdict(tmp_path / "empty", []) is False


def test_scanner_newest_file_decides_inflight(tmp_path):
    """With multiple JSONLs, the most-recently-modified one decides the verdict."""
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
    s = agent_handler.TranscriptScanner(proj, now=0.0)
    s.tick(1.0)
    assert s.last_entry_inflight() is False  # newest = text-only (both top-level)

    os.utime(old, (3, 3))  # old is now newest and holds the tool_use
    s.tick(2.0)
    assert s.last_entry_inflight() is True


def _stub_scanner(
    tracker,
    tick: "bool | Callable[[], bool]" = False,
    inflight: "bool | Callable[[], bool]" = False,
):
    """Pin a tracker's scanner signals: bools, or zero-arg callables to flip them mid-flight."""
    tick_fn = tick if callable(tick) else (lambda: tick)
    inflight_fn = inflight if callable(inflight) else (lambda: inflight)
    tracker.scanner.tick = lambda now: tick_fn()
    tracker.scanner.last_entry_inflight = lambda: inflight_fn()
    tracker.scanner.refresh = lambda now: None


def test_stalltracker_reports_stall_after_threshold(capsys, tmp_path):
    """No activity past STALL_THRESHOLD → a [watchdog.stall] line on stdout."""
    t = agent_handler.StallTracker("@x", tmp_path / "nope", now=0.0, pid=123)
    _stub_scanner(t, tick=False, inflight=False)

    t.observe(now=60.0)  # below threshold
    assert "[watchdog.stall]" not in capsys.readouterr().out
    assert t.stall_reported is False

    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD)  # at threshold
    assert "[watchdog.stall]" in capsys.readouterr().out
    assert t.stall_reported is True


def test_stalltracker_inflight_tool_prevents_stall(capsys, tmp_path):
    """An in-flight tool call resets the idle timer every tick → never a stall."""
    t = agent_handler.StallTracker("@x", tmp_path / "nope", now=0.0, pid=123)
    _stub_scanner(t, tick=False, inflight=True)

    for now in (120.0, 240.0, 360.0, 480.0):
        t.observe(now=now)

    out = capsys.readouterr().out
    assert "[watchdog.stall]" not in out
    assert t.stall_reported is False


def test_stalltracker_long_tool_advisory(capsys, tmp_path):
    """One tool call held in-flight past LONG_TOOL_THRESHOLD → advisory, not a stall."""
    t = agent_handler.StallTracker("@x", tmp_path / "nope", now=0.0, pid=123)
    _stub_scanner(t, tick=False, inflight=True)

    t.observe(now=0.0)  # first in-flight tick → anchors in_flight_since
    t.observe(now=agent_handler.StallTracker.LONG_TOOL_THRESHOLD)
    out = capsys.readouterr().out
    assert "[watchdog.longtool]" in out
    assert "[watchdog.stall]" not in out
    assert t.long_tool_reported is True


def test_stalltracker_resume_clears_stall(capsys, tmp_path):
    """After a stall, real activity emits [watchdog.resumed] and clears the flag."""
    signals = {"size": False}
    t = agent_handler.StallTracker("@x", tmp_path / "nope", now=0.0, pid=123)
    _stub_scanner(t, tick=lambda: signals["size"], inflight=False)

    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD)  # stall
    assert "[watchdog.stall]" in capsys.readouterr().out
    assert t.stall_reported is True

    signals["size"] = True  # activity resumes
    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD + 5)
    out = capsys.readouterr().out
    assert "[watchdog.resumed]" in out
    assert t.stall_reported is False


def _fake_clock_sleep(agent_module, monkeypatch, lock_file, unlink_at=200.0, step=60.0):
    """Fake clock: each sleep advances `step`; the lock goes once it passes `unlink_at`.

    THREAD-SCOPED: ``time.sleep`` is process-global, and the logger's daemon threads would
    race the clock forward. Only sleeps called FROM the agent module advance it.
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
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: pid == os.getpid())
    ticked: list = []
    asked: list = []
    monkeypatch.setattr(agent_handler.TranscriptScanner, "tick", lambda self, now: ticked.append(now) or False)
    monkeypatch.setattr(agent_handler.TranscriptScanner, "last_entry_inflight", lambda self: asked.append(1) or False)
    # Lock must outlive STALL_THRESHOLD (300s) or the watch completes stall-free.
    _fake_clock_sleep(agent_handler, monkeypatch, lock_file, unlink_at=400.0)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=100000, poll_interval=0.01)
    out = capsys.readouterr().out
    assert "[watchdog.stall]" in out
    assert result["woke"] is True
    # one poll per fake minute, and the threshold poll re-asks after its forced re-walk
    assert ticked == [0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 300.0, 360.0]
    assert len(asked) == len(ticked)


def test_watch_agent_inflight_tool_no_false_stall(monkeypatch, tmp_path, capsys):
    """End-to-end: a long in-flight tool call must NOT surface a stall (#634 part 1)."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(agent_handler, "_pid_alive", lambda pid: pid == os.getpid())
    ticked: list = []
    asked: list = []
    monkeypatch.setattr(agent_handler.TranscriptScanner, "tick", lambda self, now: ticked.append(now) or False)
    monkeypatch.setattr(agent_handler.TranscriptScanner, "last_entry_inflight", lambda self: asked.append(1) or True)
    _fake_clock_sleep(agent_handler, monkeypatch, lock_file)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=100000, poll_interval=0.01)
    out = capsys.readouterr().out
    assert "[watchdog.stall]" not in out
    assert result["woke"] is True
    assert ticked == [0.0, 60.0, 120.0, 180.0]
    assert len(asked) == len(ticked)


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
        encoding="utf-8",
        timeout=60,
    )
    assert dispatch.returncode == 0, f"dispatch failed: {dispatch.stderr}"

    result = agent_handler.watch_agent("@drone", timeout_seconds=300, poll_interval=2.0)
    assert result["woke"] is True
    assert result["agent_state"] in ("completed_replied", "completed_silent", "crashed")


def test_scanner_sees_subagent_transcript_growth(tmp_path):
    """A sub-agent transcript growing under <session>/subagents/ counts as activity: the parent writes nothing."""
    proj = tmp_path / "proj"
    _write_jsonl(proj, {"type": "user", "message": {"role": "user", "content": []}})
    sub = proj / "session-abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.jsonl").write_text('{"type": "assistant"}\n', encoding="utf-8")

    s = agent_handler.TranscriptScanner(proj, now=0.0)
    assert s.tick(1.0) is False
    with (sub / "agent-x.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"type": "assistant"}\n')
    assert s.tick(2.0) is True


def test_scanner_no_basename_collision(tmp_path):
    """Equal basenames in different session dirs are tracked independently (absolute-path keys)."""
    proj = tmp_path / "proj"
    a = proj / "session-a" / "subagents"
    b = proj / "session-b" / "subagents"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "agent-1.jsonl").write_text("x\n", encoding="utf-8")
    (b / "agent-1.jsonl").write_text("longer content\n", encoding="utf-8")

    s = agent_handler.TranscriptScanner(proj, now=0.0)
    assert len(s.sizes) == 2
    assert s.tick(1.0) is False
    with (a / "agent-1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("more\n")
    assert s.tick(2.0) is True


def test_inflight_seen_past_bookkeeping_lines(tmp_path):
    """Bookkeeping lines (type: last-prompt) after the assistant tool_use must not
    mask the in-flight signal — the live false-STALLED had exactly this shape."""
    tool_use = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Task", "input": {}}]},
    }
    bookkeeping = {"type": "last-prompt", "prompt": "..."}
    assert _scanner_verdict(tmp_path / "inflight", _lines(tool_use, bookkeeping)) is True

    # But a returned tool_result behind the same bookkeeping → NOT in-flight.
    tool_result = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]},
    }
    assert _scanner_verdict(tmp_path / "returned", _lines(tool_use, tool_result, bookkeeping)) is False


def test_scanner_newest_file_may_be_subagent(tmp_path):
    """The newest transcript can be a nested sub-agent file — its in-flight
    tool_use counts (the sub-agent working IS the parent working)."""
    proj = tmp_path / "proj"
    parent = _write_jsonl(
        proj,
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
    )
    sub = proj / "session-abc" / "subagents"
    sub.mkdir(parents=True)
    subfile = sub / "agent-x.jsonl"
    subfile.write_text(
        json.dumps(
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}]}}
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(parent, (1, 1))
    os.utime(subfile, (2, 2))
    s = agent_handler.TranscriptScanner(proj, now=0.0)
    s.tick(1.0)
    assert s.last_entry_inflight() is True


def test_scanner_growth_and_steady_state(tmp_path):
    """Seed at construction; growth is one tick's True, steady state is False."""
    proj = tmp_path / "proj"
    f = _write_jsonl(proj, {"type": "user"})
    s = agent_handler.TranscriptScanner(proj, now=0.0)

    assert s.tick(1.0) is False  # nothing changed since the seed pass
    with f.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "assistant"}\n')
    assert s.tick(2.0) is True  # growth
    assert s.tick(3.0) is False  # steady again


def test_scanner_discovers_new_subagent_file_on_refresh(tmp_path):
    """A transcript born between refreshes is invisible to the stat pass but
    counts as activity once the refresh interval re-walks the tree."""
    proj = tmp_path / "proj"
    _write_jsonl(proj, {"type": "user"})
    s = agent_handler.TranscriptScanner(proj, now=0.0)
    assert s.tick(1.0) is False

    sub = proj / "session-abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.jsonl").write_text('{"type": "assistant"}\n', encoding="utf-8")

    assert s.tick(2.0) is False  # not yet discovered — stat pass only
    assert s.tick(2.0 + agent_handler.TranscriptScanner.REFRESH_INTERVAL) is True


@pytest.mark.skipif(
    os.name == "nt" or getattr(os, "geteuid", lambda: -1)() == 0,
    reason="an unlistable directory needs POSIX modes and a non-root reader",
)
def test_scanner_records_a_directory_it_cannot_list_and_keeps_walking(tmp_path):
    """A subtree the walk cannot list is named in ``unreadable``; the rest is still scanned."""
    proj = tmp_path / "proj"
    seen = _write_jsonl(proj, {"type": "user"}, name="seen.jsonl")
    locked = proj / "locked"
    _write_jsonl(locked, {"type": "user"}, name="hidden.jsonl")
    locked.chmod(0o000)
    try:
        s = agent_handler.TranscriptScanner(proj, now=0.0)
    finally:
        locked.chmod(0o700)

    assert str(seen) in s._paths
    assert list(s.unreadable) == [str(locked)]
    assert s.unreadable[str(locked)] != ""


def test_scanner_vanished_file_is_not_activity(tmp_path):
    """Deletion (rollover/cleanup) neither crashes the pass nor reads as activity."""
    proj = tmp_path / "proj"
    a = _write_jsonl(proj, {"type": "user"}, name="a.jsonl")
    b = _write_jsonl(proj, {"type": "user"}, name="b.jsonl")
    s = agent_handler.TranscriptScanner(proj, now=0.0)

    a.unlink()
    assert s.tick(1.0) is False
    with b.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "assistant"}\n')
    assert s.tick(2.0) is True  # survivors still tracked


def test_scanner_inflight_verdict_cached_until_file_changes(tmp_path):
    """The tail parse runs only when the newest file's (size, mtime) changed; silence reuses the verdict."""
    proj = tmp_path / "proj"
    inflight = {"message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}]}}
    done = {"message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}}
    transcript = _write_jsonl(proj, inflight)
    s = agent_handler.TranscriptScanner(proj, now=0.0)
    s.tick(1.0)
    assert s.last_entry_inflight() is True

    seen_ns = os.stat(transcript).st_mtime_ns
    transcript.write_text(json.dumps(done).ljust(len(json.dumps(inflight))) + "\n", encoding="utf-8")
    os.utime(transcript, ns=(seen_ns, seen_ns))  # same size, same mtime: the key is unchanged
    for now in (2.0, 3.0, 4.0):
        s.tick(now)
        assert s.last_entry_inflight() is True  # unchanged key → cached verdict, the done line unread

    _write_jsonl(proj, done)
    s.tick(5.0)
    assert s.last_entry_inflight() is False  # change → re-read → new verdict


def test_scanner_parent_inflight_covers_composing_subagent(tmp_path):
    """Sub-agent newest but idle-looking (composing writes nothing) while the
    parent's top-level transcript holds the in-flight Agent tool_use → the
    parent candidate keeps this out of STALLED (todo #126)."""
    proj = tmp_path / "proj"
    parent = _write_jsonl(
        proj,
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Agent"}]}},
        name="parent.jsonl",
    )
    sub = proj / "session-abc" / "subagents"
    sub.mkdir(parents=True)
    subfile = sub / "agent-x.jsonl"
    subfile.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(parent, (1, 1))
    os.utime(subfile, (2, 2))  # nested file is newest; its last entry is NOT in-flight

    s = agent_handler.TranscriptScanner(proj, now=0.0)
    s.tick(1.0)
    assert s.last_entry_inflight() is True


def test_stall_confirm_refresh_suppresses_false_stall(tmp_path, monkeypatch, capsys):
    """At the stall threshold the tracker forces a re-walk — a transcript born
    since the last refresh suppresses the would-be stall."""
    monkeypatch.setattr(agent_handler.TranscriptScanner, "REFRESH_INTERVAL", 10_000.0)
    proj = tmp_path / "proj"
    _write_jsonl(proj, {"type": "user"})
    t = agent_handler.StallTracker("@x", proj, now=0.0, pid=1)
    t.observe(now=1.0)

    sub = proj / "session-abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-x.jsonl").write_text('{"type": "assistant"}\n', encoding="utf-8")

    t.observe(now=agent_handler.StallTracker.STALL_THRESHOLD + 1.0)
    assert "[watchdog.stall]" not in capsys.readouterr().out
    assert t.stall_reported is False


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
        encoding="utf-8",
        timeout=60,
    )

    result = agent_handler.watch_agent("@drone", timeout_seconds=2, poll_interval=0.5)
    assert result["agent_state"] == "timeout"


def _case_insensitive_glob(monkeypatch):
    """Emulate NTFS's case-folded glob, so agent.py's exact-case filter is provably load-bearing from Linux."""
    real_glob = agent_handler.Path.glob

    def widened(self, pattern):
        if pattern.endswith("_REGISTRY.json"):
            folded = pattern[: -len("_REGISTRY.json")] + "_registry.json"
            yield from real_glob(self, folded)
        yield from real_glob(self, pattern)

    monkeypatch.setattr(agent_handler.Path, "glob", widened)


def test_lowercase_counter_never_answers_a_projects_resolve(monkeypatch, tmp_path):
    """A lowercase *_registry.json is never a trust anchor; the decoy sorts FIRST, so without the check it wins."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    wrong_dir = tmp_path / "projects" / "aaa" / "wrong"
    wrong_dir.mkdir(parents=True)
    (tmp_path / "projects" / "aaa" / "aaa_registry.json").write_text(
        json.dumps({"branches": [{"name": "AAA", "email": "@baud", "path": "wrong"}]}),
        encoding="utf-8",
    )
    right_dir = tmp_path / "projects" / "baud" / "home"
    right_dir.mkdir(parents=True)
    (tmp_path / "projects" / "baud" / "BAUD_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "BAUD", "email": "@baud", "path": "home"}]}),
        encoding="utf-8",
    )

    _case_insensitive_glob(monkeypatch)
    widened = [p.name for p in (tmp_path / "projects").glob("*/*_REGISTRY.json")]
    assert "aaa_registry.json" in widened, "emulation is blind — this test proves nothing"

    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    _pin_home(monkeypatch, tmp_path / "nohome")
    _mark_resolved(right_dir)

    result = agent_handler.watch_agent("@baud", timeout_seconds=5)
    assert (result["agent_state"], result["exit_code"]) == ("crashed", 7)


def test_lowercase_counter_never_answers_an_external_resolve(monkeypatch, tmp_path):
    """The external-roots walk: a lowercase counter must not resolve a branch at all."""
    ext = tmp_path / "ext"
    (ext / "somewhere").mkdir(parents=True)
    (ext / "ext_registry.json").write_text(
        json.dumps({"branches": [{"name": "EXT", "email": "@ext", "path": "somewhere"}]}),
        encoding="utf-8",
    )

    _case_insensitive_glob(monkeypatch)
    widened = [p.name for p in ext.glob("*_REGISTRY.json")]
    assert "ext_registry.json" in widened, "emulation is blind — this test proves nothing"

    asked: list = []
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: asked.append(a) or None)
    _pin_home(monkeypatch, tmp_path / "nohome", caller_cwd=str(ext))

    result = agent_handler.watch_agent("@ext", timeout_seconds=5)
    assert result["reason"] == "agent not found"
    assert asked == [()]


# The zombie rule lives once, in registry.py; these pretend darwin here.


def _watch_this_pid_as_darwin(monkeypatch, pretend_platform, tmp_path, ps_state: str) -> dict:
    """watch_agent on a lock holding THIS pid, with agent and registry both seeing darwin."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    pretend_platform(agent_handler, "darwin")
    pretend_platform(watch_registry, "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=ps_state, stderr=""),
    )
    _exit_during_first_poll(monkeypatch, lambda: lock_file.unlink(missing_ok=True))
    return agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)


def test_a_zombie_agent_is_not_alive_off_linux(monkeypatch, pretend_platform, tmp_path):
    """This pid answers os.kill(pid, 0); only the ps state can call it a corpse."""
    result = _watch_this_pid_as_darwin(monkeypatch, pretend_platform, tmp_path, "Z+\n")
    assert "dead, lock still present" in result["reason"]


def test_a_live_agent_off_linux_is_still_alive(monkeypatch, pretend_platform, tmp_path):
    """The portable probe must not bury a working agent: the watch runs on until the lock goes."""
    result = _watch_this_pid_as_darwin(monkeypatch, pretend_platform, tmp_path, "S+\n")
    assert result["reason"].endswith("(lock removed)")


def test_the_zombie_rule_is_not_duplicated_in_this_module():
    """One implementation, in registry.py: a drifted private copy lets a dead watch pass for live. Runs everywhere."""
    assert not hasattr(agent_handler, "_is_zombie_linux")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows has no zombie state, so the rule is not duplicated there — it is ABSENT by design: "
    "_pid_alive answers from OpenProcess/GetExitCodeProcess and never asks registry.is_zombie at all. "
    "A call-through pin cannot see a call that correctly never happens. The no-second-copy half above "
    "still runs on this host.",
)
def test_pid_alive_asks_the_registry_for_the_zombie_rule(monkeypatch, tmp_path):
    """The single implementation is actually REACHED: the registry's zombie verdict ends the watch as a crash."""
    branch_path = _build_fake_branch(tmp_path)
    _write_lock(branch_path, pid=os.getpid())
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    calls: list = []
    monkeypatch.setattr(watch_registry, "is_zombie", lambda pid: calls.append(pid) or True)

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=60, poll_interval=0.01)
    assert calls == [os.getpid()]
    assert result["agent_state"] == "crashed"


# Verbatim ~/.codex/sessions rollout lines.
_CODEX_RESPONSE_ITEM = (
    '{"timestamp":"2026-05-24T20:51:19.010Z","type":"response_item","payload":{"type":"function_call",'
    '"name":"exec_command","arguments":"{\\"cmd\\":\\"drone --help\\",\\"yield_time_ms\\":10000,'
    '\\"max_output_tokens\\":12000}","call_id":"call_wADEomvKq47K13N4PdSqvbB2"}}'
)
_CODEX_TASK_COMPLETE = (
    '{"timestamp":"2026-05-15T23:21:07.369Z","type":"event_msg","payload":{"type":"task_complete",'
    '"turn_id":"019e2df1-7da4-76d3-8e62-174023da0df3","last_agent_message":"NO","completed_at":1778887267,'
    '"duration_ms":5749,"time_to_first_token_ms":5531}}'
)
_CODEX_TURN_ABORTED = (
    '{"timestamp":"2026-09-20T06:40:52.909Z","ordinal":142,"type":"event_msg","payload":{"type":"turn_aborted",'
    '"turn_id":"01a0bd8a-9a6a-7d00-a6e8-9701801884c4","reason":"interrupted","started_at":1789886372,'
    '"completed_at":1789886452,"duration_ms":80448}}'
)


def _write_pointer(branch: Path, provider: str | None, session_id: str = "thread-1") -> None:
    data = {"session_id": session_id, "cwd": str(branch)}
    if provider is not None:
        data["provider"] = provider
    (branch / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
    (branch / ".ai_mail.local" / "session.json").write_text(json.dumps(data), encoding="utf-8")


def test_scanner_follows_the_branch_pointer_between_codex_and_claude(tmp_path, monkeypatch):
    """A codex pointer watches its one rollout; a claude pointer or none walks the projects dir."""
    branch = tmp_path / "branch"
    branch.mkdir()
    proj = tmp_path / "proj"
    claude_file = _write_jsonl(proj, {"message": {"role": "assistant", "content": [{"type": "tool_use"}]}})
    rollout = tmp_path / "rollout-2026-10-26T09-59-59-thread-1.jsonl"
    rollout.write_text(_CODEX_RESPONSE_ITEM + "\n", encoding="utf-8")
    monkeypatch.setattr(agent_handler, "codex_thread_file", lambda tid: rollout if tid == "thread-1" else None)

    _write_pointer(branch, "codex")
    s = agent_handler.TranscriptScanner(proj, now=0.0, branch_path=branch)
    assert s.provider == "codex" and s._paths == [str(rollout)]
    assert s.last_entry_inflight() is True

    with rollout.open("a", encoding="utf-8") as fh:
        fh.write(_CODEX_TASK_COMPLETE + "\n")
    assert s.tick(1.0) is True
    assert s.last_entry_inflight() is False

    _write_pointer(branch, "claude")
    s.refresh(2.0)
    assert s.provider == "claude" and s._paths == [str(claude_file)]

    (branch / ".ai_mail.local" / "session.json").unlink()
    s.refresh(3.0)
    assert s.provider == "claude" and s._paths == [str(claude_file)]


@pytest.mark.parametrize(
    ("tail", "inflight"),
    [
        ([_CODEX_RESPONSE_ITEM], True),
        ([_CODEX_RESPONSE_ITEM, _CODEX_TASK_COMPLETE], False),
        ([_CODEX_RESPONSE_ITEM, _CODEX_TURN_ABORTED], False),
        ([_CODEX_RESPONSE_ITEM, _CODEX_TASK_COMPLETE[:40]], True),
    ],
    ids=["turn-open", "task-complete", "turn-aborted", "torn-tail"],
)
def test_codex_rollout_tail_decides_inflight(tmp_path, monkeypatch, tail, inflight):
    """A Codex turn is in flight until an event_msg ends it; a torn last line is Codex mid-write."""
    branch = tmp_path / "branch"
    branch.mkdir()
    rollout = tmp_path / "rollout-thread-1.jsonl"
    rollout.write_text("\n".join(tail) + "\n", encoding="utf-8")
    monkeypatch.setattr(agent_handler, "codex_thread_file", lambda tid: rollout)
    _write_pointer(branch, "codex")

    s = agent_handler.TranscriptScanner(tmp_path / "proj", now=0.0, branch_path=branch)

    assert s.last_entry_inflight() is inflight


def _opencode_store(path: Path, session_id: str, updated: int, idle: int | None, outcome: str | None) -> None:
    """One session_v2 row in a scratch OpenCode store, the three columns the scanner reads."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "create table if not exists session_v2 "
            "(id text primary key, time_updated int, time_idle int, idle_outcome text)"
        )
        conn.execute(
            "insert or replace into session_v2 values (?, ?, ?, ?)",
            (session_id, updated, idle, outcome),
        )


def test_opencode_pointer_watches_the_session_row(tmp_path, monkeypatch):
    """An opencode pointer watches no file: the row's time_updated is growth, idle after update is done."""
    branch = tmp_path / "branch"
    branch.mkdir()
    store = tmp_path / "opencode.db"
    _opencode_store(store, "ses_1", updated=1000, idle=None, outcome=None)
    monkeypatch.setattr(agent_handler, "opencode_db", lambda: store)
    _write_pointer(branch, "opencode", "ses_1")

    s = agent_handler.TranscriptScanner(tmp_path / "proj", now=0.0, branch_path=branch)
    assert s.provider == "opencode" and s._paths == []
    assert s.last_entry_inflight() is True  # never idled
    assert s.tick(1.0) is False  # nothing changed since the watch started

    _opencode_store(store, "ses_1", updated=2000, idle=1500, outcome="succeeded")
    assert s.tick(2.0) is True  # time_updated grew
    assert s.last_entry_inflight() is True  # idled before its last update: a turn is running

    _opencode_store(store, "ses_1", updated=2000, idle=2001, outcome="succeeded")
    assert s.tick(3.0) is False
    assert s.last_entry_inflight() is False

    _write_pointer(branch, "opencode", "ses_missing")
    s.refresh(4.0)
    assert s.last_entry_inflight() is False  # no row is no agent, not a stall

    store.write_text("not a database", encoding="utf-8")
    assert s.last_entry_inflight() is True  # an unreadable store counts as in flight


@pytest.mark.parametrize(
    ("bounce_ts", "state"), [("2026-04-01T09:00:00", "completed_silent"), ("2026-04-14T00:00:00", "crashed")]
)
def test_bounce_older_than_the_dispatch_is_not_a_crash(monkeypatch, tmp_path, bounce_ts, state):
    """Nothing deletes last_bounce.json; a past run's file must not mark this clean run crashed."""
    branch_path = _build_fake_branch(tmp_path)
    lock_file = _write_lock(branch_path, pid=os.getpid())
    (branch_path / ".ai_mail.local" / "last_bounce.json").write_text(
        json.dumps({"timestamp": bounce_ts}), encoding="utf-8"
    )
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)
    _exit_during_first_poll(monkeypatch, lambda: lock_file.unlink(missing_ok=True))

    result = agent_handler.watch_agent("@fakebranch", timeout_seconds=5, poll_interval=0.01)

    assert result["agent_state"] == state


def test_null_email_row_does_not_stop_the_search(monkeypatch, tmp_path):
    """A row with "email": null is skipped by email and still matched by name."""
    (tmp_path / "b" / ".ai_mail.local").mkdir(parents=True)
    rows = {"branches": [{"name": "B", "email": None, "path": "b"}]}
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(agent_handler, "_find_repo_root", lambda *a, **kw: tmp_path)

    result = agent_handler.watch_agent("@b", timeout_seconds=1, poll_interval=0.01)

    assert result["reason"] != "agent not found" and result["woke"] is True
