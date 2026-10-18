# =================== AIPass ====================
# Name: test_dispatch_monitor_artifacts.py
# Description: Tests for what each dispatch attempt leaves behind - stdout, exit codes, result JSON, the lock
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's attempt artifacts: stdout, stderr, result JSON, lock."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import BG_TASKS_MARKER, main
from aipass.ai_mail.tests.support_dispatch_monitor import _run_main

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


def test_stdout_preserved_across_retries(monkeypatch, main_argv, tmp_path):
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

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert "attempt-1-failure" in (logs_dir / "dispatch_stdout.attempt-1.log").read_text(encoding="utf-8")
    assert "attempt-2-failure" in (logs_dir / "dispatch_stdout.attempt-2.log").read_text(encoding="utf-8")
    assert "attempt-3-failure" in (logs_dir / "dispatch_stdout.log").read_text(encoding="utf-8")
    bounce.assert_called_once()
    assert "attempt-3-failure" in bounce.call_args.args[1]


def test_per_attempt_exit_code_written_to_stderr_log(monkeypatch, main_argv, tmp_path):
    """Each attempt's exit code lands in dispatch_stderr.log itself, not just prax."""
    argv, lock_file, stderr_log = main_argv

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(side_effect=[(1, False), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    content = Path(stderr_log).read_text(encoding="utf-8")
    assert "Attempt 1/3 exited: code=1" in content
    assert "Attempt 2/3 exited: code=0" in content
    bounce.assert_not_called()


def test_per_attempt_startup_timeout_noted_in_stderr_log(monkeypatch, main_argv, tmp_path):
    """A startup-timeout attempt is distinguished from a plain exit code in the log."""
    argv, lock_file, stderr_log = main_argv

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", MagicMock(side_effect=[(-3, True), (0, False)]))
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    content = Path(stderr_log).read_text(encoding="utf-8")
    assert "Attempt 1/3 exited: code=-3 (startup timeout)" in content
    bounce.assert_not_called()


def test_bounce_reason_includes_parsed_stdout_result(monkeypatch, main_argv, tmp_path):
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
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "boom detail" in reason
    assert "is_error=True" in reason


# The owner-deletes and missing-lock cases are pinned once, through main(), in
# tests/test_dispatch_monitor.py::test_lock_cleanup_on_success and
# tests/test_dispatch_monitor_helpers.py::test_a_lock_gone_before_cleanup_is_not_recreated.


def test_main_does_not_steal_successor_lock(monkeypatch, main_argv, tmp_path):
    """If a successor monitor re-owns the lock mid-run, this monitor's
    end-of-run cleanup must not delete it out from under the successor."""
    argv, lock_file, stderr_log = main_argv
    successor_pid = os.getpid() + 999

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        lock_file.write_text(json.dumps({"pid": successor_pid}), encoding="utf-8")
        return (0, False)

    bounce = MagicMock()
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit):
        main()

    assert lock_file.exists()
    assert json.loads(lock_file.read_text(encoding="utf-8"))["pid"] == successor_pid
    bounce.assert_not_called()


def test_bg_tasks_still_running_treated_as_incomplete(monkeypatch, main_argv, tmp_path):
    """Exit 0 with the print-mode bg-wait-ceiling marker in this attempt's
    stderr is NOT a silent success -- it bounces and exits nonzero."""
    argv, lock_file, stderr_log = main_argv

    def fake_run(cmd, stdout_path, stderr_fh, cwd, spawn_env, branch_email, pass_fds=()):
        with open(stderr_log, "a", encoding="utf-8") as f:
            f.write(f"{BG_TASKS_MARKER} after 600s; terminating.\n")
        return (0, False)

    mock_bounce = MagicMock()

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    mock_bounce.assert_called_once()
    reason = mock_bounce.call_args[0][1]
    assert "background tasks" in reason.lower()


def test_bg_tasks_marker_from_prior_attempt_does_not_leak_forward(monkeypatch, main_argv, tmp_path):
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
    monkeypatch.setattr(mod, "run_with_startup_check", fake_run)
    monkeypatch.setattr(mod, "_send_bounce", mock_bounce)
    monkeypatch.setattr(mod, "_check_rate_limited", MagicMock(return_value=False))
    monkeypatch.setattr(mod, "time", MagicMock(time=time.time, strftime=time.strftime, sleep=MagicMock()))
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.paths.find_repo_root",
        MagicMock(return_value=tmp_path / "repo"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    mock_bounce.assert_not_called()


def test_a_failed_attempts_stdout_is_moved_aside_not_copied(monkeypatch, main_argv, tmp_path):
    argv, lock_file, _ = main_argv
    logs_dir = lock_file.parent.parent / "logs"
    stdout_there_at_start = []

    def fails_printing(stdout_log):
        stdout_there_at_start.append(Path(stdout_log).exists())
        Path(stdout_log).write_text('{"result": "boom"}', encoding="utf-8")
        return 1

    def succeeds(stdout_log):
        stdout_there_at_start.append(Path(stdout_log).exists())
        return 0

    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    code, _ = _run_main(monkeypatch, argv, tmp_path, [fails_printing, succeeds])

    assert code == 0
    assert stdout_there_at_start == [False, False]
    assert (logs_dir / "dispatch_stdout.attempt-1.log").read_text(encoding="utf-8") == '{"result": "boom"}'
    bounce.assert_not_called()


def _bounce_reason(monkeypatch, argv, tmp_path, attempt):
    """Run main() through three failed attempts played by `attempt`; returns the bounce reason."""
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    code, _ = _run_main(monkeypatch, argv, tmp_path, [attempt, attempt, attempt])
    assert code == 1
    bounce.assert_called_once()
    return bounce.call_args.args[1]


def test_a_result_json_after_banner_text_still_reaches_the_bounce(monkeypatch, main_argv, tmp_path):
    def prints_a_banner_first(stdout_log):
        Path(stdout_log).write_text('some banner text\n{"is_error": false, "result": "ok"}', encoding="utf-8")
        return 1

    reason = _bounce_reason(monkeypatch, main_argv[0], tmp_path, prints_a_banner_first)

    assert "is_error=False" in reason
    assert "result: ok" in reason


def test_a_dispatch_that_printed_nothing_bounces_with_no_result_json(monkeypatch, main_argv, tmp_path):
    reason = _bounce_reason(monkeypatch, main_argv[0], tmp_path, lambda stdout_log: 1)

    assert reason.endswith("Last attempt result JSON: (no result JSON captured)")


def test_a_lock_turned_unreadable_mid_run_is_left_in_place(monkeypatch, main_argv, tmp_path):
    argv, lock_file, _ = main_argv
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    def corrupts_the_lock(stdout_log):
        lock_file.write_text("not json", encoding="utf-8")
        return 0

    code, _ = _run_main(monkeypatch, argv, tmp_path, [corrupts_the_lock])

    assert code == 0
    assert lock_file.read_text(encoding="utf-8") == "not json"
    bounce.assert_not_called()
