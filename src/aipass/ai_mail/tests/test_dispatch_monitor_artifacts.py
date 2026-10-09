# =================== AIPass ====================
# Name: test_dispatch_monitor_artifacts.py
# Description: Tests for what each dispatch attempt leaves behind - stdout, exit codes, result JSON, the lock
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's attempt artifacts: stdout, stderr, result JSON, lock."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: the five fixes that keep a failed attempt's evidence.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    BG_TASKS_MARKER,
    _cleanup_own_lock,
    _parse_result_json,
    _read_stderr_segment,
    _rotate_attempt_stdout,
    _summarize_result_json,
    main,
)

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# --- Fix 1: per-attempt stdout preservation ---------------------------


def test_rotate_attempt_stdout_preserves_content(tmp_path):
    """A non-empty stdout log is renamed to dispatch_stdout.attempt-N.log."""
    stdout_log = tmp_path / "dispatch_stdout.log"
    stdout_log.write_text('{"result": "boom"}', encoding="utf-8")

    _rotate_attempt_stdout(str(stdout_log), 2)

    assert not stdout_log.exists()
    preserved = tmp_path / "dispatch_stdout.attempt-2.log"
    assert preserved.read_text(encoding="utf-8") == '{"result": "boom"}'


# test_rotate_attempt_stdout_empty_file_noop retired under compass 443 (2026-09-27):
# a line-for-line copy of its survivor, test_rotate_attempt_stdout_skips_empty.


def test_rotate_attempt_stdout_missing_file_noop(tmp_path):
    """No error when there's no stdout log yet."""
    _rotate_attempt_stdout(str(tmp_path / "missing.log"), 1)
    assert not (tmp_path / "dispatch_stdout.attempt-1.log").exists()


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
    # Final (3rd) attempt's stdout is left in place, unrotated, for post-processing
    assert "attempt-3-failure" in (logs_dir / "dispatch_stdout.log").read_text(encoding="utf-8")
    # The bounce names the last attempt's result, read from the unrotated log
    bounce.assert_called_once()
    assert "attempt-3-failure" in bounce.call_args.args[1]


# --- Fix 2: per-attempt exit codes in the branch-local stderr log -----


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


def test_summarize_result_json_no_capture(tmp_path):
    """No result JSON captured is reported explicitly, not as a blank string."""
    assert _summarize_result_json(str(tmp_path / "nonexistent" / "path.log")) == "(no result JSON captured)"


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


# --- Fix 4: lock-ownership-verified cleanup ----------------------------


# test_cleanup_own_lock_deletes_when_pid_matches retired under compass 443 (2026-09-27):
# a line-for-line copy of its survivor, test_cleanup_own_lock_deletes_when_owner.


def test_cleanup_own_lock_preserves_foreign_pid(tmp_path):
    """A lock re-owned by a successor monitor (different PID) is left alone --
    unconditional unlink previously let one monitor steal a successor's lock."""
    lock = tmp_path / ".dispatch.lock"
    foreign_pid = os.getpid() + 1
    lock.write_text(json.dumps({"pid": foreign_pid}), encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()
    assert json.loads(lock.read_text(encoding="utf-8"))["pid"] == foreign_pid


# The missing-lock no-op is pinned once, at test_cleanup_own_lock_missing_noop.
# A second copy sat here under a longer name (DPLAN-0323, merged FPLAN-0492).


def test_cleanup_own_lock_unreadable_json_preserved(tmp_path):
    """Corrupt lock content is left in place rather than blindly deleted."""
    lock = tmp_path / ".dispatch.lock"
    lock.write_text("not json", encoding="utf-8")

    _cleanup_own_lock(str(lock))

    assert lock.exists()


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
