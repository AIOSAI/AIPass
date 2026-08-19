# =================== AIPass ====================
# Name: test_watchdog_baseline.py
# Description: Tests for the watchdog baseline handler
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Tests for watch_baseline (P1, DPLAN-0308).

Every test builds its own branch tree + registry under tmp_path and passes
``repo_root``/``storage_path`` explicitly, so the real fleet can neither save
nor break them. The poll loop is driven by replacing ``baseline._sleep`` with a
per-tick script that mutates the tree — no test ever waits a real 2s tick.
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.watchdog import baseline
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry


# A pid that cannot be running. Same value test_watchdog_registry.py pins
# is_pid_alive(999999) is False against; the tests using it re-assert that
# themselves so a machine where it IS alive fails as fixture-broken, loudly,
# instead of quietly passing for the wrong reason.
DEAD_PID = 999999


@pytest.fixture(autouse=True)
def _no_json_writes():
    """Keep the suite off devpulse's real json store — arm + register both log."""
    with patch("aipass.devpulse.apps.handlers.json.json_handler.log_operation", return_value=True):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────


def _build_registry(tmp_path: Path, names, include_self: bool = True, relative: bool = False) -> Path:
    """Create a fake repo root: branch dirs + an AIPASS_REGISTRY.json listing them."""
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    entries = []
    for name in list(names) + (["devpulse"] if include_self else []):
        branch = root / name
        (branch / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        entries.append(
            {
                "name": name.upper(),
                "email": f"@{name}",
                "path": name if relative else str(branch),
            }
        )
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": entries}), encoding="utf-8")
    return root


def _add_project_citizen(root: Path, project: str, name: str, rel_path: str | None = None) -> Path:
    """Host a project citizen the way the real tree does.

    ``projects/<project>/<PROJECT>_REGISTRY.json`` with a path RELATIVE to that
    project's root — the shape that made @baud invisible to the first build.
    Returns the project's registry file.
    """
    rel = rel_path or f"src/{name}/{name}"
    project_root = root / "projects" / project
    (project_root / rel / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
    registry_file = project_root / f"{project.upper()}_REGISTRY.json"
    registry_file.write_text(
        json.dumps({"branches": [{"name": name.upper(), "email": f"@{name}", "path": rel}]}),
        encoding="utf-8",
    )
    return registry_file


def _store(tmp_path: Path) -> Path:
    """Watch-registry path for this test."""
    return tmp_path / "trinity" / "watchdog_active.json"


def _write_lock(branch_path: Path, pid: int, subject: str = "ship it", age_seconds: int = 30) -> Path:
    """Write a .dispatch.lock in the real shape (pid/timestamp/branch/subject)."""
    lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
    stamp = (datetime.now() - timedelta(seconds=age_seconds)).isoformat()
    payload = {"pid": pid, "timestamp": stamp, "branch": str(branch_path), "subject": subject}
    lock_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return lock_file


def _tick_script(monkeypatch, steps) -> dict:
    """Replace the inter-tick pause with a script: ``steps[i]`` runs after tick i+1.

    Patching ``baseline._sleep`` rather than ``time.sleep`` keeps the mutation
    on this loop — a global patch also fires on every daemon thread sleeping in
    the same process (the prax logger runs three).
    """
    counter = {"n": 0}

    def fake_sleep(_seconds):
        """Scripted inter-tick pause — mutates the tree instead of waiting."""
        index = counter["n"]
        counter["n"] += 1
        if index < len(steps):
            steps[index]()

    monkeypatch.setattr(baseline, "_sleep", fake_sleep)
    return counter


def _completion_lines(out: str) -> list[str]:
    """Every COMPLETE event line in captured stdout."""
    return [line for line in out.splitlines() if line.startswith("COMPLETE ")]


def _age_of(line: str) -> int:
    """Extract the integer age from a COMPLETE line."""
    match = re.search(r"age=(\d+)s", line)
    assert match is not None, f"no numeric age in event line: {line}"
    return int(match.group(1))


# ─────────────────────────────────────────────────────────────────────────────
# Roster — registry parsing, self-exclusion, path resolution
# ─────────────────────────────────────────────────────────────────────────────


def test_roster_excludes_devpulse_itself(tmp_path):
    """The self branch is never watched — self-completions are meaningless."""
    root = _build_registry(tmp_path, ["alpha", "beta"])
    roster = baseline._read_registry_branches(root / "AIPASS_REGISTRY.json")

    names = [name for name, _path in roster]
    assert names == ["alpha", "beta"]
    assert "devpulse" not in names


def test_roster_resolves_relative_paths_against_the_registry(tmp_path):
    """A relative registry path resolves against the registry's own directory."""
    root = _build_registry(tmp_path, ["alpha"], relative=True)
    roster = baseline._read_registry_branches(root / "AIPASS_REGISTRY.json")

    assert roster[0][1].resolve() == (root / "alpha").resolve()


def test_roster_accepts_dict_shaped_branches(tmp_path):
    """branches[] may be a dict in the wild — both shapes parse (agent.py doctrine)."""
    root = tmp_path / "repo"
    root.mkdir()
    payload = {"branches": {"a": {"email": "@alpha", "path": "alpha"}, "d": {"email": "@devpulse", "path": "devpulse"}}}
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(payload), encoding="utf-8")

    roster = baseline._read_registry_branches(root / "AIPASS_REGISTRY.json")
    assert [name for name, _path in roster] == ["alpha"]


# ─────────────────────────────────────────────────────────────────────────────
# Completions — present -> gone
# ─────────────────────────────────────────────────────────────────────────────


def test_lock_appear_then_vanish_reports_completion(monkeypatch, tmp_path, capsys):
    """A lock that disappears emits exactly one COMPLETE line with subject + age."""
    root = _build_registry(tmp_path, ["alpha", "beta"])
    lock = _write_lock(root / "alpha", pid=os.getpid(), subject="ship it", age_seconds=30)
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert lines[0].startswith('COMPLETE @alpha subject="ship it" age=')
    assert "bounce=no" in lines[0]
    assert 28 <= _age_of(lines[0]) <= 40
    assert result["completions"] == 1


def test_completion_reports_bounce_yes_for_a_fresh_bounce_file(monkeypatch, tmp_path, capsys):
    """last_bounce.json newer than the lock's timestamp = crashed run -> bounce=yes."""
    root = _build_registry(tmp_path, ["alpha"])
    alpha = root / "alpha"
    lock = _write_lock(alpha, pid=os.getpid(), age_seconds=60)
    bounce = alpha / ".ai_mail.local" / "last_bounce.json"
    bounce.write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    _tick_script(monkeypatch, [lock.unlink])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert "bounce=yes" in lines[0]


def test_completion_reports_bounce_no_for_a_stale_bounce_file(monkeypatch, tmp_path, capsys):
    """An OLD bounce file belongs to a previous run — presence alone is not a crash."""
    root = _build_registry(tmp_path, ["alpha"])
    alpha = root / "alpha"
    lock = _write_lock(alpha, pid=os.getpid(), age_seconds=60)
    bounce = alpha / ".ai_mail.local" / "last_bounce.json"
    bounce.write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    # Older than the lock's timestamp: last run's marker, not this run's.
    old = time.time() - 3600
    os.utime(bounce, (old, old))
    _tick_script(monkeypatch, [lock.unlink])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert "bounce=no" in lines[0]


def test_torn_lock_read_keeps_the_cached_subject(monkeypatch, tmp_path, capsys):
    """A half-written lock never costs the completion its subject.

    dispatch_monitor.py rewrites the lock IN PLACE (no atomic replace) to
    self-register its pid, so a reader really can catch a torn document. The
    sighting and the last good contents both have to survive it.
    """
    root = _build_registry(tmp_path, ["alpha"])
    lock = _write_lock(root / "alpha", pid=os.getpid(), subject="deep work", age_seconds=10)

    def tear():
        """Overwrite the lock with a half-written document."""
        lock.write_text('{"pid": 1234, "timesta', encoding="utf-8")

    _tick_script(monkeypatch, [tear, lock.unlink])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=4)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert 'subject="deep work"' in lines[0]


def test_lock_seen_only_as_a_torn_document_still_reports_completion(monkeypatch, tmp_path, capsys):
    """Presence is recorded before parsing — an unreadable lock is still a dispatch."""
    root = _build_registry(tmp_path, ["alpha"])
    lock = root / "alpha" / ".ai_mail.local" / ".dispatch.lock"
    lock.write_text("{not json at all", encoding="utf-8")
    _tick_script(monkeypatch, [lock.unlink])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert lines[0].startswith('COMPLETE @alpha subject="?" age=unknown')


def test_self_branch_completion_is_never_reported(monkeypatch, tmp_path, capsys):
    """devpulse's own lock lifecycle produces no event."""
    root = _build_registry(tmp_path, ["alpha"])
    self_lock = _write_lock(root / "devpulse", pid=os.getpid(), subject="my own run")
    _tick_script(monkeypatch, [self_lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    assert _completion_lines(capsys.readouterr().out) == []
    assert result["branches"] == 1
    assert result["completions"] == 0


def test_continuous_mode_keeps_ticking_after_a_completion(monkeypatch, tmp_path, capsys):
    """Default mode does not exit on a wake — one watcher, no re-arm."""
    root = _build_registry(tmp_path, ["alpha"])
    lock = _write_lock(root / "alpha", pid=os.getpid())
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=4)

    assert len(_completion_lines(capsys.readouterr().out)) == 1
    assert result["state"] == "stopped"
    assert result["ticks"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# Stale lock — present with a dead pid
# ─────────────────────────────────────────────────────────────────────────────


def test_stale_pid_lock_reports_completed_crashed_once(monkeypatch, tmp_path, capsys):
    """A lock whose monitor pid is dead is a crashed completion — named loudly, once."""
    assert baseline._pid_alive(DEAD_PID) is False, "fixture broken: DEAD_PID is alive on this machine"

    root = _build_registry(tmp_path, ["alpha"])
    lock = _write_lock(root / "alpha", pid=DEAD_PID, subject="died mid-run", age_seconds=45)
    _tick_script(monkeypatch, [])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=8)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert lines[0].startswith('COMPLETE @alpha subject="died mid-run" age=')
    assert "state=completed_crashed" in lines[0]
    assert f"stale_lock_pid={DEAD_PID}" in lines[0]
    assert result["completions"] == 1
    # Not ours to delete: the lock belongs to the branch's dispatcher.
    assert lock.exists()


def test_stale_pid_needs_more_than_two_consecutive_ticks(monkeypatch, tmp_path, capsys):
    """Two ticks of a dead pid are not yet a verdict — the monitor's pid handover window."""
    root = _build_registry(tmp_path, ["alpha"])
    _write_lock(root / "alpha", pid=DEAD_PID)
    _tick_script(monkeypatch, [])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=2)

    assert _completion_lines(capsys.readouterr().out) == []


def test_reported_stale_branch_is_treated_as_idle(monkeypatch, tmp_path, capsys):
    """After a crashed report, the lock's later removal is not a second completion."""
    root = _build_registry(tmp_path, ["alpha"])
    lock = _write_lock(root / "alpha", pid=DEAD_PID)
    # Ticks 1-3 build the verdict; the lock is cleaned up after tick 4.
    _tick_script(monkeypatch, [lambda: None, lambda: None, lambda: None, lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=7)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert "state=completed_crashed" in lines[0]
    assert result["completions"] == 1


def test_live_pid_lock_reports_nothing_while_it_runs(monkeypatch, tmp_path, capsys):
    """A running dispatch is silence — only its end is an event."""
    root = _build_registry(tmp_path, ["alpha"])
    _write_lock(root / "alpha", pid=os.getpid())
    _tick_script(monkeypatch, [])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=6)

    assert _completion_lines(capsys.readouterr().out) == []
    assert result["completions"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# --once
# ─────────────────────────────────────────────────────────────────────────────


def test_once_exits_after_the_first_reporting_tick(monkeypatch, tmp_path, capsys):
    """--once returns on the first tick that reports a completion, not on the bound."""
    root = _build_registry(tmp_path, ["alpha"])
    lock = _write_lock(root / "alpha", pid=os.getpid())
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(
        repo_root=root, storage_path=_store(tmp_path), once=True, poll_interval=0.0, max_ticks=50
    )

    assert result["state"] == "completed"
    assert result["ticks"] == 2
    assert result["completions"] == 1
    assert len(_completion_lines(capsys.readouterr().out)) == 1


def test_once_keeps_polling_until_something_completes(monkeypatch, tmp_path, capsys):
    """--once is not one tick — it waits for the first completion."""
    root = _build_registry(tmp_path, ["alpha"])
    alpha = root / "alpha"
    lock_holder = {}

    def arm_lock():
        """Third tick is when the dispatch actually starts."""
        lock_holder["lock"] = _write_lock(alpha, pid=os.getpid(), subject="late start")

    def drop_lock():
        """...and the tick after that is when it finishes."""
        lock_holder["lock"].unlink()

    _tick_script(monkeypatch, [lambda: None, arm_lock, drop_lock])

    result = baseline.watch_baseline(
        repo_root=root, storage_path=_store(tmp_path), once=True, poll_interval=0.0, max_ticks=50
    )

    assert result["state"] == "completed"
    assert result["ticks"] == 4
    assert 'subject="late start"' in _completion_lines(capsys.readouterr().out)[0]


# ─────────────────────────────────────────────────────────────────────────────
# Arming — idempotent, stale-replacing, always deregistered
# ─────────────────────────────────────────────────────────────────────────────


def test_arm_is_idempotent_when_a_live_baseline_holds_the_slot(monkeypatch, tmp_path, capsys):
    """A second arm with the first still alive says so and exits 0 without watching."""
    root = _build_registry(tmp_path, ["alpha"])
    store = _store(tmp_path)
    existing = watch_registry.register("baseline", {"scope": "all citizens"}, storage_path=store)
    lock = _write_lock(root / "alpha", pid=os.getpid())
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=3)

    captured = capsys.readouterr()
    assert result["state"] == "already_armed"
    assert result["pid"] == os.getpid()
    assert f"baseline already armed (pid {os.getpid()})" in captured.err
    # The loop never ran, and the live slot is untouched.
    assert _completion_lines(captured.out) == []
    active = watch_registry.list_active(storage_path=store, prune_stale=False)
    assert [w["handle"] for w in active] == [existing]


def test_arm_replaces_a_registered_but_dead_baseline(monkeypatch, tmp_path, capsys):
    """A dead registered pid is a watcher that died — replaced, and SAID out loud."""
    assert baseline._pid_alive(DEAD_PID) is False, "fixture broken: DEAD_PID is alive on this machine"

    root = _build_registry(tmp_path, ["alpha"])
    store = _store(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(
            {
                "version": 1,
                "watches": [
                    {
                        "handle": "baseline-dead01",
                        "type": "baseline",
                        "started_at": "2026-08-18T00:00:00",
                        "started_epoch": time.time() - 600,
                        "pid": DEAD_PID,
                        "metadata": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _tick_script(monkeypatch, [])

    result = baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=1)

    err = capsys.readouterr().err
    assert result["state"] == "stopped"
    assert "replaced stale entry baseline-dead01" in err
    assert str(DEAD_PID) in err
    assert watch_registry.list_active(storage_path=store, prune_stale=False) == []


def test_arm_ignores_other_watch_kinds(monkeypatch, tmp_path):
    """A live agent watch is not a baseline — it must not block arming."""
    root = _build_registry(tmp_path, ["alpha"])
    store = _store(tmp_path)
    other = watch_registry.register("agent", {"agent_id": "@alpha"}, storage_path=store)
    _tick_script(monkeypatch, [])

    result = baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=1)

    assert result["state"] == "stopped"
    assert [w["handle"] for w in watch_registry.list_active(storage_path=store, prune_stale=False)] == [other]


def test_registers_as_kind_baseline_while_running(monkeypatch, tmp_path):
    """The live watch is visible to `watchdog status` / `cancel` as kind=baseline."""
    root = _build_registry(tmp_path, ["alpha"])
    store = _store(tmp_path)
    seen = {}

    def snapshot():
        """Read the watch registry from inside the running loop."""
        seen["watches"] = watch_registry.list_active(storage_path=store, prune_stale=False)

    _tick_script(monkeypatch, [snapshot])

    result = baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=2)

    assert len(seen["watches"]) == 1
    entry = seen["watches"][0]
    assert entry["type"] == "baseline"
    assert entry["pid"] == os.getpid()
    assert entry["handle"] == result["handle"]
    # ...and gone again on the way out.
    assert watch_registry.list_active(storage_path=store, prune_stale=False) == []


# ─────────────────────────────────────────────────────────────────────────────
# Registry re-read discipline
# ─────────────────────────────────────────────────────────────────────────────


def test_registry_is_read_once_when_its_mtime_never_moves(monkeypatch, tmp_path):
    """Ticks are stats, not parses — the roster is re-read only on mtime change."""
    root = _build_registry(tmp_path, ["alpha", "beta"])
    reads = []
    real_read = baseline._read_registry_branches

    def counting_read(registry_file):
        """Wrap the real parse so the test can count how often it happens."""
        reads.append(registry_file)
        return real_read(registry_file)

    monkeypatch.setattr(baseline, "_read_registry_branches", counting_read)
    _tick_script(monkeypatch, [])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=6)

    assert len(reads) == 1, f"registry parsed {len(reads)}x across 6 ticks — mtime gate is not holding"


def test_registry_is_reread_when_its_mtime_moves(monkeypatch, tmp_path):
    """A new citizen joins mid-watch: the roster reloads exactly once, and grows."""
    root = _build_registry(tmp_path, ["alpha"])
    registry_file = root / "AIPASS_REGISTRY.json"
    reads = []
    real_read = baseline._read_registry_branches

    def counting_read(path):
        """Wrap the real parse so the test can count how often it happens."""
        reads.append(path)
        return real_read(path)

    def add_branch():
        """Register a second citizen and move the registry's mtime forward."""
        payload = json.loads(registry_file.read_text(encoding="utf-8"))
        gamma = root / "gamma"
        (gamma / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        payload["branches"].append({"name": "GAMMA", "email": "@gamma", "path": str(gamma)})
        registry_file.write_text(json.dumps(payload), encoding="utf-8")
        future = time.time() + 10
        os.utime(registry_file, (future, future))

    monkeypatch.setattr(baseline, "_read_registry_branches", counting_read)
    _tick_script(monkeypatch, [add_branch])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=4)

    assert len(reads) == 2, f"expected 1 initial parse + 1 reload, got {len(reads)}"
    assert result["branches"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Crash honesty — silence must never mean covered
# ─────────────────────────────────────────────────────────────────────────────


def test_unexpected_exception_kills_the_watch_loudly(monkeypatch, tmp_path, capsys):
    """An unexpected error announces BASELINE DEAD on stdout and exits nonzero.

    The species this pins (learning #420): a watcher that swallows the error and
    keeps looping looks alive to its owner while covering nothing.
    """
    root = _build_registry(tmp_path, ["alpha", "beta"])
    store = _store(tmp_path)
    scans = []

    def exploding_scan(name, branch_path, state):
        """Fail the way a real defect would — not an OSError the loop tolerates."""
        scans.append(name)
        raise RuntimeError("boom")

    monkeypatch.setattr(baseline, "_scan_branch", exploding_scan)
    _tick_script(monkeypatch, [])

    with pytest.raises(SystemExit) as excinfo:
        baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=5)

    assert excinfo.value.code != 0
    out = capsys.readouterr().out
    assert "BASELINE DEAD: RuntimeError: boom" in out
    # It died where it broke — it did not carry on to the next branch or tick.
    assert scans == ["alpha"]
    # ...and it did not leave a registry entry claiming live coverage.
    assert watch_registry.list_active(storage_path=store, prune_stale=False) == []


def test_per_branch_probe_error_is_survived_not_fatal(monkeypatch, tmp_path, capsys):
    """One branch failing to stat is an event to log — the other branches keep their watch."""
    root = _build_registry(tmp_path, ["alpha", "beta"])
    lock = _write_lock(root / "beta", pid=os.getpid(), subject="unaffected")
    real_stat = baseline._stat_lock

    def selective_stat(lock_file):
        """Deny alpha's lock the way a permissions/vanished-dir miss would."""
        if lock_file.parent.parent.name == "alpha":
            raise PermissionError(13, "Permission denied")
        return real_stat(lock_file)

    monkeypatch.setattr(baseline, "_stat_lock", selective_stat)
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    captured = capsys.readouterr()
    assert result["state"] == "stopped"
    assert result["ticks"] == 3
    lines = _completion_lines(captured.out)
    assert len(lines) == 1
    assert 'subject="unaffected"' in lines[0]
    # Announced once on the diagnostic channel, never as a wake event.
    assert captured.err.count("@alpha probe failed") == 1
    assert "BASELINE DEAD" not in captured.out


def test_missing_registry_is_fatal(tmp_path, capsys):
    """No roster means no coverage — that must be loud, not an empty quiet watch."""
    root = tmp_path / "no_repo"
    root.mkdir()

    with pytest.raises(SystemExit) as excinfo:
        baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=1)

    assert excinfo.value.code != 0
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "AIPASS_REGISTRY.json" in out


def test_empty_roster_is_fatal(monkeypatch, tmp_path, capsys):
    """A registry with nothing but devpulse is a watcher watching nothing."""
    root = _build_registry(tmp_path, [])
    store = _store(tmp_path)
    _tick_script(monkeypatch, [])

    with pytest.raises(SystemExit) as excinfo:
        baseline.watch_baseline(repo_root=root, storage_path=store, poll_interval=0.0, max_ticks=1)

    assert excinfo.value.code != 0
    out = capsys.readouterr().out
    assert "BASELINE DEAD" in out
    assert "roster is empty" in out
    assert watch_registry.list_active(storage_path=store, prune_stale=False) == []


def test_unreadable_registry_at_startup_is_fatal(monkeypatch, tmp_path, capsys):
    """A corrupt registry cannot be shrugged off into an empty roster."""
    root = _build_registry(tmp_path, ["alpha"])
    (root / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
    _tick_script(monkeypatch, [])

    with pytest.raises(SystemExit) as excinfo:
        baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=1)

    assert excinfo.value.code != 0
    assert "BASELINE DEAD" in capsys.readouterr().out


def test_registry_unreadable_mid_watch_keeps_the_roster(monkeypatch, tmp_path, capsys):
    """A registry caught mid-rewrite is a retry, not a death — the roster held stands."""
    root = _build_registry(tmp_path, ["alpha"])
    registry_file = root / "AIPASS_REGISTRY.json"
    lock = _write_lock(root / "alpha", pid=os.getpid(), subject="still watched")

    def corrupt_registry():
        """Torn registry write — new mtime, unparseable content."""
        registry_file.write_text("{half-writ", encoding="utf-8")
        future = time.time() + 10
        os.utime(registry_file, (future, future))

    _tick_script(monkeypatch, [corrupt_registry, lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=4)

    captured = capsys.readouterr()
    assert result["state"] == "stopped"
    assert result["branches"] == 1
    lines = _completion_lines(captured.out)
    assert len(lines) == 1
    assert 'subject="still watched"' in lines[0]
    assert "AIPASS_REGISTRY.json re-read failed" in captured.err


# ─────────────────────────────────────────────────────────────────────────────
# Event line shape
# ─────────────────────────────────────────────────────────────────────────────


def test_event_line_survives_a_multiline_subject(tmp_path):
    """One completion is one line — a newline in a subject cannot split the event."""
    state = baseline.BranchState()
    state.lock_data = {"subject": 'ship\nit  "now"', "pid": 1}
    state.lock_stamp = time.time() - 5
    record = baseline._completion_record("alpha", tmp_path, state, "completed")

    line = baseline._format_completion(record)
    assert "\n" not in line
    assert line.count('subject="') == 1
    assert "ship it 'now'" in line


# ─────────────────────────────────────────────────────────────────────────────
# Hosted project citizens — projects/*/*_REGISTRY.json
#
# The live catch (2026-08-18 20:14): @baud completed and the baseline said
# nothing. The watcher was alive and healthy; its roster had never contained
# baud, because citizens hosted in projects live in per-project registries.
# ─────────────────────────────────────────────────────────────────────────────


def test_project_citizen_completion_is_reported(monkeypatch, tmp_path, capsys):
    """A citizen in projects/*/*_REGISTRY.json wakes the baseline like any other."""
    root = _build_registry(tmp_path, ["alpha"])
    _add_project_citizen(root, "baud", "baud")
    lock = _write_lock(root / "projects" / "baud" / "src" / "baud" / "baud", pid=os.getpid(), subject="phone lane")
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert lines[0].startswith('COMPLETE @baud subject="phone lane" age=')
    assert result["branches"] == 2


def test_project_citizen_path_resolves_against_its_own_project_root(tmp_path):
    """ "src/baud/baud" is relative to projects/baud — not to the repo root."""
    root = _build_registry(tmp_path, ["alpha"])
    _add_project_citizen(root, "baud", "baud")

    roster = baseline.Roster(root / "AIPASS_REGISTRY.json")
    roster.refresh(required=True)

    resolved = dict(roster.branches)
    assert resolved["baud"].resolve() == (root / "projects" / "baud" / "src" / "baud" / "baud").resolve()


def test_arm_line_reports_the_root_projects_split(monkeypatch, tmp_path, capsys):
    """The count split is what makes a coverage gap visible at a glance."""
    root = _build_registry(tmp_path, ["alpha"])
    _add_project_citizen(root, "baud", "baud")
    _tick_script(monkeypatch, [])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=1)

    assert "branches=2 (root=1 projects=1)" in capsys.readouterr().err


def test_new_project_registry_joins_the_roster_mid_watch(monkeypatch, tmp_path, capsys):
    """The projects glob runs every tick — a project born mid-watch needs no restart."""
    root = _build_registry(tmp_path, ["alpha"])
    holder = {}

    def host_a_project():
        """A new project is sealed while the watcher is already running."""
        _add_project_citizen(root, "earmark", "earmark")
        holder["lock"] = _write_lock(
            root / "projects" / "earmark" / "src" / "earmark" / "earmark",
            pid=os.getpid(),
            subject="brand new",
        )

    def finish_the_run():
        """...and the new citizen's first run ends."""
        holder["lock"].unlink()

    _tick_script(monkeypatch, [host_a_project, lambda: None, finish_the_run])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=5)

    lines = _completion_lines(capsys.readouterr().out)
    assert len(lines) == 1, lines
    assert 'COMPLETE @earmark subject="brand new"' in lines[0]
    assert result["branches"] == 2


def test_project_registry_vanishing_mid_watch_shrinks_the_roster(monkeypatch, tmp_path, capsys):
    """A project leaving costs its own citizens their watch — never the whole watch."""
    root = _build_registry(tmp_path, ["alpha"])
    project_registry = _add_project_citizen(root, "baud", "baud")
    _tick_script(monkeypatch, [project_registry.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    captured = capsys.readouterr()
    assert result["state"] == "stopped"
    assert result["branches"] == 1
    assert "BAUD_REGISTRY.json is gone" in captured.err
    assert "BASELINE DEAD" not in captured.out


def test_broken_project_registry_does_not_kill_the_watch(monkeypatch, tmp_path, capsys):
    """One project's corrupt registry must not take fleet-wide coverage down."""
    root = _build_registry(tmp_path, ["alpha"])
    project_registry = _add_project_citizen(root, "baud", "baud")
    project_registry.write_text("{half-writ", encoding="utf-8")
    lock = _write_lock(root / "alpha", pid=os.getpid(), subject="still watched")
    _tick_script(monkeypatch, [lock.unlink])

    result = baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=3)

    captured = capsys.readouterr()
    assert result["state"] == "stopped"
    assert result["branches"] == 1
    assert "BAUD_REGISTRY.json re-read failed" in captured.err
    assert "BASELINE DEAD" not in captured.out
    assert 'subject="still watched"' in _completion_lines(captured.out)[0]


def test_root_registry_wins_a_name_collision_with_a_project(tmp_path):
    """Same rule agent.py ships: a local branch always wins the name."""
    root = _build_registry(tmp_path, ["twin"])
    _add_project_citizen(root, "shadow", "twin")

    roster = baseline.Roster(root / "AIPASS_REGISTRY.json")
    roster.refresh(required=True)

    resolved = dict(roster.branches)
    assert len(roster.branches) == 1
    assert resolved["twin"].resolve() == (root / "twin").resolve()
    assert roster.root_count == 1
    assert roster.project_count == 0


def test_each_registry_is_parsed_only_when_its_own_mtime_moves(monkeypatch, tmp_path):
    """The mtime gate is PER FILE — touching a project must not re-parse the root."""
    root = _build_registry(tmp_path, ["alpha"])
    root_registry = root / "AIPASS_REGISTRY.json"
    project_registry = _add_project_citizen(root, "baud", "baud")
    parses = {}
    real_read = baseline._read_registry_branches

    def counting_read(path):
        """Wrap the real parse so the test can count it per file."""
        parses[path.name] = parses.get(path.name, 0) + 1
        return real_read(path)

    def touch_the_project_only():
        """The project seals a change; the root registry is untouched."""
        payload = json.loads(project_registry.read_text(encoding="utf-8"))
        payload["branches"][0]["description"] = "changed"
        project_registry.write_text(json.dumps(payload), encoding="utf-8")
        future = time.time() + 10
        os.utime(project_registry, (future, future))

    monkeypatch.setattr(baseline, "_read_registry_branches", counting_read)
    _tick_script(monkeypatch, [lambda: None, touch_the_project_only])

    baseline.watch_baseline(repo_root=root, storage_path=_store(tmp_path), poll_interval=0.0, max_ticks=6)

    assert parses[root_registry.name] == 1, f"root re-parsed {parses[root_registry.name]}x — per-file gate leaking"
    assert parses[project_registry.name] == 2, (
        f"project parsed {parses[project_registry.name]}x — expected 1 + 1 reload"
    )
