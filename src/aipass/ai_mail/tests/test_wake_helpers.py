# =================== AIPass ====================
# Name: test_wake_helpers.py
# Description: Tests for the wake's small parts - dispatch status, the grant read, pid lock and branch resolution
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/dispatch/wake.py's helpers and pid_lock.py: status, locks, pids, resolve_branch."""

# Split out of test_wake.py on 2026-10-08 to keep that file under the 1,200-line
# target: the parts a wake is built from, each pinned on its own.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — wake_branch()'s own lanes and gates: tests/test_wake.py

import json
import os
import subprocess
import pytest
from datetime import datetime, timedelta
from pathlib import Path as _Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
import aipass.ai_mail.apps.handlers.dispatch.pid_lock as pid_lock_mod
from aipass.ai_mail.apps.handlers.dispatch.pid_lock import (
    acquire_lock,
    check_lock,
    check_pid_alive,
    clean_zombies,
    is_branch_occupied,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import (
    resolve_branch,
    DispatchStatus,
    KNOWN_MODEL_ALIASES,
    DEFAULT_MODEL,
    wake_branch,
)
from aipass.ai_mail.tests.support_wake import (
    _claude_args,
    _make_wake_fixtures,
    _patch_wake_deps,
    _record_spawn_routes,
)

pytestmark = pytest.mark.usefixtures("wake_log_operation_suppressed")


# --- DispatchStatus tests --------------------------------------------


def test_dispatch_status_ok_step():
    """ok() appends a step with 'ok' status."""
    ds = DispatchStatus()
    ds.ok("resolve", "found it")
    assert ds.steps == [("ok", "resolve", "found it")]
    assert ds.success is True


def test_dispatch_status_fail_marks_failure():
    """fail() appends a step and sets success to False."""
    ds = DispatchStatus()
    ds.ok("step1", "good")
    ds.fail("step2", "bad")
    assert ds.success is False
    assert len(ds.steps) == 2
    assert ds.steps[1][0] == "fail"


def test_dispatch_status_summary_uses_last_step():
    """summary property returns label: detail of the last step."""
    ds = DispatchStatus()
    ds.ok("resolve", "found")
    ds.info("delivery", "routed")
    assert ds.summary == "delivery: routed"


def test_dispatch_status_summary_empty():
    """summary returns 'no status' when no steps recorded."""
    ds = DispatchStatus()
    assert ds.summary == "no status"


def test_dispatch_status_find_step_returns_match():
    """find_step() returns the full (status, label, detail) tuple."""
    ds = DispatchStatus()
    ds.ok("resolve", "found")
    ds.info("manager", "@devpulse is a manager — mail only, wake skipped")
    assert ds.find_step("manager") == ("info", "manager", "@devpulse is a manager — mail only, wake skipped")


def test_dispatch_status_find_step_missing_returns_none():
    """find_step() returns None when the label was never recorded."""
    ds = DispatchStatus()
    ds.ok("resolve", "found")
    assert ds.find_step("manager") is None


def test_dispatch_status_find_step_distinguishes_gate_outcomes():
    """The manager label carries ok (daemon bypass) vs info (skipped) — callers rely on it."""
    skipped = DispatchStatus()
    skipped.info("manager", "mail only, wake skipped")
    bypassed = DispatchStatus()
    bypassed.ok("manager", "gate bypassed — daemon-scheduled self-wake")
    skipped_step = skipped.find_step("manager")
    bypassed_step = bypassed.find_step("manager")
    assert skipped_step is not None and bypassed_step is not None
    assert skipped_step[0] == "info"
    assert bypassed_step[0] == "ok"


def test_dispatch_status_find_step_returns_last_occurrence():
    """A repeated label resolves to the most recent record."""
    ds = DispatchStatus()
    ds.info("spawn", "first try")
    ds.ok("spawn", "second try")
    assert ds.find_step("spawn") == ("ok", "spawn", "second try")


def test_dispatch_status_format_output():
    """format() produces multi-line output with icons."""
    ds = DispatchStatus()
    ds.ok("resolve", "found")
    ds.fail("spawn", "died")
    output = ds.format()
    lines = output.strip().split("\n")
    assert len(lines) == 2
    assert "resolve" in lines[0]
    assert "spawn" in lines[1]


# --- _read_json tests ------------------------------------------------


# Read through fable_allowed(), the public reader of the wake config, not called
# directly. A missing file and a corrupt one both fall to the
# default grant; only the corrupt one is warned about.


def _grant_from(monkeypatch, config_file):
    """The Fable grant read from `config_file`, and the logger that saw the read."""
    monkeypatch.setattr(wake_mod, "CONFIG_FILE", config_file)
    log = MagicMock()
    monkeypatch.setattr(wake_mod, "logger", log)
    return wake_mod.fable_allowed(), log


def test_read_json_valid(tmp_path, monkeypatch):
    """Valid JSON file returns parsed dict."""
    f = tmp_path / "data.json"
    f.write_text(json.dumps({wake_mod.FABLE_GRANT_KEY: ["@vera"]}), encoding="utf-8")
    grant, log = _grant_from(monkeypatch, f)
    assert grant == frozenset({"@vera"})
    log.warning.assert_not_called()


def test_read_json_missing_file(tmp_path, monkeypatch):
    """Missing file returns None: the default grant, and nothing to warn about."""
    grant, log = _grant_from(monkeypatch, tmp_path / "nope.json")
    assert grant == wake_mod.FABLE_GRANT_DEFAULT
    log.warning.assert_not_called()


def test_read_json_corrupt(tmp_path, monkeypatch):
    """Corrupt JSON raises JsonUnreadable, distinct from a missing file."""
    f = tmp_path / "bad.json"
    f.write_text("{not valid", encoding="utf-8")
    grant, log = _grant_from(monkeypatch, f)
    assert grant == wake_mod.FABLE_GRANT_DEFAULT
    fmt, raised = log.warning.call_args.args
    assert fmt == "[wake] %s — the Fable grant falls back to the default"
    assert isinstance(raised, wake_mod.JsonUnreadable)
    assert str(raised).startswith("bad.json could not be read")


# --- check_pid_alive tests -------------------------------------------


def test_check_pid_alive_dead(monkeypatch):
    """Dead PID returns False."""
    monkeypatch.setattr(os, "kill", _raise_process_lookup)
    assert check_pid_alive(99999) is False


def test_check_pid_alive_permission_error(monkeypatch):
    """PermissionError means process exists but cannot signal -- returns True."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(os, "kill", _raise_permission)
    assert check_pid_alive(1) is True


def test_check_pid_alive_running_non_zombie(monkeypatch, tmp_path):
    """Running non-zombie process returns True on Linux."""
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr("sys.platform", "linux")
    # Create a fake /proc/{pid}/status
    proc_dir = tmp_path / "proc" / "42"
    proc_dir.mkdir(parents=True)
    status_file = proc_dir / "status"
    status_file.write_text("Name:\tfake\nState:\tS (sleeping)\n", encoding="utf-8")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(status_file), {"/proc/42/status": str(status_file)}),
    )
    assert check_pid_alive(42) is True


def test_check_pid_alive_zombie(monkeypatch, tmp_path):
    """Zombie process (State: Z) returns False on Linux."""
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr("sys.platform", "linux")
    proc_dir = tmp_path / "proc" / "42"
    proc_dir.mkdir(parents=True)
    status_file = proc_dir / "status"
    status_file.write_text("Name:\tfake\nState:\tZ (zombie)\n", encoding="utf-8")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(status_file), {"/proc/42/status": str(status_file)}),
    )
    assert check_pid_alive(42) is False


# --- pid_lock's process readers, through is_branch_occupied -----------
#
# The cwd and session-type readers are reached through the occupancy check,
# their one caller: one claude pid, its cwd, its session type.
# A blocking session reads occupied; a dispatched/daemon one, a cwd elsewhere,
# or a cwd that cannot be read, reads free. The darwin branch is a synthetic
# POSIX literal, never a tmp_path: lsof output is DATA the parser reads, and on
# a Windows runner a tmp_path is a drive-letter path (CI 35058244702). Both the
# branch and the cwd go through the same resolve(), so they compare alike there.

# Data, never a host path: built from the root separator, so lsof's name line is
# "/private/..." on every runner and nothing on disk is read or owned.
_DARWIN_BRANCH = _Path(os.sep, "private", "var", "folders", "aipass", "pytest-project")


class _Ran:
    """A finished process: its return code and stdout."""

    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _processes(monkeypatch, pid, lsof=None, ps=None):
    """pgrep answers one claude *pid*; lsof and ps answer as handed (darwin)."""

    def run(cmd, *a, **kw):
        if cmd[0] == "pgrep":
            return _Ran(0, f"{pid}\n")
        answer = {"lsof": lsof, "ps": ps}[cmd[0]]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(subprocess, "run", run)


def _linux_claude_in(monkeypatch, tmp_path, branch, environ):
    """A linux claude pid 123 standing in *branch*, its environ holding *environ*."""
    monkeypatch.setattr("sys.platform", "linux")
    _processes(monkeypatch, 123)
    monkeypatch.setattr(os, "readlink", lambda p: str(branch.resolve()) if p == "/proc/123/cwd" else "")
    env_file = tmp_path / "environ"
    env_file.write_bytes(environ)
    monkeypatch.setattr("builtins.open", _fake_open_factory(str(env_file), {"/proc/123/environ": str(env_file)}))


def test_read_session_type_found(monkeypatch, tmp_path):
    """Linux: a daemon session read from the environ does not block."""
    environ = b"HOME=/home/user\x00AIPASS_SESSION_TYPE=daemon\x00PATH=/usr/bin\x00"
    _linux_claude_in(monkeypatch, tmp_path, tmp_path, environ)
    assert is_branch_occupied(tmp_path) is False


def test_read_session_type_not_set(monkeypatch, tmp_path):
    """Linux: no session type in the environ reads interactive, which blocks."""
    _linux_claude_in(monkeypatch, tmp_path, tmp_path, b"HOME=/home/user\x00PATH=/usr/bin\x00")
    assert is_branch_occupied(tmp_path) is True


def test_read_session_type_non_linux(monkeypatch, tmp_path):
    """win32: no cwd can be read, so no session in the branch is seen and it reads free.

    The session-type reader's own win32 arm sits behind this: through its one
    caller it is never reached on win32, since the cwd read answers None first.
    """
    monkeypatch.setattr("sys.platform", "win32")
    _processes(monkeypatch, 123)
    monkeypatch.setattr(os, "readlink", lambda p: str(tmp_path.resolve()))
    assert is_branch_occupied(tmp_path) is False


def test_read_session_type_unreadable_environ(monkeypatch, tmp_path):
    """Linux: an environ that cannot be opened answers interactive, the blocking class.

    Moved from test_daemon.py when the daemon took wake's reader (ai_mail,
    leg 12; todo 39). The open is made to raise, so no host /proc is read.
    """
    _linux_claude_in(monkeypatch, tmp_path, tmp_path, b"")

    def _no_environ(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr("builtins.open", _no_environ)
    assert is_branch_occupied(tmp_path) is True


def _darwin_claude(monkeypatch, cwd_stdout, ps):
    """A darwin claude pid 123: lsof answers *cwd_stdout*, ps answers *ps*."""
    monkeypatch.setattr("sys.platform", "darwin")
    _processes(monkeypatch, 123, lsof=_Ran(0, cwd_stdout), ps=ps)


def test_read_session_type_darwin_found(monkeypatch):
    """macOS: a dispatched session read from ps -wwE does not block."""
    ps = _Ran(0, "/usr/bin/claude AIPASS_SESSION_TYPE=dispatched HOME=/Users/u")
    _darwin_claude(monkeypatch, f"p123\nn{_DARWIN_BRANCH.as_posix()}\n", ps)
    assert is_branch_occupied(_DARWIN_BRANCH) is False


def test_read_session_type_darwin_not_set(monkeypatch):
    """macOS: no session type in ps output reads interactive, which blocks."""
    _darwin_claude(monkeypatch, f"p123\nn{_DARWIN_BRANCH.as_posix()}\n", _Ran(0, "/usr/bin/claude HOME=/Users/u"))
    assert is_branch_occupied(_DARWIN_BRANCH) is True


def test_read_session_type_darwin_ps_failure(monkeypatch):
    """macOS: a ps that fails reads interactive, which blocks."""
    _darwin_claude(monkeypatch, f"p123\nn{_DARWIN_BRANCH.as_posix()}\n", _Ran(1))
    assert is_branch_occupied(_DARWIN_BRANCH) is True


def test_get_pid_cwd_linux(monkeypatch, tmp_path):
    """Linux: the cwd is read from /proc/{pid}/cwd; a session standing there blocks."""
    _linux_claude_in(monkeypatch, tmp_path, tmp_path / "project", b"PATH=/usr/bin\x00")
    assert is_branch_occupied(tmp_path / "project") is True
    assert is_branch_occupied(tmp_path / "elsewhere") is False


def test_get_pid_cwd_linux_oserror(monkeypatch, tmp_path):
    """Linux: a cwd that cannot be read is no session in the branch."""
    _linux_claude_in(monkeypatch, tmp_path, tmp_path, b"PATH=/usr/bin\x00")
    monkeypatch.setattr(os, "readlink", lambda p: (_ for _ in ()).throw(OSError("no proc")))
    assert is_branch_occupied(tmp_path) is False


def test_get_pid_cwd_darwin(monkeypatch):
    """macOS: the cwd is read from lsof's name line; a session standing there blocks."""
    _darwin_claude(monkeypatch, f"p123\nn{_DARWIN_BRANCH.as_posix()}\n", _Ran(0, "/usr/bin/claude"))
    assert is_branch_occupied(_DARWIN_BRANCH) is True
    assert is_branch_occupied(_DARWIN_BRANCH.parent) is False


def test_get_pid_cwd_darwin_ignores_a_name_line_that_is_not_an_absolute_path(monkeypatch):
    """The leading slash is load-bearing: 'n' alone is not a cwd.

    lsof -Fn prefixes every name line with 'n'; the parser takes only the ones
    that are absolute POSIX paths. Without the slash a non-path name line would
    be returned as a cwd, and this branch, named the same, would read occupied.
    This is the mechanism behind CI 35058244702.
    """
    _darwin_claude(monkeypatch, "p123\nnD:\\build\\project\n", _Ran(0, "/usr/bin/claude"))
    assert is_branch_occupied(_Path("D:\\build\\project")) is False


def test_get_pid_cwd_darwin_failure(monkeypatch):
    """macOS: an lsof that fails is no session in the branch, even when it printed a name line."""
    monkeypatch.setattr("sys.platform", "darwin")
    failed = _Ran(1, f"p123\nn{_DARWIN_BRANCH.as_posix()}\n")
    _processes(monkeypatch, 123, lsof=failed, ps=_Ran(0, "/usr/bin/claude"))
    assert is_branch_occupied(_DARWIN_BRANCH) is False


def test_get_pid_cwd_unsupported_platform(monkeypatch, tmp_path):
    """An unsupported platform reads no cwd, even where /proc would name the branch."""
    monkeypatch.setattr("sys.platform", "sunos5")
    _processes(monkeypatch, 123)
    monkeypatch.setattr(os, "readlink", lambda p: str(tmp_path.resolve()))
    assert is_branch_occupied(tmp_path) is False


# test_is_zombie_linux_not_zombie and _zombie retired: they
# pinned the same two answers as test_check_pid_alive_running_non_zombie and
# test_check_pid_alive_zombie above, which reach the reader through its caller.


def test_is_zombie_linux_no_proc(monkeypatch):
    """Linux: a pid that answers the signal but has no /proc entry reads alive, not zombie."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    _real_open = open

    def _fake_open(path, *a, **kw):
        if "/proc/99999/" in str(path):
            raise FileNotFoundError(path)
        return _real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", _fake_open)
    assert check_pid_alive(99999) is True


# --- check_lock tests -------------------------------------------------


def test_check_lock_no_file(tmp_path):
    """No lock file returns None."""
    result = check_lock(tmp_path)
    assert result is None


def test_check_lock_alive_pid(tmp_path, monkeypatch):
    """Lock with alive PID returns the lock data."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 1234, "timestamp": "2026-03-29T10:00:00"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    alive = MagicMock(return_value=True)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)
    result = check_lock(tmp_path)
    assert result is not None
    assert result["pid"] == 1234
    alive.assert_called_once_with(1234)


def test_check_lock_dead_pid_removes_lock(tmp_path, monkeypatch):
    """Lock with dead PID removes the lock file and returns None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": "2026-03-29T10:00:00"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)
    result = check_lock(tmp_path)
    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_stale_old_timestamp(tmp_path, monkeypatch):
    """Lock with dead PID and timestamp >10 min old is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat()
    lock_data = {"pid": 99999, "timestamp": old_ts}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(os, "kill", _raise_process_lookup)
    result = check_lock(tmp_path)
    assert result is None
    assert not lock_file.exists()


def test_check_lock_permission_error_treated_active(tmp_path, monkeypatch):
    """Lock PID that raises PermissionError is treated as active."""
    monkeypatch.setattr("sys.platform", "linux")
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 1, "timestamp": "2026-03-29T10:00:00"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(os, "kill", _raise_permission)
    result = check_lock(tmp_path)
    assert result is not None
    assert result["pid"] == 1


def test_check_lock_fresh_corrupt_json_is_held(tmp_path):
    """A corrupt lock younger than the grace is a writer mid-write: held, not removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json", encoding="utf-8")
    result = check_lock(tmp_path)
    assert result is not None
    assert lock_file.exists()


def test_check_lock_old_corrupt_json_is_reclaimed(tmp_path):
    """A corrupt lock an hour old is a crashed writer's leftover: removed, None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json", encoding="utf-8")
    hour_ago = lock_file.stat().st_mtime - 3600
    os.utime(lock_file, (hour_ago, hour_ago))
    result = check_lock(tmp_path)
    assert result is None
    assert not lock_file.exists()


def test_check_lock_unreadable_is_held(tmp_path):
    """A lock that cannot be read at all is held and left in place.

    A directory where the lock file belongs cannot be read as text; the wake
    once answered None for it and the daemon tried to remove it.
    """
    lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
    lock_file.mkdir(parents=True)
    result = check_lock(tmp_path)
    assert result is not None
    assert lock_file.exists()


# --- resolve_branch tests --------------------------------------------


def test_resolve_branch_found(repo_root):
    """Resolves @branch to (Path, email) when registry entry exists."""
    branch_dir = repo_root / "src" / "aipass" / "flow"
    branch_dir.mkdir(parents=True)
    registry = {
        "branches": [
            {"email": "@flow", "path": "src/aipass/flow"},
        ]
    }
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    result = resolve_branch("@flow")
    assert result is not None
    path, email = result
    assert path == branch_dir
    assert email == "@flow"


def test_resolve_branch_not_in_registry(repo_root):
    """Returns None if branch is not in registry."""
    registry = {"branches": []}
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    result = resolve_branch("@ghost")
    assert result is None


def test_resolve_branch_no_registry(repo_root, monkeypatch):
    """Returns None when registry file does not exist.

    Clears AIPASS_CALLER_CWD explicitly: with it set, step 2's caller-project
    walk finds the real repo registry and this test would assert the opposite
    of its own name depending on who ran it.
    """
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    result = resolve_branch("@flow")
    assert result is None


def test_resolve_branch_directory_missing(repo_root):
    """Returns None when registry entry path does not exist on disk."""
    registry = {
        "branches": [
            {"email": "@flow", "path": "src/aipass/flow"},
        ]
    }
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    # Do NOT create the directory
    result = resolve_branch("@flow")
    assert result is None


def test_resolve_branch_case_insensitive(repo_root):
    """Branch resolution is case-insensitive."""
    branch_dir = repo_root / "src" / "aipass" / "flow"
    branch_dir.mkdir(parents=True)
    registry = {
        "branches": [
            {"email": "@Flow", "path": "src/aipass/flow"},
        ]
    }
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    result = resolve_branch("@FLOW")
    assert result is not None
    _, email = result
    assert email == "@flow"


def test_resolve_branch_absolute_path(repo_root):
    """Absolute path in registry is used directly."""
    branch_dir = repo_root / "absolute" / "branch"
    branch_dir.mkdir(parents=True)
    registry = {
        "branches": [
            {"email": "@abs", "path": str(branch_dir)},
        ]
    }
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    result = resolve_branch("@abs")
    assert result is not None
    path, _ = result
    assert path == branch_dir


def test_resolve_branch_strips_leading_at(repo_root):
    """Input with or without leading @ resolves the same."""
    branch_dir = repo_root / "src" / "aipass" / "flow"
    branch_dir.mkdir(parents=True)
    registry = {
        "branches": [
            {"email": "@flow", "path": "src/aipass/flow"},
        ]
    }
    wake_mod.BRANCH_REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
    result_with = resolve_branch("@flow")
    result_without = resolve_branch("flow")
    assert result_with is not None
    assert result_without is not None
    assert result_with[1] == result_without[1]


# --- clean_zombies tests --------------------------------------------


def test_clean_zombies_finds_zombie(monkeypatch):
    """Detects zombie claude processes from ps output."""

    class FakeResult:
        stdout = "  100 Z+   claude\n  200 Ss   claude\n  300 Z    claude\n"
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: FakeResult(),
    )
    count = clean_zombies()
    assert count == 2


def test_clean_zombies_none_found(monkeypatch):
    """Returns 0 when no zombie processes exist."""

    class FakeResult:
        stdout = "  PID STAT COMM\n  200 Ss   claude\n"
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: FakeResult(),
    )
    count = clean_zombies()
    assert count == 0


def test_clean_zombies_counts_a_codex_zombie_and_never_another_process(monkeypatch):
    class FakeResult:
        stdout = "  100 Z+   codex\n  200 Z    node\n  300 Ss   codex\n"
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeResult())
    assert clean_zombies() == 1


def test_clean_zombies_subprocess_error(monkeypatch):
    """Returns 0 on subprocess failure."""
    monkeypatch.setattr(
        "subprocess.run",
        _raise_subprocess_error,
    )
    count = clean_zombies()
    assert count == 0


# --- Helpers ---------------------------------------------------------

_REAL_OPEN = open


def _raise_process_lookup(pid, sig):
    raise ProcessLookupError(f"No such process: {pid}")


def _raise_permission(pid, sig):
    raise PermissionError(f"Operation not permitted: {pid}")


def _raise_subprocess_error(*args, **kwargs):
    import subprocess

    raise subprocess.SubprocessError("failed")


def _fake_open_factory(real_status_path, mapping):
    """Return an open() replacement that redirects /proc paths to real files."""

    def _fake_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str in mapping:
            return _REAL_OPEN(mapping[path_str], *args, **kwargs)
        return _REAL_OPEN(path, *args, **kwargs)

    return _fake_open


# --- Model flag tests ---------------------------------------------------


def test_known_model_aliases_has_expected_entries():
    """KNOWN_MODEL_ALIASES should contain sonnet, opus, haiku."""
    assert "sonnet" in KNOWN_MODEL_ALIASES
    assert "opus" in KNOWN_MODEL_ALIASES
    assert "haiku" in KNOWN_MODEL_ALIASES


def test_default_model_is_opus():
    """Default model should be opus (the owner ruling 2026-08-01)."""
    assert DEFAULT_MODEL == "opus"


def test_known_model_aliases_are_bare_names():
    """All KNOWN_MODEL_ALIASES should be bare alias names (no 'claude-' prefix).

    The floor below is the whole point: the only assertion here is inside the
    loop, so emptying KNOWN_MODEL_ALIASES — which would break every wake — made
    this unit pass having checked nothing. Four is measured 2026-09-08: sonnet,
    opus, haiku, fable.
    """
    assert len(KNOWN_MODEL_ALIASES) == 4, sorted(KNOWN_MODEL_ALIASES)
    for alias in KNOWN_MODEL_ALIASES:
        assert not alias.startswith("claude-"), f"{alias} should be a bare alias"


# --- _find_claude_bin tests ------------------------------------------


class TestFindClaudeBin:
    """The claude binary, resolved by the wake that spawns it.

    Each row reads the command the wake handed the monitor, so the answer is
    the one a spawn carries. HOME/USERPROFILE name tmp_path so Path.home
    answers from the environment the platform reads. shutil.which is the
    stand-in for PATH, as in _record_spawn_routes.
    """

    def _wake(self, tmp_path, monkeypatch, claude_on_path):
        """Wake once with which answering *claude_on_path* for claude."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, resolve_claude=True)
        calls = _record_spawn_routes(monkeypatch)
        monkeypatch.setattr(wake_mod.shutil, "which", lambda name: claude_on_path if name == "claude" else None)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        status, ok = wake_branch("@testbranch")
        return status, ok, calls

    def test_uses_shutil_which_when_found(self, tmp_path, monkeypatch):
        """The PATH answer at the wake is the binary spawned, not one read at import."""
        on_path = str(tmp_path / "bin" / "claude")

        status, ok, calls = self._wake(tmp_path, monkeypatch, on_path)

        assert ok is True
        assert _claude_args(calls["popen"][0]["cmd"])[0] == on_path

    def test_falls_back_to_local_bin(self, tmp_path, monkeypatch):
        """Off PATH, ~/.local/bin/claude is the binary spawned."""
        fake_claude = tmp_path / ".local" / "bin" / "claude"
        fake_claude.parent.mkdir(parents=True)
        fake_claude.touch()

        status, ok, calls = self._wake(tmp_path, monkeypatch, None)

        assert ok is True
        assert _claude_args(calls["popen"][0]["cmd"])[0] == str(fake_claude)

    def test_falls_back_to_name_when_not_found(self, tmp_path, monkeypatch):
        """No binary anywhere refuses the wake by name: no spawn of a bare 'claude'."""
        status, ok, calls = self._wake(tmp_path, monkeypatch, None)

        assert ok is False
        assert calls["popen"] == []
        step = status.find_step("claude")
        assert step is not None
        assert step[0] == "fail"
        assert "PATH" in step[2]
        assert str(tmp_path / ".local" / "bin" / "claude") in step[2]


class TestResolveBranchCallerRegistry:
    """resolve_branch() falls back to caller's project registry for cross-project wake."""

    def test_resolves_from_caller_registry(self, tmp_path, monkeypatch):
        """Branch not in AIPass registry is found via AIPASS_CALLER_CWD."""
        # External branch path
        branch_path = tmp_path / "src" / "strategy"
        branch_path.mkdir(parents=True)
        (branch_path / ".ai_mail.local").mkdir()

        # External registry
        registry = {"branches": [{"name": "STRATEGY", "email": "@strategy", "path": str(branch_path)}]}
        (tmp_path / "VERA_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")

        # AIPass registry has no @strategy
        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(json.dumps({"branches": []}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", aipass_registry)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        result = resolve_branch("@strategy")
        assert result is not None
        resolved_path, email = result
        assert email == "@strategy"
        assert resolved_path == branch_path

    def test_aipass_registry_takes_precedence(self, tmp_path, monkeypatch):
        """AIPass registry result is returned before checking caller registry."""
        branch_path = tmp_path / "src" / "drone"
        branch_path.mkdir(parents=True)

        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(
            json.dumps({"branches": [{"name": "DRONE", "email": "@drone", "path": str(branch_path)}]}), encoding="utf-8"
        )
        monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", aipass_registry)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        result = resolve_branch("@drone")
        assert result is not None
        assert result[1] == "@drone"

    def test_returns_none_when_not_found_anywhere(self, tmp_path, monkeypatch):
        """Returns None when branch is missing from both registries."""
        aipass_registry = tmp_path / "AIPASS_REGISTRY.json"
        aipass_registry.write_text(json.dumps({"branches": []}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", aipass_registry)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        # No *_REGISTRY.json in tmp_path other than the aipass one (which has no @nonexistent)

        result = resolve_branch("@nonexistent")
        assert result is None


# ─── NEW LINE COVERAGE TESTS ──────────────────────────────────


# --- acquire_lock tests ------------------------------------------------


class TestAcquireLock:
    """Tests for acquire_lock() — atomic lock file creation."""

    def test_successful_lock_creation(self, tmp_path):
        """Successful lock writes pid, timestamp, and branch to JSON file."""
        ok, msg = acquire_lock(tmp_path, 12345)
        assert ok is True
        assert msg == "Lock acquired"
        lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
        assert lock_file.exists()
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        assert data["pid"] == 12345
        assert "timestamp" in data
        assert data["branch"] == str(tmp_path)

    def test_file_exists_error(self, tmp_path):
        """FileExistsError returns (False, 'Lock file already exists')."""
        lock_dir = tmp_path / ".ai_mail.local"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / ".dispatch.lock"
        lock_file.write_text("{}", encoding="utf-8")
        ok, msg = acquire_lock(tmp_path, 999)
        assert ok is False
        assert msg == "Lock file already exists"

    def test_os_error(self, tmp_path, monkeypatch):
        """OSError returns (False, error message)."""
        original_os_open = os.open

        def _fail_open(path, flags, *args, **kwargs):
            if ".dispatch.lock" in str(path):
                raise OSError("disk full")
            return original_os_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", _fail_open)
        ok, msg = acquire_lock(tmp_path, 999)
        assert ok is False
        assert "Lock failed:" in msg
        assert "disk full" in msg


# --- _load_config tests -------------------------------------------------


class TestLoadConfig:
    """The safety config's turn cap, read through the wake that spawns with it.

    The unreadable-config row is TestScheduledManagerLane's
    test_an_unreadable_safety_config_refuses_the_wake.
    """

    def _turns(self, tmp_path, monkeypatch, config_text=None):
        """The --max-turns value the wake handed claude."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        if config_text is not None:
            (tmp_path / "safety_config.json").write_text(config_text, encoding="utf-8")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        wake_branch("@testbranch")

        assert len(calls["popen"]) == 1
        args = _claude_args(calls["popen"][0]["cmd"])
        return args[args.index("--max-turns") + 1]

    def test_no_config_file_returns_defaults(self, tmp_path, monkeypatch):
        """Missing config file spawns with the default cap."""
        assert self._turns(tmp_path, monkeypatch) == "100"

    def test_partial_config_fills_defaults(self, tmp_path, monkeypatch):
        """Config file without max_turns_per_wake spawns with the default cap."""
        assert self._turns(tmp_path, monkeypatch, json.dumps({"other_key": "value"})) == "100"

    def test_full_config_returned(self, tmp_path, monkeypatch):
        """Config file's own cap is the one the spawn carries."""
        assert self._turns(tmp_path, monkeypatch, json.dumps({"max_turns_per_wake": 50})) == "50"


# --- is_branch_occupied tests -------------------------------------------


class TestIsBranchOccupied:
    """Tests for is_branch_occupied() — checks for interactive Claude sessions."""

    def test_no_claude_processes(self, tmp_path, monkeypatch):
        """pgrep returns non-zero (no claude processes) -> not occupied."""

        class FakeResult:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        assert is_branch_occupied(tmp_path) is False

    def test_claude_in_different_dir(self, tmp_path, monkeypatch):
        """Claude running in a different directory -> not occupied."""
        monkeypatch.setattr("sys.platform", "linux")

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        monkeypatch.setattr(os, "readlink", lambda p: "/some/other/dir")
        assert is_branch_occupied(tmp_path) is False

    def test_claude_in_same_dir_interactive(self, tmp_path, monkeypatch):
        """Claude in same dir with interactive session -> occupied."""
        monkeypatch.setattr("sys.platform", "linux")
        resolved = str(tmp_path.resolve())

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        monkeypatch.setattr(os, "readlink", lambda p: resolved)
        # _read_session_type returns "interactive" for this PID
        monkeypatch.setattr(pid_lock_mod, "_read_session_type", lambda pid_str: "interactive")
        assert is_branch_occupied(tmp_path) is True

    def test_claude_in_same_dir_daemon_not_blocking(self, tmp_path, monkeypatch):
        """Claude in same dir with daemon session -> not blocking."""
        monkeypatch.setattr("sys.platform", "linux")
        resolved = str(tmp_path.resolve())

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        monkeypatch.setattr(os, "readlink", lambda p: resolved)
        monkeypatch.setattr(pid_lock_mod, "_read_session_type", lambda pid_str: "daemon")
        assert is_branch_occupied(tmp_path) is False

    def test_an_interactive_codex_in_the_branch_occupies_it(self, tmp_path, monkeypatch):
        """pgrep is asked for codex as well as claude, exact-match; a codex in the dir blocks the wake."""
        import re

        monkeypatch.setattr("sys.platform", "linux")
        resolved = str(tmp_path.resolve())
        asked = []

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        def fake_run(cmd, **kw):
            asked.append(list(cmd))
            return FakeResult()

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(os, "readlink", lambda p: resolved)
        monkeypatch.setattr(pid_lock_mod, "_read_session_type", lambda pid_str: "interactive")

        assert is_branch_occupied(tmp_path) is True
        assert asked[0][:2] == ["pgrep", "-x"]
        assert all(re.fullmatch(asked[0][2], name) for name in ("claude", "codex"))
        assert not re.fullmatch(asked[0][2], "codex-helper")

    def test_pgrep_subprocess_failure_returns_false(self, tmp_path, monkeypatch):
        """subprocess failure returns False."""

        def _fail(*a, **kw):
            raise subprocess.SubprocessError("pgrep failed")

        monkeypatch.setattr(subprocess, "run", _fail)
        assert is_branch_occupied(tmp_path) is False

    def test_readlink_oserror_continues(self, tmp_path, monkeypatch):
        """OSError on readlink is caught, continues to next PID."""
        monkeypatch.setattr("sys.platform", "linux")

        class FakeResult:
            returncode = 0
            stdout = "100\n200\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())

        def _fail_readlink(p):
            raise OSError("no such file")

        monkeypatch.setattr(os, "readlink", _fail_readlink)
        assert is_branch_occupied(tmp_path) is False


def test_prepend_path_uses_the_platform_separator(monkeypatch):
    """The PATH joiner is os.pathsep, not a literal colon: a Windows PATH joined with ':' loses every entry after it."""
    monkeypatch.setattr(wake_mod.os, "pathsep", ";")
    env = {"PATH": "C:\\tools"}

    wake_mod.prepend_path(env, "C:\\venv\\Scripts")
    wake_mod.prepend_path(env, "C:\\venv\\Scripts")

    assert env["PATH"] == "C:\\venv\\Scripts;C:\\tools", "prepended once, joined with the platform separator"


def test_systemd_scope_env_file_does_not_outlive_the_launch(tmp_path, monkeypatch):
    """The environment copy handed to systemd-run is removed once the launch returns, pass or fail."""
    branch_path = tmp_path / "branch"
    (branch_path / "logs").mkdir(parents=True)
    env_file = branch_path / "logs" / ".dispatch_env"
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["existed_during_launch"] = env_file.exists()
        return MagicMock(returncode=1, stderr="unit refused")

    monkeypatch.setattr(wake_mod.subprocess, "run", fake_run)

    ok = wake_mod.spawn_in_systemd_scope(["monitor"], branch_path, {"A": "1"}, "@target", tmp_path / "lock", None, None)

    assert ok is False
    assert seen["existed_during_launch"] is True, "systemd-run reads the file at launch"
    assert not env_file.exists(), "the environment copy must not stay on disk"
