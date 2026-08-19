# =================== AIPass ====================
# Name: test_watchdog_wire.py
# Description: Tests for the watchdog wire handler (DPLAN-0308 round 2)
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""Tests for arm_wire + the daemon face of watch_baseline.

The failure these pin was witnessed live on 2026-08-19: a session-wired
watcher kept detecting after the session id churned, delivering COMPLETE lines
into a dead session's task file. The wire architecture must (a) never lose an
event across the unwired window (replay), (b) take over a wire soldered to
another session, (c) never SIGTERM a recycled pid, and (d) die loudly when the
detection daemon dies — silence must never mean covered.

Every test passes ``repo_root``/``storage_path`` explicitly and drives loops by
replacing the handler's own ``_sleep`` — no test waits a real tick.
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import baseline
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry
from aipass.devpulse.apps.handlers.watchdog import wire


# Same convention as test_watchdog_baseline.py: a pid that cannot be running,
# re-asserted where used so a machine where it IS alive fails as
# fixture-broken instead of quietly passing for the wrong reason.
DEAD_PID = 999999


@pytest.fixture(autouse=True)
def _no_json_writes():
    """Keep the suite off devpulse's real json store."""
    with patch("aipass.devpulse.apps.handlers.json.json_handler.log_operation", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _private_heartbeat(tmp_path, monkeypatch):
    """Point the heartbeat at a per-test file — never the real /tmp signal."""
    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(baseline, "HEARTBEAT_FILE", hb)
    return hb


@pytest.fixture(autouse=True)
def _no_signal_rebind(monkeypatch):
    """arm_wire installs a SIGTERM handler for clean deregistration; inside
    pytest that rebinding must not leak past the test."""
    monkeypatch.setattr(wire.signal, "signal", lambda *a, **kw: None)


def _repo(tmp_path: Path) -> Path:
    """A minimal repo root: registry file is all the wire itself needs."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    return root


def _store(tmp_path: Path) -> Path:
    return tmp_path / "trinity" / "watchdog_active.json"


def _write_events(root: Path, records: list[dict], tail: str = "") -> Path:
    """Write the daemon's events JSONL; ``tail`` appends raw bytes (torn line)."""
    events = baseline.events_file_for(root)
    events.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r) + "\n" for r in records) + tail
    events.write_text(body, encoding="utf-8")
    return events


def _event(branch: str, subject: str = "job done") -> dict:
    return {
        "branch": branch,
        "subject": subject,
        "age": 12,
        "bounce": False,
        "state": "completed",
        "pid": None,
        "epoch": time.time(),
        "iso": datetime.now().isoformat(timespec="seconds"),
    }


def _plant_entry(store: Path, wtype: str, pid: int, metadata: dict | None = None, handle: str | None = None) -> str:
    """Write a registry entry with an ARBITRARY pid — the shape register()
    can't produce (it stamps os.getpid), which is exactly what a leftover from
    another process looks like."""
    store.parent.mkdir(parents=True, exist_ok=True)
    handle = handle or f"{wtype}-{pid:06x}"
    try:
        doc = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {"version": 1, "watches": []}
    doc["watches"].append(
        {
            "handle": handle,
            "type": wtype,
            "started_at": datetime.now().isoformat(),
            "started_epoch": time.time(),
            "pid": pid,
            "metadata": metadata or {},
        }
    )
    store.write_text(json.dumps(doc), encoding="utf-8")
    return handle


def _live_daemon(store: Path) -> str:
    """A daemon entry whose pid is THIS test process — alive by construction."""
    return _plant_entry(store, "baseline", os.getpid(), {"role": "daemon", "scope": "all citizens"})


def _fresh_heartbeat(hb: Path) -> None:
    hb.touch()


def _entries(store: Path) -> list[dict]:
    try:
        return json.loads(store.read_text(encoding="utf-8"))["watches"]
    except FileNotFoundError:
        return []


def _spawn_named(name: str) -> subprocess.Popen:
    """A live process whose cmdline carries ``name`` — argv[0] via exec -a."""
    return subprocess.Popen(
        ["bash", "-c", f"exec -a {name} sleep 30"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Replay — the whole point: churn delays events, never loses them
# ─────────────────────────────────────────────────────────────────────────────


def test_replay_delivers_missed_events_and_advances_cursor(tmp_path, capsys, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    events = _write_events(root, [_event("api"), _event("baud")])

    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert out.count("MISSED COMPLETE") == 2
    assert "@api" in out and "@baud" in out
    assert "no wire was up" in out
    assert result["replayed"] == 2
    cursor = json.loads(baseline.cursor_file_for(root).read_text(encoding="utf-8"))
    assert cursor["offset"] == events.stat().st_size


def test_replay_starts_where_the_cursor_left_off(tmp_path, capsys, _private_heartbeat):
    """Already-delivered events must not repeat on the next arm."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    delivered_already = _event("api")
    first = json.dumps(delivered_already) + "\n"
    _write_events(root, [delivered_already, _event("prax")])
    wire._write_cursor(baseline.cursor_file_for(root), len(first.encode()))

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert "@prax" in out
    assert "@api" not in out


def test_once_returns_after_replay(tmp_path, capsys, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    _write_events(root, [_event("api")])

    result = wire.arm_wire(repo_root=root, storage_path=store, once=True, wire_poll=0)

    assert result["state"] == "completed"
    assert result["delivered"] == 1
    assert "MISSED COMPLETE @api" in capsys.readouterr().out


def test_live_follow_delivers_appended_event(tmp_path, capsys, monkeypatch, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    events = _write_events(root, [])

    appended = {"done": False}

    def append_event(_seconds):
        if appended["done"]:
            return
        appended["done"] = True
        with open(events, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_event("trigger", "third door closed")) + "\n")

    monkeypatch.setattr(wire, "_sleep", append_event)
    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=3, wire_poll=0)

    out = capsys.readouterr().out
    assert "COMPLETE @trigger" in out
    assert "MISSED" not in out
    assert result["delivered"] == 1


def test_torn_tail_line_is_not_consumed(tmp_path, _private_heartbeat):
    """A write still in flight stays for the next tick — never half-delivered."""
    root = _repo(tmp_path)
    record = _event("api")
    complete = json.dumps(record) + "\n"
    _write_events(root, [record], tail='{"branch":"ba')

    records, offset = wire._drain_events(baseline.events_file_for(root), 0)

    assert [r["branch"] for r in records] == ["api"]
    assert offset == len(complete.encode())


def test_junk_line_is_skipped_and_cursor_moves_past_it(tmp_path, capsys, _private_heartbeat):
    """Unparseable-but-complete lines must not wedge delivery at the same offset."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    events = baseline.events_file_for(root)
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text("this is not json\n" + json.dumps(_event("memory")) + "\n", encoding="utf-8")

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    captured = capsys.readouterr()
    assert "COMPLETE @memory" in captured.out
    assert "skipped an unparseable event line" in captured.err
    cursor = json.loads(baseline.cursor_file_for(root).read_text(encoding="utf-8"))
    assert cursor["offset"] == events.stat().st_size


def test_shrunk_events_file_replays_from_top(tmp_path, capsys, _private_heartbeat):
    """Truncation/replacement = duplicates over silence, said out loud."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    _write_events(root, [_event("hooks")])
    wire._write_cursor(baseline.cursor_file_for(root), 10_000)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    captured = capsys.readouterr()
    assert "COMPLETE @hooks" in captured.out
    assert "replaying from the top" in captured.err


def test_corrupt_cursor_resets_to_zero(tmp_path, _private_heartbeat):
    root = _repo(tmp_path)
    cursor = baseline.cursor_file_for(root)
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("{broken", encoding="utf-8")

    assert wire._read_cursor(cursor) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Daemon lifecycle — ensure, spawn, and die loudly
# ─────────────────────────────────────────────────────────────────────────────


def test_arm_spawns_daemon_when_none_lives(tmp_path, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _fresh_heartbeat(_private_heartbeat)
    calls = []

    def fake_spawn(devpulse_dir, daemon_log):
        calls.append((devpulse_dir, daemon_log))
        _live_daemon(store)

    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0, spawn_fn=fake_spawn)

    assert len(calls) == 1
    assert result["state"] == "stopped"


def test_arm_dies_loudly_when_spawn_never_registers(tmp_path, capsys, monkeypatch, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    monkeypatch.setattr(wire, "_DAEMON_SPAWN_WAIT_SECONDS", 0.0)

    with pytest.raises(SystemExit) as exc_info:
        wire.arm_wire(repo_root=root, storage_path=store, spawn_fn=lambda *a: None)

    assert exc_info.value.code == 1
    assert "BASELINE DEAD" in capsys.readouterr().out


def test_wire_dies_loudly_when_daemon_pid_dies(tmp_path, capsys, _private_heartbeat):
    """The wire watches the daemon back — a dead detector must never look covered."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _fresh_heartbeat(_private_heartbeat)
    victim = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL)
    _plant_entry(store, "baseline", victim.pid, {"role": "daemon"})
    victim.terminate()
    victim.wait(timeout=5)

    # The sweep buries the dead daemon, so hand arm a spawn that "revives" it
    # with a pid that dies between arm and the first follow tick.
    revived = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL)

    def fake_spawn(*_a):
        _plant_entry(store, "baseline", revived.pid, {"role": "daemon"})

    revived_killed = {"done": False}

    def kill_before_tick(_seconds):
        if not revived_killed["done"]:
            revived.terminate()
            revived.wait(timeout=5)
            revived_killed["done"] = True

    with patch.object(wire, "_sleep", kill_before_tick):
        # First tick sees the daemon alive; the scripted sleep kills it; the
        # second tick must exit loudly.
        with pytest.raises(SystemExit) as exc_info:
            wire.arm_wire(repo_root=root, storage_path=store, spawn_fn=fake_spawn, max_ticks=10, wire_poll=0)

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "daemon gone" in out
    assert "re-arm" in out


def test_wire_dies_loudly_when_heartbeat_goes_stale(tmp_path, capsys, _private_heartbeat):
    """A live pid with a stale heartbeat is a HUNG detector — the worse corpse."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    stale = time.time() - (baseline.HEARTBEAT_STALE_SECONDS + 60)
    _private_heartbeat.touch()
    os.utime(_private_heartbeat, (stale, stale))

    with pytest.raises(SystemExit) as exc_info:
        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=5, wire_poll=0)

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "hung" in out


def test_missing_heartbeat_with_live_pid_is_grace_not_death(tmp_path, _private_heartbeat):
    """A fresh daemon that hasn't completed its first tick is not a corpse."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    assert not _private_heartbeat.exists()

    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=2, wire_poll=0)

    assert result["state"] == "stopped"


# ─────────────────────────────────────────────────────────────────────────────
# Takeover + migration — one wire, the right wire, and never an innocent pid
# ─────────────────────────────────────────────────────────────────────────────


def test_takeover_kills_wire_soldered_to_another_session(tmp_path, capsys, monkeypatch, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    stale = _spawn_named("watchdog-wire-stale")
    try:
        _plant_entry(store, "baseline_wire", stale.pid, {"session": "dead-session"})
        # My stdout is pytest's pipe (no session); theirs is a devnull (no
        # session either) — force distinct session dirs so the comparison is
        # exercised, not short-circuited by two Nones.
        mine = tmp_path / "sess-mine" / "tasks" / "a.output"
        theirs = tmp_path / "sess-theirs" / "tasks" / "b.output"
        monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: mine if pid is None else theirs)

        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

        assert "took over stale wire" in capsys.readouterr().err
        stale.wait(timeout=5)
        assert stale.returncode is not None
        leftover = [w for w in _entries(store) if w["type"] == "baseline_wire" and w["pid"] == stale.pid]
        assert leftover == []
    finally:
        if stale.poll() is None:
            stale.kill()


def test_same_session_wire_is_taken_over_too(tmp_path, capsys, monkeypatch, _private_heartbeat):
    """No 'already wired' answer exists: a wire writing into the CURRENT
    session dir proves a writer, never a listener (the 10:55 wire kept writing
    into the live session dir after the resume killed its monitor). The arm
    happening right now is the only wire known to have ears."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    peer = _spawn_named("watchdog-wire-peer")
    try:
        _plant_entry(store, "baseline_wire", peer.pid, {"session": "same-session"})
        shared = tmp_path / "same-session" / "tasks"
        monkeypatch.setattr(
            wire,
            "_stdout_target",
            lambda pid=None: shared / ("mine.output" if pid is None else "theirs.output"),
        )

        result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

        assert result["state"] == "stopped"
        assert "took over stale wire" in capsys.readouterr().err
        peer.wait(timeout=5)
        assert peer.returncode is not None, "the old wire must die — only the newest arm has ears"
        leftover = [w for w in _entries(store) if w["type"] == "baseline_wire" and w["pid"] == peer.pid]
        assert leftover == []
    finally:
        if peer.poll() is None:
            peer.kill()


def test_recycled_pid_is_never_signalled(tmp_path, capsys, _private_heartbeat):
    """A registry pid whose cmdline is not a watchdog gets buried, not shot."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    innocent = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL)
    try:
        _plant_entry(store, "baseline_wire", innocent.pid, {"session": "other"})

        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

        assert innocent.poll() is None, "recycled pid must be left alone"
        assert "process left alone" in capsys.readouterr().err
        leftover = [w for w in _entries(store) if w.get("pid") == innocent.pid]
        assert leftover == []
    finally:
        innocent.kill()


def test_legacy_single_process_watcher_is_migrated(tmp_path, capsys, _private_heartbeat):
    """A live round-1 baseline (no role=daemon) is the orphan species — killed
    and replaced, said out loud."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _fresh_heartbeat(_private_heartbeat)
    legacy = _spawn_named("watchdog-legacy")
    try:
        _plant_entry(store, "baseline", legacy.pid, {"scope": "all citizens"})

        def fake_spawn(*_a):
            _live_daemon(store)

        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0, spawn_fn=fake_spawn)

        assert "migrated legacy single-process watcher" in capsys.readouterr().err
        legacy.wait(timeout=5)
        assert legacy.returncode is not None
    finally:
        if legacy.poll() is None:
            legacy.kill()


def test_dead_entries_are_buried_on_arm(tmp_path, capsys, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    assert not watch_registry.is_pid_alive(DEAD_PID), "fixture broken: DEAD_PID is alive on this machine"
    _plant_entry(store, "baseline_wire", DEAD_PID, {"session": "gone"})
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert "buried dead" in capsys.readouterr().err
    assert [w for w in _entries(store) if w.get("pid") == DEAD_PID] == []


def test_wire_deregisters_itself_on_exit(tmp_path, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert [w for w in _entries(store) if w["type"] == "baseline_wire"] == []


def test_continuous_arm_under_run_in_background_is_refused(tmp_path, capsys, monkeypatch, _private_heartbeat):
    """Monitor stdout is a socket; run_in_background stdout is a REAL FILE in a
    tasks dir (measured live 2026-08-19). A continuous wire behind that file
    never notifies — the 12:34 failure — so the arm refuses before touching
    anything (no takeover, no daemon spawn, no registration)."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    peer = _spawn_named("watchdog-wire-good")
    try:
        _plant_entry(store, "baseline_wire", peer.pid, {"session": "healthy"})
        bg_file = tmp_path / "some-session" / "tasks" / "b0l5zsqp7.output"
        bg_file.parent.mkdir(parents=True)
        bg_file.touch()
        monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: bg_file if pid is None else None)

        with pytest.raises(SystemExit) as exc_info:
            wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "run_in_background" in out
        assert "Monitor" in out
        assert peer.poll() is None, "a refused arm must not have taken over the existing wire"
    finally:
        peer.kill()


def test_once_arm_under_run_in_background_is_allowed(tmp_path, capsys, monkeypatch, _private_heartbeat):
    """--once exits on first delivery, so bg-Bash DOES notify — stays legal."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    _write_events(root, [_event("api")])
    bg_file = tmp_path / "some-session" / "tasks" / "b0l5zsqp7.output"
    bg_file.parent.mkdir(parents=True)
    bg_file.touch()
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: bg_file if pid is None else None)

    result = wire.arm_wire(repo_root=root, storage_path=store, once=True, wire_poll=0)

    assert result["state"] == "completed"
    assert "MISSED COMPLETE @api" in capsys.readouterr().out


def test_wire_records_conversation_id_from_env(tmp_path, monkeypatch, _private_heartbeat):
    """metadata.session is the CONVERSATION id (what the statusline receives),
    never the tasks-dir id — the two namespaces measured 2026-08-19 differ."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "conv-abc-123")
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: tmp_path / "runtime-xyz" / "tasks" / "t.output")
    seen = {}
    real_register = watch_registry.register

    def spy_register(watch_type, metadata=None, storage_path=None):
        if watch_type == "baseline_wire":
            seen.update(metadata or {})
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(wire._registry, "register", spy_register)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["session"] == "conv-abc-123"
    assert seen["tasks_dir"] == "runtime-xyz"


def test_wire_falls_back_to_tasks_dir_without_env(tmp_path, monkeypatch, _private_heartbeat):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _live_daemon(store)
    _fresh_heartbeat(_private_heartbeat)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: tmp_path / "runtime-xyz" / "tasks" / "t.output")
    seen = {}
    real_register = watch_registry.register

    def spy_register(watch_type, metadata=None, storage_path=None):
        if watch_type == "baseline_wire":
            seen.update(metadata or {})
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(wire._registry, "register", spy_register)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["session"] == "runtime-xyz"


# ─────────────────────────────────────────────────────────────────────────────
# Wire identity primitives
# ─────────────────────────────────────────────────────────────────────────────


def test_session_dir_requires_tasks_parent(tmp_path):
    inside = tmp_path / "abc-session" / "tasks" / "x.output"
    assert wire._session_dir_of(inside) == tmp_path / "abc-session"
    assert wire._session_dir_of(tmp_path / "abc-session" / "x.output") is None
    assert wire._session_dir_of(None) is None


def test_stdout_target_reads_proc_truth(tmp_path):
    """The identity primitive against a real process with a known stdout."""
    target = tmp_path / "known.output"
    with open(target, "wb") as fh:
        proc = subprocess.Popen(["sleep", "5"], stdout=fh)
    try:
        assert wire._stdout_target(proc.pid) == target
    finally:
        proc.kill()


def test_dead_pid_has_no_stdout_target():
    assert not watch_registry.is_pid_alive(DEAD_PID)
    assert wire._stdout_target(DEAD_PID) is None


# ─────────────────────────────────────────────────────────────────────────────
# The daemon face of watch_baseline
# ─────────────────────────────────────────────────────────────────────────────


def _daemon_repo(tmp_path: Path) -> Path:
    """A repo with one citizen mid-dispatch, for daemon-mode runs."""
    root = tmp_path / "repo"
    branch = root / "alpha"
    (branch / ".ai_mail.local").mkdir(parents=True)
    (root / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "ALPHA", "email": "@alpha", "path": str(branch)}]}),
        encoding="utf-8",
    )
    return root


def test_daemon_mode_appends_event_and_heartbeats(tmp_path, monkeypatch, _private_heartbeat):
    root = _daemon_repo(tmp_path)
    store = _store(tmp_path)
    branch = root / "alpha"
    lock = branch / ".ai_mail.local" / ".dispatch.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "timestamp": datetime.now().isoformat(), "subject": "alpha run"}),
        encoding="utf-8",
    )

    def steps(_seconds):
        if lock.exists():
            lock.unlink()

    monkeypatch.setattr(baseline, "_sleep", steps)
    result = baseline.watch_baseline(daemon=True, repo_root=root, storage_path=store, max_ticks=3)

    assert result["completions"] == 1
    assert _private_heartbeat.exists(), "daemon must heartbeat every tick"
    events = baseline.events_file_for(root)
    lines = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["branch"] == "alpha"
    assert "epoch" in lines[0] and "iso" in lines[0]


def test_daemon_mode_registers_with_daemon_role(tmp_path, monkeypatch, _private_heartbeat):
    root = _daemon_repo(tmp_path)
    store = _store(tmp_path)
    seen = {}

    real_register = watch_registry.register

    def spy_register(watch_type, metadata=None, storage_path=None):
        seen["metadata"] = metadata
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(baseline._registry, "register", spy_register)
    baseline.watch_baseline(daemon=True, repo_root=root, storage_path=store, max_ticks=1)

    assert seen["metadata"]["role"] == "daemon"


def test_non_daemon_mode_registers_without_role(tmp_path, monkeypatch, _private_heartbeat):
    """The role key IS the migration discriminator — its absence must stay
    exactly what a legacy watcher looks like."""
    root = _daemon_repo(tmp_path)
    store = _store(tmp_path)
    seen = {}

    real_register = watch_registry.register

    def spy_register(watch_type, metadata=None, storage_path=None):
        seen["metadata"] = metadata
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(baseline._registry, "register", spy_register)
    baseline.watch_baseline(repo_root=root, storage_path=store, max_ticks=1)

    assert "role" not in seen["metadata"]
    events = baseline.events_file_for(root)
    assert not events.exists(), "non-daemon mode must not write the events file"


def test_replayed_line_matches_live_format(tmp_path):
    """One formatter, two moments: MISSED is the live line plus lateness."""
    record = _event("api", subject="daemon wake")
    live = wire._format_delivery(record, missed=False)
    missed = wire._format_delivery(record, missed=True)
    assert live == baseline.format_completion(record)
    assert missed.startswith("MISSED " + live)
    assert record["iso"] in missed
