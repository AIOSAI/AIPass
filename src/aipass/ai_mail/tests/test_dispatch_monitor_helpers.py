# =================== AIPass ====================
# Name: test_dispatch_monitor_helpers.py
# Description: Tests for the dispatch monitor's units - rate limit, fresh cmd, startup check, kill, logs, lock, JSONL
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/dispatch_monitor.py's units: startup check, kill, result logs, own lock, JSONL."""

# Split out of test_dispatch_monitor.py on 2026-10-08 to keep that file under the
# 1,200-line target: the parts main() is built from, each pinned on its own.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — STARTUP_TIMEOUT and HARD_TIMEOUT: real timeout seconds, overridden by every test
# seedgo: no-test-needed(shared) — main()'s attempts and the bounce: tests/test_dispatch_monitor.py

import json
import os
import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as mod
from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import (
    _check_jsonl_activity,
    _check_rate_limited,
    _cleanup_own_lock,
    _get_jsonl_projects_dir,
    _kill_process,
    _make_fresh_cmd,
    _parse_result_json,
    _read_stderr_segment,
    _rotate_attempt_stdout,
    _run_with_startup_check,
    _snapshot_jsonl_sizes,
    _summarize_result_json,
)

pytestmark = pytest.mark.usefixtures("monitor_json_silenced", "monitor_logger_silenced", "monitor_wake_stubbed")


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
    sizes = {"seen.jsonl": 7}
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: sizes)
    # The activity probe is asserted on what it was asked: the projects dir and the
    # snapshot taken before the spawn (ai_mail, leg 7)
    activity = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "_check_jsonl_activity", activity)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
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
    monkeypatch.setattr(mod, "_get_jsonl_projects_dir", lambda cwd: tmp_path / "projects")
    sizes = {"seen.jsonl": 7}
    monkeypatch.setattr(mod, "_snapshot_jsonl_sizes", lambda d: sizes)
    activity = MagicMock(return_value=True)
    monkeypatch.setattr(mod, "_check_jsonl_activity", activity)

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
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

    exit_code, startup_failed = _run_with_startup_check(["claude"], stdout_log, stderr_fh, str(tmp_path), {}, "@test")
    assert exit_code == -2
    assert startup_failed is False


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

    mock_proc.terminate.assert_called_once_with()
    mock_proc.kill.assert_called_once_with()
    assert [c.kwargs for c in mock_proc.wait.call_args_list] == [{"timeout": 10}, {"timeout": 5}]


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
    """A missing lock is a no-op — it is not created on the way past.

    Had no oracle: the trailing comment said "must not raise" and nothing
    checked anything. A cleanup that touched the path, or wrote an empty lock
    before deciding it was absent, would have passed — and would then hold a
    lock nobody owns.
    """
    lock = tmp_path / ".dispatch.lock"

    _cleanup_own_lock(str(lock))

    assert not lock.exists()
    # Narrower than "tmp_path is empty" on purpose: this branch's conftest
    # plants its own seam directories in tmp_path, so an empty-directory
    # assertion would be pinning the fixture, not the cleanup.
    assert list(tmp_path.glob("*.lock")) == []


# --- JSONL helper tests ----------------------------------------------------


def test_get_jsonl_projects_dir():
    """Verifies path encoding: / replaced with -, _ replaced with -.

    The sample cwd is deliberately NOT home-shaped. It used to be
    "/home/user/my_project", which the hardcoded-path guard reads as this
    machine's real home; the encoding under test cares only about the
    separators, so a neutral path exercises it identically and lets both the
    input and the expected answer stay written out as literals.
    """
    result = _get_jsonl_projects_dir("/srv/data/my_project")
    expected = Path.home() / ".claude" / "projects" / "-srv-data-my-project"
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
