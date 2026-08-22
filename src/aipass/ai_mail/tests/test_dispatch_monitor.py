# =================== AIPass ====================
# Name: test_dispatch_monitor.py
# Description: Tests for dispatch monitor lifecycle handler
# Version: 1.0.0
# Created: 2026-04-02
# Modified: 2026-04-02
# =============================================

"""Tests for dispatch_monitor -- startup check, retry loop, bounce, rate limiting."""

import json
import os
import subprocess
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    BG_TASKS_MARKER,
    MAX_WAKE_DEPTH,
    _check_jsonl_activity,
    _check_rate_limited,
    _cleanup_own_lock,
    _cmd_for_attempt,
    _get_jsonl_projects_dir,
    _has_resume,
    _is_sandbox_enabled,
    _kill_process,
    _log_wake_result,
    _make_fresh_cmd,
    _parse_result_json,
    _read_stderr_segment,
    _reconcile_pointer,
    _rotate_attempt_stdout,
    _run_with_startup_check,
    _send_bounce,
    _session_id_in,
    _snapshot_jsonl_sizes,
    _summarize_result_json,
    _wake_sender,
    _wrap_for_sandbox,
    main,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(
        mod,
        "json_handler",
        MagicMock(),
    )


@pytest.fixture(autouse=True)
def _suppress_logger(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(mod, "logger", MagicMock())


@pytest.fixture(autouse=True)
def _suppress_wake(monkeypatch):
    """Prevent _wake_sender from importing/calling real wake_branch in unrelated tests."""
    monkeypatch.setattr(mod, "_wake_sender", MagicMock(return_value="skipped_sender"))
    monkeypatch.setattr(mod, "_log_wake_result", MagicMock())


@pytest.fixture
def stderr_log(tmp_path):
    """Create a stderr log file and return its path string."""
    log_file = tmp_path / "stderr.log"
    log_file.write_text("", encoding="utf-8")
    return str(log_file)


@pytest.fixture
def lock_file(tmp_path):
    """Create a lock file structure and return the lock path string."""
    # Lock lives at branch_path/.ai_mail.local/.dispatch.lock
    ai_mail_dir = tmp_path / "branch" / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    lock = ai_mail_dir / ".dispatch.lock"
    lock.write_text("{}", encoding="utf-8")
    return str(lock)


# --- _check_rate_limited tests ----------------------------------------


def test_check_rate_limited_429(tmp_path):
    """Returns True when stderr contains '429'."""
    log = tmp_path / "stderr.log"
    log.write_text("Error: API returned 429 Too Many Requests", encoding="utf-8")
    assert _check_rate_limited(str(log)) is True


def test_check_rate_limited_rate_limit(tmp_path):
    """Returns True when stderr contains 'rate_limit'."""
    log = tmp_path / "stderr.log"
    log.write_text("error: rate_limit exceeded", encoding="utf-8")
    assert _check_rate_limited(str(log)) is True


def test_check_rate_limited_overloaded(tmp_path):
    """Returns True when stderr contains 'overloaded'."""
    log = tmp_path / "stderr.log"
    log.write_text("API is overloaded, please retry", encoding="utf-8")
    assert _check_rate_limited(str(log)) is True


def test_check_rate_limited_529(tmp_path):
    """Returns True when stderr contains '529'."""
    log = tmp_path / "stderr.log"
    log.write_text("HTTP 529 Service Unavailable", encoding="utf-8")
    assert _check_rate_limited(str(log)) is True


def test_check_rate_limited_normal_content(tmp_path):
    """Returns False for normal stderr content."""
    log = tmp_path / "stderr.log"
    log.write_text("Starting agent...\nProcessing task\nDone", encoding="utf-8")
    assert _check_rate_limited(str(log)) is False


def test_check_rate_limited_missing_file(tmp_path):
    """Returns False when file doesn't exist."""
    assert _check_rate_limited(str(tmp_path / "nonexistent.log")) is False


# --- _make_fresh_cmd tests --------------------------------------------


def test_make_fresh_cmd_removes_c_flag():
    """Removes -c flag from command."""
    cmd = ["claude", "-c", "--model", "opus"]
    result = _make_fresh_cmd(cmd)
    assert result == ["claude", "--model", "opus"]


def test_make_fresh_cmd_no_c_flag():
    """Returns same command if no -c flag."""
    cmd = ["claude", "--model", "opus"]
    result = _make_fresh_cmd(cmd)
    assert result == ["claude", "--model", "opus"]


def test_make_fresh_cmd_does_not_remove_c_value():
    """Doesn't remove -c from positions where it's a standalone flag."""
    # _make_fresh_cmd removes all standalone "-c" args. If -c only appears
    # as the flag itself, it gets removed. Other args containing "c" are kept.
    cmd = ["claude", "-c", "--config", "c_file.json"]
    result = _make_fresh_cmd(cmd)
    assert result == ["claude", "--config", "c_file.json"]
    assert "-c" not in result


# --- _run_with_startup_check tests (mock Popen) -----------------------


def test_run_startup_check_success(tmp_path, monkeypatch):
    """JSONL activity detected within timeout, process exits 0."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.5)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.05)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 5)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.returncode = 0
    mock_proc.wait = MagicMock(return_value=0)

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: mock_proc)
    # Simulate JSONL activity on first check
    activity_calls = [0]

    def fake_activity(projects_dir, initial_sizes):
        activity_calls[0] += 1
        return activity_calls[0] >= 1  # Active from first call

    monkeypatch.setattr(mod, "_get_jsonl_projects_dir", lambda cwd: tmp_path / "projects")
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: {})
    monkeypatch.setattr(mod, "_check_jsonl_activity", fake_activity)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == 0
    assert startup_failed is False


def test_run_startup_check_timeout(tmp_path, monkeypatch):
    """Process produces no stdout, gets killed after STARTUP_TIMEOUT."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.1)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 5)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # Never exits on its own
    mock_proc.returncode = None
    mock_proc.wait.return_value = None
    mock_proc.terminate = MagicMock()

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: mock_proc)
    mock_kill = MagicMock()
    monkeypatch.setattr(mod, "_kill_process", mock_kill)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == -3
    assert startup_failed is True
    mock_kill.assert_called_once()


def test_run_startup_check_process_exits_during_startup_no_output(tmp_path, monkeypatch):
    """Process exits during startup with zero output — IS a startup failure."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.5)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 5)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # Already exited with error
    mock_proc.returncode = 1

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: mock_proc)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == 1
    assert startup_failed is True  # Zero output = startup failure


def test_run_startup_check_process_exits_during_startup_with_output(tmp_path, monkeypatch):
    """Process exits during startup WITH JSONL activity — NOT a startup failure."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.5)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 5)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    mock_proc = MagicMock()
    poll_calls = [0]

    def fake_poll():
        poll_calls[0] += 1
        if poll_calls[0] <= 1:
            return None
        # Second poll: process has exited
        return 1

    mock_proc.poll = fake_poll
    mock_proc.returncode = 1
    mock_proc.wait = MagicMock(return_value=1)

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: mock_proc)
    # Simulate JSONL activity so started=True
    monkeypatch.setattr(mod, "_get_jsonl_projects_dir", lambda cwd: tmp_path / "projects")
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: {})
    monkeypatch.setattr(mod, "_check_jsonl_activity", lambda d, s: True)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == 1
    assert startup_failed is False  # Had JSONL activity = normal failure, not startup


def test_run_startup_check_hard_timeout(tmp_path, monkeypatch):
    """Process starts but runs past HARD_TIMEOUT."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.5)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 0.1)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    mock_proc = MagicMock()
    poll_calls = [0]

    def fake_poll():
        poll_calls[0] += 1
        if poll_calls[0] == 1:
            Path(stdout_log).write_text("output", encoding="utf-8")
            return None
        return None

    mock_proc.poll = fake_poll
    mock_proc.returncode = None
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=0.1)

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: mock_proc)
    mock_kill = MagicMock()
    monkeypatch.setattr(mod, "_kill_process", mock_kill)
    # Simulate JSONL activity so startup succeeds and we reach the hard timeout
    monkeypatch.setattr(mod, "_get_jsonl_projects_dir", lambda cwd: tmp_path / "projects")
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: {})
    monkeypatch.setattr(mod, "_check_jsonl_activity", lambda d, s: True)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == -1
    assert startup_failed is False
    mock_kill.assert_called_once()


def test_run_startup_check_spawn_failure(tmp_path, monkeypatch):
    """Popen raises exception, returns (-2, False)."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.1)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)

    stdout_log = str(tmp_path / "stdout.log")
    stderr_fh = MagicMock()

    def raise_oserror(*a, **kw):
        raise OSError("spawn failed")

    monkeypatch.setattr(mod.subprocess, "Popen", raise_oserror)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == -2
    assert startup_failed is False


# --- Retry loop in main() tests --------------------------------------


@pytest.fixture
def main_argv(tmp_path):
    """Build sys.argv and supporting files for main() tests."""
    branch_dir = tmp_path / "branch"
    ai_mail_dir = branch_dir / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True)

    lock_file = ai_mail_dir / ".dispatch.lock"
    lock_file.write_text("{}", encoding="utf-8")

    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("", encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test_branch",
        str(lock_file),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
        "-c",
        "--model",
        "opus",
    ]
    return argv, lock_file, stderr_log


def test_main_single_attempt_success(monkeypatch, main_argv):
    """First attempt succeeds, no retries."""
    argv, lock_file, stderr_log = main_argv

    mock_run = MagicMock(return_value=(0, False))
    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", mock_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_run.assert_called_once()
    mock_bounce.assert_not_called()


def test_main_second_attempt_success(monkeypatch, main_argv):
    """First fails, second succeeds."""
    argv, lock_file, stderr_log = main_argv

    mock_run = MagicMock(side_effect=[(1, False), (0, False)])
    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", mock_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(
            time=time.time,
            strftime=time.strftime,
            sleep=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert mock_run.call_count == 2
    mock_bounce.assert_not_called()


def test_main_third_attempt_fresh(monkeypatch, main_argv):
    """Third attempt removes -c flag (fresh start)."""
    argv, lock_file, stderr_log = main_argv

    calls: list[list[str]] = []

    def track_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return (1, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", track_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(
            time=time.time,
            strftime=time.strftime,
            sleep=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    assert len(calls) == 3
    # Attempts 1 and 2 should have -c
    assert "-c" in calls[0]
    assert "-c" in calls[1]
    # Attempt 3 should NOT have -c (fresh)
    assert "-c" not in calls[2]


def test_main_all_three_fail_sends_bounce(monkeypatch, main_argv):
    """All 3 fail: bounce is sent with attempt details."""
    argv, lock_file, stderr_log = main_argv

    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (-3, True), (1, False)]))
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(
            time=time.time,
            strftime=time.strftime,
            sleep=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "3 attempts" in reason


def test_main_rate_limit_delay(monkeypatch, main_argv):
    """When _check_rate_limited returns True, verify delay happens."""
    argv, lock_file, stderr_log = main_argv

    mock_time = MagicMock()
    mock_time.time = time.time
    mock_time.strftime = time.strftime
    mock_time.sleep = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=True))
    monkeypatch.setattr(mod, "time", mock_time)
    monkeypatch.setattr(mod, "RATE_LIMIT_DELAY", 30)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    # Verify rate limit delay was used (30s, not 5s)
    mock_time.sleep.assert_called_with(30)


# --- _send_bounce tests -----------------------------------------------


def test_send_bounce_success(tmp_path, monkeypatch):
    """Successful bounce sends email via drone subprocess."""
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("some error output\nmore lines\n", encoding="utf-8")

    lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_sub_run = MagicMock(return_value=mock_result)
    monkeypatch.setattr(mod.subprocess, "run", mock_sub_run)

    result = _send_bounce("@test", "failed", "@sender", str(lock), str(stderr_log))
    assert result is True
    mock_sub_run.assert_called_once()


def test_send_bounce_falls_back_to_file(tmp_path, monkeypatch):
    """Failed drone send falls back to bounce file."""
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("error output\n", encoding="utf-8")

    lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")

    def raise_error(*a, **kw):
        raise subprocess.SubprocessError("drone failed")

    monkeypatch.setattr(mod.subprocess, "run", raise_error)

    result = _send_bounce("@test", "failed", "@sender", str(lock), str(stderr_log))
    assert result is False

    bounce_file = lock.parent / "last_bounce.json"
    assert bounce_file.exists()
    data = json.loads(bounce_file.read_text(encoding="utf-8"))
    assert data["branch"] == "@test"
    assert data["reason"] == "failed"


def test_send_bounce_missing_stderr(tmp_path, monkeypatch):
    """Missing stderr log handled gracefully."""
    lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_sub_run = MagicMock(return_value=mock_result)
    monkeypatch.setattr(mod.subprocess, "run", mock_sub_run)

    # Pass a nonexistent stderr log
    result = _send_bounce("@test", "failed", "@sender", str(lock), str(tmp_path / "nonexistent.log"))
    assert result is True
    # The body should contain "(no stderr captured)" fallback
    call_args = mock_sub_run.call_args
    body = call_args[0][0][5]  # ["drone", "@ai_mail", "send", sender, subject, body]
    assert "no stderr captured" in body


# --- Notification naming test ------------------------------------------


def test_notification_uses_at_branch_format(monkeypatch, main_argv):
    """Notification title uses '@branch_name status' format."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    mock_notify = MagicMock()
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.notify.send_notification",
        mock_notify,
    )

    with pytest.raises(SystemExit):
        main()

    mock_notify.assert_called_once()
    title = mock_notify.call_args[0][0]
    assert title.startswith("@test_branch")
    assert "completed" in title


# --- _kill_process tests -----------------------------------------------


def test_kill_process_terminate_succeeds():
    """SIGTERM succeeds within 10s — no SIGKILL needed."""
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(return_value=None)
    mock_proc.kill = MagicMock()

    _kill_process(mock_proc, "@test")

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once_with(timeout=10)
    mock_proc.kill.assert_not_called()


def test_kill_process_terminate_timeout_falls_back_to_sigkill():
    """SIGTERM times out — falls back to SIGKILL."""
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(side_effect=[subprocess.TimeoutExpired(cmd="claude", timeout=10), None])
    mock_proc.kill = MagicMock()

    _kill_process(mock_proc, "@test")

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


# --- Max-turns detection tests -----------------------------------------


def test_max_turns_changes_notification_status(monkeypatch, main_argv):
    """stdout containing stop_reason:max_turns changes status even with exit_code==0."""
    argv, lock_file, stderr_log = main_argv

    # Write max_turns to stdout log
    stdout_log = Path(str(lock_file)).parent.parent / "logs" / "dispatch_stdout.log"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(cmd, stdout_log_path, stderr_fh, cwd, env, branch, **kwargs):
        # Simulate writing max_turns output
        stdout_log.write_text('{"stop_reason":"max_turns"}', encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    mock_notify = MagicMock()
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.notify.send_notification",
        mock_notify,
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0  # Claude exited 0
    mock_notify.assert_called_once()
    title = mock_notify.call_args[0][0]
    assert "MAX TURNS" in title  # But notification shows max turns


# --- Log rotation tests ------------------------------------------------


def test_stderr_rotation_on_large_file(tmp_path, monkeypatch):
    """stderr > 512KB triggers rotation to .log.1 before opening."""
    stderr_log = tmp_path / "stderr.log"
    # Write > 512KB to trigger rotation
    stderr_log.write_text("x" * 520_000, encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test",
        str(tmp_path / ".dispatch.lock"),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
    ]

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path),
    )

    # Create required dirs
    (tmp_path / ".ai_mail.local").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    lock = tmp_path / ".ai_mail.local" / ".dispatch.lock"
    lock.write_text("{}", encoding="utf-8")
    argv[2] = str(lock)
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit):
        main()

    # Rotated file should exist
    rotated = tmp_path / "stderr.log.1"
    assert rotated.exists()
    assert rotated.stat().st_size >= 520_000


def test_stdout_rotation_on_large_file(tmp_path, monkeypatch):
    """stdout > 512KB triggers rotation to .log.1 before first attempt."""
    branch_dir = tmp_path / "branch"
    ai_mail_dir = branch_dir / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True)

    lock = ai_mail_dir / ".dispatch.lock"
    lock.write_text("{}", encoding="utf-8")
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("", encoding="utf-8")

    # Write large stdout log
    stdout_log = logs_dir / "dispatch_stdout.log"
    stdout_log.write_text("x" * 520_000, encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test",
        str(lock),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
    ]

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path),
    )

    with pytest.raises(SystemExit):
        main()

    rotated = logs_dir / "dispatch_stdout.log.1"
    assert rotated.exists()


# --- Lock file cleanup tests ------------------------------------------


def test_lock_cleanup_on_success(monkeypatch, main_argv):
    """Lock is deleted on successful exit."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()


def test_lock_cleanup_on_failure(monkeypatch, main_argv):
    """Lock is deleted even after all attempts fail (bounce path)."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(
            time=time.time,
            strftime=time.strftime,
            sleep=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()


# --- _rotate_attempt_stdout tests --------------------------------------


def test_rotate_attempt_stdout_moves_file(tmp_path):
    """Non-empty stdout log is preserved as dispatch_stdout.attempt-N.log."""
    stdout_log = tmp_path / "dispatch_stdout.log"
    stdout_log.write_text('{"is_error":true}', encoding="utf-8")

    _rotate_attempt_stdout(str(stdout_log), 1)

    preserved = tmp_path / "dispatch_stdout.attempt-1.log"
    assert not stdout_log.exists()
    assert preserved.exists()
    assert preserved.read_text(encoding="utf-8") == '{"is_error":true}'


def test_rotate_attempt_stdout_skips_empty(tmp_path):
    """Empty stdout log is left in place — nothing worth preserving."""
    stdout_log = tmp_path / "dispatch_stdout.log"
    stdout_log.write_text("", encoding="utf-8")

    _rotate_attempt_stdout(str(stdout_log), 1)

    assert stdout_log.exists()
    assert not (tmp_path / "dispatch_stdout.attempt-1.log").exists()


def test_rotate_attempt_stdout_missing_file_no_raise(tmp_path):
    """Missing stdout log does not raise."""
    _rotate_attempt_stdout(str(tmp_path / "nope.log"), 2)

    assert not (tmp_path / "dispatch_stdout.attempt-2.log").exists()


# --- _parse_result_json / _summarize_result_json tests ------------------


def test_parse_result_json_whole_file(tmp_path):
    """Single JSON object filling the file parses directly."""
    log = tmp_path / "stdout.log"
    log.write_text('{"is_error": true, "api_error_status": 529}', encoding="utf-8")

    result = _parse_result_json(str(log))

    assert result == {"is_error": True, "api_error_status": 529}


def test_parse_result_json_last_line_fallback(tmp_path):
    """Result JSON on the last line is found when earlier output precedes it."""
    log = tmp_path / "stdout.log"
    log.write_text('some banner text\n{"is_error": false, "result": "done"}\n', encoding="utf-8")

    result = _parse_result_json(str(log))

    assert result == {"is_error": False, "result": "done"}


def test_parse_result_json_garbage_returns_empty(tmp_path):
    """Non-JSON content returns {}."""
    log = tmp_path / "stdout.log"
    log.write_text("not json at all\nstill not json", encoding="utf-8")

    assert _parse_result_json(str(log)) == {}


def test_parse_result_json_missing_file_returns_empty(tmp_path):
    """Missing file returns {}."""
    assert _parse_result_json(str(tmp_path / "nope.log")) == {}


def test_summarize_result_json_includes_error_fields(tmp_path):
    """Summary names is_error, subtype, api_error_status and the result snippet."""
    log = tmp_path / "stdout.log"
    log.write_text(
        '{"is_error": true, "subtype": "error_during_execution", "api_error_status": 529, "result": "API overload"}',
        encoding="utf-8",
    )

    summary = _summarize_result_json(str(log))

    assert "is_error=True" in summary
    assert "subtype=error_during_execution" in summary
    assert "api_error_status=529" in summary
    assert "API overload" in summary


def test_summarize_result_json_no_file(tmp_path):
    """Missing result JSON produces the explicit placeholder."""
    assert _summarize_result_json(str(tmp_path / "nope.log")) == "(no result JSON captured)"


# --- _read_stderr_segment tests -----------------------------------------


def test_read_stderr_segment_returns_content_after_offset(tmp_path):
    """Only content written after the byte offset is returned."""
    log = tmp_path / "stderr.log"
    log.write_text("old attempt output\n", encoding="utf-8")
    offset = log.stat().st_size
    with open(log, "a", encoding="utf-8") as f:
        f.write("new attempt output\n")

    segment = _read_stderr_segment(str(log), offset)

    assert segment == "new attempt output\n"
    assert "old attempt" not in segment


def test_read_stderr_segment_missing_file(tmp_path):
    """Missing stderr log returns empty string."""
    assert _read_stderr_segment(str(tmp_path / "nope.log"), 0) == ""


# --- _cleanup_own_lock tests ---------------------------------------------


def test_cleanup_own_lock_deletes_when_owner(tmp_path):
    """Lock holding our PID is deleted."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert not lock.exists()


def test_cleanup_own_lock_leaves_foreign_pid(tmp_path):
    """Lock owned by another PID (successor monitor) is left in place."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text(json.dumps({"pid": 999999999}), encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()


def test_cleanup_own_lock_leaves_unreadable(tmp_path):
    """Unparseable lock is left for stale-lock cleanup, not deleted blind."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text("not json{{{", encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()


def test_cleanup_own_lock_missing_noop(tmp_path):
    """Missing lock file is a no-op."""
    _cleanup_own_lock(str(tmp_path / ".dispatch.lock"))  # must not raise


# --- Forensics + incomplete-detection main() tests ------------------------


def test_main_attempt_exit_lines_in_stderr(monkeypatch, main_argv):
    """Each attempt's exit code lands in the dispatch stderr log itself."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(-3, True), (1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    content = stderr_log.read_text(encoding="utf-8")
    assert "--- Attempt 1/3 exited: code=-3 (startup timeout) ---" in content
    assert "--- Attempt 2/3 exited: code=1 ---" in content
    assert "--- Attempt 3/3 exited: code=0 ---" in content


def test_main_failed_attempt_stdout_preserved(monkeypatch, main_argv, tmp_path):
    """A failed attempt's stdout is preserved before the retry truncates it."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = tmp_path / "branch" / "logs"

    call_count = {"n": 0}

    def fake_run(cmd, stdout_log, *args, **kwargs):
        call_count["n"] += 1
        Path(stdout_log).write_text(f'{{"is_error": true, "attempt": {call_count["n"]}}}', encoding="utf-8")
        return (1, False) if call_count["n"] == 1 else (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    preserved = logs_dir / "dispatch_stdout.attempt-1.log"
    assert preserved.exists()
    assert '"attempt": 1' in preserved.read_text(encoding="utf-8")
    assert '"attempt": 2' in (logs_dir / "dispatch_stdout.log").read_text(encoding="utf-8")


def test_main_stale_attempt_files_shifted(monkeypatch, main_argv, tmp_path):
    """A previous run's attempt-N stdout files are shifted aside at startup."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = tmp_path / "branch" / "logs"
    stale = logs_dir / "dispatch_stdout.attempt-2.log"
    stale.write_text("previous run", encoding="utf-8")

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert not stale.exists()
    assert (logs_dir / "dispatch_stdout.attempt-2.log.1").read_text(encoding="utf-8") == "previous run"


def test_main_bounce_includes_result_json(monkeypatch, main_argv, tmp_path):
    """Total failure bounce carries the last attempt's parsed result JSON."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = tmp_path / "branch" / "logs"
    mock_bounce = MagicMock()

    def fake_run(cmd, stdout_log, *args, **kwargs):
        Path(stdout_log).write_text(
            '{"is_error": true, "api_error_status": 529, "result": "API Error: overloaded"}', encoding="utf-8"
        )
        return (1, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "api_error_status=529" in reason
    assert "API Error: overloaded" in reason
    # attempt-3 stdout stays in place; attempts 1-2 preserved for forensics
    assert (logs_dir / "dispatch_stdout.attempt-1.log").exists()
    assert (logs_dir / "dispatch_stdout.attempt-2.log").exists()


def test_main_bg_orphaned_treated_as_incomplete(monkeypatch, main_argv):
    """Exit 0 + 'Background tasks still running' marker => bounce + exit 1."""
    argv, lock_file, stderr_log = main_argv
    mock_bounce = MagicMock()

    def fake_run(cmd, stdout_log, *args, **kwargs):
        with open(stderr_log, "a", encoding="utf-8") as f:
            f.write(f"{BG_TASKS_MARKER} after 600s; terminating.\n")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "background tasks were still running" in reason
    assert not lock_file.exists()  # cleanup still runs on incomplete


def test_main_bg_marker_from_previous_run_ignored(monkeypatch, main_argv):
    """A BG marker already in the stderr log from a PREVIOUS run is not counted."""
    argv, lock_file, stderr_log = main_argv
    stderr_log.write_text(f"{BG_TASKS_MARKER} after 600s; terminating.\n", encoding="utf-8")
    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_bounce.assert_not_called()


def test_main_lock_left_for_successor_monitor(monkeypatch, main_argv):
    """A lock re-created by a successor monitor (different PID) is not deleted."""
    argv, lock_file, stderr_log = main_argv

    def fake_run(cmd, stdout_log, *args, **kwargs):
        # Simulate a successor monitor taking over the lock mid-run
        lock_file.write_text(json.dumps({"pid": 999999999}), encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert lock_file.exists()
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == 999999999


# --- Environment variable setup tests ---------------------------------


def test_env_vars_set_correctly(monkeypatch, main_argv):
    """Verify AIPASS_SPAWNED, SESSION_TYPE, BRANCH_NAME set; CLAUDE* stripped; venv on PATH."""
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))

    fake_repo = Path("/fake/repo")
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=fake_repo),
    )

    # Set a CLAUDE var that should be stripped
    monkeypatch.setenv("CLAUDE_TEST_VAR", "should_be_stripped")
    monkeypatch.setenv("AIPASS_BOT_ID", "should_be_stripped_too")
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@old_caller")
    monkeypatch.setenv("AIPASS_CALLER_CWD", "/old/cwd")

    with pytest.raises(SystemExit):
        main()

    assert captured_env["AIPASS_SPAWNED"] == "1"
    assert captured_env["AIPASS_SESSION_TYPE"] == "dispatched"
    assert captured_env["AIPASS_BRANCH_NAME"] == "test_branch"
    assert "CLAUDE_TEST_VAR" not in captured_env
    assert "AIPASS_BOT_ID" not in captured_env
    assert "AIPASS_CALLER_BRANCH" not in captured_env
    assert "AIPASS_CALLER_CWD" not in captured_env
    # Venv bin should be on PATH (platform-aware: Scripts on Windows, bin elsewhere)
    import os
    import sys

    venv_dir = "Scripts" if sys.platform == "win32" else "bin"
    path_entries = captured_env.get("PATH", "").split(os.pathsep)
    venv_in_path = any(
        entry.endswith(os.sep + ".venv" + os.sep + venv_dir) or entry.endswith("/.venv/" + venv_dir)
        for entry in path_entries
    )
    assert venv_in_path, f"Expected .venv/{venv_dir} in PATH entries: {path_entries}"


def test_auto_compact_window_pinned_to_350k(monkeypatch, main_argv):
    """Dispatched agents get a 350k auto-compact window, model-independent.

    The pin is written AFTER the CLAUDE* strip loop, so a parent's own window
    never leaks in and the pin is not stripped on its way out.
    """
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    # Parent carries a different window — the spawn must overwrite it, not inherit it.
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "999999")

    with pytest.raises(SystemExit):
        main()

    assert captured_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "350000"


# === Additional tests (added 2026-04-03) ===================================


# --- _kill_process tests (named per spec) ----------------------------------


def test_kill_process_sigterm_success():
    """terminate() succeeds within timeout — no SIGKILL needed."""
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(return_value=None)
    mock_proc.kill = MagicMock()

    _kill_process(mock_proc, "@test")

    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once_with(timeout=10)
    mock_proc.kill.assert_not_called()


def test_kill_process_sigkill_fallback():
    """terminate() times out — falls back to kill()."""
    mock_proc = MagicMock()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = MagicMock(side_effect=[subprocess.TimeoutExpired(cmd="claude", timeout=10), None])
    mock_proc.kill = MagicMock()

    _kill_process(mock_proc, "@test")

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


# --- Max-turns detection (named per spec) ----------------------------------


def test_main_max_turns_detected(monkeypatch, main_argv):
    """stdout containing stop_reason:max_turns changes status to MAX TURNS HIT
    in notification even when exit_code==0."""
    argv, lock_file, stderr_log = main_argv

    # Determine where main() will write its stdout log
    branch_dir = lock_file.parent.parent
    stdout_log = branch_dir / "logs" / "dispatch_stdout.log"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(cmd, stdout_log_path, stderr_fh, cwd, env, branch, **kwargs):
        # Write max_turns stop_reason into stdout log
        Path(stdout_log_path).write_text('{"stop_reason":"max_turns"}', encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    mock_notify = MagicMock()
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.notify.send_notification",
        mock_notify,
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_notify.assert_called_once()
    title = mock_notify.call_args[0][0]
    assert "MAX TURNS HIT" in title


# --- Log rotation tests (named per spec) -----------------------------------


def test_stderr_rotation(tmp_path, monkeypatch):
    """stderr log > 512KB triggers rotation to .log.1."""
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("x" * 520_000, encoding="utf-8")

    branch_dir = tmp_path / "branch"
    ai_mail_dir = branch_dir / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True)

    lock = ai_mail_dir / ".dispatch.lock"
    lock.write_text("{}", encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test",
        str(lock),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
    ]

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path),
    )

    with pytest.raises(SystemExit):
        main()

    rotated = tmp_path / "stderr.log.1"
    assert rotated.exists()
    assert rotated.stat().st_size >= 520_000


def test_stdout_rotation(tmp_path, monkeypatch):
    """stdout log > 512KB triggers rotation to .log.1 before first attempt."""
    branch_dir = tmp_path / "branch"
    ai_mail_dir = branch_dir / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True)

    lock = ai_mail_dir / ".dispatch.lock"
    lock.write_text("{}", encoding="utf-8")
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("", encoding="utf-8")

    stdout_log = logs_dir / "dispatch_stdout.log"
    stdout_log.write_text("x" * 520_000, encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test",
        str(lock),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
    ]

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path),
    )

    with pytest.raises(SystemExit):
        main()

    rotated = logs_dir / "dispatch_stdout.log.1"
    assert rotated.exists()


# --- Lock file cleanup tests (named per spec) ------------------------------


def test_lock_cleaned_on_success(monkeypatch, main_argv):
    """Lock is deleted when exit_code==0."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()


def test_lock_cleaned_on_failure(monkeypatch, main_argv):
    """Lock is deleted even when all attempts fail."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(
            time=time.time,
            strftime=time.strftime,
            sleep=MagicMock(),
        ),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()


# --- Environment variables tests (named per spec) --------------------------


def test_env_vars_setup(monkeypatch, main_argv):
    """Verify spawn_env contains AIPASS_SPAWNED=1, AIPASS_SESSION_TYPE=dispatched,
    AIPASS_BRANCH_NAME set, CLAUDE* vars stripped, venv bin on PATH."""
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))

    fake_repo = Path("/fake/repo")
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=fake_repo),
    )

    # Set CLAUDE* and AIPASS_BOT_ID vars that should be stripped
    monkeypatch.setenv("CLAUDE_ACCESS_TOKEN", "secret")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "abc123")
    monkeypatch.setenv("AIPASS_BOT_ID", "bot42")
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@other")
    monkeypatch.setenv("AIPASS_CALLER_CWD", "/other/cwd")

    with pytest.raises(SystemExit):
        main()

    assert captured_env["AIPASS_SPAWNED"] == "1"
    assert captured_env["AIPASS_SESSION_TYPE"] == "dispatched"
    assert captured_env["AIPASS_BRANCH_NAME"] == "test_branch"
    assert "CLAUDE_ACCESS_TOKEN" not in captured_env
    assert "CLAUDE_SESSION_ID" not in captured_env
    assert "AIPASS_BOT_ID" not in captured_env
    assert "AIPASS_CALLER_BRANCH" not in captured_env
    assert "AIPASS_CALLER_CWD" not in captured_env
    # Venv bin should be on PATH (platform-aware: Scripts on Windows, bin elsewhere)
    import os
    import sys

    venv_dir = "Scripts" if sys.platform == "win32" else "bin"
    path_entries = captured_env.get("PATH", "").split(os.pathsep)
    venv_in_path = any(
        entry.endswith(os.sep + ".venv" + os.sep + venv_dir) or entry.endswith("/.venv/" + venv_dir)
        for entry in path_entries
    )
    assert venv_in_path, f"Expected .venv/{venv_dir} in PATH entries: {path_entries}"


# --- JSONL helper tests ----------------------------------------------------


def test_get_jsonl_projects_dir():
    """Verifies path encoding: / replaced with -, _ replaced with -."""
    result = _get_jsonl_projects_dir("/home/user/my_project")
    expected = Path.home() / ".claude" / "projects" / "-home-user-my-project"
    assert result == expected


def test_snapshot_jsonl_sizes(tmp_path):
    """Creates .jsonl files in tmp_path and verifies correct size dict."""
    f1 = tmp_path / "session1.jsonl"
    f2 = tmp_path / "session2.jsonl"
    f1.write_text("line1\n", encoding="utf-8")
    f2.write_text("line1\nline2\n", encoding="utf-8")

    sizes = _snapshot_jsonl_sizes(tmp_path)
    assert sizes["session1.jsonl"] == f1.stat().st_size
    assert sizes["session2.jsonl"] == f2.stat().st_size
    assert len(sizes) == 2


def test_snapshot_jsonl_sizes_empty_dir(tmp_path):
    """Returns empty dict for a directory with no .jsonl files."""
    sizes = _snapshot_jsonl_sizes(tmp_path)
    assert sizes == {}


def test_snapshot_jsonl_sizes_missing_dir(tmp_path):
    """Returns empty dict for a nonexistent directory."""
    sizes = _snapshot_jsonl_sizes(tmp_path / "does_not_exist")
    assert sizes == {}


def test_check_jsonl_activity_new_file(tmp_path):
    """New file appears after snapshot -> True."""
    initial = _snapshot_jsonl_sizes(tmp_path)
    assert initial == {}

    # New file appears
    (tmp_path / "new_session.jsonl").write_text("data\n", encoding="utf-8")

    assert _check_jsonl_activity(tmp_path, initial) is True


def test_check_jsonl_activity_file_grew(tmp_path):
    """Existing file larger than snapshot -> True."""
    f = tmp_path / "session.jsonl"
    f.write_text("line1\n", encoding="utf-8")

    initial = _snapshot_jsonl_sizes(tmp_path)

    # File grows
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("line2\n")

    assert _check_jsonl_activity(tmp_path, initial) is True


def test_check_jsonl_activity_no_change(tmp_path):
    """No change -> False."""
    f = tmp_path / "session.jsonl"
    f.write_text("line1\n", encoding="utf-8")

    initial = _snapshot_jsonl_sizes(tmp_path)

    assert _check_jsonl_activity(tmp_path, initial) is False


def test_check_jsonl_activity_missing_dir(tmp_path):
    """Nonexistent directory -> False."""
    assert _check_jsonl_activity(tmp_path / "nope", {}) is False


# --- Sandbox gate tests (Phase 4 FPLAN-0250) --------------------------------


class TestIsSandboxEnabled:
    """_is_sandbox_enabled reads AIPASS_SANDBOX_ENABLED from env."""

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)
        assert _is_sandbox_enabled() is False

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "")
        assert _is_sandbox_enabled() is False

    def test_false_string_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "false")
        assert _is_sandbox_enabled() is False

    def test_zero_returns_false(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "0")
        assert _is_sandbox_enabled() is False

    def test_one_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")
        assert _is_sandbox_enabled() is True

    def test_true_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "true")
        assert _is_sandbox_enabled() is True

    def test_yes_returns_true(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "yes")
        assert _is_sandbox_enabled() is True

    def test_TRUE_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "TRUE")
        assert _is_sandbox_enabled() is True


class TestFlagOffOldPath:
    """Flag OFF (default): dispatch uses the original cmd, no sandbox wrapping."""

    def test_flag_off_cmd_unchanged(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        captured_cmds = []

        def capture_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(captured_cmds) == 1
        assert captured_cmds[0] == ["claude", "-c", "--model", "opus"]

    def test_flag_off_wrap_never_called(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        wrap_calls = []
        original_wrap = mod._wrap_for_sandbox

        def tracking_wrap(*args, **kwargs):
            wrap_calls.append(args)
            return original_wrap(*args, **kwargs)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_wrap_for_sandbox", tracking_wrap)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        assert wrap_calls == []


class TestFlagOnSandboxPath:
    """Flag ON: dispatch wraps cmd via _wrap_for_sandbox."""

    def test_flag_on_cmd_wrapped(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        captured_cmds = []

        def capture_run(cmd, *args, **kwargs):
            captured_cmds.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap --sandbox " + " ".join(cmd)],
        )
        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 99
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(captured_cmds) == 1
        assert captured_cmds[0][0] == "/bin/bash"
        assert captured_cmds[0][1] == "-c"
        assert "bwrap --sandbox" in captured_cmds[0][2]

    def test_wrap_calls_building_blocks(self, monkeypatch, tmp_path):
        call_log = []

        def mock_build_policy(bp):
            call_log.append("build_policy")
            return {"allow_write": [str(bp)], "deny_write": [], "deny_read": []}

        def mock_build_srt_config(policy):
            call_log.append("build_srt_config")
            return {"filesystem": {"allowWrite": policy["allow_write"]}}

        def mock_resolve_bwrap(cmd_str, srt_config):
            call_log.append("resolve_bwrap_command")
            return f"bwrap --ro-bind / / {cmd_str}"

        monkeypatch.setattr("aipass.hooks.apps.modules.sandbox.build_policy", mock_build_policy)
        monkeypatch.setattr(
            "aipass.hooks.apps.modules.sandbox.build_srt_config",
            mock_build_srt_config,
        )
        monkeypatch.setattr(
            "aipass.hooks.apps.modules.sandbox.resolve_bwrap_command",
            mock_resolve_bwrap,
        )

        result = _wrap_for_sandbox(["claude", "--model", "opus"], tmp_path)

        assert call_log == ["build_policy", "build_srt_config", "resolve_bwrap_command"]
        assert result[0] == "/bin/bash"
        assert result[1] == "-c"
        assert "claude" in result[2]


class TestBrokenSandboxFailsLoud:
    """Flag ON but sandbox init fails: ABORT, never silently unsandbox."""

    def test_sandbox_init_failure_aborts(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        def broken_wrap(cmd, bp):
            raise RuntimeError("srt resolve failed: node not found")

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "_wrap_for_sandbox", broken_wrap)
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0

    def test_sandbox_failure_sends_bounce(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        def broken_wrap(cmd, bp):
            raise FileNotFoundError("node not found in PATH")

        mock_bounce = MagicMock()

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_wrap_for_sandbox", broken_wrap)
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        mock_bounce.assert_called_once()
        reason = mock_bounce.call_args[0][1]
        assert "sandbox" in reason.lower() or "-4" in reason

    def test_never_falls_back_to_unsandboxed(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        wrap_calls = [0]
        run_calls = []

        def counting_broken_wrap(cmd, bp):
            wrap_calls[0] += 1
            raise RuntimeError("srt unavailable")

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "_wrap_for_sandbox", counting_broken_wrap)
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        assert wrap_calls[0] == 1
        assert run_calls == []


# --- Broker-fd handshake tests (Phase 6b FPLAN-0250) -------------------------


class TestFlagOffNoBroker:
    """Flag OFF: no broker connection attempted at all."""

    def test_flag_off_no_broker_activity(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        connect_calls = []

        def tracking_connect(*args, **kwargs):
            connect_calls.append(args)
            raise RuntimeError("should never be called")

        monkeypatch.setattr(mod, "_connect_broker", tracking_connect)
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert connect_calls == []

    def test_flag_off_no_broker_fd_in_env(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.delenv("AIPASS_SANDBOX_ENABLED", raising=False)

        captured_env = {}

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
            captured_env.update(env)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        assert "AIPASS_BROKER_FD" not in captured_env


class TestBrokerDownFailsLoud:
    """Broker down + flag ON → exit -4, agent never spawned."""

    def test_broker_connect_failure_aborts(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=OSError("broker socket not found")),
        )
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0

    def test_broker_bad_hmac_aborts(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        run_calls = []

        def capture_run(cmd, *args, **kwargs):
            run_calls.append(cmd)
            return (0, False)

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=RuntimeError("Broker identify failed: bad HMAC")),
        )
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert run_calls == []
        assert exc_info.value.code != 0

    def test_broker_failure_sends_bounce(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        mock_bounce = MagicMock()
        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(
            mod,
            "_connect_broker",
            MagicMock(side_effect=OSError("socket missing")),
        )
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        mock_bounce.assert_called_once()


class TestBrokerFdHandshake:
    """Flag ON + broker up: fd passed to child, parent closes after spawn."""

    def test_broker_fd_in_env_and_pass_fds(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        captured_env = {}
        captured_pass_fds = []

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, pass_fds=()):
            captured_env.update(env)
            captured_pass_fds.append(pass_fds)
            return (0, False)

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 42

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert captured_env.get("AIPASS_BROKER_FD") == "42"
        assert captured_pass_fds == [(42,)]
        mock_sock.close.assert_called_once()

    def test_parent_closes_socket_after_spawn(self, monkeypatch, main_argv):
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 7

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        mock_sock.close.assert_called_once()

    def test_broker_fd_cleaned_from_env_after_spawn(self, monkeypatch, main_argv):
        """After spawn+close, AIPASS_BROKER_FD removed from spawn_env."""
        argv, lock_file, stderr_log = main_argv
        monkeypatch.setenv("AIPASS_SANDBOX_ENABLED", "1")

        env_snapshots = []

        def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, pass_fds=()):
            env_snapshots.append(dict(env))
            return (0, False)

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 10

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
        monkeypatch.setattr(
            mod,
            "_wrap_for_sandbox",
            lambda cmd, bp: ["/bin/bash", "-c", "bwrap " + " ".join(cmd)],
        )
        monkeypatch.setattr(mod, "_connect_broker", MagicMock(return_value=mock_sock))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        # During the run, env had the FD
        assert env_snapshots[0]["AIPASS_BROKER_FD"] == "10"


@pytest.mark.skipif(sys.platform != "linux", reason="AF_UNIX broker daemon is Linux-only")
class TestBrokerRealE2E:
    """Real multi-process e2e: broker daemon, identified connection, child reads fd."""

    def test_child_inherits_broker_fd(self, tmp_path):
        """Start real broker, create identified conn, spawn child that reads AIPASS_BROKER_FD."""
        import time as time_mod
        from aipass.drone.apps.handlers.broker.daemon import BrokerDaemon
        from aipass.drone.apps.handlers.broker.client import create_identified_connection

        # Set up repo root with branch dir + .trinity marker (broker marker-walk requires it)
        repo_root = tmp_path / "repo"
        branch_dir = repo_root / "src" / "aipass" / "testbranch"
        branch_dir.mkdir(parents=True)
        trinity_dir = branch_dir / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / "passport.json").write_text('{"branch_info": {"branch_name": "testbranch"}}', encoding="utf-8")
        target_file = branch_dir / "deleteme.txt"
        target_file.write_text("delete me", encoding="utf-8")

        # Start real broker
        sock_path = tmp_path / "broker.sock"
        audit_path = tmp_path / "audit.jsonl"
        secret_path = tmp_path / "secret"
        broker = BrokerDaemon(
            repo_root=repo_root,
            socket_path=sock_path,
            audit_path=audit_path,
            secret_path=secret_path,
        )
        t = broker.start_background()
        time_mod.sleep(0.5)

        try:
            # Create identified connection (as the launcher would)
            sock = create_identified_connection(sock_path, secret_path, "testbranch")
            broker_fd = sock.fileno()

            # Spawn a real child that reads AIPASS_BROKER_FD and sends a delete
            child_script = tmp_path / "child.py"
            child_script.write_text(
                """
import os, socket, json

fd = int(os.environ["AIPASS_BROKER_FD"])
s = socket.socket(fileno=fd)
try:
    req = json.dumps({"op": "delete", "path": "deleteme.txt", "request_id": "e2e1"}) + "\\n"
    s.sendall(req.encode())
    data = b""
    while b"\\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    resp = json.loads(data.decode())
    # Write result to a file so parent can verify
    with open(os.environ["RESULT_FILE"], "w") as f:
        json.dump(resp, f)
finally:
    s.detach()
""",
                encoding="utf-8",
            )

            result_file = tmp_path / "result.json"
            env = os.environ.copy()
            env["AIPASS_BROKER_FD"] = str(broker_fd)
            env["RESULT_FILE"] = str(result_file)

            proc = subprocess.Popen(
                [sys.executable, str(child_script)],
                env=env,
                pass_fds=(broker_fd,),
                close_fds=True,
            )
            # Parent closes its copy
            sock.close()

            proc.wait(timeout=10)
            assert proc.returncode == 0

            # Verify the delete happened
            assert not target_file.exists()

            # Verify the child got a success response
            import json as json_mod

            result = json_mod.loads(result_file.read_text(encoding="utf-8"))
            assert result["ok"] is True

            # Verify audit log carries identity
            audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            delete_entries = [
                json_mod.loads(line) for line in audit_lines if json_mod.loads(line).get("op") == "delete"
            ]
            assert len(delete_entries) >= 1
            assert delete_entries[-1]["identity"] == "testbranch"
            assert delete_entries[-1]["result"] == "DELETED"

        finally:
            broker.stop()
            t.join(timeout=3)


# === Wake-back tests (TDPLAN-0012) ==========================================


class TestWakeSender:
    """_wake_sender guards and wake-back dispatch."""

    def test_skips_empty_sender(self, monkeypatch):
        """Empty sender returns skipped_sender."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        result = _wake_sender("", "@target", 0, "/fake/lock")
        assert result == "skipped_sender"

    def test_skips_whitespace_sender(self, monkeypatch):
        """Whitespace-only sender returns skipped_sender."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        result = _wake_sender("   ", "@target", 0, "/fake/lock")
        assert result == "skipped_sender"

    def test_skips_self_wake(self, monkeypatch):
        """Sender equal to completed agent returns skipped_self."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        result = _wake_sender("@trigger", "@trigger", 0, "/fake/lock")
        assert result == "skipped_self"

    def test_skips_self_wake_case_insensitive(self, monkeypatch):
        """Self-wake guard is case-insensitive."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        result = _wake_sender("Trigger", "@TRIGGER", 0, "/fake/lock")
        assert result == "skipped_self"

    def test_wake_back_carries_empty_sender(self, monkeypatch):
        """Wake-back session carries empty sender to terminate the chain."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        _wake_sender("@prax", "@trigger", 0, "/fake/lock")
        _, kwargs = mock_wake.call_args
        assert mock_wake.call_args.args == ("@prax",)
        assert kwargs["auto"] is True
        assert kwargs["sender"] == ""

    def test_any_citizen_reaches_wake_branch(self, monkeypatch):
        """Any citizen sender reaches wake_branch."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        result = _wake_sender("@prax", "@target", 0, "/fake/lock")
        assert result == "success"
        mock_wake.assert_called_once()

    def test_depth_cap_blocks(self, monkeypatch):
        """AIPASS_WAKE_DEPTH >= MAX_WAKE_DEPTH returns blocked_depth."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", str(MAX_WAKE_DEPTH))
        result = _wake_sender("@prax", "@target", 0, "/fake/lock")
        assert result == "blocked_depth"

    def test_depth_cap_over_max_blocks(self, monkeypatch):
        """Depth above max also blocks."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", str(MAX_WAKE_DEPTH + 5))
        result = _wake_sender("@prax", "@target", 0, "/fake/lock")
        assert result == "blocked_depth"

    def test_success_on_wake(self, monkeypatch):
        """Successful wake_branch call returns success."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@trigger", "@target", 0, "/fake/lock")
        assert result == "success"
        _, kwargs = mock_wake.call_args
        assert mock_wake.call_args.args == ("@trigger",)
        assert kwargs["auto"] is True
        assert kwargs["sender"] == ""

    def test_wake_back_message_names_completed_target(self, monkeypatch):
        """Wake-back custom_message names the completed target and exit code,
        not the generic mail-check prompt — the woken lead was told nothing
        about which target finished (@daemon, 077cd1cf)."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        _wake_sender("@prax", "@target", 1, "/fake/lock")
        _, kwargs = mock_wake.call_args
        assert "@target" in kwargs["custom_message"]
        assert "1" in kwargs["custom_message"]

    def test_blocked_locked_on_lock_failure(self, monkeypatch):
        """wake_branch failing with lock-related message returns blocked_locked."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "lock: Active agent (PID 1234)"
        mock_wake = MagicMock(return_value=(mock_status, False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@prax", "@target", 0, "/fake/lock")
        assert result == "blocked_locked"

    def test_blocked_occupied_on_interactive(self, monkeypatch):
        """wake_branch failing with occupancy message returns blocked_occupied."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "blocked: Cannot spawn — interactive session running"
        mock_wake = MagicMock(return_value=(mock_status, False))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@trigger", "@target", 0, "/fake/lock")
        assert result == "blocked_occupied"

    def test_failed_on_exception(self, monkeypatch):
        """Exception during wake returns failed."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            MagicMock(side_effect=RuntimeError("broken")),
        )

        result = _wake_sender("@prax", "@target", 0, "/fake/lock")
        assert result == "failed"

    def test_depth_incremented_before_wake(self, monkeypatch):
        """AIPASS_WAKE_DEPTH is incremented before calling wake_branch."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.setenv("AIPASS_WAKE_DEPTH", "1")

        captured_depth = []

        def capture_wake(*args, **kwargs):
            captured_depth.append(os.environ.get("AIPASS_WAKE_DEPTH"))
            mock_status = MagicMock()
            mock_status.summary = "ok"
            return mock_status, True

        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            capture_wake,
        )

        _wake_sender("@trigger", "@target", 0, "/fake/lock")
        assert captured_depth == ["2"]

    def test_wake_called_on_failure_exit(self, monkeypatch):
        """Wake fires on non-zero exit code too."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)

        mock_status = MagicMock()
        mock_status.summary = "ok"
        mock_wake = MagicMock(return_value=(mock_status, True))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )

        result = _wake_sender("@prax", "@target", 1, "/fake/lock")
        assert result == "success"
        mock_wake.assert_called_once()


class TestLogWakeResult:
    """_log_wake_result writes to dispatch_wake.log."""

    def test_creates_log_file(self, tmp_path):
        """Log file created under target's logs/ directory."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")
        logs_dir = tmp_path / "branch" / "logs"

        _log_wake_result("@target", "@sender", 0, "success", str(lock))

        log_file = logs_dir / "dispatch_wake.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "target=@target" in content
        assert "sender=@sender" in content
        assert "exit_code=0" in content
        assert "wake_result=success" in content

    def test_appends_to_existing(self, tmp_path):
        """Subsequent calls append, not overwrite."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")
        logs_dir = tmp_path / "branch" / "logs"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "dispatch_wake.log"
        log_file.write_text("existing line\n", encoding="utf-8")

        _log_wake_result("@target", "@sender", 0, "success", str(lock))

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "existing line"
        assert "wake_result=success" in lines[1]

    def test_all_result_values(self, tmp_path):
        """All result enum values are logged correctly."""
        lock = tmp_path / "branch" / ".ai_mail.local" / ".dispatch.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("{}", encoding="utf-8")

        for result_tag in (
            "success",
            "blocked_occupied",
            "blocked_locked",
            "blocked_depth",
            "skipped_sender",
            "failed",
        ):
            _log_wake_result("@t", "@s", 0, result_tag, str(lock))

        log_file = tmp_path / "branch" / "logs" / "dispatch_wake.log"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 6


class TestWakeBackIntegration:
    """Wake-back wired into main() — fires after lock cleanup on both paths."""

    def test_wake_called_on_success(self, monkeypatch, main_argv):
        """_wake_sender called with correct args after successful agent run."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []

        def track_wake(sender, branch_email, exit_code, lf):
            wake_calls.append((sender, branch_email, exit_code))
            return "success"

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", track_wake)
        monkeypatch.setattr(mod, "_log_wake_result", MagicMock())
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert len(wake_calls) == 1
        assert wake_calls[0] == ("@sender", "@test_branch", 0)

    def test_wake_called_on_failure(self, monkeypatch, main_argv):
        """_wake_sender called after all attempts fail (in addition to bounce)."""
        argv, lock_file, stderr_log = main_argv

        wake_calls = []
        mock_bounce = MagicMock()

        def track_wake(sender, branch_email, exit_code, lf):
            wake_calls.append((sender, branch_email, exit_code))
            return "success"

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
        monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", track_wake)
        monkeypatch.setattr(mod, "_log_wake_result", MagicMock())
        monkeypatch.setattr(
            mod,
            "time",
            MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()),
        )
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        mock_bounce.assert_called_once()
        assert len(wake_calls) == 1
        assert wake_calls[0][2] != 0

    def test_log_wake_result_called(self, monkeypatch, main_argv):
        """_log_wake_result called with wake result after main completes."""
        argv, lock_file, stderr_log = main_argv

        log_calls = []

        monkeypatch.setattr("sys.argv", argv)
        monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
        monkeypatch.setattr(mod, "_send_bounce", MagicMock())
        monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_wake_sender", MagicMock(return_value="success"))
        monkeypatch.setattr(mod, "_log_wake_result", lambda *a: log_calls.append(a))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.paths.find_repo_root",
            MagicMock(return_value=Path("/fake/repo")),
        )

        with pytest.raises(SystemExit):
            main()

        assert len(log_calls) == 1
        branch_email, sender, exit_code, result, lf = log_calls[0]
        assert branch_email == "@test_branch"
        assert sender == "@sender"
        assert exit_code == 0
        assert result == "success"


# --- Fix 1: per-attempt stdout preservation ---------------------------


def test_rotate_attempt_stdout_preserves_content(tmp_path):
    """A non-empty stdout log is renamed to dispatch_stdout.attempt-N.log."""
    stdout_log = tmp_path / "dispatch_stdout.log"
    stdout_log.write_text('{"result": "boom"}', encoding="utf-8")

    _rotate_attempt_stdout(str(stdout_log), 2)

    assert not stdout_log.exists()
    preserved = tmp_path / "dispatch_stdout.attempt-2.log"
    assert preserved.read_text(encoding="utf-8") == '{"result": "boom"}'


def test_rotate_attempt_stdout_empty_file_noop(tmp_path):
    """An empty stdout log is left alone -- nothing worth preserving."""
    stdout_log = tmp_path / "dispatch_stdout.log"
    stdout_log.write_text("", encoding="utf-8")

    _rotate_attempt_stdout(str(stdout_log), 1)

    assert stdout_log.exists()
    assert not (tmp_path / "dispatch_stdout.attempt-1.log").exists()


def test_rotate_attempt_stdout_missing_file_noop(tmp_path):
    """No error when there's no stdout log yet."""
    _rotate_attempt_stdout(str(tmp_path / "missing.log"), 1)
    assert not (tmp_path / "dispatch_stdout.attempt-1.log").exists()


def test_stdout_preserved_across_retries(monkeypatch, main_argv):
    """Each failed attempt's stdout survives as dispatch_stdout.attempt-N.log
    instead of being silently truncated by the next attempt -- the result
    JSON is the only artifact naming why an attempt failed."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = lock_file.parent.parent / "logs"

    calls = {"n": 0}

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        calls["n"] += 1
        Path(stdout_path).write_text(f'{{"result": "attempt-{calls["n"]}-failure"}}', encoding="utf-8")
        return (1, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert "attempt-1-failure" in (logs_dir / "dispatch_stdout.attempt-1.log").read_text(encoding="utf-8")
    assert "attempt-2-failure" in (logs_dir / "dispatch_stdout.attempt-2.log").read_text(encoding="utf-8")
    # Final (3rd) attempt's stdout is left in place, unrotated, for post-processing
    assert "attempt-3-failure" in (logs_dir / "dispatch_stdout.log").read_text(encoding="utf-8")


# --- Fix 2: per-attempt exit codes in the branch-local stderr log -----


def test_per_attempt_exit_code_written_to_stderr_log(monkeypatch, main_argv):
    """Each attempt's exit code lands in dispatch_stderr.log itself, not just prax."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    content = Path(stderr_log).read_text(encoding="utf-8")
    assert "Attempt 1/3 exited: code=1" in content
    assert "Attempt 2/3 exited: code=0" in content


def test_per_attempt_startup_timeout_noted_in_stderr_log(monkeypatch, main_argv):
    """A startup-timeout attempt is distinguished from a plain exit code in the log."""
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(-3, True), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    content = Path(stderr_log).read_text(encoding="utf-8")
    assert "Attempt 1/3 exited: code=-3 (startup timeout)" in content


# --- Fix 3: parsed stdout result JSON reaches the bounce reason -------


def test_parse_result_json_from_whole_file(tmp_path):
    """The whole stdout file parses as the print-mode result object."""
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text('{"is_error": true, "result": "boom"}', encoding="utf-8")
    assert _parse_result_json(str(stdout_log)) == {"is_error": True, "result": "boom"}


def test_parse_result_json_last_line_when_output_precedes_it(tmp_path):
    """When earlier stdout precedes the JSON, only the last line is the result object."""
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text('some banner text\n{"is_error": false, "result": "ok"}', encoding="utf-8")
    assert _parse_result_json(str(stdout_log)) == {"is_error": False, "result": "ok"}


def test_parse_result_json_empty_or_missing_returns_empty_dict(tmp_path):
    """Missing or empty stdout log parses to {} rather than raising."""
    assert _parse_result_json(str(tmp_path / "missing.log")) == {}
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    assert _parse_result_json(str(empty)) == {}


def test_summarize_result_json_no_capture():
    """No result JSON captured is reported explicitly, not as a blank string."""
    assert _summarize_result_json("/nonexistent/path.log") == "(no result JSON captured)"


def test_bounce_reason_includes_parsed_stdout_result(monkeypatch, main_argv):
    """Bounce reason names the actual failure cause from the result JSON,
    not just the bare exit code."""
    argv, lock_file, stderr_log = main_argv

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        Path(stdout_path).write_text(
            '{"is_error": true, "subtype": "error_during_execution", "result": "boom detail"}',
            encoding="utf-8",
        )
        return (1, False)

    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "boom detail" in reason
    assert "is_error=True" in reason


# --- Fix 4: lock-ownership-verified cleanup ----------------------------


def test_cleanup_own_lock_deletes_when_pid_matches(tmp_path):
    """Lock is deleted when its recorded pid matches this process."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert not lock.exists()


def test_cleanup_own_lock_preserves_foreign_pid(tmp_path):
    """A lock re-owned by a successor monitor (different PID) is left alone --
    unconditional unlink previously let one monitor steal a successor's lock."""
    lock = tmp_path / ".dispatch.lock"
    foreign_pid = os.getpid() + 1
    lock.write_text(json.dumps({"pid": foreign_pid}), encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == foreign_pid


def test_cleanup_own_lock_missing_file_noop(tmp_path):
    """No error when the lock file doesn't exist."""
    _cleanup_own_lock(str(tmp_path / ".dispatch.lock"))


def test_cleanup_own_lock_unreadable_json_preserved(tmp_path):
    """Corrupt lock content is left in place rather than blindly deleted."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text("not json", encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()


def test_main_does_not_steal_successor_lock(monkeypatch, main_argv):
    """If a successor monitor re-owns the lock mid-run, this monitor's
    end-of-run cleanup must not delete it out from under the successor."""
    argv, lock_file, stderr_log = main_argv
    successor_pid = os.getpid() + 999

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        lock_file.write_text(json.dumps({"pid": successor_pid}), encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert lock_file.exists()
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == successor_pid


# --- Fix 5: orphaned background tasks are not a silent success --------


def test_read_stderr_segment_only_after_offset(tmp_path):
    """Only content written after the given byte offset is returned."""
    log = tmp_path / "stderr.log"
    log.write_text("before\n", encoding="utf-8")
    offset = log.stat().st_size
    with open(log, "a", encoding="utf-8") as f:
        f.write("after\n")

    segment = _read_stderr_segment(str(log), offset)

    assert "after" in segment
    assert "before" not in segment


def test_bg_tasks_still_running_treated_as_incomplete(monkeypatch, main_argv):
    """Exit 0 with the print-mode bg-wait-ceiling marker in this attempt's
    stderr is NOT a silent success -- it bounces and exits nonzero."""
    argv, lock_file, stderr_log = main_argv

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        with open(stderr_log, "a", encoding="utf-8") as f:
            f.write(f"{BG_TASKS_MARKER} after 600s; terminating.\n")
        return (0, False)

    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "background tasks" in reason.lower()


def test_bg_tasks_marker_from_prior_attempt_does_not_leak_forward(monkeypatch, main_argv):
    """The bg-orphan check only looks at THIS attempt's stderr slice --
    a marker from an earlier, unrelated failure must not taint a later
    clean success."""
    argv, lock_file, stderr_log = main_argv
    calls = {"n": 0}

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        calls["n"] += 1
        if calls["n"] == 1:
            with open(stderr_log, "a", encoding="utf-8") as f:
                f.write(f"unrelated crash trace mentioning {BG_TASKS_MARKER} in passing\n")
            return (1, False)
        return (0, False)

    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_bounce.assert_not_called()


# === Wake-back honesty: manager senders (VERA field report) =================
#
# wake_branch's manager gate delivers the mail and skips the wake by design, but
# returns (status, True) — so _wake_sender read success=True and logged
# "woken after ... completed" for a wake that never happened. The status object
# was honest; the bool was not. These pin the honest tag.


class TestWakeBackManagerHonesty:
    """A manager sender is mailed, never woken — the log must say exactly that."""

    @staticmethod
    def _manager_gate_status():
        """Real DispatchStatus as wake_branch's manager gate leaves it."""
        status = DispatchStatus()
        status.ok("resolve", "@devpulse → /repo/src/aipass/devpulse")
        status.info("manager", "@devpulse is a manager — mail only, wake skipped")
        return status

    @staticmethod
    def _patch_wake(monkeypatch, status, success):
        monkeypatch.delenv("AIPASS_WAKE_DEPTH", raising=False)
        mock_wake = MagicMock(return_value=(status, success))
        monkeypatch.setattr(
            "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
            mock_wake,
        )
        return mock_wake

    def test_manager_sender_returns_mailed_manager(self, monkeypatch):
        """The gate's True must not be reported as a successful wake.

        Tag changed from skipped_manager to mailed_manager on 2026-08-21: the
        manager is no longer merely skipped, it is mailed. "Skipped" was the
        honest tag for a silent drop and is the wrong word for a delivery.
        """
        monkeypatch.setattr(mod, "logger", MagicMock())
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        )
        result = _wake_sender("@devpulse", "@ai_mail", 0, "/fake/lock")
        assert result == "mailed_manager"

    def test_manager_wake_back_never_claims_woken(self, monkeypatch):
        """No log line may assert the manager was woken — it says MAILED instead."""
        mock_logger = MagicMock()
        monkeypatch.setattr(mod, "logger", mock_logger)
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        )

        _wake_sender("@devpulse", "@ai_mail", 0, "/fake/lock")

        formats = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
        assert not any("woken after" in f for f in formats), f"claimed a wake: {formats}"
        assert any("mailed" in f.lower() for f in formats), f"no mail logged: {formats}"

    def test_daemon_bypassed_manager_still_reports_success(self, monkeypatch):
        """The @daemon self-wake exception records manager as ok — that IS a real wake."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        status = DispatchStatus()
        status.ok("manager", "@devpulse manager gate bypassed — daemon-scheduled self-wake")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        result = _wake_sender("@devpulse", "@ai_mail", 0, "/fake/lock")
        assert result == "success"

    def test_builder_sender_unaffected(self, monkeypatch):
        """A normal citizen has no manager step and still reports success."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        status = DispatchStatus()
        status.ok("resolve", "@prax → /repo/src/aipass/prax")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        result = _wake_sender("@prax", "@ai_mail", 0, "/fake/lock")
        assert result == "success"

    def test_manager_sender_is_mailed_not_silently_dropped(self, monkeypatch):
        """P0: a manager was TOLD it would be woken and then silently was not.

        The blocklist is correct and stays — two claudes on one session id kills
        the running job (the OSPREY kill). The bug is the silent return: the
        wake-back message was built and dropped on the floor, so a manager learned
        a dispatch finished only if the agent volunteered an email. Ten consecutive
        skipped_manager lines in canary's dispatch_wake.log, and @devpulse confirmed
        it live twice tonight (@ai_mail and @drone back to back).
        """
        monkeypatch.setattr(mod, "logger", MagicMock())
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)

        result = _wake_sender("@devpulse", "@ai_mail", 0, "/fake/lock")

        assert result == "mailed_manager"
        assert sent.called, "manager wake-back sent no mail — the silent drop"
        argv = sent.call_args.args[0]
        assert argv[:3] == ["drone", "@ai_mail", "send"]
        assert argv[3] == "@devpulse"

    def test_manager_mail_names_target_and_exit_code(self, monkeypatch):
        """The mail must carry what the dropped wake-back carried: WHICH target
        finished and how. A manager cannot verify or hand off the next phase
        without it (@daemon, 077cd1cf)."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        sent = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(mod.subprocess, "run", sent)

        _wake_sender("@devpulse", "@ai_mail", 3, "/fake/lock")

        body = " ".join(sent.call_args.args[0][4:])
        assert "@ai_mail" in body
        assert "3" in body

    def test_manager_mail_failure_is_not_reported_as_delivered(self, monkeypatch):
        """If the send fails the manager still learns nothing — that must not wear
        the same tag as a delivered mail. Same lesson as the gate's True."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        self._patch_wake(monkeypatch, self._manager_gate_status(), True)
        monkeypatch.setattr(
            mod.subprocess, "run", MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr="boom"))
        )

        result = _wake_sender("@devpulse", "@ai_mail", 0, "/fake/lock")
        assert result == "failed_manager_mail"

    def test_non_manager_wake_back_sends_no_mail(self, monkeypatch):
        """An ordinary citizen is woken, not mailed. The mail exists only because
        the wake cannot happen — adding it everywhere would double every wake-back."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        status = DispatchStatus()
        status.ok("resolve", "@prax → /repo/src/aipass/prax")
        status.ok("spawn", "agent started")
        self._patch_wake(monkeypatch, status, True)
        sent = MagicMock()
        monkeypatch.setattr(mod.subprocess, "run", sent)

        result = _wake_sender("@prax", "@ai_mail", 0, "/fake/lock")
        assert result == "success"
        assert not sent.called

    def test_skipped_manager_reaches_the_wake_log(self, monkeypatch, tmp_path):
        """The honest tag is what lands in dispatch_wake.log."""
        monkeypatch.setattr(mod, "logger", MagicMock())
        lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
        lock_file.parent.mkdir(parents=True)
        lock_file.write_text("{}", encoding="utf-8")

        _log_wake_result("@ai_mail", "@devpulse", 0, "skipped_manager", str(lock_file))

        written = (tmp_path / "logs" / "dispatch_wake.log").read_text(encoding="utf-8")
        assert "wake_result=skipped_manager" in written
        assert "sender=@devpulse" in written


# --- session-pointer aware retry loop ---------------------------------
#
# wake.py now emits --resume <id> and --session-id <id> where it only ever
# emitted -c. Every place the monitor reasoned about "-c" had to learn the
# new flags, and one of them (the attempt loop) had to learn that a session
# id is single-use: the CLI refuses an id that already exists, so re-running
# an identical command is fatal where it used to be free.


@pytest.fixture
def pointer_home(tmp_path, monkeypatch):
    """Point Path.home at tmp_path so transcript paths land under the sandbox."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _plant_transcript(branch_path, session_id):
    """Create the transcript file Claude would have written for a session."""
    transcript = mod.session_pointer.transcript_file(branch_path, session_id)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")
    return transcript


def test_has_resume_detects_dash_c():
    """The original form: continue whatever transcript was modified last."""
    assert _has_resume(["claude", "-c", "-p", "hi"]) is True


def test_has_resume_detects_long_resume_flag():
    """--resume was invisible to the old check, so a resumed run logged as fresh
    and never earned its strike-3 fresh switch."""
    assert _has_resume(["claude", "--resume", "abc", "-p", "hi"]) is True


def test_has_resume_detects_short_resume_flag():
    """-r is the same flag; the CLI accepts it and so must we."""
    assert _has_resume(["claude", "-r", "abc", "-p", "hi"]) is True


def test_has_resume_false_for_a_fresh_command():
    """A minted session is not a resume — --session-id starts something new."""
    assert _has_resume(["claude", "-p", "hi", "--session-id", "abc"]) is False


def test_session_id_in_reads_the_value():
    assert _session_id_in(["claude", "--session-id", "abc", "-p", "hi"]) == "abc"


def test_session_id_in_none_when_absent():
    assert _session_id_in(["claude", "-c", "-p", "hi"]) is None


def test_session_id_in_none_when_flag_has_no_value():
    """A truncated command must read as "no id", not raise on the way past."""
    assert _session_id_in(["claude", "-p", "hi", "--session-id"]) is None


def test_make_fresh_cmd_removes_resume_pair():
    """The uuid goes with its flag — orphaned, it becomes a positional prompt."""
    cmd = ["claude", "--resume", "abc-123", "-p", "hi", "--model", "opus"]
    assert _make_fresh_cmd(cmd) == ["claude", "-p", "hi", "--model", "opus"]


def test_make_fresh_cmd_removes_short_resume_pair():
    cmd = ["claude", "-r", "abc-123", "-p", "hi", "--model", "opus"]
    assert _make_fresh_cmd(cmd) == ["claude", "-p", "hi", "--model", "opus"]


def test_make_fresh_cmd_removes_session_id_pair():
    cmd = ["claude", "-p", "hi", "--model", "opus", "--session-id", "abc-123"]
    assert _make_fresh_cmd(cmd) == ["claude", "-p", "hi", "--model", "opus"]


def test_make_fresh_cmd_leaves_everything_else_byte_identical():
    """Strip the bindings and nothing else — the prompt and every option survive."""
    cmd = [
        "claude",
        "-c",
        "--resume",
        "abc-123",
        "--session-id",
        "def-456",
        "-p",
        "check inbox",
        "--model",
        "opus",
        "--max-turns",
        "100",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
    ]
    assert _make_fresh_cmd(cmd) == [
        "claude",
        "-p",
        "check inbox",
        "--model",
        "opus",
        "--max-turns",
        "100",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "json",
    ]


def test_attempt_1_is_the_command_as_built(tmp_path, pointer_home):
    """Strike 1 changes nothing — wake.py already decided where this lands."""
    cmd = ["claude", "--resume", "abc", "-p", "hi"]
    built, mode = _cmd_for_attempt(cmd, 1, tmp_path)
    assert built == cmd
    assert mode == "resume"


def test_attempt_2_converts_a_consumed_session_id_to_resume(tmp_path, pointer_home):
    """THE regression guard: attempt 1 created the session, so the id is spent.

    Re-sending it gets "Session ID <id> is already in use" and no output at
    all — three strikes would fail instantly instead of recovering.

    The rebuilt command must match wake.py's shape exactly: `--resume <id>`
    leads, because that is the form verified against the CLI. Swapping the
    flag where --session-id sat would trail it after `-p <prompt>` — an
    argument order nobody has ever run.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = _cmd_for_attempt(cmd, 2, branch)

    assert built == ["claude", "--resume", "abc-123", "-p", "hi"]
    assert "--session-id" not in built
    assert mode == "resume"


def test_attempt_2_resume_leads_even_for_a_long_command(tmp_path, pointer_home):
    """Position is what this pins: --resume sits at index 1, never after -p."""
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = [
        "/usr/bin/claude",
        "-p",
        "check inbox",
        "--model",
        "opus",
        "--max-turns",
        "100",
        "--output-format",
        "json",
        "--session-id",
        "abc-123",
    ]

    built, _ = _cmd_for_attempt(cmd, 2, branch)

    assert built[:3] == ["/usr/bin/claude", "--resume", "abc-123"]
    assert built[3:] == ["-p", "check inbox", "--model", "opus", "--max-turns", "100", "--output-format", "json"]


def test_attempt_2_leaves_a_command_with_nothing_but_a_session_id_alone(tmp_path, pointer_home):
    """Degenerate input: no binary to lead with, so there is nothing to rebuild."""
    branch = tmp_path / "branch"
    branch.mkdir()
    _plant_transcript(branch, "abc-123")
    cmd = ["--session-id", "abc-123"]

    built, _ = _cmd_for_attempt(cmd, 2, branch)

    assert built == cmd


def test_attempt_2_leaves_an_unconsumed_session_id_alone(tmp_path, pointer_home):
    """No transcript means attempt 1 never got far enough to claim the id."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "-p", "hi", "--session-id", "abc-123"]

    built, mode = _cmd_for_attempt(cmd, 2, branch)

    assert built == cmd
    assert mode == "fresh"


def test_attempt_2_of_a_dash_c_run_is_unchanged(tmp_path, pointer_home):
    """The -c path has no id to consume — retrying it is free, as before."""
    cmd = ["claude", "-c", "-p", "hi"]
    built, mode = _cmd_for_attempt(cmd, 2, tmp_path)
    assert built == cmd
    assert mode == "resume"


def test_attempt_3_mints_a_new_id_and_repoints_the_branch(tmp_path, pointer_home):
    """Strike 3 abandons the bad session but keeps its own crash-safety."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "--resume", "old-id", "-p", "hi", "--model", "opus"]

    built, mode = _cmd_for_attempt(cmd, 3, branch)

    assert mode == "fresh"
    assert "--resume" not in built and "old-id" not in built
    assert "--session-id" in built
    new_id = built[built.index("--session-id") + 1]
    assert new_id != "old-id"
    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == new_id
    assert pointer["set_by"] == "monitor-retry-fresh"


def test_attempt_3_replaces_a_spent_minted_id(tmp_path, pointer_home):
    """A fresh run that failed twice must not re-send the id it already used."""
    branch = tmp_path / "branch"
    branch.mkdir()
    cmd = ["claude", "-p", "hi", "--session-id", "spent-id"]

    built, _ = _cmd_for_attempt(cmd, 3, branch)

    assert "spent-id" not in built
    assert built[built.index("--session-id") + 1] != "spent-id"


def test_attempt_3_still_spawns_when_the_pointer_cannot_be_written(tmp_path, pointer_home, monkeypatch):
    """A pointer write is never worth losing the last attempt over."""
    branch = tmp_path / "branch"
    branch.mkdir()
    monkeypatch.setattr(mod.session_pointer, "write_pointer", lambda *a, **kw: False)

    built, mode = _cmd_for_attempt(["claude", "-c", "-p", "hi"], 3, branch)

    assert mode == "fresh"
    assert "-c" not in built
    assert "--session-id" in built


def test_attempt_3_of_an_unbound_command_is_unchanged(tmp_path, pointer_home):
    """Nothing to abandon and no id to burn — leave it exactly as it is."""
    cmd = ["claude", "-p", "hi", "--model", "opus"]
    built, mode = _cmd_for_attempt(cmd, 3, tmp_path)
    assert built == cmd
    assert mode == "fresh"


_AIMED_CMD = ["claude", "--resume", "aimed-id", "-p", "hi"]
_C_CMD = ["claude", "-c", "-p", "hi"]


def test_reconcile_refuses_to_adopt_a_session_landed_on_by_bare_c(tmp_path, pointer_home):
    """THE RULING (Patrick, 2026-08-20): a -c landing is never written down.

    -c picks by file mtime. Recording that choice would promote a guess into a
    durable record, and every later dispatch would resume it deliberately — so
    a branch whose newest transcript happened to be a human's chat would be
    married to that chat forever. One wrong landing becomes permanent.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "landed-by-mtime", "is_error": False}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _C_CMD)

    assert mod.session_pointer.read_pointer(branch) is None, "a -c landing must leave the branch pointerless"


def test_reconcile_writes_the_pointer_when_we_aimed_and_landed_elsewhere(tmp_path, pointer_home):
    """We named a session and the CLI reports a different one — record the truth.

    This is how a strike-3 remint reaches the pointer: we aimed, the id moved,
    and the branch must end up pointing at where its agent actually is.
    """
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "actual-id", "is_error": False}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "actual-id"
    assert pointer["set_by"] == "monitor-reconciled"


def test_reconcile_adopts_a_minted_session_id(tmp_path, pointer_home):
    """--session-id counts as aiming just as much as --resume does."""
    branch = tmp_path / "branch"
    branch.mkdir()
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "minted-id"}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), ["claude", "-p", "hi", "--session-id", "minted-id"])

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "minted-id"


def test_reconcile_does_not_rewrite_a_matching_pointer(tmp_path, pointer_home):
    """We landed where we aimed — no write, so set_by keeps naming who decided."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "same-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "same-id"}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["set_by"] == "wake-fresh"


def test_reconcile_ignores_result_json_without_a_session_id(tmp_path, pointer_home):
    """Nothing to reconcile against; the existing pointer stands."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "kept-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"is_error": True}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "kept-id"


def test_reconcile_leaves_an_existing_pointer_alone_on_a_c_run(tmp_path, pointer_home):
    """A -c fallback must not disturb a pointer that is already there."""
    branch = tmp_path / "branch"
    branch.mkdir()
    mod.session_pointer.write_pointer(branch, "kept-id", "wake-fresh")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "somewhere-else"}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _C_CMD)

    pointer = mod.session_pointer.read_pointer(branch)
    assert pointer is not None
    assert pointer["session_id"] == "kept-id"


def test_reconcile_survives_a_failing_pointer_write(tmp_path, pointer_home, monkeypatch):
    """Reconciliation is bookkeeping — it must never raise into the exit path."""
    branch = tmp_path / "branch"
    branch.mkdir()
    monkeypatch.setattr(mod.session_pointer, "write_pointer", lambda *a, **kw: False)
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text(json.dumps({"session_id": "actual-id"}), encoding="utf-8")

    _reconcile_pointer(branch, str(stdout_log), _AIMED_CMD)  # no raise


def test_main_third_attempt_is_fresh_for_a_resumed_dispatch(monkeypatch, main_argv, pointer_home):
    """End-to-end: --resume reaches strike 3 as a fresh, newly-minted session.

    The old `"-c" in claude_cmd` check would have left all three attempts
    identical, so a broken session could never be escaped.
    """
    argv, lock_file, stderr_log = main_argv
    argv = argv[:6] + ["claude", "--resume", "old-id", "--model", "opus"]
    calls: list[list[str]] = []

    def track_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return (1, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", track_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    assert len(calls) == 3
    assert "--resume" in calls[0] and "--resume" in calls[1]
    assert "--resume" not in calls[2]
    assert "--session-id" in calls[2]


def _run_main_capturing_pointer(monkeypatch, argv, landed_session):
    """Drive main() to a clean exit with a result JSON naming `landed_session`."""

    def fake_run(cmd, stdout_log, *args, **kwargs):
        Path(stdout_log).write_text(json.dumps({"session_id": landed_session}), encoding="utf-8")
        return (0, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_main_does_not_adopt_a_pointer_after_a_successful_c_run(monkeypatch, main_argv, pointer_home):
    """End-to-end of the ruling: a whole successful -c dispatch records nothing.

    The fixture's command is `claude -c`, so the session it landed in was chosen
    by file mtime. Writing that down would make the next dispatch resume it on
    purpose — see test_reconcile_refuses_to_adopt_a_session_landed_on_by_bare_c.
    The branch stays on -c until something dispatches it --fresh.
    """
    argv, lock_file, _ = main_argv
    branch_path = lock_file.parent.parent

    _run_main_capturing_pointer(monkeypatch, argv, "landed-by-mtime")

    assert mod.session_pointer.read_pointer(branch_path) is None


def test_main_reconciles_the_pointer_after_a_successful_aimed_run(monkeypatch, main_argv, pointer_home):
    """We aimed with --resume, so where the run actually landed IS recorded."""
    argv, lock_file, _ = main_argv
    branch_path = lock_file.parent.parent
    argv = [arg if arg != "-c" else "--resume" for arg in argv]
    argv.insert(argv.index("--resume") + 1, "aimed-id")

    _run_main_capturing_pointer(monkeypatch, argv, "landed-here")

    pointer = mod.session_pointer.read_pointer(branch_path)
    assert pointer is not None
    assert pointer["session_id"] == "landed-here"
    assert pointer["set_by"] == "monitor-reconciled"


def test_main_does_not_reconcile_after_a_failed_run(monkeypatch, main_argv, pointer_home):
    """A failed run's result JSON names a session not worth returning to."""
    argv, lock_file, stderr_log = main_argv
    branch_path = lock_file.parent.parent

    def fake_run(cmd, stdout_log, *args, **kwargs):
        Path(stdout_log).write_text(json.dumps({"session_id": "bad-session"}), encoding="utf-8")
        return (1, False)

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", MagicMock())
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        mod,
        "time",
        MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()),
    )
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=Path("/fake/repo")),
    )

    with pytest.raises(SystemExit):
        main()

    pointer = mod.session_pointer.read_pointer(branch_path)
    assert pointer is None or pointer["session_id"] != "bad-session"
