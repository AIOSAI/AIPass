# =================== AIPass ====================
# Name: test_wake.py
# Description: Tests for wake dispatch handler
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-04-26
# =============================================

"""Tests for wake handler -- branch resolution, lock checking, PID checks, helpers."""

import json
import os
import subprocess
import pytest
from datetime import datetime, timedelta
from pathlib import Path as _Path

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
from aipass.ai_mail.apps.handlers.dispatch.wake import (
    _read_json,
    _check_lock,
    _check_pid_alive,
    _get_pid_cwd,
    _get_pid_cwd_darwin,
    _read_session_type,
    _read_session_type_darwin,
    _is_zombie_linux,
    _clean_zombies,
    _find_claude_bin,
    resolve_branch,
    DispatchStatus,
    KNOWN_MODEL_ALIASES,
    DEFAULT_MODEL,
    _acquire_lock,
    _load_config,
    _is_branch_occupied,
    wake_branch,
)


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.dispatch.wake.json_handler.log_operation",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    """Redirect _REPO_ROOT and BRANCH_REGISTRY to tmp_path."""
    registry_file = tmp_path / "AIPASS_REGISTRY.json"
    monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", registry_file)
    return tmp_path


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
    assert skipped.find_step("manager")[0] == "info"
    assert bypassed.find_step("manager")[0] == "ok"


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


def test_read_json_valid(tmp_path):
    """Valid JSON file returns parsed dict."""
    f = tmp_path / "data.json"
    f.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    result = _read_json(f)
    assert result == {"key": "value"}


def test_read_json_missing_file(tmp_path):
    """Missing file returns None."""
    result = _read_json(tmp_path / "nope.json")
    assert result is None


def test_read_json_corrupt(tmp_path):
    """Corrupt JSON returns None."""
    f = tmp_path / "bad.json"
    f.write_text("{not valid", encoding="utf-8")
    result = _read_json(f)
    assert result is None


# --- _check_pid_alive tests ------------------------------------------


def test_check_pid_alive_dead(monkeypatch):
    """Dead PID returns False."""
    monkeypatch.setattr(os, "kill", _raise_process_lookup)
    assert _check_pid_alive(99999) is False


def test_check_pid_alive_permission_error(monkeypatch):
    """PermissionError means process exists but cannot signal -- returns True."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(os, "kill", _raise_permission)
    assert _check_pid_alive(1) is True


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
    assert _check_pid_alive(42) is True


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
    assert _check_pid_alive(42) is False


# --- _read_session_type tests ----------------------------------------


def test_read_session_type_found(monkeypatch, tmp_path):
    """Reads AIPASS_SESSION_TYPE from proc environ."""
    monkeypatch.setattr("sys.platform", "linux")
    env_file = tmp_path / "environ"
    env_file.write_bytes(b"HOME=/home/user\x00AIPASS_SESSION_TYPE=daemon\x00PATH=/usr/bin\x00")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(env_file), {"/proc/123/environ": str(env_file)}),
    )
    assert _read_session_type("123") == "daemon"


def test_read_session_type_not_set(monkeypatch, tmp_path):
    """Missing env var returns 'interactive'."""
    monkeypatch.setattr("sys.platform", "linux")
    env_file = tmp_path / "environ"
    env_file.write_bytes(b"HOME=/home/user\x00PATH=/usr/bin\x00")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(env_file), {"/proc/456/environ": str(env_file)}),
    )
    assert _read_session_type("456") == "interactive"


def test_read_session_type_non_linux(monkeypatch):
    """Non-linux, non-darwin platform returns 'interactive' immediately."""
    monkeypatch.setattr("sys.platform", "win32")
    assert _read_session_type("999") == "interactive"


def test_read_session_type_darwin_found(monkeypatch):
    """macOS: reads AIPASS_SESSION_TYPE from ps -wwE output."""
    monkeypatch.setattr("sys.platform", "darwin")

    class FakeResult:
        returncode = 0
        stdout = "/usr/bin/claude AIPASS_SESSION_TYPE=dispatched HOME=/Users/u"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert _read_session_type("123") == "dispatched"


def test_read_session_type_darwin_not_set(monkeypatch):
    """macOS: missing env var returns 'interactive'."""
    monkeypatch.setattr("sys.platform", "darwin")

    class FakeResult:
        returncode = 0
        stdout = "/usr/bin/claude HOME=/Users/u"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert _read_session_type("456") == "interactive"


def test_read_session_type_darwin_ps_failure(monkeypatch):
    """macOS: ps failure returns 'interactive'."""
    assert _read_session_type_darwin("999") == "interactive"


# --- _get_pid_cwd tests ------------------------------------------------


def test_get_pid_cwd_linux(monkeypatch, tmp_path):
    """Linux: reads /proc/{pid}/cwd via readlink."""
    monkeypatch.setattr("sys.platform", "linux")
    target = str(tmp_path / "project")
    monkeypatch.setattr(os, "readlink", lambda p: target)
    assert _get_pid_cwd("100") == target


def test_get_pid_cwd_linux_oserror(monkeypatch):
    """Linux: OSError returns None."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(os, "readlink", lambda p: (_ for _ in ()).throw(OSError("no proc")))
    assert _get_pid_cwd("100") is None


def test_get_pid_cwd_darwin(monkeypatch, tmp_path):
    """macOS: reads cwd via lsof."""
    monkeypatch.setattr("sys.platform", "darwin")
    target = "/tmp/pytest-project"

    class FakeResult:
        returncode = 0
        stdout = f"p100\nn{target}\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert _get_pid_cwd("100") == target


def test_get_pid_cwd_darwin_failure(monkeypatch):
    """macOS: lsof failure returns None."""

    class FailedResult:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FailedResult())
    assert _get_pid_cwd_darwin("999") is None


def test_get_pid_cwd_unsupported_platform(monkeypatch):
    """Unsupported platform returns None."""
    monkeypatch.setattr("sys.platform", "win32")
    assert _get_pid_cwd("100") is None


# --- _is_zombie_linux tests --------------------------------------------


def test_is_zombie_linux_not_zombie(monkeypatch, tmp_path):
    """Non-zombie process returns False."""
    status_file = tmp_path / "status"
    status_file.write_text("Name:\tclaude\nState:\tS (sleeping)\nPid:\t42\n")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(status_file), {"/proc/42/status": str(status_file)}),
    )
    assert _is_zombie_linux(42) is False


def test_is_zombie_linux_zombie(monkeypatch, tmp_path):
    """Zombie process returns True."""
    status_file = tmp_path / "status"
    status_file.write_text("Name:\tclaude\nState:\tZ (zombie)\nPid:\t42\n")
    monkeypatch.setattr(
        "builtins.open",
        _fake_open_factory(str(status_file), {"/proc/42/status": str(status_file)}),
    )
    assert _is_zombie_linux(42) is True


def test_is_zombie_linux_no_proc(monkeypatch):
    """Missing /proc entry returns False (not zombie, just gone)."""
    _real_open = open

    def _fake_open(path, *a, **kw):
        if "/proc/99999/" in str(path):
            raise FileNotFoundError(path)
        return _real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", _fake_open)
    assert _is_zombie_linux(99999) is False


# --- _check_lock tests ------------------------------------------------


def test_check_lock_no_file(tmp_path):
    """No lock file returns None."""
    result = _check_lock(tmp_path)
    assert result is None


def test_check_lock_alive_pid(tmp_path, monkeypatch):
    """Lock with alive PID returns the lock data."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 1234, "timestamp": "2026-03-29T10:00:00"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(wake_mod, "_check_pid_alive", lambda pid: True)
    result = _check_lock(tmp_path)
    assert result is not None
    assert result["pid"] == 1234


def test_check_lock_dead_pid_removes_lock(tmp_path, monkeypatch):
    """Lock with dead PID removes the lock file and returns None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": "2026-03-29T10:00:00"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(wake_mod, "_check_pid_alive", lambda pid: False)
    result = _check_lock(tmp_path)
    assert result is None
    assert not lock_file.exists()


def test_check_lock_stale_old_timestamp(tmp_path, monkeypatch):
    """Lock with dead PID and timestamp >10 min old is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    old_ts = (datetime.now() - timedelta(minutes=15)).isoformat()
    lock_data = {"pid": 99999, "timestamp": old_ts}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")
    monkeypatch.setattr(os, "kill", _raise_process_lookup)
    result = _check_lock(tmp_path)
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
    result = _check_lock(tmp_path)
    assert result is not None
    assert result["pid"] == 1


def test_check_lock_corrupt_json(tmp_path):
    """Corrupt lock file returns None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json", encoding="utf-8")
    result = _check_lock(tmp_path)
    assert result is None


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


def test_resolve_branch_no_registry(repo_root):
    """Returns None when registry file does not exist."""
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


# --- _clean_zombies tests -------------------------------------------


def test_clean_zombies_finds_zombie(monkeypatch):
    """Detects zombie claude processes from ps output."""

    class FakeResult:
        stdout = "  100 Z+   claude\n  200 Ss   claude\n  300 Z    claude\n"
        returncode = 0

    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: FakeResult(),
    )
    count = _clean_zombies()
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
    count = _clean_zombies()
    assert count == 0


def test_clean_zombies_subprocess_error(monkeypatch):
    """Returns 0 on subprocess failure."""
    monkeypatch.setattr(
        "subprocess.run",
        _raise_subprocess_error,
    )
    count = _clean_zombies()
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
    """Default model should be opus (Patrick ruling 2026-08-01)."""
    assert DEFAULT_MODEL == "opus"


def test_known_model_aliases_are_bare_names():
    """All KNOWN_MODEL_ALIASES should be bare alias names (no 'claude-' prefix)."""
    for alias in KNOWN_MODEL_ALIASES:
        assert not alias.startswith("claude-"), f"{alias} should be a bare alias"


# --- _find_claude_bin tests ------------------------------------------


class TestFindClaudeBin:
    """Tests for _find_claude_bin() — resolves claude binary path."""

    def test_uses_shutil_which_when_found(self, monkeypatch):
        """Returns shutil.which result when claude is on PATH."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.shutil.which",
            lambda _: "/usr/local/bin/claude",
        )
        result = _find_claude_bin()
        assert result == "/usr/local/bin/claude"

    def test_falls_back_to_local_bin(self, monkeypatch, tmp_path):
        """Falls back to ~/.local/bin/claude when not on PATH."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.shutil.which",
            lambda _: None,
        )
        fake_local_bin = tmp_path / ".local" / "bin"
        fake_local_bin.mkdir(parents=True)
        fake_claude = fake_local_bin / "claude"
        fake_claude.touch()
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.Path.home",
            lambda: tmp_path,
        )
        result = _find_claude_bin()
        assert result == str(fake_claude)

    def test_falls_back_to_name_when_not_found(self, monkeypatch, tmp_path):
        """Returns bare 'claude' when no known location has the binary."""
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.shutil.which",
            lambda _: None,
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.Path.home",
            lambda: tmp_path,
        )
        result = _find_claude_bin()
        assert result == "claude"


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


class TestWakeBranchSpawnEnv:
    """Ensure wake_branch() spawn_env includes ~/.local/bin for restricted-PATH envs."""

    def test_spawn_env_includes_local_bin(self, tmp_path, monkeypatch):
        """spawn_env PATH includes ~/.local/bin even when not in os.environ PATH."""
        # Set up a minimal registry with one branch
        branch_path = tmp_path / "src" / "aipass" / "testbranch"
        branch_path.mkdir(parents=True)
        (branch_path / ".ai_mail.local").mkdir()
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        import json

        registry_file.write_text(
            json.dumps({"branches": [{"name": "TESTBRANCH", "email": "@testbranch", "path": str(branch_path)}]}),
            encoding="utf-8",
        )

        monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", registry_file)
        monkeypatch.setattr(wake_mod, "PAUSE_FILE", tmp_path / ".aipass" / "autonomous_pause")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", tmp_path / "safety_config.json")
        monkeypatch.setattr(wake_mod, "MONITOR_SCRIPT", tmp_path / "dispatch_monitor.py")
        (tmp_path / "dispatch_monitor.py").touch()

        # Strip ~/.local/bin from os.environ to simulate restricted PATH
        from pathlib import Path as _Path

        local_bin = str(_Path.home() / ".local" / "bin")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.delenv("INVOCATION_ID", raising=False)

        captured_envs: list = []

        def fake_popen(cmd, **kwargs):
            """Capture spawn_env without launching a real process."""
            captured_envs.append(kwargs.get("env", {}))

            class FakeProc:
                pid = 99999

            return FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(wake_mod, "_check_pid_alive", lambda pid: True)
        monkeypatch.setattr(wake_mod, "_clean_zombies", lambda: 0)
        monkeypatch.setattr(wake_mod, "_is_branch_occupied", lambda p: False)
        monkeypatch.setattr(wake_mod, "_acquire_lock", lambda p, pid: (True, "ok"))
        monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.time.sleep", lambda _: None)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )

        wake_mod.wake_branch("@testbranch", fresh=True)

        assert captured_envs, "Popen was not called"
        env = captured_envs[0]
        assert local_bin in env.get("PATH", ""), f"~/.local/bin not in spawn_env PATH: {env.get('PATH', '')}"


# ─── NEW LINE COVERAGE TESTS ──────────────────────────────────


# --- _acquire_lock tests -----------------------------------------------


class TestAcquireLock:
    """Tests for _acquire_lock() — atomic lock file creation."""

    def test_successful_lock_creation(self, tmp_path):
        """Successful lock writes pid, timestamp, and branch to JSON file."""
        ok, msg = _acquire_lock(tmp_path, 12345)
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
        ok, msg = _acquire_lock(tmp_path, 999)
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
        ok, msg = _acquire_lock(tmp_path, 999)
        assert ok is False
        assert "Lock failed:" in msg
        assert "disk full" in msg


# --- _load_config tests -------------------------------------------------


class TestLoadConfig:
    """Tests for _load_config() — safety config loading with defaults."""

    def test_no_config_file_returns_defaults(self, tmp_path, monkeypatch):
        """Missing config file returns default dict."""
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", tmp_path / "nonexistent.json")
        result = _load_config()
        assert result == {"max_turns_per_wake": 100}

    def test_partial_config_fills_defaults(self, tmp_path, monkeypatch):
        """Config file without max_turns_per_wake gets default filled in."""
        config_file = tmp_path / "safety_config.json"
        config_file.write_text(json.dumps({"other_key": "value"}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config_file)
        result = _load_config()
        assert result["max_turns_per_wake"] == 100
        assert result["other_key"] == "value"

    def test_full_config_returned(self, tmp_path, monkeypatch):
        """Config file with all keys returned as-is."""
        config_file = tmp_path / "safety_config.json"
        config_file.write_text(json.dumps({"max_turns_per_wake": 50}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config_file)
        result = _load_config()
        assert result["max_turns_per_wake"] == 50


# --- _is_branch_occupied tests ------------------------------------------


class TestIsBranchOccupied:
    """Tests for _is_branch_occupied() — checks for interactive Claude sessions."""

    def test_no_claude_processes(self, monkeypatch):
        """pgrep returns non-zero (no claude processes) -> not occupied."""

        class FakeResult:
            returncode = 1
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        assert _is_branch_occupied(_Path("/some/branch")) is False

    def test_claude_in_different_dir(self, tmp_path, monkeypatch):
        """Claude running in a different directory -> not occupied."""
        monkeypatch.setattr("sys.platform", "linux")

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        monkeypatch.setattr(os, "readlink", lambda p: "/some/other/dir")
        assert _is_branch_occupied(tmp_path) is False

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
        monkeypatch.setattr(wake_mod, "_read_session_type", lambda pid_str: "interactive")
        assert _is_branch_occupied(tmp_path) is True

    def test_claude_in_same_dir_daemon_not_blocking(self, tmp_path, monkeypatch):
        """Claude in same dir with daemon session -> not blocking."""
        monkeypatch.setattr("sys.platform", "linux")
        resolved = str(tmp_path.resolve())

        class FakeResult:
            returncode = 0
            stdout = "100\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
        monkeypatch.setattr(os, "readlink", lambda p: resolved)
        monkeypatch.setattr(wake_mod, "_read_session_type", lambda pid_str: "daemon")
        assert _is_branch_occupied(tmp_path) is False

    def test_pgrep_subprocess_failure_returns_false(self, monkeypatch):
        """subprocess failure returns False."""

        def _fail(*a, **kw):
            raise subprocess.SubprocessError("pgrep failed")

        monkeypatch.setattr(subprocess, "run", _fail)
        assert _is_branch_occupied(_Path("/some/branch")) is False

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
        assert _is_branch_occupied(tmp_path) is False


# --- wake_branch integration tests -------------------------------------


def _make_wake_fixtures(tmp_path, monkeypatch):
    """Helper: set up branch directory, registry, and monkeypatched module constants."""
    branch_path = tmp_path / "src" / "aipass" / "testbranch"
    branch_path.mkdir(parents=True)
    (branch_path / ".ai_mail.local").mkdir()

    registry_file = tmp_path / "AIPASS_REGISTRY.json"
    registry_file.write_text(
        json.dumps({"branches": [{"name": "TESTBRANCH", "email": "@testbranch", "path": str(branch_path)}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", registry_file)
    monkeypatch.setattr(wake_mod, "PAUSE_FILE", tmp_path / ".aipass" / "autonomous_pause")
    monkeypatch.setattr(wake_mod, "CONFIG_FILE", tmp_path / "safety_config.json")
    monkeypatch.setattr(wake_mod, "MONITOR_SCRIPT", tmp_path / "dispatch_monitor.py")
    (tmp_path / "dispatch_monitor.py").touch()

    return branch_path


def _patch_wake_deps(monkeypatch, **overrides):
    """Monkeypatch all wake_branch dependencies with sane defaults; override as needed."""
    defaults = {
        "_check_lock": lambda p: None,
        "_clean_zombies": lambda: 0,
        "_is_branch_occupied": lambda p: False,
        "_acquire_lock": lambda p, pid: (True, "ok"),
        "_check_pid_alive": lambda pid: True,
    }
    defaults.update(overrides)
    for attr, val in defaults.items():
        monkeypatch.setattr(wake_mod, attr, val)

    monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.wake.time.sleep", lambda _: None)
    monkeypatch.delenv("INVOCATION_ID", raising=False)


class _FakeProc:
    """Minimal stand-in for subprocess.Popen return value."""

    def __init__(self, pid: int = 55555):
        self.pid = pid


class TestWakeBranch:
    """Tests for wake_branch() — all remaining code paths."""

    # --- early exits ---

    def test_auto_pause_file_blocks(self, tmp_path, monkeypatch):
        """auto=True with PAUSE_FILE existing returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        pause = tmp_path / ".aipass" / "autonomous_pause"
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch()
        status, ok = wake_branch("@testbranch", auto=True)
        assert ok is False
        assert any(s[0] == "fail" and "pause" in s[1] for s in status.steps)

    def test_resolve_fails(self, tmp_path, monkeypatch):
        """Branch not found returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        status, ok = wake_branch("@nonexistent")
        assert ok is False
        assert any(s[0] == "fail" and "resolve" in s[1] for s in status.steps)

    # --- manager check ---

    def test_manager_target_skips_wake(self, tmp_path, monkeypatch):
        """Target with citizen_class=manager returns True (mail only, no wake)."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert any(s[1] == "manager" for s in status.steps)

    def test_manager_daemon_scheduled_wake_spawns_interactive(self, tmp_path, monkeypatch):
        """Manager + sender=@daemon bypasses the gate and spawns an interactive
        tmux session — managers are never headless. Self-authored
        .daemon/schedule.json = consent; the daemon cannot write other branches' files."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, _clean_zombies=lambda: 0)
        tmux_calls = []

        def _fake_run(cmd, **kwargs):
            tmux_calls.append(list(cmd))

            class _Done:
                returncode = 0
                stderr = ""

            return _Done()

        monkeypatch.setattr(wake_mod.shutil, "which", lambda name: "/usr/bin/tmux")
        monkeypatch.setattr(wake_mod.subprocess, "run", _fake_run)
        status, ok = wake_branch("@testbranch", custom_message="continue the work", sender="@daemon")
        assert ok is True
        # Gate records the bypass as an ok step (not the info skip)...
        assert any(s[0] == "ok" and s[1] == "manager" for s in status.steps)
        # ...and the spawn is an interactive tmux session, not the headless monitor.
        assert any(s[0] == "ok" and s[1] == "spawn" and "tmux" in s[2] for s in status.steps)
        assert [c[:2] for c in tmux_calls] == [["tmux", "new-session"], ["tmux", "send-keys"]]
        # Prompt travels via file (quoting-proof, debuggable).
        prompt_file = branch_path / ".daemon" / "last_wake_prompt.txt"
        assert prompt_file.read_text(encoding="utf-8") == "continue the work"

    def test_manager_daemon_wake_fails_without_tmux(self, tmp_path, monkeypatch):
        """Manager + sender=@daemon with no tmux binary fails loud (no silent headless fallback)."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, _clean_zombies=lambda: 0)
        monkeypatch.setattr(wake_mod.shutil, "which", lambda name: None)
        status, ok = wake_branch("@testbranch", sender="@daemon")
        assert ok is False
        assert any(s[0] == "fail" and s[1] == "tmux" for s in status.steps)

    def test_non_manager_target_continues(self, tmp_path, monkeypatch):
        """Target with non-manager citizen_class proceeds to spawn."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        trinity = branch_path / ".trinity"
        trinity.mkdir(parents=True, exist_ok=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "aipass_framework"}}),
            encoding="utf-8",
        )
        _patch_wake_deps(monkeypatch, _clean_zombies=lambda: 0)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert not any(s[1] == "manager" for s in status.steps)

    def test_missing_passport_continues(self, tmp_path, monkeypatch):
        """No passport.json — wake proceeds normally."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _clean_zombies=lambda: 0)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert not any(s[1] == "manager" for s in status.steps)

    # --- zombie check ---

    def test_zombie_check_warns_but_continues(self, tmp_path, monkeypatch):
        """Zombie detected adds warning but dispatch continues."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _clean_zombies=lambda: 2)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert any(s[0] == "warn" and "zombie" in s[2].lower() for s in status.steps)

    # --- lock exists ---

    def test_lock_exists_auto_true_fails(self, tmp_path, monkeypatch):
        """Lock active + auto=True returns failure."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(
            monkeypatch,
            _check_lock=lambda p: {"pid": 111, "timestamp": "2026-01-01T00:00:00"},
            _clean_zombies=lambda: 0,
        )
        status, ok = wake_branch("@testbranch", auto=True)
        assert ok is False
        assert any(s[0] == "fail" and "lock" in s[1] for s in status.steps)

    def test_lock_exists_auto_false_delivers_to_inbox(self, tmp_path, monkeypatch):
        """Lock active + auto=False returns info + True (routed to inbox)."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(
            monkeypatch,
            _check_lock=lambda p: {"pid": 111, "timestamp": "2026-01-01T00:00:00"},
            _clean_zombies=lambda: 0,
        )
        status, ok = wake_branch("@testbranch", auto=False)
        assert ok is True
        assert any(s[0] == "info" and "delivery" in s[1] for s in status.steps)

    # --- branch occupied ---

    def test_branch_occupied_blocks(self, tmp_path, monkeypatch):
        """Interactive session running -> blocked."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _is_branch_occupied=lambda p: True)
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "blocked" in s[1] for s in status.steps)

    # --- fresh vs resume ---

    def test_fresh_true_no_continue_flag(self, tmp_path, monkeypatch):
        """fresh=True -> claude_cmd does NOT include '-c' flag."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch", fresh=True)
        assert ok is True
        # The claude subcommand is embedded after "--" in monitor_cmd
        assert captured_cmds
        cmd = captured_cmds[0]
        # Everything after "--" is the claude command
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        assert "-c" not in claude_part

    def test_fresh_false_has_continue_flag(self, tmp_path, monkeypatch):
        """fresh=False -> claude_cmd includes '-c' flag."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch", fresh=False)
        assert ok is True
        assert captured_cmds
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        assert "-c" in claude_part

    # --- custom message ---

    def test_custom_message_sets_prompt(self, tmp_path, monkeypatch):
        """custom_message uses 'Hi. <message>' instead of DEFAULT_PROMPT."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch", custom_message="Run the audit")
        assert ok is True
        assert captured_cmds
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        # Find the prompt argument (follows -p)
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert prompt.startswith("Hi. Run the audit")

    def test_prompt_does_not_ask_agent_to_delete_lock(self, tmp_path, monkeypatch):
        """Monitor owns lock cleanup — the prompt must not also tell the agent to delete it.

        A dual-delete race let a second monitor spawn onto a lock the first
        agent had already removed mid-run (lock-theft, observed 2026-07-31).
        """
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert "delete" not in prompt.lower()
        assert ".dispatch.lock" not in prompt

    def test_prompt_instructs_synchronous_subagents(self, tmp_path, monkeypatch):
        """Prompt tells the agent to run sub-agents in the foreground, not background.

        Headless print-mode kills orphaned background tasks after 600s with
        no reply sent — the agent needs to know not to background work.
        """
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        captured_cmds: list = []

        def fake_popen(cmd, **kwargs):
            captured_cmds.append(cmd)
            return _FakeProc()

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        cmd = captured_cmds[0]
        sep_idx = cmd.index("--")
        claude_part = cmd[sep_idx + 1 :]
        p_idx = claude_part.index("-p")
        prompt = claude_part[p_idx + 1]
        assert "synchronously" in prompt.lower()

    # --- spawn errors ---

    def test_spawn_file_not_found(self, tmp_path, monkeypatch):
        """FileNotFoundError during Popen -> fail step."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        def _fail_popen(*a, **kw):
            raise FileNotFoundError("python not found")

        monkeypatch.setattr("subprocess.Popen", _fail_popen)
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "spawn" in s[1] for s in status.steps)

    def test_spawn_generic_exception(self, tmp_path, monkeypatch):
        """Generic exception during Popen -> fail step with class name."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)

        def _fail_popen(*a, **kw):
            raise RuntimeError("something broke")

        monkeypatch.setattr("subprocess.Popen", _fail_popen)
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "RuntimeError" in s[2] for s in status.steps)

    # --- pre-spawn: lock acquisition failure (DPLAN-0155) ---

    def test_lock_acquisition_fails_before_spawn(self, tmp_path, monkeypatch):
        """Lock fails before spawn -> fail step, returns False (DPLAN-0155 lock-before-spawn)."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _acquire_lock=lambda p, pid: (False, "Lock file already exists"))
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "lock-acquire" in s[1] for s in status.steps)

    # --- alive check fails ---

    def test_alive_check_fails_cleans_up_lock(self, tmp_path, monkeypatch):
        """Agent dies immediately -> cleans up lock, returns False."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, _check_pid_alive=lambda pid: False)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        # Create the lock file so we can verify it gets cleaned up
        lock_dir = branch_path / ".ai_mail.local"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / ".dispatch.lock"
        lock_file.write_text("{}", encoding="utf-8")
        status, ok = wake_branch("@testbranch")
        assert ok is False
        assert any(s[0] == "fail" and "alive" in s[1] for s in status.steps)
        # Lock file should be cleaned up
        assert not lock_file.exists()

    # --- successful full path ---

    def test_successful_full_path(self, tmp_path, monkeypatch):
        """All steps OK -> returns (status, True) with all expected steps."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            lambda *a, **kw: None,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
        assert status.success is True
        labels = [s[1] for s in status.steps]
        assert "resolve" in labels
        assert "pre-flight" in labels
        assert "lock" in labels
        assert "occupancy" in labels
        assert "spawn" in labels
        assert "lock-acquire" in labels
        assert "alive" in labels

    # --- notification failure doesn't break success ---

    def test_notification_failure_does_not_break_success(self, tmp_path, monkeypatch):
        """Exception in send_notification is caught — overall success unchanged."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())

        def _fail_notify(*a, **kw):
            raise RuntimeError("dbus not found")

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.notify.send_notification",
            _fail_notify,
            raising=False,
        )
        status, ok = wake_branch("@testbranch")
        assert ok is True
