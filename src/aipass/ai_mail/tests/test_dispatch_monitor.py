# =================== AIPass ====================
# Name: test_dispatch_monitor.py
# Description: Tests for dispatch monitor lifecycle handler
# Version: 1.0.0
# Created: 2026-04-02
# Modified: 2026-04-02
# =============================================

"""Tests for dispatch_monitor -- startup check, retry loop, bounce, rate limiting."""

import json
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    _check_jsonl_activity,
    _check_rate_limited,
    _get_jsonl_projects_dir,
    _make_fresh_cmd,
    _run_with_startup_check,
    _send_bounce,
    _snapshot_jsonl_sizes,
    main,
)


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

from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import _kill_process


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

    def fake_run(cmd, stdout_log_path, stderr_fh, cwd, env, branch):
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


# --- Environment variable setup tests ---------------------------------


def test_env_vars_set_correctly(monkeypatch, main_argv):
    """Verify AIPASS_SPAWNED, SESSION_TYPE, BRANCH_NAME set; CLAUDE* stripped; venv on PATH."""
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch):
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
    # Venv bin should be on PATH
    assert "/fake/repo/.venv/bin" in captured_env.get("PATH", "")


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

    def fake_run(cmd, stdout_log_path, stderr_fh, cwd, env, branch):
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

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch):
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
    assert "/fake/repo/.venv/bin" in captured_env.get("PATH", "")


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
