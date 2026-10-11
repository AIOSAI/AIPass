# =================== AIPass ====================
# Name: test_daemon.py
# Description: Tests for the dispatch daemon's run loop - poll_cycle, spawn_agent, run_daemon
# Version: 1.2.0
# Created: 2026-03-29
# Modified: 2026-10-11
# =============================================

"""Tests for apps/handlers/dispatch/daemon.py -- the run loop: poll_cycle, the stop signal, spawn_agent, run_daemon."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — load_config() and the daemon state file: tests/test_daemon_state.py
# seedgo: no-test-needed(shared) — check_lock() and the daemon's pid file: tests/test_daemon_locks.py

import json
import signal
import subprocess
import sys
import pytest
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    poll_cycle,
    spawn_agent,
    run_daemon,
)

pytestmark = pytest.mark.usefixtures("daemon_json_silenced", "daemon_paths_in_tmp", "daemon_signals_restored")


# ---- poll_cycle absolute path regression tests ---------------


def test_poll_cycle_resolves_relative_branch_path(tmp_path, monkeypatch):
    """poll_cycle resolves relative registry paths to absolute before spawning.

    Regression test for issue #360 finding #3: spawn_agent was called with a
    relative branch_path when the registry stores paths like 'src/aipass/ai_mail'.
    A relative cwd cascades through dispatch_monitor, producing the wrong
    working directory for the spawned claude process.
    """
    # Set up fake repo root and branch inside it
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "src" / "aipass" / "ai_mail"
    branch_dir.mkdir(parents=True)
    (branch_dir / ".ai_mail.local").mkdir()
    inbox = {
        "messages": [
            {
                "id": "d1",
                "status": "new",
                "from": "@devpulse",
                "subject": "probe",
                "body": "report your pwd",
                "auto_execute": True,
            }
        ]
    }
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    # Registry with relative path (real-world format)
    registry = {"branches": [{"email": "@ai_mail", "path": "src/aipass/ai_mail", "status": "active"}]}
    (repo_root / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", repo_root / "AIPASS_REGISTRY.json")
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)

    spawned_paths = []

    def mock_spawn_agent(branch_path, branch_email, message, config, state):
        spawned_paths.append(branch_path)
        return True

    config = {
        "autonomous_branches": ["@ai_mail"],
        "max_dispatches_per_branch_per_day": 10,
    }
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent", side_effect=mock_spawn_agent),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.check_lock", return_value=None),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.is_branch_occupied", return_value=False),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails", return_value=0),
    ):
        daemon_mod.poll_cycle(config, state)

    assert len(spawned_paths) == 1, "Expected one spawn"
    assert spawned_paths[0].is_absolute(), f"branch_path must be absolute, got: {spawned_paths[0]}"
    assert spawned_paths[0] == branch_dir


def test_poll_cycle_absolute_path_unchanged(tmp_path, monkeypatch):
    """poll_cycle passes already-absolute registry paths through unchanged."""
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "src" / "aipass" / "drone"
    branch_dir.mkdir(parents=True)
    (branch_dir / ".ai_mail.local").mkdir()
    inbox = {
        "messages": [
            {
                "id": "d2",
                "status": "new",
                "from": "@devpulse",
                "subject": "probe",
                "body": "task",
                "auto_execute": True,
            }
        ]
    }
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    registry = {"branches": [{"email": "@drone", "path": str(branch_dir), "status": "active"}]}
    (repo_root / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", repo_root / "AIPASS_REGISTRY.json")
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)

    spawned_paths = []

    def mock_spawn_agent(branch_path, branch_email, message, config, state):
        spawned_paths.append(branch_path)
        return True

    config = {"autonomous_branches": ["@drone"], "max_dispatches_per_branch_per_day": 10}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent", side_effect=mock_spawn_agent),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.check_lock", return_value=None),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.is_branch_occupied", return_value=False),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails", return_value=0),
    ):
        daemon_mod.poll_cycle(config, state)

    assert len(spawned_paths) == 1
    assert spawned_paths[0].is_absolute()
    assert spawned_paths[0] == branch_dir


# ---- _handle_signal tests --------------------------------------


@pytest.mark.parametrize("signame", ["SIGTERM", "SIGINT"])
def test_the_registered_stop_signal_sets_shutdown(tmp_path, monkeypatch, signame):
    """The handler the started daemon registers for a stop signal sets SHUTDOWN.

    Reached through the handler table run_daemon fills, not by name, and
    called directly: no signal is sent to the test process (ai_mail, leg 14).
    """
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)
    run_daemon()
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)
    signum = getattr(daemon_mod.signal, signame)
    handler = daemon_mod.signal.getsignal(signum)
    # Python's own SIGINT handler raises KeyboardInterrupt: never call it here.
    assert handler not in (signal.SIG_DFL, signal.SIG_IGN, signal.default_int_handler)
    assert callable(handler)

    handler(signum, None)

    assert daemon_mod.SHUTDOWN is True


def test_importing_the_daemon_leaves_the_stop_signals_as_they_were():
    probe = (
        "import signal\n"
        "before = [repr(signal.getsignal(s)) for s in (signal.SIGTERM, signal.SIGINT)]\n"
        "import aipass.ai_mail.apps.handlers.dispatch.daemon\n"
        "after = [repr(signal.getsignal(s)) for s in (signal.SIGTERM, signal.SIGINT)]\n"
        "print(before == after, before, after)\n"
    )

    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, encoding="utf-8", timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("True "), result.stdout


# ---- spawn_agent tests ------------------------------------------


def test_spawn_agent_success(tmp_path):
    """Successful spawn returns True and increments state counts."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "msg1", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    mock_process = MagicMock()
    mock_process.pid = 54321

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            return_value=mock_process,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    assert state["daily_counts"]["@testbranch"] == 1
    assert state["session_cycles"][str(branch_path)] == 1
    # log_dispatch writes the live dispatch log, so the patch stays and is asserted (ai_mail, leg 5)
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
    mock_notify.assert_called_once_with(
        "Daemon → @testbranch", 'Task from @devpulse: "Test task"', source="testbranch", kind="dispatch"
    )


def test_spawn_agent_exception(tmp_path):
    """Spawn failure returns False."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "msg1", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=OSError("command not found"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is False
    mock_log_dispatch.assert_called_once_with("@testbranch", None, "failed", error_msg="command not found")


def test_spawn_agent_strips_claude_env_vars(tmp_path, monkeypatch):
    """Spawn strips CLAUDE* and AIPASS_BOT_ID env vars from child."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    monkeypatch.setenv("CLAUDE_API_KEY", "secret")
    monkeypatch.setenv("CLAUDE_MODEL", "opus")
    monkeypatch.setenv("AIPASS_BOT_ID", "bot123")

    message = {"from": "@devpulse", "id": "msg1", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    captured_env = {}

    def capture_popen(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        mock_proc = MagicMock()
        mock_proc.pid = 11111
        return mock_proc

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=capture_popen,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    assert "CLAUDE_API_KEY" not in captured_env
    assert "CLAUDE_MODEL" not in captured_env
    assert "AIPASS_BOT_ID" not in captured_env
    assert captured_env.get("AIPASS_SPAWNED") == "1"
    assert captured_env.get("AIPASS_SESSION_TYPE") == "daemon"
    mock_notify.assert_called_once()
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")


def test_spawn_agent_claude_cmd_includes_model_flag(tmp_path):
    """Poller-triggered spawn passes --model DEFAULT_MODEL to the claude invocation."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "msg1", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    captured_args = []

    def capture_popen(*args, **kwargs):
        captured_args.append(args[0] if args else kwargs.get("args"))
        mock_proc = MagicMock()
        mock_proc.pid = 22222
        return mock_proc

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=capture_popen,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    monitor_cmd = captured_args[0]
    assert "--model" in monitor_cmd
    model_idx = monitor_cmd.index("--model")
    assert monitor_cmd[model_idx + 1] == daemon_mod.DEFAULT_MODEL
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
    mock_notify.assert_called_once()


def test_spawn_agent_prompt_includes_reply_id(tmp_path):
    """Prompt includes explicit reply command with the dispatch email ID."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "abc12345", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    captured_cmd = []

    def capture_popen(cmd, *args, **kwargs):
        captured_cmd.extend(cmd)
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        return mock_proc

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=capture_popen,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "drone @ai_mail reply abc12345" in prompt
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
    assert "required" in prompt.lower()
    mock_notify.assert_called_once_with(
        "Daemon → @testbranch", 'Task from @devpulse: "Test task"', source="testbranch", kind="dispatch"
    )


def test_spawn_agent_prompt_includes_sender(tmp_path):
    """Prompt includes sender address from the dispatch email."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "abc12345", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    captured_cmd = []

    def capture_popen(cmd, *args, **kwargs):
        captured_cmd.extend(cmd)
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        return mock_proc

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=capture_popen,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "@devpulse" in prompt
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
    mock_notify.assert_called_once_with(
        "Daemon → @testbranch", 'Task from @devpulse: "Test task"', source="testbranch", kind="dispatch"
    )


def test_spawn_agent_prompt_fallback_without_id(tmp_path):
    """Without a valid ID, prompt uses generic reply instruction."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    message = {"from": "@devpulse", "id": "", "subject": "Test task"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    captured_cmd = []

    def capture_popen(cmd, *args, **kwargs):
        captured_cmd.extend(cmd)
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        return mock_proc

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            side_effect=capture_popen,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "reply <id>" in prompt
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
    assert "required" in prompt.lower()
    mock_notify.assert_called_once_with(
        "Daemon → @testbranch", 'Task from @devpulse: "Test task"', source="testbranch", kind="dispatch"
    )


# ---- run_daemon tests -------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.WNOHANG)")
def test_run_daemon_kill_switch_pauses(tmp_path, monkeypatch):
    """Kill switch active causes daemon to pause and loop, then SHUTDOWN exits."""
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_mod, "DAEMON_LOG_FILE", tmp_path / "daemon.log")

    call_count = {"n": 0}

    def fake_is_kill_switch(config):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            daemon_mod.SHUTDOWN = True
        return True

    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._write_pid_file",
            return_value=True,
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._remove_pid_file") as mock_remove_pid,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.load_config",
            return_value={
                "poll_interval_seconds": 0,
                "kill_switch_path": str(tmp_path / "nope"),
                "max_turns_per_wake": 10,
                "max_dispatches_per_branch_per_day": 5,
                "autonomous_branches": [],
            },
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.is_kill_switch_active",
            side_effect=fake_is_kill_switch,
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.time.sleep") as mock_sleep,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.os.waitpid",
            side_effect=ChildProcessError,
        ),
    ):
        run_daemon()

    assert call_count["n"] >= 2
    # The paused loop waits before re-checking, and shutdown still cleans its pid file (ai_mail, leg 5)
    assert mock_sleep.called
    mock_remove_pid.assert_called_once_with()


def test_run_daemon_shutdown_exits_loop(tmp_path, monkeypatch):
    """SHUTDOWN=True exits the main loop."""
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_mod, "DAEMON_LOG_FILE", tmp_path / "daemon.log")
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._write_pid_file",
            return_value=True,
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._remove_pid_file") as mock_remove_pid,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.load_config",
            return_value={
                "poll_interval_seconds": 0,
                "kill_switch_path": str(tmp_path / "nope"),
                "max_turns_per_wake": 10,
                "max_dispatches_per_branch_per_day": 5,
                "autonomous_branches": [],
            },
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.poll_cycle",
            return_value=0,
        ) as mock_poll,
    ):
        run_daemon()

    mock_poll.assert_not_called()
    mock_remove_pid.assert_called_once_with()


def test_run_daemon_write_pid_failure_returns_early(tmp_path, monkeypatch):
    """Failed _write_pid_file causes run_daemon to return early."""
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._write_pid_file",
            return_value=False,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.load_config",
        ) as mock_config,
    ):
        run_daemon()

    mock_config.assert_not_called()


def test_run_daemon_does_not_start_on_an_unreadable_config(tmp_path, monkeypatch):
    """An unreadable safety config stops the daemon before a cycle, and its pid file goes (ai_mail, leg 13)."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)
    (tmp_path / "safety_config.json").write_text("{{broken", encoding="utf-8")
    cycles = []
    monkeypatch.setattr(daemon_mod, "poll_cycle", lambda config, state: cycles.append(config) or 0)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    run_daemon()

    assert cycles == []
    assert not pid_file.exists()


def test_run_daemon_skips_a_cycle_on_unreadable_state(tmp_path, monkeypatch):
    """A cycle whose state file cannot be read spawns nothing (ai_mail, leg 13)."""
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    (tmp_path / "daemon_state.json").write_text("{{broken", encoding="utf-8")
    config = {"poll_interval_seconds": 0, "kill_switch_path": str(tmp_path / "pause"), "autonomous_branches": []}
    monkeypatch.setattr(daemon_mod, "load_config", lambda: dict(config))
    cycles = []
    monkeypatch.setattr(daemon_mod, "poll_cycle", lambda cfg, state: cycles.append(state) or 0)
    sleeps = []

    def _stop_after_one_skip(seconds):
        sleeps.append(seconds)
        daemon_mod.SHUTDOWN = True

    monkeypatch.setattr(daemon_mod.time, "sleep", _stop_after_one_skip)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    run_daemon()

    assert cycles == []
    assert sleeps == [0]


# ---- poll_cycle edge case tests -----------------------------------


def test_poll_cycle_shutdown_breaks_loop(tmp_path, monkeypatch):
    """SHUTDOWN=True breaks the poll loop mid-iteration."""
    repo_root = tmp_path / "repo"
    branch1 = repo_root / "branch1"
    branch2 = repo_root / "branch2"
    branch1.mkdir(parents=True)
    branch2.mkdir(parents=True)

    registry = {
        "branches": [
            {"email": "@branch1", "path": str(branch1)},
            {"email": "@branch2", "path": str(branch2)},
        ]
    }
    reg_file = repo_root / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)

    def shutdown_on_scan(branch_path, branch_email):
        daemon_mod.SHUTDOWN = True
        return 0

    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    config = {"autonomous_branches": [], "max_dispatches_per_branch_per_day": 10}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails",
            side_effect=shutdown_on_scan,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.check_lock",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.check_inbox_for_dispatch",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent",
        ) as mock_spawn,
    ):
        poll_cycle(config, state)

    mock_spawn.assert_not_called()


def test_poll_cycle_protected_branch_skipped(tmp_path, monkeypatch):
    """Protected branch (@devpulse) is skipped in poll cycle."""
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "devpulse"
    branch_dir.mkdir(parents=True)

    registry = {"branches": [{"email": "@devpulse", "path": str(branch_dir)}]}
    reg_file = repo_root / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    config = {"autonomous_branches": [], "max_dispatches_per_branch_per_day": 10}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails",
        ) as mock_scan,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent",
        ) as mock_spawn,
    ):
        result = poll_cycle(config, state)

    assert result == 0
    mock_scan.assert_not_called()
    mock_spawn.assert_not_called()


def test_poll_cycle_daily_limit_reached(tmp_path, monkeypatch):
    """Branch at daily limit is skipped."""
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "flow"
    branch_dir.mkdir(parents=True)

    registry = {"branches": [{"email": "@flow", "path": str(branch_dir)}]}
    reg_file = repo_root / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    config = {"autonomous_branches": [], "max_dispatches_per_branch_per_day": 3}
    state = {"daily_counts": {"@flow": 3}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails",
        ) as mock_scan,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent",
        ) as mock_spawn,
    ):
        result = poll_cycle(config, state)

    assert result == 0
    mock_scan.assert_not_called()
    mock_spawn.assert_not_called()


def test_poll_cycle_branch_occupied_skipped(tmp_path, monkeypatch):
    """Occupied branch is skipped even if dispatch email exists."""
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "flow"
    branch_dir.mkdir(parents=True)
    (branch_dir / ".ai_mail.local").mkdir()
    inbox = {
        "messages": [
            {
                "id": "d1",
                "status": "new",
                "from": "@devpulse",
                "subject": "task",
                "auto_execute": True,
            }
        ]
    }
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    registry = {"branches": [{"email": "@flow", "path": str(branch_dir)}]}
    reg_file = repo_root / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    config = {"autonomous_branches": [], "max_dispatches_per_branch_per_day": 10}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails",
            return_value=0,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.check_lock",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.is_branch_occupied",
            return_value=True,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent",
        ) as mock_spawn,
    ):
        result = poll_cycle(config, state)

    assert result == 0
    mock_spawn.assert_not_called()


def test_poll_cycle_spawn_failure_not_counted(tmp_path, monkeypatch):
    """Spawn failure does not increment spawned count."""
    repo_root = tmp_path / "repo"
    branch_dir = repo_root / "flow"
    branch_dir.mkdir(parents=True)
    (branch_dir / ".ai_mail.local").mkdir()
    inbox = {
        "messages": [
            {
                "id": "d1",
                "status": "new",
                "from": "@devpulse",
                "subject": "task",
                "auto_execute": True,
            }
        ]
    }
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

    registry = {"branches": [{"email": "@flow", "path": str(branch_dir)}]}
    reg_file = repo_root / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    config = {"autonomous_branches": [], "max_dispatches_per_branch_per_day": 10}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails",
            return_value=0,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.check_lock",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.is_branch_occupied",
            return_value=False,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.spawn_agent",
            return_value=False,
        ),
    ):
        result = poll_cycle(config, state)

    assert result == 0


# ---- _is_registered_sender tests (DPLAN-0159 S2) ----------------


def _sender_admitted(tmp_path, monkeypatch, registry, sender):
    """Run an auto_execute dispatch from sender through spawn_agent; True if the sender gate let it by.

    An admitted dispatch reaches the lock, which answers held, so nothing is
    spawned either way (ai_mail, leg 14). registry None leaves the file missing.
    """
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    if registry is not None:
        reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    message = {"from": sender, "id": "msg1", "subject": "Run this", "auto_execute": True}
    with (
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen") as popen,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(False, "held"),
        ) as lock,
    ):
        result = spawn_agent(tmp_path / "branch", "@testbranch", message, {"max_turns_per_wake": 5}, {})
    assert result is False
    popen.assert_not_called()
    return lock.call_count == 1


@pytest.mark.parametrize(
    ("registry", "sender", "admitted"),
    [
        ({"branches": [{"email": "@flow"}, {"email": "@backup"}]}, "@flow", True),
        ({"branches": [{"email": "@flow"}]}, "@evil", False),
        (None, "@anyone", True),
        ({"branches": []}, "@flow", False),
    ],
    ids=["registered", "unregistered", "missing_registry_admits", "empty_branches"],
)
def test_the_sender_gate_admits_only_a_registered_sender(tmp_path, monkeypatch, registry, sender, admitted):
    """Only a sender the registry lists passes; a missing registry admits (DPLAN-0159 S2)."""
    assert _sender_admitted(tmp_path, monkeypatch, registry, sender) is admitted


def test_an_auto_execute_dispatch_is_refused_when_the_registry_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable registry cannot vouch for a sender, so no auto-execute spawn.

    Before leg 12 _is_registered_sender answered True on an unreadable registry
    (fail open) and spawn_agent ran an auto_execute dispatch from any sender. A
    missing registry still answers True, as pinned above (ai_mail, leg 12).
    """
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)
    branch_path = tmp_path / "branch"
    (branch_path / "logs").mkdir(parents=True)
    message = {"from": "@evil", "id": "msg1", "subject": "Run this", "auto_execute": True}
    state = {"daily_counts": {}, "session_cycles": {}}

    with (
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen") as popen,
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, {"max_turns_per_wake": 5}, state)

    assert result is False
    popen.assert_not_called()
    log_dispatch.assert_not_called()
    notify.assert_not_called()
    assert state["daily_counts"] == {}


# ---- spawn_agent sender auth tests (DPLAN-0159 S2) ----------------


def test_spawn_agent_rejects_unregistered_auto_execute(tmp_path, monkeypatch):
    """Auto-execute dispatch from unregistered sender is rejected."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    registry = {"branches": [{"email": "@flow"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    message = {"from": "@forged", "id": "msg1", "subject": "Fake", "auto_execute": True}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is False


def test_spawn_agent_allows_registered_auto_execute(tmp_path, monkeypatch):
    """Auto-execute dispatch from registered sender proceeds to spawn."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    registry = {"branches": [{"email": "@devpulse"}, {"email": "@flow"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    message = {"from": "@devpulse", "id": "msg1", "subject": "Task", "auto_execute": True}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    mock_process = MagicMock()
    mock_process.pid = 54321

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            return_value=mock_process,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    mock_notify.assert_called_once()
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")


def test_spawn_agent_no_auth_check_without_auto_execute(tmp_path, monkeypatch):
    """Non-auto_execute email skips sender auth check."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()
    (branch_path / "logs").mkdir()

    registry = {"branches": []}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    message = {"from": "@unknown", "id": "msg1", "subject": "Manual"}
    config = {"max_turns_per_wake": 50}
    state = {"daily_counts": {}, "session_cycles": {}}

    mock_process = MagicMock()
    mock_process.pid = 54321

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.Popen",
            return_value=mock_process,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch") as mock_log_dispatch,
        patch("aipass.ai_mail.apps.handlers.notify.send_notification") as mock_notify,
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    mock_notify.assert_called_once()
    mock_log_dispatch.assert_called_once()
    assert mock_log_dispatch.call_args.args[0::2] == ("@testbranch", "spawned")
