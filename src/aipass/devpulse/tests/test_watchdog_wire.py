# =================== AIPass ====================
# Name: test_watchdog_wire.py
# Description: Tests for the watchdog wire handler (DPLAN-0317 r4 — report, filter, deliver)
# Version: 2.2.0
# Created: 2026-08-19
# Modified: 2026-09-12
# =============================================

"""Tests for arm_wire — delivering THIS seat's dispatch completions.

Two failures are pinned here, from two different rounds.

r2's, witnessed live on 2026-08-19: a session-wired watcher kept detecting after
the session id churned, delivering COMPLETE lines into a dead session's task
file. So the wire must take over a wire soldered to another session, never
SIGTERM a recycled pid, and refuse to run continuously under
run_in_background — where its per-line stdout notifies nobody.

r4's, measured 2026-08-22 and the reason this file lost seventeen tests: the
wire drained the detection daemon's events file AND @ai_mail's notification
feed, with no dedupe. They carried the same completions 1-2 seconds apart, so
every dispatch produced TWO wakes for months. ``test_one_completion_delivers_one_line``
is the load-bearing test of this rewrite — a duplicate wake looks exactly like a
working wake, so only a count can tell them apart.

The other r4 headline is attribution: the feed names the branch that FINISHED,
never the one that SENT the work, so this seat used to be woken fleet-wide.
``test_another_citizens_completion_is_not_delivered`` pins rule 5.

Every test passes ``repo_root``/``storage_path`` explicitly and drives loops by
replacing the handler's own ``_sleep`` — no test waits a real tick.

One thing here is about the HOST rather than the wire. ``_stdout_target`` has a
recipe on Linux (/proc) and off it (``lsof``), and none at all on Windows, where
a continuous arm therefore refuses. ``_a_stdout_target_this_host_can_name``
below hands the arm a target on such a host so the ~35 pins that are about
delivery keep running there; the pins that are about stdout resolution itself
opt out of it by naming ``raw_stdout_probe``.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import feed as watch_feed
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry
from aipass.devpulse.apps.handlers.watchdog import wire


# A pid that cannot be running, re-asserted where used so a machine where it IS
# alive fails as fixture-broken instead of quietly passing for the wrong reason.
DEAD_PID = 999999

SEAT = "@devpulse"


@pytest.fixture(autouse=True)
def _no_json_writes():
    """Keep the suite off devpulse's real json store."""
    with patch("aipass.devpulse.apps.handlers.json.json_handler.log_operation", return_value=True):
        yield


@pytest.fixture(autouse=True)
def _mail_doors(hermetic_mail_doors):
    """Every test here re-roots the feed; none may depend on this machine's
    live registry marker (the CI fresh-checkout failure, PR #739)."""
    return hermetic_mail_doors


@pytest.fixture(autouse=True)
def _private_heartbeat(tmp_path, monkeypatch):
    """Point the heartbeat at a per-test file — never the real /tmp signal.

    r4 moved this file's WRITER from the daemon to the wire; it is patched on
    ``wire`` now for that reason, not merely because the module moved.
    """
    hb = tmp_path / "heartbeat"
    monkeypatch.setattr(wire, "HEARTBEAT_FILE", hb)
    return hb


@pytest.fixture(autouse=True)
def _no_signal_rebind(monkeypatch):
    """arm_wire installs a SIGTERM handler for clean deregistration; inside
    pytest that rebinding must not leak past the test."""
    monkeypatch.setattr(wire.signal, "signal", lambda *a, **kw: None)


@pytest.fixture
def raw_stdout_probe():
    """Opt-out token for ``_a_stdout_target_this_host_can_name`` below.

    A test whose SUBJECT is ``_stdout_target`` — its probes, or the refusal a
    None answer earns — has to meet the real function or it would be pinning
    the fixture instead of the code. Naming this fixture is how it says so.
    """
    return None


@pytest.fixture(autouse=True)
def _a_stdout_target_this_host_can_name(request, tmp_path, monkeypatch):
    """Hand the arm a stdout target on a host that owns no way to find one.

    What is missing on such a host is the RECIPE, never the STATE these tests
    pin. ``_stdout_target`` reads ``/proc`` on Linux and shells out to ``lsof``
    off it; Windows has neither, so every answer there is None — and since
    FPLAN-0554 a CONTINUOUS ``arm_wire`` refuses on None, correctly: a wire that
    cannot name its wrapper cannot know anyone would hear a delivery. Left
    alone, that turns every continuous arm in this file into ``SystemExit(1)``
    on Windows CI and takes ~35 behaviour pins off the board in one go, not one
    of which is about resolving stdout.

    Which host that is, is decided by ASKING the primitive rather than by
    naming a platform: the honest question is whether the answer comes back,
    and a spelled-out ``sys.platform`` test would also fire on a Linux box with
    no lsof, where /proc answers perfectly well. On Linux and on macOS the
    probe answers and this fixture does nothing at all.

    The substitute is a plain regular file, deliberately NOT under a ``tasks``
    directory, so ``_session_dir_of`` stays None and the run_in_background
    tripwire stays quiet. Other pids still answer None — off Linux that is the
    truth, and the sweep is written for it.
    """
    if "raw_stdout_probe" in request.fixturenames or wire._stdout_target() is not None:
        return None
    target = tmp_path / "host-stdout.log"
    target.write_text("", encoding="utf-8")
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: target if pid is None else None)
    return target


def _repo(tmp_path: Path) -> Path:
    """A minimal repo root with a SEALED OWNER.

    The owner entry is not decoration: dispatches.seat_email() resolves "whose
    dispatches are these" through spawn's owner contract, and a repo without one
    refuses to attribute anything at all — which is the correct behaviour and
    would make every test here fail for the wrong reason.
    """
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
    """One feed line in the shape dispatch_monitor writes at the terminal moment.

    ``sender`` is the field that makes rule 5 answerable at all — @ai_mail
    stamps it on the line (FPLAN-0452 P1) precisely so a consumer never has to
    join back to the register to ask "was this mine".
    """
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
    """Absorb the current feed so a later append is the only NEW record.

    drain_feed seeds silently on its first look — there is no honest way to know
    what a previous session already saw — so a test about *live* delivery has to
    get past that first look deliberately.
    """
    watch_feed.drain_feed(
        watch_feed.cursor_file_for(root),
        kinds=("dispatch",),
        feed_file_path=watch_feed.feed_file(root),
    )


def _plant_entry(store: Path, wtype: str, pid: int, metadata: dict | None = None, handle: str | None = None) -> str:
    """Write a registry entry with an ARBITRARY pid — the shape register()
    can't produce (it stamps os.getpid), which is exactly what a leftover from
    another process looks like."""
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

    Waits for the POST-exec cmdline, and the distinction matters: during
    ``execve`` /proc/<pid>/cmdline reads EMPTY for an instant, and a sweep that
    looks in that window sees no watchdog name and correctly refuses to signal
    what looks like a recycled pid — so the test asserts against the wrong
    branch. Merely checking that the name is present is not enough, because the
    ``bash -c`` string contains it too and matches immediately, before the exec
    has happened at all. argv[0] == name is the only proof the exec landed.

    Not a new race: r4 exposed it by removing the daemon-ensure step the arm
    door used to spend time on before sweeping.
    """
    proc = subprocess.Popen(
        ["bash", "-c", f"exec -a {name} sleep 30"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(500):
        if wire._cmdline(proc.pid).startswith(name):
            return proc
        time.sleep(0.01)
    proc.kill()
    raise AssertionError(f"fixture broken: {name} never became argv[0] of pid {proc.pid}")


# ─────────────────────────────────────────────────────────────────────────────
# THE r4 HEADLINE — one completion, one wake, and only mine
# ─────────────────────────────────────────────────────────────────────────────


def test_one_completion_delivers_one_line(tmp_path, capsys, monkeypatch):
    """The defect r4 exists to kill: every completion used to wake twice.

    The daemon's events file and @ai_mail's feed carried the SAME completion
    1-2s apart, and the wire drained both with no dedupe. Only a COUNT can
    catch this — a duplicate wake is indistinguishable from a working one.
    """
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
    """Rule 5: if @flow dispatched @seedgo, that is @flow's wake, not mine.

    Note both records name a branch that FINISHED — ``source`` cannot separate
    them. Only ``sender`` can, which is why @ai_mail stamps it.
    """
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
    """Unattributable fails CLOSED. Failing open restores the fleet-wide wake.

    This is the shape every completion has under an OLDER producer, so the
    open/closed choice here decides what happens during a rollout, not just in
    a corner case.
    """
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
    """Only a COMPLETION wakes (rule 5).

    An agent may mail a report and then mail a correction, so the wake waits for
    it to be FINISHED. The feed also carries kind="wake" start edges, which this
    wire used to deliver — that is noise, not news.
    """
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

    A wire that armed here would sit looking healthy and deliver nothing, which
    is silence reading as coverage: the failure shape this release exists to
    remove. Note the deliberate asymmetry with the register, whose ABSENCE is
    legitimate (no dispatch has ever been sent from this project yet); an
    unknown seat never is.
    """
    root = tmp_path / "repo"
    root.mkdir()
    # A registry with no sealed owner — nobody to attribute dispatches to.
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    _write_feed(root, [])

    with pytest.raises(SystemExit) as exc_info:
        wire.arm_wire(repo_root=root, storage_path=_store(tmp_path), max_ticks=1, wire_poll=0)

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "whose dispatches to deliver" in out


# ─────────────────────────────────────────────────────────────────────────────
# Replay — churn delays completions, never loses them
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
# The daemon is gone — and must not come back through a side door
# ─────────────────────────────────────────────────────────────────────────────


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
def test_the_wire_leaves_no_process_running(tmp_path, monkeypatch, lane):
    """Rule 2: idle is zero running processes. The arm door used to spawn a daemon.

    The claim is about what is LEFT RUNNING, and the mock has to read no wider
    than that. An earlier version of this pin replaced ``subprocess.Popen`` with
    a function that exploded on ANY spawn, and macOS CI run 34704362515
    collected the bill: FPLAN-0554 gave ``_stdout_target`` an ``lsof`` fallback
    off Linux, the arm WAITS for that probe, and the pin failed on
    ``['lsof', '-p', ..., '-Fn']`` while the wire had in fact left nothing
    running. On Linux the ``/proc`` fast path never reaches subprocess at all,
    so the same pin passed here and the red was invisible until CI.

    So the REAL Popen runs. Every instance is recorded, a DETACHED spawn still
    fails by name — that is the daemon shape this test exists for — and once the
    arm has returned, every process it started must already be reaped.

    The darwin lane forces the off-Linux branch on this box so the probes are
    actually exercised rather than assumed. A literal "linux" lane is
    deliberately absent: on the real macOS runner it would read a ``/proc`` that
    is not there, get None, and the continuous arm would refuse.
    """
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    if lane == "darwin":
        monkeypatch.setattr(wire.sys, "platform", "darwin")

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
    """An old detached daemon from another checkout would restore the double-wake.

    It would also be invisible while doing it — the second wake looks like the
    first — so the arm retires it by name rather than ignoring an unknown type.
    """
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
    """Move this and the statusline paints red forever with a healthy wire.

    That is not hypothetical — FPLAN-0451 P2 hit the same trap from the other
    side with a hardcoded /tmp path.
    """
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    assert not _private_heartbeat.exists()

    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert _private_heartbeat.exists(), "the wire owns the heartbeat now — nothing else writes it"


# ─────────────────────────────────────────────────────────────────────────────
# Takeover — one wire, the right wire, and never an innocent pid
# ─────────────────────────────────────────────────────────────────────────────


@_POSIX_ARGV0
def test_takeover_kills_wire_soldered_to_another_session(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
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


@_POSIX_ARGV0
def test_same_session_wire_is_taken_over_too(tmp_path, capsys, monkeypatch):
    """No 'already wired' answer exists: a wire writing into the CURRENT
    session dir proves a writer, never a listener (the 10:55 wire kept writing
    into the live session dir after the resume killed its monitor). The arm
    happening right now is the only wire known to have ears."""
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


# ─────────────────────────────────────────────────────────────────────────────
# The wrapper tripwire — the 12:34 failure
# ─────────────────────────────────────────────────────────────────────────────


@_POSIX_ARGV0
def test_continuous_arm_under_run_in_background_is_refused(tmp_path, capsys, monkeypatch):
    """Monitor stdout is a socket; run_in_background stdout is a REAL FILE in a
    tasks dir (measured live 2026-08-19). A continuous wire behind that file
    never notifies — the 12:34 failure — so the arm refuses before touching
    anything (no takeover, no registration)."""
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
        assert "Monitor" in out
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


# ─────────────────────────────────────────────────────────────────────────────
# Wire identity — two id namespaces, do not confuse them
# ─────────────────────────────────────────────────────────────────────────────


def _spy_register(monkeypatch, seen: dict) -> None:
    real_register = watch_registry.register

    def spy(watch_type, metadata=None, storage_path=None):
        if watch_type == "baseline_wire":
            seen.update(metadata or {})
        return real_register(watch_type, metadata=metadata, storage_path=storage_path)

    monkeypatch.setattr(wire._registry, "register", spy)


def test_wire_records_conversation_id_from_env(tmp_path, monkeypatch):
    """metadata.session is the CONVERSATION id (what the statusline receives),
    never the tasks-dir id — the two namespaces measured 2026-08-19 differ."""
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
    """A socket stdout is a Monitor child — the only wrapper that can hear a
    continuous wire. Recorded at arm time, because by the time anyone asks
    'was that wire real' the pid is gone and /proc cannot answer."""
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


def test_the_run_in_background_shape_records_as_background(tmp_path, monkeypatch):
    """--once is legal under run_in_background (it exits on delivery), so the
    wrapper must still be recorded truthfully there rather than assumed."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Off Linux — FPLAN-0554, from macOS CI run 34682737363
#
# /proc does not exist on macOS, and answering ""/None for every pid was never
# graceful degradation. It was three silent lies:
#   1. _cmdline "" -> _looks_like_ours False for EVERY pid -> every live wire
#      read as a recycled pid, was left alone, and nothing was ever taken over;
#   2. _stdout_target None -> wrapper recorded "foreground", stdout null, and
#      the wire announced "armed" while no wrapper could hear a single line;
#   3. the zombie check skipped (registry/agent) -> an exited pid read alive.
#
# These run on THIS Linux box by pretending to be darwin: sys.platform is
# monkeypatched and subprocess.run answers in the shape the real ps/lsof print.
# ─────────────────────────────────────────────────────────────────────────────


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


def test_cmdline_off_linux_asks_ps(monkeypatch):
    argv_seen: list = []
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("drone @devpulse watchdog baseline --once\n", argv_seen))

    assert wire._cmdline(4242) == "drone @devpulse watchdog baseline --once"
    assert argv_seen == [["ps", "-p", "4242", "-o", "command="]]


def test_a_live_wire_off_linux_is_recognised_as_ours(monkeypatch):
    """Row 1 in one assertion: with "" this was False for every pid, so a live
    wire was buried as a recycled pid instead of taken over."""
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("drone @devpulse watchdog baseline\n"))

    assert wire._looks_like_ours(4242) is True


def test_cmdline_off_linux_is_empty_when_ps_cannot_run(monkeypatch):
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _missing_binary("ps"))

    assert wire._cmdline(4242) == ""


def test_stdout_target_off_linux_asks_lsof(monkeypatch, raw_stdout_probe):
    argv_seen: list = []
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run("p4242\nfd1\nn/Users/p/.claude/sess-abc/tasks/t.output\n", argv_seen),
    )

    assert wire._stdout_target(4242) == Path("/Users/p/.claude/sess-abc/tasks/t.output")
    assert argv_seen == [["lsof", "-p", "4242", "-a", "-d", "1", "-Fn"]]


def test_stdout_target_off_linux_names_this_process_by_number(monkeypatch, raw_stdout_probe):
    """pid None means "me". /proc spells that "self"; lsof needs the number."""
    argv_seen: list = []
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("nsocket:[4532132]\n", argv_seen))

    assert wire._stdout_target() == Path("socket:[4532132]")
    assert argv_seen == [["lsof", "-p", str(os.getpid()), "-a", "-d", "1", "-Fn"]]


def test_stdout_target_off_linux_is_none_when_lsof_names_no_file(monkeypatch, raw_stdout_probe):
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run("p4242\nfd1\n"))

    assert wire._stdout_target(4242) is None


def test_stdout_target_off_linux_is_none_when_lsof_cannot_run(monkeypatch, raw_stdout_probe):
    """None is "cannot tell". A guessed path would be read as a wrapper."""
    monkeypatch.setattr(wire.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _missing_binary("lsof"))

    assert wire._stdout_target(4242) is None


def test_a_continuous_wire_refuses_when_its_stdout_is_unknowable(tmp_path, capsys, monkeypatch, raw_stdout_probe):
    """Row 2's product half. "armed" with no way of being heard is the exact
    lie this whole file exists to remove — refuse by name, non-zero, no entry."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: None)

    with pytest.raises(SystemExit) as exit_info:
        wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "stdout target unresolvable" in captured.err
    assert "BASELINE DEAD: stdout target unresolvable" in captured.out
    assert "armed handle=" not in captured.err
    assert _entries(store) == []


def test_once_still_arms_when_the_stdout_target_is_unknowable(tmp_path, capsys, monkeypatch, raw_stdout_probe):
    """--once exits on delivery, so ANY wrapper hears it. The refusal belongs to
    the continuous wire alone; widening it would kill the bg-safe shape."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])
    monkeypatch.setattr(wire, "_stdout_target", lambda pid=None: None)

    result = wire.arm_wire(once=True, repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)

    assert result["state"] == "stopped"
    assert "BASELINE DEAD" not in capsys.readouterr().out


def test_find_repo_root_walks_up_to_the_registry(tmp_path):
    """Moved here from baseline.py when r4 deleted the daemon around it."""
    root = _repo(tmp_path)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert wire.find_repo_root(deep) == root.resolve()


def test_find_repo_root_returns_none_without_a_registry(tmp_path):
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    assert wire.find_repo_root(orphan) is None


# ─────────────────────────────────────────────────────────────────────────────
# The dead-monitor backstop (FPLAN-0499) — DPLAN-0314's "outcome M"
#
# A monitor that died in a reboot finishes nothing, so no completion ever
# reaches the feed. The 2026-09-07 12:17 reboot killed two wave-3 agents and
# nothing said so for 2.5 h. The wire now reads the register itself, on a
# five-minute cadence, and speaks once per death.
# ─────────────────────────────────────────────────────────────────────────────


def _register_row(
    target: str,
    dispatch_id: str,
    overdue: bool = True,
    sender: str = SEAT,
    monitor_alive: bool | None = None,
    monitor_pid: int | None = None,
) -> dict:
    """One row in the shape @ai_mail's outstanding_dispatches door returns.

    ``monitor_alive`` is tri-state exactly as ai_mail serves it (FPLAN-0499
    phase 2): True alive, False gone, None never learned a pid.
    """
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

    monkeypatch.setattr(wire._dispatches, "outstanding", _outstanding)
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
    assert "Re-dispatch in continue mode" in out


def test_a_death_is_announced_once_ever_not_once_per_wire(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _write_feed(root, [])
    _register(monkeypatch, [_register_row("drone", "bc7fe224-7a4a-4a64-8869-08c29716ce75")])
    store = _store(tmp_path)

    first = wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)
    assert first["dead"] == 1
    assert "DEAD @drone" in capsys.readouterr().out
    assert wire._dead_cursor_file(root).is_file()

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
    """FPLAN-0499 phase 2: ai_mail records the monitor's pid and derives
    ``monitor_alive`` from /proc at read time. A gone pid is a death NOW — the
    wire must not wait the two hours for ``expected_by``."""
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
    """``monitor_alive`` None is every row written before phase 2 and the
    systemd-scope path: not dead, not alive, unknown. Folding it into dead would
    announce the whole historic backlog at once, so None keeps the overdue rule."""
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
    """Patrick, 2026-09-07 15:00: five minutes, not sixty seconds, and the
    code checks — the redesign exists to cut cpu. One read at sign-in, none
    per tick at the default cadence; every tick only when a test asks for it."""
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

    monkeypatch.setattr(wire._dispatches, "outstanding", _broken)

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
