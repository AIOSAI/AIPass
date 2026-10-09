# =================== AIPass ====================
# Name: test_dispatch_monitor.py
# Description: Tests for dispatch monitor lifecycle handler
# Version: 1.2.0
# Created: 2026-04-02
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's main(): the attempts, the bounce, the completion fire."""

# Split on 2026-10-08: the units, the sandbox, the wake-back, the attempt artifacts
# and the session pointer are their own files.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — STARTUP_TIMEOUT and HARD_TIMEOUT: real timeout seconds, overridden by every test
# seedgo: no-test-needed(constant) — POLL_INTERVAL and RATE_LIMIT_DELAY: real values, overridden by every test
# seedgo: no-test-needed(shared) — the startup check, kill, logs, lock, JSONL: tests/test_dispatch_monitor_helpers.py
# seedgo: no-test-needed(shared) — the sandbox gate and the broker handshake: tests/test_dispatch_monitor_sandbox.py
# seedgo: no-test-needed(shared) — _wake_sender, _log_wake_result and the decline: tests/test_dispatch_monitor_wake.py
# seedgo: no-test-needed(shared) — what each attempt leaves behind: tests/test_dispatch_monitor_artifacts.py
# seedgo: no-test-needed(shared) — the session-pointer retry loop: tests/test_dispatch_monitor_pointer.py

import json
import subprocess
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    BG_TASKS_MARKER,
    _send_bounce,
    main,
)
from aipass.ai_mail.tests.support_dispatch_monitor import _assert_sent_as_ai_mail

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# --- Fixtures --------------------------------------------------------


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


# --- Retry loop in main() tests --------------------------------------


def test_main_single_attempt_success(monkeypatch, main_argv, tmp_path, recorded_bus):
    """First attempt succeeds, no retries, and the completion fires once on the bus.

    The fire carries the dispatch id this process runs under, the report file just
    written, and sender/target as the argv named them.
    mutant: report.py fires "dispatch_complete" instead of "dispatch_completed" -> KILLED
    """
    argv, lock_file, stderr_log = main_argv

    mock_run = MagicMock(return_value=(0, False))
    mock_bounce = MagicMock()

    monkeypatch.setenv("AIPASS_DISPATCH_ID", "dsp-single")
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", mock_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_run.assert_called_once()
    mock_bounce.assert_not_called()
    report_file = tmp_path / ".dispatch_register_root" / ".aipass" / "dispatch_reports" / "dsp-single.json"
    assert report_file.is_file()
    assert recorded_bus.fires == [
        (
            "dispatch_completed",
            {
                "dispatch_id": "dsp-single",
                "report_path": str(report_file),
                "sender": "@sender",
                "target": "@test_branch",
            },
        )
    ]


def test_main_second_attempt_success(monkeypatch, main_argv, tmp_path):
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
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert mock_run.call_count == 2
    mock_bounce.assert_not_called()


def test_main_third_attempt_fresh(monkeypatch, main_argv, tmp_path):
    """Third attempt removes -c flag (fresh start)."""
    argv, lock_file, stderr_log = main_argv

    calls: list[list[str]] = []

    def track_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return (1, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", track_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
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
        MagicMock(return_value=tmp_path / "repo"),
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
    bounce.assert_called_once()


def test_main_all_three_fail_sends_bounce(monkeypatch, main_argv, tmp_path, recorded_bus):
    """All 3 fail: bounce is sent with attempt details, and the completion still fires.

    A failed dispatch is still a completed one: outside a dispatch the id is None and
    the report lands as unregistered.json.
    mutant: report.py fires sender=target -> KILLED
    """
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
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "3 attempts" in reason
    report_file = tmp_path / ".dispatch_register_root" / ".aipass" / "dispatch_reports" / "unregistered.json"
    assert recorded_bus.fires == [
        (
            "dispatch_completed",
            {
                "dispatch_id": None,
                "report_path": str(report_file),
                "sender": "@sender",
                "target": "@test_branch",
            },
        )
    ]


def test_main_rate_limit_delay(monkeypatch, main_argv, tmp_path):
    """When _check_rate_limited returns True, verify delay happens."""
    argv, lock_file, stderr_log = main_argv

    mock_time = MagicMock()
    mock_time.time = time.time
    mock_time.strftime = time.strftime
    mock_time.sleep = MagicMock()

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=True))
    monkeypatch.setattr(mod, "time", mock_time)
    monkeypatch.setattr(mod, "RATE_LIMIT_DELAY", 30)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    # Verify rate limit delay was used (30s, not 5s)
    mock_time.sleep.assert_called_with(30)
    bounce.assert_not_called()


# --- _send_bounce tests -----------------------------------------------


def test_send_bounce_success(tmp_path, monkeypatch):
    """Successful bounce sends email via drone subprocess, as ai_mail (2026-10-04)."""
    monkeypatch.setenv("AIPASS_BRANCH_NAME", "trigger")
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
    _assert_sent_as_ai_mail(mock_sub_run)


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


def test_notification_uses_at_branch_format(monkeypatch, main_argv, tmp_path, recorded_bus):
    """Notification title uses '@branch_name status' format.

    The feed line and the bus fire are two halves of one completion: both carry
    the same dispatch id, sender and report path.
    mutant: report.py fires report_path=None -> KILLED
    """
    argv, lock_file, stderr_log = main_argv

    monkeypatch.setenv("AIPASS_DISPATCH_ID", "dsp-notify")
    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    mock_notify = MagicMock()
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.notify.send_notification",
        mock_notify,
    )

    with pytest.raises(SystemExit):
        main()

    mock_notify.assert_called_once()
    bounce.assert_not_called()
    title = mock_notify.call_args[0][0]
    assert title.startswith("@test_branch")
    assert "completed" in title
    feed_extra = mock_notify.call_args.kwargs["extra"]
    assert recorded_bus.events() == ["dispatch_completed"]
    fired = recorded_bus.fires[0][1]
    assert fired["report_path"] is not None
    assert fired == {**feed_extra, "target": "@test_branch"}
    assert fired["dispatch_id"] == "dsp-notify"


# --- Max-turns detection tests -----------------------------------------


def test_max_turns_changes_notification_status(monkeypatch, main_argv, tmp_path, recorded_bus):
    """stdout containing stop_reason:max_turns changes status even with exit_code==0.

    A max-turns stop still completes: the bus fire names the same sender and target.
    mutant: report.py fires target=sender -> KILLED
    """
    argv, lock_file, stderr_log = main_argv

    # Write max_turns to stdout log
    stdout_log = Path(str(lock_file)).parent.parent / "logs" / "dispatch_stdout.log"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(cmd, stdout_log_path, stderr_fh, cwd, env, branch, **kwargs):
        # Simulate writing max_turns output
        stdout_log.write_text('{"stop_reason":"max_turns"}', encoding="utf-8")
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
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
    bounce.assert_not_called()
    title = mock_notify.call_args[0][0]
    assert "MAX TURNS" in title  # But notification shows max turns
    assert recorded_bus.events() == ["dispatch_completed"]
    fired = recorded_bus.fires[0][1]
    assert sorted(fired) == ["dispatch_id", "report_path", "sender", "target"]
    assert (fired["sender"], fired["target"]) == ("@sender", "@test_branch")


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

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
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
    bounce.assert_not_called()


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

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path),
    )

    with pytest.raises(SystemExit):
        main()

    rotated = logs_dir / "dispatch_stdout.log.1"
    assert rotated.exists()
    bounce.assert_not_called()


# --- Lock file cleanup tests ------------------------------------------


def test_lock_cleanup_on_success(monkeypatch, main_argv, tmp_path):
    """Lock is deleted on successful exit."""
    argv, lock_file, stderr_log = main_argv

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()
    bounce.assert_not_called()


def test_lock_cleanup_on_failure(monkeypatch, main_argv, tmp_path):
    """Lock is deleted even after all attempts fail (bounce path)."""
    argv, lock_file, stderr_log = main_argv

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(1, False), (1, False), (1, False)]))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
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
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert not lock_file.exists()
    # The bounce is handed the lock path while the lock still exists — cleanup follows it
    bounce.assert_called_once()
    assert bounce.call_args.args[3] == str(lock_file)


# --- Forensics + incomplete-detection main() tests ------------------------


def test_main_attempt_exit_lines_in_stderr(monkeypatch, main_argv, tmp_path):
    """Each attempt's exit code lands in the dispatch stderr log itself."""
    argv, lock_file, stderr_log = main_argv

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(side_effect=[(-3, True), (1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    content = stderr_log.read_text(encoding="utf-8")
    assert "--- Attempt 1/3 exited: code=-3 (startup timeout) ---" in content
    assert "--- Attempt 2/3 exited: code=1 ---" in content
    assert "--- Attempt 3/3 exited: code=0 ---" in content
    bounce.assert_not_called()


def test_main_failed_attempt_stdout_preserved(monkeypatch, main_argv, tmp_path):
    """A failed attempt's stdout is preserved before the retry truncates it."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = tmp_path / "branch" / "logs"

    call_count = {"n": 0}

    def fake_run(cmd, stdout_log, *args, **kwargs):
        call_count["n"] += 1
        Path(stdout_log).write_text(f'{{"is_error": true, "attempt": {call_count["n"]}}}', encoding="utf-8")
        return (1, False) if call_count["n"] == 1 else (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    preserved = logs_dir / "dispatch_stdout.attempt-1.log"
    assert preserved.exists()
    assert '"attempt": 1' in preserved.read_text(encoding="utf-8")
    assert '"attempt": 2' in (logs_dir / "dispatch_stdout.log").read_text(encoding="utf-8")
    bounce.assert_not_called()


def test_main_stale_attempt_files_shifted(monkeypatch, main_argv, tmp_path):
    """A previous run's attempt-N stdout files are shifted aside at startup."""
    argv, lock_file, stderr_log = main_argv
    logs_dir = tmp_path / "branch" / "logs"
    stale = logs_dir / "dispatch_stdout.attempt-2.log"
    stale.write_text("previous run", encoding="utf-8")

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert not stale.exists()
    assert (logs_dir / "dispatch_stdout.attempt-2.log.1").read_text(encoding="utf-8") == "previous run"
    bounce.assert_not_called()


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
        MagicMock(return_value=tmp_path / "repo"),
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


def test_main_bg_orphaned_treated_as_incomplete(monkeypatch, main_argv, tmp_path):
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
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "background tasks were still running" in reason
    assert not lock_file.exists()  # cleanup still runs on incomplete


def test_main_bg_marker_from_previous_run_ignored(monkeypatch, main_argv, tmp_path):
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
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_bounce.assert_not_called()


def test_main_lock_left_for_successor_monitor(monkeypatch, main_argv, tmp_path):
    """A lock re-created by a successor monitor (different PID) is not deleted."""
    argv, lock_file, stderr_log = main_argv

    def fake_run(cmd, stdout_log, *args, **kwargs):
        # Simulate a successor monitor taking over the lock mid-run
        lock_file.write_text(json.dumps({"pid": 999999999}), encoding="utf-8")
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert lock_file.exists()
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == 999999999
    bounce.assert_not_called()


# --- Environment variable setup tests ---------------------------------


def test_spawn_path_is_joined_with_the_separator_handed_in():
    """The spawn PATH joins with the host's separator, never a literal colon.

    The other host's separator is handed in, so the Windows answer is pinned on any
    host; the string is asserted and nothing is started. Red first by the mutant that
    restores the old literal ":" join (leg 3).
    """
    windows_path = "C:\\Windows;C:\\Tools"

    assert mod.prepend_to_path(windows_path, "C:\\repo\\.venv\\bin", sep=";") == (
        "C:\\repo\\.venv\\bin;C:\\Windows;C:\\Tools"
    )
    assert mod.prepend_to_path("usr_bin", "venv_bin", sep=":") == "venv_bin:usr_bin"
    assert mod.prepend_to_path("", "venv_bin", sep=":") == "venv_bin"


def test_env_vars_set_correctly(monkeypatch, main_argv, tmp_path):
    """Verify AIPASS_SPAWNED, SESSION_TYPE, BRANCH_NAME set; CLAUDE* stripped; venv on PATH."""
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))

    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=fake_repo),
    )

    # Set a CLAUDE var that should be stripped
    monkeypatch.setenv("CLAUDE_TEST_VAR", "should_be_stripped")
    monkeypatch.setenv("AIPASS_BOT_ID", "should_be_stripped_too")
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@old_caller")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "old_cwd"))

    with pytest.raises(SystemExit):
        main()

    bounce.assert_not_called()
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


def test_auto_compact_window_pinned_to_350k(monkeypatch, main_argv, tmp_path):
    """Dispatched agents get a 350k auto-compact window, model-independent.

    The pin is written AFTER the CLAUDE* strip loop, so a parent's own window
    never leaks in and the pin is not stripped on its way out.
    """
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    # Parent carries a different window — the spawn must overwrite it, not inherit it.
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "999999")

    with pytest.raises(SystemExit):
        main()

    assert captured_env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "350000"
    bounce.assert_not_called()


# === Additional tests (added 2026-04-03) ===================================


# --- _kill_process tests (named per spec) ----------------------------------


# _kill_process's two outcomes are pinned once, at test_kill_process_terminate_succeeds
# and test_kill_process_terminate_timeout_falls_back_to_sigkill. This file carried a
# second line-for-line copy of both, 640 lines apart under SIGTERM/SIGKILL names
# (DPLAN-0323 contested band, merged FPLAN-0492).


# --- Max-turns detection (named per spec) ----------------------------------


def test_main_max_turns_detected(monkeypatch, main_argv, tmp_path):
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

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
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
    bounce.assert_not_called()


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

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", MagicMock(return_value=(0, False)))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
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
    bounce.assert_not_called()


# Retired under compass 443 (2026-09-27), each a line-for-line copy of its survivor:
# test_stdout_rotation -> test_stdout_rotation_on_large_file;
# test_lock_cleaned_on_success -> test_lock_cleanup_on_success;
# test_lock_cleaned_on_failure -> test_lock_cleanup_on_failure.


# --- Environment variables tests (named per spec) --------------------------


def test_env_vars_setup(monkeypatch, main_argv, tmp_path):
    """Verify spawn_env contains AIPASS_SPAWNED=1, AIPASS_SESSION_TYPE=dispatched,
    AIPASS_BRANCH_NAME set, CLAUDE* vars stripped, venv bin on PATH."""
    argv, lock_file, stderr_log = main_argv

    captured_env = {}

    def capture_run(cmd, stdout_log, stderr_fh, cwd, env, branch, **kwargs):
        captured_env.update(env)
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "_run_with_startup_check", capture_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))

    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=fake_repo),
    )

    # Set CLAUDE* and AIPASS_BOT_ID vars that should be stripped
    monkeypatch.setenv("CLAUDE_ACCESS_TOKEN", "secret")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "abc123")
    monkeypatch.setenv("AIPASS_BOT_ID", "bot42")
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "@other")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "other_cwd"))

    with pytest.raises(SystemExit):
        main()

    bounce.assert_not_called()
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
