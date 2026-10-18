# =================== AIPass ====================
# Name: test_watchdog_wire.py
# Description: Tests for the watchdog wire handler (DPLAN-0317 r4 — report, filter, deliver)
# Version: 2.3.0
# Created: 2026-08-19
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/watchdog/wire.py: arm_wire delivering THIS seat's dispatch completions."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/watchdog/wire.py parses and imports
# seedgo: no-test-needed(documentation) — that arm_wire and find_repo_root carry docstrings
# seedgo: no-test-needed(constant) — the WRAPPER_* names and the BASELINE DEAD wording

import json
import os
import shutil
import signal as _real_signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import dispatches as watch_dispatches
from aipass.devpulse.apps.handlers.watchdog import feed as watch_feed
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry
from aipass.devpulse.apps.handlers.watchdog import wire

# Tests drive loops by replacing the handler's own ``_sleep``; none waits a real tick.


# Re-asserted dead where used, so a machine where it IS alive fails as fixture-broken.
DEAD_PID = 999999

SEAT = "@devpulse"


@pytest.fixture(autouse=True)
def _no_json_writes():
    """Keep the suite off devpulse's real json store."""
    with patch("aipass.devpulse.apps.handlers.json.json_handler.log_operation", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _mail_doors(hermetic_mail_doors):
    """Every test here re-roots the feed; none may depend on this machine's live registry marker."""
    return hermetic_mail_doors


@pytest.fixture(autouse=True)
def _private_heartbeat(tmp_path, monkeypatch):
    """Point the heartbeat at a per-test file — never the real /tmp signal."""
    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(wire, "HEARTBEAT_FILE", hb)
    return hb


class _SignalNoRebind:
    """wire's ``signal`` for a test: real constants, and installing a handler does nothing."""

    def __getattr__(self, name: str):
        return getattr(_real_signal, name)

    @staticmethod
    def signal(*args, **kwargs) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_signal_rebind(monkeypatch):
    """arm_wire's SIGTERM handler must not leak; only wire's ``signal`` is swapped, never the process-wide one."""
    monkeypatch.setattr(wire, "signal", _SignalNoRebind())


@pytest.fixture
def raw_stdout_probe():
    """Opt-out from ``_a_stdout_target_this_host_can_name``: a test about ``_stdout_target`` meets the real one."""
    return None


@pytest.fixture(autouse=True)
def _a_stdout_target_this_host_can_name(request, tmp_path, monkeypatch):
    """Hand the arm a stdout target on a host that owns no way to find one.

    Windows has no recipe, so a continuous arm refuses there and the delivery pins
    would all exit 1. The host is found by asking the primitive, not naming a platform.
    The file is NOT under ``tasks/``, so the run_in_background tripwire stays quiet.
    """
    if "raw_stdout_probe" in request.fixturenames or wire._stdout_target() is not None:
        return None
    target = tmp_path / "host-stdout.log"
    target.write_text("", encoding="utf-8")
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: target if pid is None else None)
    return target


def _repo(tmp_path: Path) -> Path:
    """A minimal repo root with a SEALED OWNER: without one, seat_email() attributes nothing."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    (root / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "DEVPULSE", "email": SEAT, "owner": True, "path": str(root)}]}),
        encoding="utf-8",
    )
    return root


def _store(tmp_path: Path) -> Path:
    return tmp_path / "trinity" / "watchdog_active.json"


def _write_feed(root: Path, records: list[dict]) -> Path:
    """Write @ai_mail's notification feed as the wire will re-root it."""
    path = watch_feed.feed_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _completion(branch: str, dispatch_id: str, minute: int = 0, sender: str = SEAT) -> dict:
    """One feed line in the shape dispatch_monitor writes; ``sender`` is what makes rule 5 answerable."""
    return {
        "ts": f"2026-08-22T12:{minute:02d}:00.000000+00:00",
        "kind": "dispatch",
        "title": f"@{branch} completed",
        "body": "Duration: 42s",
        "source": branch,
        "sender": sender,
        "dispatch_id": dispatch_id,
        "report_path": f".aipass/dispatch_reports/{dispatch_id}.json",
    }


def _seed_cursor(root: Path) -> None:
    """Absorb the current feed so a later append is the only NEW record (drain_feed's first look is silent)."""
    watch_feed.drain_feed(
        watch_feed.cursor_file_for(root),
        kinds=("dispatch",),
        feed_file_path=watch_feed.feed_file(root),
    )


def _plant_entry(store: Path, wtype: str, pid: int, metadata: dict | None = None, handle: str | None = None) -> str:
    """Write a registry entry with an ARBITRARY pid: a leftover from another process."""
    store.parent.mkdir(parents=True, exist_ok=True)
    handle = handle or f"{wtype}-{pid:06x}"
    doc = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {"version": 1, "watches": []}
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


def _entries(store: Path) -> list[dict]:
    try:
        return json.loads(store.read_text(encoding="utf-8"))["watches"]
    except FileNotFoundError:
        return []


def _spawn_named(name: str) -> subprocess.Popen:
    """A live process whose cmdline carries ``name`` — argv[0] via exec -a.

    Waits for argv[0] == name: mid-execve the cmdline reads EMPTY, and the
    ``bash -c`` string matches the name before the exec has landed.
    """
    proc = subprocess.Popen(
        ["bash", "-c", f"exec -a {name} sleep 30"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and proc.poll() is None:
        if _argv_of(proc.pid).startswith(name):
            return proc
    proc.kill()
    raise AssertionError(f"fixture broken: {name} never became argv[0] of pid {proc.pid}")


def _argv_of(pid: int) -> str:
    """A pid's command line as ``ps`` prints it — the OS's answer, not the wire's own reader."""
    done = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, encoding="utf-8", check=False)
    return done.stdout.strip()


def test_one_completion_delivers_one_line(tmp_path, capsys, monkeypatch):
    """One completion, one wake: only a COUNT catches a duplicate, which looks like a working wake."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)

    appended = {"done": False}

    def append_once(_seconds):
        if not appended["done"]:
            _write_feed(root, [_completion("flow", "d1")])
            appended["done"] = True

    monkeypatch.setattr(wire, "_sleep", append_once)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=3, wire_poll=0)

    lines = [ln for ln in capsys.readouterr().out.splitlines() if "@flow" in ln]
    assert len(lines) == 1, f"one completion must produce exactly one wake, got {lines}"


def test_another_citizens_completion_is_not_delivered(tmp_path, capsys, monkeypatch):
    """Rule 5: if @flow dispatched @seedgo, that is @flow's wake; only ``sender`` can tell."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)

    def append_both(_seconds):
        _write_feed(
            root,
            [
                _completion("flow", "mine"),
                _completion("seedgo", "theirs", sender="@flow"),
            ],
        )

    monkeypatch.setattr(wire, "_sleep", append_both)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=2, wire_poll=0)

    out = capsys.readouterr().out
    assert "@flow" in out
    assert "@seedgo" not in out, "another citizen's dispatch must never reach this seat"


def test_a_completion_without_a_sender_is_not_mine(tmp_path, capsys, monkeypatch):
    """Unattributable fails CLOSED (every older producer's shape); failing open restores the fleet-wide wake."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)

    anonymous = _completion("stranger", "ignored")
    anonymous.pop("sender")
    monkeypatch.setattr(wire, "_sleep", lambda _s: _write_feed(root, [anonymous]))
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=2, wire_poll=0)

    assert "@stranger" not in capsys.readouterr().out


def test_wake_start_edges_are_not_delivered(tmp_path, capsys, monkeypatch):
    """Only a COMPLETION wakes (rule 5); a kind="wake" start edge is noise, not news."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)

    start_edge = {
        "ts": "2026-08-22T12:00:00+00:00",
        "kind": "wake",
        "title": "@flow waking",
        "body": "dispatched",
        "source": "flow",
        "dispatch_id": "d1",
    }
    monkeypatch.setattr(wire, "_sleep", lambda _s: _write_feed(root, [start_edge]))
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=2, wire_poll=0)

    assert "waking" not in capsys.readouterr().out


def test_an_unresolvable_seat_refuses_to_arm(tmp_path, capsys):
    """No identity means every completion filters out — that must be LOUD, not quiet.

    Unlike an absent register (legitimate), an unknown seat is never legitimate.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    _write_feed(root, [])

    with pytest.raises(SystemExit) as exc_info:
        wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "whose dispatches to deliver" in out


def test_replay_delivers_completions_missed_while_unwired(tmp_path, capsys):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)
    _write_feed(root, [_completion("flow", "d1"), _completion("baud", "d2", minute=5)])

    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert "MISSED" in out
    assert "@flow" in out and "@baud" in out
    assert result["replayed"] == 2


def test_replay_does_not_resurface_what_was_already_delivered(tmp_path, capsys):
    """The cursor is a digest set, not an offset — the feed is rewritten on trim."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [_completion("flow", "d1")])
    _seed_cursor(root)

    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert result["replayed"] == 0
    assert "@flow" not in capsys.readouterr().out


def test_once_returns_after_replay(tmp_path, capsys):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)
    _write_feed(root, [_completion("api", "d1")])

    result = wire.arm_wire(repo_root=root, storage_path=store, once=True, wire_poll=0)

    assert result["state"] == "completed"
    assert "MISSED" in capsys.readouterr().out


def test_live_follow_delivers_an_appended_completion(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)

    monkeypatch.setattr(wire, "_sleep", lambda _s: _write_feed(root, [_completion("flow", "d1")]))
    result = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=2, wire_poll=0)

    assert result["delivered"] == 1
    assert "@flow" in capsys.readouterr().out


_REAL_LSOF = pytest.mark.skipif(
    shutil.which("lsof") is None,
    reason="the darwin lane drives the REAL lsof probe; a host without one (Windows) cannot exercise it",
)


@pytest.mark.parametrize(
    "lane",
    [
        pytest.param("host", id="host"),
        pytest.param("darwin", id="darwin", marks=_REAL_LSOF),
    ],
)
def test_the_wire_leaves_no_process_running(tmp_path, monkeypatch, lane, pretend_platform):
    """Rule 2: idle is zero running processes. The arm door used to spawn a daemon.

    The claim is what is LEFT RUNNING: the real Popen runs (the arm waits on an
    lsof probe off Linux), and only a DETACHED spawn fails. No literal "linux"
    lane: on a macOS runner it would find no /proc and the continuous arm refuse.
    """
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    if lane == "darwin":
        pretend_platform(wire, "darwin")

    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    class _Recorded(real_popen):
        """A real child process that records itself and refuses to be detached."""

        def __init__(self, *args, **kwargs):
            detached = [flag for flag in ("start_new_session", "creationflags") if kwargs.get(flag)]
            assert not detached, f"the wire must not detach a process: {detached} in {args[:1] or kwargs}"
            super().__init__(*args, **kwargs)
            spawned.append(self)

    monkeypatch.setattr(subprocess, "Popen", _Recorded)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    still_running = [proc.args for proc in spawned if proc.poll() is None]
    assert still_running == [], f"the arm returned with a process still running: {still_running}"
    if lane == "darwin":
        assert spawned, "the darwin lane must reach the real lsof/ps probes, or it pins nothing"


_POSIX_ARGV0 = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only fixture: argv[0] via exec -a — the Windows process table never shows it",
)


@_POSIX_ARGV0
def test_a_pre_r4_daemon_still_running_is_retired(tmp_path, capsys):
    """An old detached daemon from another checkout would restore the double-wake, invisibly."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    old = _spawn_named("watchdog-baseline-daemon")
    try:
        _plant_entry(store, "baseline", old.pid, {"role": "daemon", "scope": "all citizens"})

        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

        assert "retired pre-r4 detection daemon" in capsys.readouterr().err
        old.wait(timeout=5)
        assert old.returncode is not None
        assert [w for w in _entries(store) if w["type"] == "baseline"] == []
    finally:
        if old.poll() is None:
            old.kill()


def test_wire_touches_the_heartbeat_the_daemon_used_to_own(tmp_path, _private_heartbeat):
    """Move this and the statusline paints red forever with a healthy wire."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    assert not _private_heartbeat.exists()

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert _private_heartbeat.exists(), "the wire owns the heartbeat now — nothing else writes it"


@_POSIX_ARGV0
def test_takeover_kills_wire_soldered_to_another_session(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    stale = _spawn_named("watchdog-wire-stale")
    try:
        _plant_entry(store, "baseline_wire", stale.pid, {"session": "dead-session"})
        # Distinct session dirs, so the comparison is not short-circuited by two Nones.
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


@_POSIX_ARGV0
def test_same_session_wire_is_taken_over_too(tmp_path, capsys, monkeypatch):
    """No 'already wired': a same-session wire proves a writer, never a listener; only the newest arm has ears."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
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


def test_recycled_pid_is_never_signalled(tmp_path, capsys):
    """A registry pid whose cmdline is not a watchdog gets buried, not shot."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
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


def test_dead_entries_are_buried_on_arm(tmp_path, capsys):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    assert not watch_registry.is_pid_alive(DEAD_PID), "fixture broken: DEAD_PID is alive on this machine"
    _plant_entry(store, "baseline_wire", DEAD_PID, {"session": "gone"})

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert "buried dead" in capsys.readouterr().err
    assert [w for w in _entries(store) if w.get("pid") == DEAD_PID] == []


def test_wire_deregisters_itself_on_exit(tmp_path):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert [w for w in _entries(store) if w["type"] == "baseline_wire"] == []


@_POSIX_ARGV0
def test_continuous_arm_under_run_in_background_is_refused(tmp_path, capsys, monkeypatch):
    """A continuous wire behind a run_in_background tasks file never notifies: refuse before touching anything."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
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
        # The remedy must still exist: Monitor's `persistent` is gone, so it names the one-shot.
        assert "baseline --once" in out
        assert "persistent" not in out
        assert peer.poll() is None, "a refused arm must not have taken over the existing wire"
    finally:
        peer.kill()


def test_once_arm_under_run_in_background_is_allowed(tmp_path, capsys, monkeypatch):
    """--once exits on first delivery, so bg-Bash DOES notify — stays legal."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    _seed_cursor(root)
    _write_feed(root, [_completion("api", "d1")])
    bg_file = tmp_path / "some-session" / "tasks" / "b0l5zsqp7.output"
    bg_file.parent.mkdir(parents=True)
    bg_file.touch()
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: bg_file if pid is None else None)

    result = wire.arm_wire(repo_root=root, storage_path=store, once=True, wire_poll=0)

    assert result["state"] == "completed"
    assert "MISSED DISPATCH @api" in capsys.readouterr().out


def _spy_register(monkeypatch, seen: dict) -> None:
    real_register = watch_registry.register

    def spy(watch_type, metadata=None, storage_path=None):
        if watch_type == "baseline_wire":
            seen.update(metadata or {})
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(watch_registry, "register", spy)


def test_wire_records_conversation_id_from_env(tmp_path, monkeypatch):
    """metadata.session is the CONVERSATION id the statusline receives, never the tasks-dir id."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "conv-abc-123")
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: tmp_path / "runtime-xyz" / "tasks" / "t.output")
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["session"] == "conv-abc-123"
    assert seen["tasks_dir"] == "runtime-xyz"


def test_wire_falls_back_to_tasks_dir_without_env(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: tmp_path / "runtime-xyz" / "tasks" / "t.output")
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["session"] == "runtime-xyz"


def test_wire_records_the_wrapper_carrying_it(tmp_path, monkeypatch):
    """A socket stdout is a Monitor child; recorded at arm time, since later the pid is gone."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: Path("socket:[4532132]"))
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["wrapper"] == wire.WRAPPER_MONITOR


def test_a_foreground_wire_is_recorded_as_foreground(tmp_path, monkeypatch):
    """A tty is not a listener. It must not record as covered."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: Path("/dev/pts/3"))
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert seen["wrapper"] == wire.WRAPPER_FOREGROUND


def test_the_run_in_background_shape_records_as_background(tmp_path, capsys, monkeypatch):
    """--once is legal under run_in_background, so the wrapper is recorded truthfully there too."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    bg_file = tmp_path / "runtime-xyz" / "tasks" / "t.output"
    bg_file.parent.mkdir(parents=True)
    bg_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: bg_file)
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, once=True, max_ticks=1, wire_poll=0)

    assert seen["wrapper"] == wire.WRAPPER_BACKGROUND
    assert "stdout is a pipe" not in capsys.readouterr().err


def test_a_piped_once_wire_says_the_statusline_will_not_count_it(tmp_path, capsys, monkeypatch):
    """A pipe after --once records as foreground; the wire names the pipe (mutant: the pipe check answers False)."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: Path("pipe:[918273]"))
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, once=True, max_ticks=1, wire_poll=0)

    err = capsys.readouterr().err
    assert seen["wrapper"] == wire.WRAPPER_FOREGROUND
    assert "stdout is a pipe" in err
    assert "drone @devpulse watchdog baseline --once" in err


def test_wire_no_longer_records_a_daemon_pid(tmp_path, monkeypatch):
    """There is no daemon to point at. A leftover key would read as one existing."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    seen: dict = {}
    _spy_register(monkeypatch, seen)

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert "daemon_pid" not in seen


def test_session_dir_requires_tasks_parent(tmp_path):
    inside = tmp_path / "abc-session" / "tasks" / "x.output"
    assert wire._session_dir_of(inside) == tmp_path / "abc-session"
    assert wire._session_dir_of(tmp_path / "abc-session" / "x.output") is None
    assert wire._session_dir_of(None) is None


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only fixture: it spawns `sleep` and reads another process's fd table. "
    "On Windows _stdout_target has no probe that can answer (neither /proc nor lsof) and "
    "returns None (cannot tell), by design and logged, never a wrong path. NOT widened to "
    "darwin — macOS has both `sleep` and `lsof`, and the lsof branch is exactly the code "
    "FPLAN-0554 added; skipping there would hide the hole it was written to close.",
)
def test_stdout_target_reads_proc_truth(tmp_path, raw_stdout_probe):
    """The identity primitive against a real process with a known stdout."""
    target = tmp_path / "known.output"
    with open(target, "wb") as fh:
        proc = subprocess.Popen(["sleep", "5"], stdout=fh)
    try:
        assert wire._stdout_target(proc.pid) == target
    finally:
        proc.kill()


def test_dead_pid_has_no_stdout_target(raw_stdout_probe):
    assert not watch_registry.is_pid_alive(DEAD_PID)
    assert wire._stdout_target(DEAD_PID) is None


# Off Linux there is no /proc, and ""/None for every pid is a silent lie, not degradation.
# These pretend darwin here, with subprocess.run answering in real ps/lsof shape.


def _fake_run(stdout: str, argv_seen: list | None = None):
    """A subprocess.run stand-in that prints ``stdout`` and records its argv."""

    def _run(argv, **kwargs):
        if argv_seen is not None:
            argv_seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    return _run


def _missing_binary(name: str):
    """What exec does when the binary is not installed — before any exit code."""

    def _run(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", name)

    return _run


def test_cmdline_off_linux_asks_ps(monkeypatch, pretend_platform):
    argv_seen: list = []
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("drone @devpulse watchdog baseline --once\n", argv_seen))

    assert wire._cmdline(4242) == "drone @devpulse watchdog baseline --once"
    assert argv_seen == [["ps", "-p", "4242", "-o", "command="]]


def test_a_live_wire_off_linux_is_recognised_as_ours(monkeypatch, pretend_platform):
    """With "" every live wire would be buried as a recycled pid instead of taken over."""
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("drone @devpulse watchdog baseline\n"))

    assert wire._looks_like_ours(4242) is True


def test_cmdline_off_linux_is_empty_when_ps_cannot_run(monkeypatch, pretend_platform):
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _missing_binary("ps"))

    assert wire._cmdline(4242) == ""


def test_stdout_target_off_linux_asks_lsof(tmp_path, monkeypatch, raw_stdout_probe, pretend_platform):
    argv_seen: list = []
    named = tmp_path / "sess-abc" / "tasks" / "t.output"
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run(f"p4242\nfd1\nn{named}\n", argv_seen))

    assert wire._stdout_target(4242) == named
    assert argv_seen == [["lsof", "-p", "4242", "-a", "-d", "1", "-Fn"]]


def test_stdout_target_off_linux_names_this_process_by_number(monkeypatch, raw_stdout_probe, pretend_platform):
    """pid None means "me". /proc spells that "self"; lsof needs the number."""
    argv_seen: list = []
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("nsocket:[4532132]\n", argv_seen))

    assert wire._stdout_target() == Path("socket:[4532132]")
    assert argv_seen == [["lsof", "-p", str(os.getpid()), "-a", "-d", "1", "-Fn"]]


def test_stdout_target_off_linux_is_none_when_lsof_names_no_file(monkeypatch, raw_stdout_probe, pretend_platform):
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("p4242\nfd1\n"))

    assert wire._stdout_target(4242) is None


def test_stdout_target_off_linux_is_none_when_lsof_cannot_run(monkeypatch, raw_stdout_probe, pretend_platform):
    """None is "cannot tell". A guessed path would be read as a wrapper."""
    pretend_platform(wire, "darwin")
    monkeypatch.setattr(subprocess, "run", _missing_binary("lsof"))

    assert wire._stdout_target(4242) is None


def test_a_continuous_wire_refuses_when_its_stdout_is_unknowable(tmp_path, capsys, monkeypatch, raw_stdout_probe):
    """Armed with no way of being heard is a lie: refuse by name, non-zero, no entry."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    asked: list = []
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: asked.append(pid))

    with pytest.raises(SystemExit) as exit_info:
        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert asked == [None], "the refusal must come from asking where THIS process's stdout goes"
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "stdout target unresolvable" in captured.err
    assert "BASELINE DEAD: stdout target unresolvable" in captured.out
    assert "armed handle=" not in captured.err
    assert _entries(store) == []


def test_once_still_arms_when_the_stdout_target_is_unknowable(tmp_path, capsys, monkeypatch, raw_stdout_probe):
    """--once exits on delivery, so ANY wrapper hears it; the refusal is the continuous wire's alone."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    asked: list = []
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: asked.append(pid))

    result = wire.arm_wire(once=True, repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert asked == [None]
    assert result["state"] == "stopped"
    assert "BASELINE DEAD" not in capsys.readouterr().out


def test_find_repo_root_walks_up_to_the_registry(tmp_path):
    root = _repo(tmp_path)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert wire.find_repo_root(deep) == root.resolve()


def test_find_repo_root_returns_none_without_a_registry(tmp_path):
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    assert wire.find_repo_root(orphan) is None


# A monitor that died finishes nothing, so no completion reaches the feed: the wire reads the register.


def _register_row(
    target: str,
    dispatch_id: str,
    overdue: bool = True,
    sender: str = SEAT,
    monitor_alive: bool | None = None,
    monitor_pid: int | None = None,
) -> dict:
    """One row as @ai_mail's outstanding_dispatches serves it; ``monitor_alive`` None is "never learned a pid"."""
    row = {
        "dispatch_id": dispatch_id,
        "ts": "2026-09-07T12:00:12.016287-07:00",
        "sender": sender,
        "target": f"@{target}",
        "subject": f"wave 3: your brief, {target}",
        "expected_by": "2026-09-07T14:00:12.016287-07:00",
        "status": "outstanding",
        "overdue": overdue,
        "monitor_alive": monitor_alive,
    }
    if monitor_pid is not None:
        row["monitor_pid"] = monitor_pid
    return row


def _register(monkeypatch, rows: list[dict]) -> list[int]:
    """Serve ``rows`` through the door the wire reads, counting every read."""
    reads = [0]

    def _outstanding(repo_root=None):
        reads[0] += 1
        return list(rows)

    monkeypatch.setattr(watch_dispatches, "outstanding", _outstanding)
    return reads


def test_a_dead_dispatch_of_mine_is_announced_at_sign_in(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("prax", "70da6e9c-3e56-46a3-a867-cd014e23e7cd")])

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert result["dead"] == 1
    assert "DEAD @prax [70da6e9c] dispatched 09-07 12:00" in out
    assert "no completion by 09-07 14:00" in out
    # Overdue proves nothing about the monitor (a retry stays overdue against the FIRST
    # deadline): no unchecked cause, no re-dispatch that would double a running retry.
    assert "Nothing here checked whether its monitor is alive" in out
    assert "retries a dispatch up to" in out
    assert "re-dispatching" in out.lower()
    assert "its monitor died" not in out


def test_a_death_is_announced_once_ever_not_once_per_wire(tmp_path, capsys, monkeypatch):
    """The cursor lives beside the feed cursor; mutant 'cursor at repo root' reddens it."""
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("drone", "bc7fe224-7a4a-4a64-8869-08c29716ce75")])
    store = _store(tmp_path)

    first = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)
    assert first["dead"] == 1
    assert "DEAD @drone" in capsys.readouterr().out
    assert watch_feed.cursor_file_for(root, name=wire.DEAD_CURSOR_NAME).is_file()

    second = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)
    assert second["dead"] == 0
    assert "DEAD" not in capsys.readouterr().out


def test_another_seats_dead_dispatch_is_not_announced(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("api", "fb25b330-e6f7-44e9-9bd4-6e75ced6e007", sender="@trigger")])

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert result["dead"] == 0
    assert "DEAD" not in capsys.readouterr().out


def test_a_dispatch_inside_its_timeout_is_silent(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("prax", "357433b4-d402-4319-8cf9-5a2d6df28abb", overdue=False)])

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert result["dead"] == 0
    assert "DEAD" not in capsys.readouterr().out


def test_a_gone_monitor_is_announced_before_the_hard_timeout(tmp_path, capsys, monkeypatch):
    """A gone monitor pid is a death NOW; the wire must not wait the two hours for ``expected_by``."""
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(
        monkeypatch,
        [
            _register_row(
                "prax", "70da6e9c-3e56-46a3-a867-cd014e23e7cd", overdue=False, monitor_alive=False, monitor_pid=4242
            )
        ],
    )

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert result["dead"] == 1
    assert "DEAD @prax [70da6e9c] dispatched 09-07 12:00" in out
    assert "monitor (pid 4242) is gone before the hard timeout 09-07 14:00" in out
    assert "Re-dispatch in continue mode" in out


def test_a_row_that_never_learned_a_pid_falls_back_to_overdue(tmp_path, capsys, monkeypatch):
    """``monitor_alive`` None is unknown: folded into dead it would announce the whole backlog at once."""
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(
        monkeypatch,
        [
            _register_row("drone", "bc7fe224-7a4a-4a64-8869-08c29716ce75", overdue=False, monitor_alive=None),
            _register_row("api", "641dddbb-0000-4000-8000-000000000000", overdue=True, monitor_alive=None),
        ],
    )

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    out = capsys.readouterr().out
    assert result["dead"] == 1
    assert "DEAD @drone" not in out
    assert "DEAD @api [641dddbb]" in out
    assert "no completion by 09-07 14:00, the hard timeout" in out


def test_a_live_monitor_inside_its_timeout_is_silent(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(
        monkeypatch,
        [_register_row("skills", "5ed35b24-1111-4000-8000-000000000000", overdue=False, monitor_alive=True)],
    )

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert result["dead"] == 0
    assert "DEAD" not in capsys.readouterr().out


def test_the_register_is_read_every_five_minutes_not_every_tick(tmp_path, monkeypatch):
    """Five minutes, not sixty seconds, to cut cpu: one read at sign-in, none per tick at the default."""
    assert wire.DEAD_CHECK_SECONDS == 300.0
    root = _repo(tmp_path)
    _write_feed(root, [])
    reads = _register(monkeypatch, [])

    wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=5, wire_poll=0)
    assert reads[0] == 1

    reads[0] = 0
    wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=5, wire_poll=0, dead_check=0)
    assert reads[0] == 1 + 5


def test_a_death_found_mid_follow_is_announced_on_the_next_check(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    rows: list[dict] = []
    _register(monkeypatch, rows)
    monkeypatch.setattr(wire, "_sleep", lambda _s: rows.append(_register_row("prax", "dead-mid-follow")))

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=2, wire_poll=0, dead_check=0)

    assert result["dead"] == 1
    assert "DEAD @prax [dead-mid]" in capsys.readouterr().out


def test_an_unreadable_register_does_not_kill_the_wire(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])

    def _broken(repo_root=None):
        raise RuntimeError("register cannot be located")

    monkeypatch.setattr(watch_dispatches, "outstanding", _broken)

    result = wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert result["state"] == "stopped"
    assert result["dead"] == 0
    assert "BASELINE DEAD" not in capsys.readouterr().out


def test_once_treats_a_death_as_the_wake_it_owes(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("prax", "once-dead")])

    result = wire.arm_wire(once=True, repo_root=root, storage_path=_store(tmp_path), wire_poll=0)

    assert result["state"] == "completed"
    assert result["dead"] == 1
    assert "DEAD @prax" in capsys.readouterr().out
