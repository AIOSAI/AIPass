# =================== AIPass ====================
# Name: test_wake.py
# Description: Tests for wake dispatch handler
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for wake handler -- branch resolution, lock checking, PID checks, helpers."""

import json
import os
import pytest
from pathlib import Path
from datetime import datetime, timedelta

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
from aipass.ai_mail.apps.handlers.dispatch.wake import (
    _read_json,
    _check_lock,
    _check_pid_alive,
    _read_session_type,
    _clean_zombies,
    resolve_branch,
    DispatchStatus,
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
    """Non-linux platform returns 'interactive' immediately."""
    monkeypatch.setattr("sys.platform", "darwin")
    assert _read_session_type("999") == "interactive"


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
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
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
    monkeypatch.setattr(os, "kill", _raise_process_lookup)
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
    import subprocess
    monkeypatch.setattr(
        "subprocess.run",
        _raise_subprocess_error,
    )
    count = _clean_zombies()
    assert count == 0


# --- Helpers ---------------------------------------------------------

_real_open = open


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
            return _real_open(mapping[path_str], *args, **kwargs)
        return _real_open(path, *args, **kwargs)
    return _fake_open
