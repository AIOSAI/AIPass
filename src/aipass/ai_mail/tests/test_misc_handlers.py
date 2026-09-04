"""Tests for miscellaneous handlers -- central_writer.update_central, dispatch status.check_pid_status,
daemon.run_daemon, delivery.deliver_to_inbox_file, inbox_resolve.resolve_inbox_target.

The increment_counter/update_data_metrics blocks left with their implementation:
they were the only readers of ai_mail's own json_utils handler, which retired
into apps/handlers/.archive/ when the canonical path became the fleet shim
(DPLAN-0325). No production call site ever used either name."""

import json
import os
import subprocess
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.handlers.central_writer as central_mod
import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
from aipass.ai_mail.apps.handlers.central_writer import update_central
from aipass.ai_mail.apps.handlers.dispatch.status import check_pid_status
from aipass.ai_mail.apps.handlers.email.delivery import deliver_to_inbox_file
from aipass.ai_mail.apps.handlers.email.inbox_resolve import resolve_inbox_target


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler_central():
    """Prevent log_operation in central_writer from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.central_writer.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_json_handler_status():
    """Prevent log_operation in dispatch status from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.dispatch.status.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_json_handler_daemon():
    """Prevent log_operation in daemon from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_json_handler_delivery():
    """Prevent log_operation in delivery from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.email.delivery.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_json_handler_inbox_resolve():
    """Prevent log_operation in inbox_resolve from writing real JSON files."""
    with patch("aipass.ai_mail.apps.handlers.email.inbox_resolve.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ==============================================================
# update_central tests
# ==============================================================


def test_update_central_calls_build_and_write():
    """update_central calls aggregate_branch_stats, build_central_data, and write_central_file."""
    mock_stats = {"FLOW": {"unread": 2, "total": 5}}
    mock_data = {"service": "ai_mail", "branch_stats": mock_stats}

    with (
        patch.object(central_mod, "aggregate_branch_stats", return_value=mock_stats),
        patch.object(central_mod, "build_central_data", return_value=mock_data),
        patch.object(central_mod, "write_central_file") as mock_write,
    ):
        result = update_central()

    assert result == mock_data
    mock_write.assert_called_once_with(mock_data)


def test_update_central_propagates_error():
    """update_central propagates exceptions from aggregate_branch_stats."""
    with (
        patch.object(central_mod, "aggregate_branch_stats", side_effect=RuntimeError("scan failed")),
        pytest.raises(RuntimeError, match="scan failed"),
    ):
        update_central()


# ==============================================================
# check_pid_status tests
# ==============================================================


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (ps command)")
def test_check_pid_status_running():
    """Returns RUNNING for the current process PID."""
    result = check_pid_status(os.getpid())

    assert result == "RUNNING"


def test_check_pid_status_completed():
    """Returns COMPLETED for a dead/nonexistent PID."""
    # Use a PID that almost certainly does not exist
    with patch("aipass.ai_mail.apps.handlers.dispatch.status.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = check_pid_status(999999999)

    assert result == "COMPLETED"


def test_check_pid_status_unknown_on_error():
    """Returns UNKNOWN when subprocess raises an error."""
    with patch("aipass.ai_mail.apps.handlers.dispatch.status.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.SubprocessError("ps failed")
        result = check_pid_status(12345)

    assert result == "UNKNOWN"


# ==============================================================
# run_daemon tests (minimal -- max_cycles not available, test poll_cycle call)
# ==============================================================


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process API (os.WNOHANG)")
def test_daemon_poll_cycle_is_called(tmp_path, monkeypatch):
    """run_daemon calls poll_cycle and save_daemon_state in the loop.

    We mock the key dependencies and set SHUTDOWN to True after one cycle
    to verify the loop structure works.
    """
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_mod, "CONFIG_FILE", tmp_path / "safety_config.json")
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", tmp_path / "daemon_state.json")

    poll_calls = []

    def mock_poll_cycle(config, state):
        """Track poll_cycle invocations and trigger shutdown."""
        poll_calls.append(True)
        daemon_mod.SHUTDOWN = True
        return 0

    with (
        patch.object(daemon_mod, "_write_pid_file", return_value=True),
        patch.object(daemon_mod, "_remove_pid_file"),
        patch.object(daemon_mod, "poll_cycle", side_effect=mock_poll_cycle),
        patch.object(daemon_mod, "save_daemon_state"),
        patch.object(daemon_mod, "is_kill_switch_active", return_value=False),
        patch("os.waitpid", side_effect=ChildProcessError),
    ):
        # Reset SHUTDOWN before running
        daemon_mod.SHUTDOWN = False
        daemon_mod.run_daemon()

    assert len(poll_calls) == 1

    # Clean up global state
    daemon_mod.SHUTDOWN = False


def test_daemon_exits_if_pid_file_blocked(tmp_path, monkeypatch):
    """run_daemon returns immediately when _write_pid_file returns False."""
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", tmp_path / "daemon.pid")

    with (
        patch.object(daemon_mod, "_write_pid_file", return_value=False),
        patch.object(daemon_mod, "poll_cycle") as mock_poll,
    ):
        daemon_mod.run_daemon()

    mock_poll.assert_not_called()


# ==============================================================
# deliver_to_inbox_file tests
# ==============================================================


@pytest.fixture
def _noop_inbox_lock(monkeypatch):
    """Replace _get_inbox_lock with a no-op context manager."""
    from contextlib import contextmanager

    @contextmanager
    def _noop_lock(path):
        yield

    monkeypatch.setattr(delivery_mod, "_get_inbox_lock", lambda: _noop_lock)


@pytest.fixture(autouse=True)
def _silence_delivery_notifications():
    """Prevent desktop notifications during delivery tests."""
    with patch.object(delivery_mod, "_emit_notification_event"):
        yield


def test_deliver_to_inbox_file_happy_path(tmp_path, _noop_inbox_lock):
    """Successful delivery writes message to inbox and returns (True, '', reply_id)."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {
        "mailbox": "inbox",
        "total_messages": 0,
        "unread_count": 0,
        "messages": [],
    }
    inbox_file.write_text(json.dumps(inbox_data, indent=2), encoding="utf-8")

    email_data = {
        "from": "@sender",
        "to": "@target",
        "subject": "Test delivery",
        "message": "Test body",
        "timestamp": "2026-04-01 10:00:00",
        "status": "new",
    }

    success, error, reply_id = deliver_to_inbox_file(inbox_file, email_data)

    assert success is True
    assert error == ""
    assert reply_id != ""
    assert len(reply_id) == 8

    with open(inbox_file, "r", encoding="utf-8") as f:
        result = json.load(f)
    assert result["total_messages"] == 1
    assert len(result["messages"]) == 1
    assert result["messages"][0]["subject"] == "Test delivery"


def test_deliver_to_inbox_file_missing_file(tmp_path, _noop_inbox_lock):
    """Returns failure when inbox file does not exist."""
    inbox_file = tmp_path / "nonexistent.json"

    email_data = {
        "from": "@sender",
        "to": "@target",
        "subject": "Test",
        "message": "Body",
        "timestamp": "2026-04-01 10:00:00",
    }

    success, error, reply_id = deliver_to_inbox_file(inbox_file, email_data)

    assert success is False
    assert "inbox not found" in error
    assert reply_id == ""


def test_deliver_to_inbox_file_preserves_existing_messages(tmp_path, _noop_inbox_lock):
    """New message is prepended to existing messages."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {
        "mailbox": "inbox",
        "total_messages": 1,
        "unread_count": 0,
        "messages": [{"id": "existing", "subject": "Old email", "status": "opened"}],
    }
    inbox_file.write_text(json.dumps(inbox_data, indent=2), encoding="utf-8")

    email_data = {
        "from": "@sender",
        "to": "@target",
        "subject": "New email",
        "message": "New body",
        "timestamp": "2026-04-01 12:00:00",
        "status": "new",
    }

    success, error, reply_id = deliver_to_inbox_file(inbox_file, email_data)

    assert success is True
    with open(inbox_file, "r", encoding="utf-8") as f:
        result = json.load(f)
    assert result["total_messages"] == 2
    assert result["messages"][0]["subject"] == "New email"
    assert result["messages"][1]["subject"] == "Old email"


# ==============================================================
# resolve_inbox_target tests
# ==============================================================


def test_resolve_inbox_target_explicit_branch(tmp_path):
    """Resolves inbox for an explicit @branch target."""
    branch_info = {"path": str(tmp_path / "flow"), "name": "FLOW"}
    mock_get_branch = MagicMock(return_value=branch_info)
    mock_get_user = MagicMock()

    success, result = resolve_inbox_target("@flow", tmp_path, mock_get_branch, mock_get_user)

    assert success is True
    assert result["target_branch"] == "@flow"
    assert result["display_name"] == "FLOW"
    assert result["error"] is None
    assert result["inbox_file"] == Path(tmp_path / "flow" / ".ai_mail.local" / "inbox.json")
    mock_get_branch.assert_called_once_with("@flow")
    mock_get_user.assert_not_called()


def test_resolve_inbox_target_unknown_branch():
    """Returns failure for unknown branch."""
    mock_get_branch = MagicMock(return_value=None)
    mock_get_user = MagicMock()

    success, result = resolve_inbox_target("@nonexistent", Path("/repo"), mock_get_branch, mock_get_user)

    assert success is False
    assert "Unknown branch" in result["error"]


def test_resolve_inbox_target_no_args_uses_current_user(tmp_path):
    """Uses current user detection when no explicit target is provided."""
    user_info = {
        "mailbox_path": str(tmp_path / ".ai_mail.local"),
        "display_name": "TRIGGER",
    }
    mock_get_branch = MagicMock()
    mock_get_user = MagicMock(return_value=user_info)

    success, result = resolve_inbox_target(None, tmp_path, mock_get_branch, mock_get_user)

    assert success is True
    assert result["target_branch"] is None
    assert result["display_name"] == "TRIGGER"
    assert result["inbox_file"] == Path(tmp_path / ".ai_mail.local" / "inbox.json")
    mock_get_branch.assert_not_called()
    mock_get_user.assert_called_once()


def test_resolve_inbox_target_non_at_arg_uses_current_user(tmp_path):
    """Non-@ argument is treated as no target (uses current user)."""
    user_info = {
        "mailbox_path": str(tmp_path / ".ai_mail.local"),
        "display_name": "TRIGGER",
    }
    mock_get_branch = MagicMock()
    mock_get_user = MagicMock(return_value=user_info)

    success, result = resolve_inbox_target("some_arg", tmp_path, mock_get_branch, mock_get_user)

    assert success is True
    assert result["target_branch"] is None
    mock_get_user.assert_called_once()


def test_resolve_inbox_target_relative_path_resolved(tmp_path):
    """Relative branch path is resolved against repo_root."""
    branch_info = {"path": "src/flow", "name": "FLOW"}
    mock_get_branch = MagicMock(return_value=branch_info)
    mock_get_user = MagicMock()

    success, result = resolve_inbox_target("@flow", tmp_path, mock_get_branch, mock_get_user)

    assert success is True
    resolved_inbox = result["inbox_file"]
    assert resolved_inbox.is_absolute()
