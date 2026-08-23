# =================== AIPass ====================
# Name: test_watchdog_wire.py
# Description: Tests for the watchdog wire handler (DPLAN-0317 r4 — report, filter, deliver)
# Version: 2.0.0
# Created: 2026-08-19
# Modified: 2026-08-22
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
"""

import json
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


def test_wire_never_spawns_anything(tmp_path, monkeypatch):
    """Rule 2: idle is zero running processes. The arm door used to spawn a daemon."""
    root = _repo(tmp_path)
    store = _store(tmp_path)
    _write_feed(root, [])

    def explode(*a, **kw):
        raise AssertionError(f"the wire must not spawn a process: {a}")

    monkeypatch.setattr(subprocess, "Popen", explode)
    wire.arm_wire(repo_root=root, storage_path=store, max_ticks=1, wire_poll=0)


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
    reason="/proc fd inspection is POSIX-only — on Windows _stdout_target answers None "
    "(cannot tell), by design and logged, never a wrong path",
)
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
