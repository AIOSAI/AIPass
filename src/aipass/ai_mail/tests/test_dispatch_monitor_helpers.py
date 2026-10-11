# =================== AIPass ====================
# Name: test_dispatch_monitor_helpers.py
# Description: Tests for the dispatch monitor's units - rate limit, fresh cmd, startup check, kill, logs, lock, JSONL
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's units: startup check, kill, result logs, own lock, JSONL."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: the parts main() is built from, each pinned on its own.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — STARTUP_TIMEOUT and HARD_TIMEOUT: real timeout seconds, overridden by every test
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import cmd_for_attempt, run_with_startup_check
from aipass.ai_mail.tests.support_dispatch_monitor import _run_main

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


# --- run_with_startup_check tests (mock Popen) -----------------------


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

    monkeypatch.setattr(mod.session_pointer, "transcript_dir", lambda cwd: tmp_path / "projects")
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: {})
    monkeypatch.setattr(mod, "_check_jsonl_activity", fake_activity)

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
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

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
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

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
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
    monkeypatch.setattr(mod.session_pointer, "transcript_dir", lambda cwd: tmp_path / "projects")
    sizes = {"seen.jsonl": 7}
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: sizes)
    # The activity probe is asserted on what it was asked: the projects dir and the
    # snapshot taken before the spawn (ai_mail, leg 7)
    activity = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "_check_jsonl_activity", activity)

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    activity.assert_called_with(tmp_path / "projects", sizes)
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
    monkeypatch.setattr(mod.session_pointer, "transcript_dir", lambda cwd: tmp_path / "projects")
    sizes = {"seen.jsonl": 7}
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: sizes)
    activity = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "_check_jsonl_activity", activity)

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    activity.assert_called_with(tmp_path / "projects", sizes)
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

    exit_code, startup_failed = run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == -2
    assert startup_failed is False


# --- The pause before a retry, through main() ------------------------------


def _fails_after_writing_stderr(stderr_log, text):
    """An attempt that writes text to the dispatch stderr log, then exits 1."""

    def attempt(stdout_log):
        with open(stderr_log, "a", encoding="utf-8") as f:
            f.write(text)
        return 1

    return attempt


@pytest.mark.parametrize(
    "stderr_text",
    [
        "Error: API returned 429 Too Many Requests\n",
        "error: rate_limit exceeded\n",
        "API is overloaded, please retry\n",
        "HTTP 529 Service Unavailable\n",
    ],
)
def test_a_rate_limited_attempt_waits_the_long_delay_before_the_retry(monkeypatch, main_argv, tmp_path, stderr_text):
    argv, _, stderr_log = main_argv
    attempts = [_fails_after_writing_stderr(stderr_log, stderr_text), lambda stdout_log: 0]
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    code, clock = _run_main(monkeypatch, argv, tmp_path, attempts)

    assert code == 0
    clock.sleep.assert_called_once_with(mod.RATE_LIMIT_DELAY)
    bounce.assert_not_called()


def test_an_ordinary_failure_waits_only_the_short_pause(monkeypatch, main_argv, tmp_path):
    argv, _, stderr_log = main_argv
    attempts = [_fails_after_writing_stderr(stderr_log, "Starting agent...\nProcessing task\nDone\n"), lambda s: 0]
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    code, clock = _run_main(monkeypatch, argv, tmp_path, attempts)

    assert code == 0
    clock.sleep.assert_called_once_with(5)
    bounce.assert_not_called()


def test_a_stderr_log_that_cannot_be_opened_reads_as_no_rate_limit(monkeypatch, main_argv, tmp_path):
    argv, _, _ = main_argv
    argv = argv[:4] + [str(tmp_path / "absent" / "stderr.log")] + argv[5:]
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    code, clock = _run_main(monkeypatch, argv, tmp_path, [lambda s: 1, lambda s: 0])

    assert code == 0
    clock.sleep.assert_called_once_with(5)
    bounce.assert_not_called()


# --- What a failed attempt leaves behind, through main() -------------------


def test_an_empty_attempt_stdout_is_left_in_place_not_preserved(monkeypatch, main_argv, tmp_path):
    argv, lock_file, _ = main_argv
    logs_dir = lock_file.parent.parent / "logs"
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    def writes_nothing(stdout_log):
        Path(stdout_log).write_text("", encoding="utf-8")
        return 1

    code, _ = _run_main(monkeypatch, argv, tmp_path, [writes_nothing, lambda s: 0])

    assert code == 0
    assert (logs_dir / "dispatch_stdout.log").exists()
    assert not (logs_dir / "dispatch_stdout.attempt-1.log").exists()
    bounce.assert_not_called()


def _bounce_reason(monkeypatch, argv, tmp_path, stdout_text):
    """Run main() through three failed attempts that each print stdout_text; returns the bounce reason."""

    def prints(stdout_log):
        Path(stdout_log).write_text(stdout_text, encoding="utf-8")
        return 1

    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)
    code, _ = _run_main(monkeypatch, argv, tmp_path, [prints, prints, prints])
    assert code == 1
    bounce.assert_called_once()
    return bounce.call_args.args[1]


def test_unparseable_stdout_is_reported_as_no_result_json(monkeypatch, main_argv, tmp_path):
    reason = _bounce_reason(monkeypatch, main_argv[0], tmp_path, "not json at all\nstill not json")

    assert reason.endswith("Last attempt result JSON: (no result JSON captured)")


def test_the_bounce_names_every_error_field_of_the_result_json(monkeypatch, main_argv, tmp_path):
    result = {"is_error": True, "subtype": "error_during_execution", "api_error_status": 529, "result": "API overload"}

    reason = _bounce_reason(monkeypatch, main_argv[0], tmp_path, json.dumps(result))

    assert "is_error=True" in reason
    assert "subtype=error_during_execution" in reason
    assert "api_error_status=529" in reason
    assert "API overload" in reason


# --- The end-of-run lock and the attempt's stderr slice, through main() ----


def test_a_lock_gone_before_cleanup_is_not_recreated(monkeypatch, main_argv, tmp_path):
    argv, lock_file, _ = main_argv
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    def removes_the_lock(stdout_log):
        lock_file.unlink()
        return 0

    code, _ = _run_main(monkeypatch, argv, tmp_path, [removes_the_lock])

    assert code == 0
    bounce.assert_not_called()
    assert not lock_file.exists()
    # Narrower than "the directory is empty": main() writes its logs beside the lock's home.
    assert list(lock_file.parent.glob("*.lock")) == []


# POSIX only: the route is a stderr log removed while the monitor holds it open,
# and Windows refuses to remove an open file.
@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses to remove a file the monitor holds open")
def test_a_stderr_log_removed_mid_attempt_is_no_background_task_marker(monkeypatch, main_argv, tmp_path):
    argv, _, stderr_log = main_argv
    bounce = MagicMock()
    monkeypatch.setattr(mod, "_send_bounce", bounce)

    def removes_the_stderr_log(stdout_log):
        stderr_log.unlink()
        return 0

    code, _ = _run_main(monkeypatch, argv, tmp_path, [removes_the_stderr_log])

    assert code == 0
    bounce.assert_not_called()


# --- The startup probe and the kill, through run_with_startup_check() ------


def _startup_run(monkeypatch, tmp_path, process):
    """Run one attempt over `process` with the transcript dir at tmp_path/projects; returns (exit, startup_failed)."""
    monkeypatch.setattr(mod, "STARTUP_TIMEOUT", 0.3)
    monkeypatch.setattr(mod, "POLL_INTERVAL", 0.02)
    monkeypatch.setattr(mod, "HARD_TIMEOUT", 5)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **kw: process)
    cwd = str(tmp_path / "branch")
    transcript_dir = MagicMock(return_value=tmp_path / "projects")
    monkeypatch.setattr(mod.session_pointer, "transcript_dir", transcript_dir)
    result = run_with_startup_check(["claude"], str(tmp_path / "stdout.log"), MagicMock(), cwd, {}, "@test")
    transcript_dir.assert_called_once_with(cwd)
    return result


def _process(polls):
    """A mock agent whose poll() plays `polls` in order (a callable is called, its answer returned), exit code 0."""
    queue = list(polls)
    process = MagicMock(returncode=0)
    process.wait = MagicMock(return_value=0)

    def poll():
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        return step() if callable(step) else step

    process.poll = poll
    return process


def test_a_transcript_that_appears_after_the_spawn_marks_the_agent_started(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()

    def writes_a_new_transcript():
        (projects / "new_session.jsonl").write_text("data\n", encoding="utf-8")

    assert _startup_run(monkeypatch, tmp_path, _process([writes_a_new_transcript, 1])) == (0, False)


def test_a_transcript_that_grows_after_the_spawn_marks_the_agent_started(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    session = projects / "session.jsonl"
    session.write_text("line1\n", encoding="utf-8")

    def grows_the_transcript():
        with open(session, "a", encoding="utf-8") as fh:
            fh.write("line2\n")

    assert _startup_run(monkeypatch, tmp_path, _process([grows_the_transcript, 1])) == (0, False)


def test_a_transcript_left_untouched_is_a_startup_failure(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "session.jsonl").write_text("line1\n", encoding="utf-8")

    assert _startup_run(monkeypatch, tmp_path, _process([1])) == (0, True)


def test_a_run_with_no_transcript_dir_is_a_startup_failure_not_a_crash(monkeypatch, tmp_path):
    assert not (tmp_path / "projects").exists()

    assert _startup_run(monkeypatch, tmp_path, _process([1])) == (0, True)


def test_a_startup_timeout_terminates_the_agent_without_a_sigkill(monkeypatch, tmp_path):
    process = _process([None])
    process.wait = MagicMock(return_value=None)

    assert _startup_run(monkeypatch, tmp_path, process) == (-3, True)

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=10)
    process.kill.assert_not_called()


def test_a_startup_timeout_sigkills_an_agent_that_ignores_the_terminate(monkeypatch, tmp_path):
    process = _process([None])
    process.wait = MagicMock(side_effect=[subprocess.TimeoutExpired(cmd="claude", timeout=10), None])

    assert _startup_run(monkeypatch, tmp_path, process) == (-3, True)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert [c.kwargs for c in process.wait.call_args_list] == [{"timeout": 10}, {"timeout": 5}]


# --- The fresh command, through cmd_for_attempt() --------------------------


def test_attempt_3_strips_the_bare_dash_c_and_keeps_an_option_that_contains_it(tmp_path):
    branch = tmp_path / "branch"
    branch.mkdir()

    built, _ = cmd_for_attempt(["claude", "-c", "--config", "c_file.json"], 3, branch)

    assert built[:3] == ["claude", "--config", "c_file.json"]
    assert "-c" not in built
