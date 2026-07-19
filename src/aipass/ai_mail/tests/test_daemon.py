# =================== AIPass ====================
# Name: test_daemon.py
# Description: Tests for dispatch daemon handler
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for dispatch daemon handler -- config loading, state management, inbox scanning."""

import json
import os
import sys
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, mock_open, patch

import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    _read_json,
    _write_json,
    load_config,
    load_daemon_state,
    save_daemon_state,
    is_kill_switch_active,
    get_registered_branches,
    check_inbox_for_dispatch,
    is_protected_branch,
    _handle_signal,
    _check_lock,
    _acquire_lock,
    _is_registered_sender,
    poll_cycle,
    _write_pid_file,
    _remove_pid_file,
    _read_session_type,
    _is_branch_occupied,
    spawn_agent,
    run_daemon,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _redirect_paths(tmp_path, monkeypatch):
    """Redirect all module-level file paths to tmp_path locations."""
    monkeypatch.setattr(daemon_mod, "CONFIG_FILE", tmp_path / "safety_config.json")
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", tmp_path / "daemon_state.json")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", tmp_path / "AIPASS_REGISTRY.json")


# ---- _read_json tests ----------------------------------------


def test_read_json_valid_file(tmp_path):
    """Valid JSON file returns parsed dict."""
    target = tmp_path / "data.json"
    target.write_text(json.dumps({"key": "value"}), encoding="utf-8")

    result = _read_json(target)

    assert result == {"key": "value"}


def test_read_json_missing_file(tmp_path):
    """Nonexistent file returns None."""
    result = _read_json(tmp_path / "does_not_exist.json")

    assert result is None


def test_read_json_invalid_json(tmp_path):
    """Corrupt JSON returns None instead of raising."""
    target = tmp_path / "bad.json"
    target.write_text("{not valid json!!!", encoding="utf-8")

    result = _read_json(target)

    assert result is None


def test_read_json_empty_file(tmp_path):
    """Empty file returns None (json.JSONDecodeError)."""
    target = tmp_path / "empty.json"
    target.write_text("", encoding="utf-8")

    result = _read_json(target)

    assert result is None


# ---- _write_json tests ----------------------------------------


def test_write_json_creates_file(tmp_path):
    """Writing data creates the file with correct content."""
    target = tmp_path / "output.json"
    data = {"branches": ["@flow", "@backup"]}

    result = _write_json(target, data)

    assert result is True
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == {"branches": ["@flow", "@backup"]}


def test_write_json_creates_parent_dirs(tmp_path):
    """Writing to a nested path creates intermediate directories."""
    target = tmp_path / "deep" / "nested" / "file.json"

    result = _write_json(target, {"ok": True})

    assert result is True
    assert target.exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == {"ok": True}


def test_write_json_unicode(tmp_path):
    """Unicode content is preserved (ensure_ascii=False)."""
    target = tmp_path / "unicode.json"
    data = {"message": "Hello from branch \u2014 done"}

    _write_json(target, data)

    raw = target.read_text(encoding="utf-8")
    assert "\u2014" in raw, "Unicode dash should appear literally, not escaped"
    written = json.loads(raw)
    assert written["message"] == "Hello from branch \u2014 done"


# ---- load_config tests ----------------------------------------


def test_load_config_no_file():
    """Missing config file returns all defaults."""
    result = load_config()

    assert isinstance(result, dict)
    assert result["poll_interval_seconds"] == 300
    assert result["max_depth"] == 3
    assert result["max_turns_per_wake"] == 100
    assert result["max_dispatches_per_branch_per_day"] == 10
    assert result["session_rotation_cycles"] == 12
    assert result["autonomous_branches"] == []
    assert "cold_start_prompt" in result
    assert "wake_prompt" in result
    assert "kill_switch_path" in result


def test_load_config_partial_file(tmp_path):
    """Config with only some keys gets remaining defaults filled in."""
    config_file = tmp_path / "safety_config.json"
    config_file.write_text(
        json.dumps({"poll_interval_seconds": 60, "max_depth": 5}),
        encoding="utf-8",
    )

    result = load_config()

    assert result["poll_interval_seconds"] == 60
    assert result["max_depth"] == 5
    # Defaults filled in
    assert result["max_turns_per_wake"] == 100
    assert result["max_dispatches_per_branch_per_day"] == 10
    assert result["autonomous_branches"] == []


def test_load_config_full_file(tmp_path):
    """Complete config file is returned with all user values."""
    config_file = tmp_path / "safety_config.json"
    full_config = {
        "kill_switch_path": "/tmp/test_pause",
        "poll_interval_seconds": 120,
        "max_depth": 2,
        "max_turns_per_wake": 50,
        "max_dispatches_per_branch_per_day": 5,
        "session_rotation_cycles": 6,
        "cold_start_prompt": "Custom cold start",
        "wake_prompt": "Custom wake",
        "autonomous_branches": ["@flow", "@backup"],
    }
    config_file.write_text(json.dumps(full_config), encoding="utf-8")

    result = load_config()

    assert result["poll_interval_seconds"] == 120
    assert result["max_depth"] == 2
    assert result["max_turns_per_wake"] == 50
    assert result["max_dispatches_per_branch_per_day"] == 5
    assert result["session_rotation_cycles"] == 6
    assert result["cold_start_prompt"] == "Custom cold start"
    assert result["wake_prompt"] == "Custom wake"
    assert result["autonomous_branches"] == ["@flow", "@backup"]
    assert result["kill_switch_path"] == "/tmp/test_pause"


def test_load_config_corrupt_json(tmp_path):
    """Corrupt config file returns defaults."""
    config_file = tmp_path / "safety_config.json"
    config_file.write_text("{{broken", encoding="utf-8")

    result = load_config()

    assert result["poll_interval_seconds"] == 300
    assert result["max_turns_per_wake"] == 100


# ---- load_daemon_state tests -----------------------------------


def test_load_daemon_state_no_file():
    """Missing state file returns empty state with today's date."""
    result = load_daemon_state()

    assert isinstance(result, dict)
    assert result["daily_counts"] == {}
    assert result["session_cycles"] == {}
    assert result["date"] == str(date.today())


def test_load_daemon_state_same_day(tmp_path):
    """State from today preserves existing daily counts."""
    state_file = tmp_path / "daemon_state.json"
    state = {
        "daily_counts": {"@flow": 3, "@backup": 1},
        "session_cycles": {},
        "date": str(date.today()),
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = load_daemon_state()

    assert result["daily_counts"] == {"@flow": 3, "@backup": 1}
    assert result["date"] == str(date.today())


def test_load_daemon_state_new_day_resets_counts(tmp_path):
    """State from a previous day resets daily_counts and updates date."""
    state_file = tmp_path / "daemon_state.json"
    yesterday = str(date.today() - timedelta(days=1))
    state = {
        "daily_counts": {"@flow": 10, "@backup": 5},
        "session_cycles": {"some_branch": 4},
        "date": yesterday,
    }
    state_file.write_text(json.dumps(state), encoding="utf-8")

    result = load_daemon_state()

    assert result["daily_counts"] == {}
    assert result["date"] == str(date.today())
    # session_cycles should NOT be reset
    assert result["session_cycles"] == {"some_branch": 4}


# ---- save_daemon_state tests -----------------------------------


def test_save_daemon_state_writes_file(tmp_path):
    """save_daemon_state writes state with last_updated timestamp."""
    state = {"daily_counts": {"@flow": 2}, "date": str(date.today())}

    save_daemon_state(state)

    state_file = tmp_path / "daemon_state.json"
    assert state_file.exists()
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert written["daily_counts"] == {"@flow": 2}
    assert written["date"] == str(date.today())
    assert "last_updated" in written
    # Verify last_updated is a valid timestamp
    parsed = datetime.strptime(written["last_updated"], "%Y-%m-%d %H:%M:%S")
    assert (datetime.now() - parsed).total_seconds() < 5


# ---- is_kill_switch_active tests -------------------------------


def test_kill_switch_active_when_file_exists(tmp_path):
    """Returns True when the kill switch file exists."""
    pause_file = tmp_path / "autonomous_pause"
    pause_file.touch()

    result = is_kill_switch_active({"kill_switch_path": str(pause_file)})

    assert result is True


def test_kill_switch_inactive_when_no_file(tmp_path):
    """Returns False when the kill switch file does not exist."""
    result = is_kill_switch_active({"kill_switch_path": str(tmp_path / "no_such_file")})

    assert result is False


def test_kill_switch_uses_default_path_when_key_missing():
    """Falls back to default path when kill_switch_path is absent from config."""
    # With no kill_switch_path key, it uses the default (which shouldn't exist in test)
    result = is_kill_switch_active({})

    # The default path uses _REPO_ROOT / ".aipass" / "autonomous_pause"
    # which should not exist in a test environment
    assert isinstance(result, bool)


# ---- get_registered_branches tests -----------------------------


def test_get_registered_branches_valid(tmp_path):
    """Returns branch list from registry file."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    branches = [
        {"email": "@flow", "path": "/home/user/flow"},
        {"email": "@backup", "path": "/home/user/backup"},
    ]
    registry.write_text(json.dumps({"branches": branches}), encoding="utf-8")

    result = get_registered_branches()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["email"] == "@flow"
    assert result[0]["path"] == "/home/user/flow"
    assert result[1]["email"] == "@backup"
    assert result[1]["path"] == "/home/user/backup"


def test_get_registered_branches_no_file():
    """Missing registry returns empty list."""
    result = get_registered_branches()

    assert result == []
    assert isinstance(result, list)


def test_get_registered_branches_no_branches_key(tmp_path):
    """Registry without 'branches' key returns empty list."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(json.dumps({"version": "1.0"}), encoding="utf-8")

    result = get_registered_branches()

    assert result == []


# ---- check_inbox_for_dispatch tests ----------------------------


def test_check_inbox_dispatch_new_message(tmp_path):
    """Returns first new auto_execute message."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_data = {
        "messages": [
            {"id": "m1", "status": "opened", "auto_execute": True},
            {"id": "m2", "status": "new", "auto_execute": True, "subject": "Deploy"},
            {"id": "m3", "status": "new", "auto_execute": True, "subject": "Later"},
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is not None
    assert result["id"] == "m2"
    assert result["subject"] == "Deploy"


def test_check_inbox_dispatch_no_dispatch_emails(tmp_path):
    """Returns None when inbox has no auto_execute messages."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_data = {
        "messages": [
            {"id": "m1", "status": "new", "subject": "Regular email"},
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is None


def test_check_inbox_dispatch_no_inbox_file(tmp_path):
    """Returns None when inbox file does not exist."""
    result = check_inbox_for_dispatch(tmp_path / "nonexistent_branch")

    assert result is None


def test_check_inbox_dispatch_orphaned_opened_message(tmp_path):
    """Returns opened dispatch email orphaned for >30 minutes."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    old_timestamp = (datetime.now() - timedelta(minutes=45)).isoformat()
    inbox_data = {
        "messages": [
            {
                "id": "m1",
                "status": "opened",
                "auto_execute": True,
                "timestamp": old_timestamp,
            },
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is not None
    assert result["id"] == "m1"


def test_check_inbox_dispatch_recent_opened_not_returned(tmp_path):
    """Opened dispatch email younger than 30 minutes is NOT returned."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    recent_timestamp = (datetime.now() - timedelta(minutes=5)).isoformat()
    inbox_data = {
        "messages": [
            {
                "id": "m1",
                "status": "opened",
                "auto_execute": True,
                "timestamp": recent_timestamp,
            },
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is None


def test_check_inbox_dispatch_new_prioritized_over_orphan(tmp_path):
    """New dispatch email is returned even when orphaned opened exists."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    old_timestamp = (datetime.now() - timedelta(minutes=60)).isoformat()
    inbox_data = {
        "messages": [
            {
                "id": "orphan1",
                "status": "opened",
                "auto_execute": True,
                "timestamp": old_timestamp,
            },
            {
                "id": "new1",
                "status": "new",
                "auto_execute": True,
                "subject": "Fresh task",
            },
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is not None
    assert result["id"] == "new1"


def test_check_inbox_dispatch_opened_no_timestamp_skipped(tmp_path):
    """Opened dispatch email without timestamp is skipped."""
    inbox_dir = tmp_path / "branch" / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_data = {
        "messages": [
            {
                "id": "m1",
                "status": "opened",
                "auto_execute": True,
                # No timestamp field
            },
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = check_inbox_for_dispatch(tmp_path / "branch")

    assert result is None


# ---- is_protected_branch tests ---------------------------------


def test_is_protected_branch_devpulse():
    """@devpulse is protected."""
    assert is_protected_branch("@devpulse") is True


def test_is_protected_branch_other():
    """Other branches are not protected."""
    assert is_protected_branch("@flow") is False
    assert is_protected_branch("@backup") is False
    assert is_protected_branch("@memory") is False


def test_is_protected_branch_empty_string():
    """Empty string is not protected."""
    assert is_protected_branch("") is False


# ---- _has_test_token tests -----------------------------------

from aipass.ai_mail.apps.handlers.dispatch.test_token import (  # noqa: E402
    has_test_token as _has_test_token,
    auto_ack_test_email as _auto_ack_test_email,
    scan_and_ack_test_emails,
    TEST_TOKEN,
)


def test_has_test_token_plain_body():
    """Token on its own line is detected."""
    body = f"Some text\n{TEST_TOKEN}\nMore text"
    assert _has_test_token(body) is True


def test_has_test_token_only_token():
    """Body containing only the token is detected."""
    assert _has_test_token(TEST_TOKEN) is True


def test_has_test_token_absent():
    """Body without token returns False."""
    assert _has_test_token("Hello, please process inbox.") is False


def test_has_test_token_inside_code_fence_ignored():
    """Token inside a code fence is not detected."""
    body = f"Example:\n```\n{TEST_TOKEN}\n```\nEnd"
    assert _has_test_token(body) is False


def test_has_test_token_after_code_fence():
    """Token after a closing fence is still detected."""
    body = f"```\nsome code\n```\n{TEST_TOKEN}"
    assert _has_test_token(body) is True


def test_has_test_token_whitespace_stripped():
    """Leading/trailing whitespace is stripped before comparison."""
    body = f"  {TEST_TOKEN}  "
    assert _has_test_token(body) is True


def test_has_test_token_partial_match_not_detected():
    """A partial token string does not match."""
    assert _has_test_token("[AIPASS-TEST]") is False


# ---- _auto_ack_test_email tests ------------------------------


def test_auto_ack_test_email_success(tmp_path):
    """Successful reply + close returns True."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    message = {"id": "abc123", "from_email": "@devpulse", "subject": "Ping"}

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = _auto_ack_test_email(branch_path, "@testbranch", message)

    assert result is True
    assert mock_run.call_count == 2


def test_auto_ack_test_email_reply_failure(tmp_path):
    """Failed reply returns False without attempting close."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    message = {"id": "abc123", "from_email": "@devpulse", "subject": "Ping"}

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"
        result = _auto_ack_test_email(branch_path, "@testbranch", message)

    assert result is False
    assert mock_run.call_count == 1


def test_auto_ack_test_email_missing_id(tmp_path):
    """Message without id returns False immediately."""
    message = {"from_email": "@devpulse", "subject": "Ping"}
    result = _auto_ack_test_email(tmp_path, "@testbranch", message)
    assert result is False


def test_auto_ack_test_email_missing_sender(tmp_path):
    """Message without from_email or from returns False immediately."""
    message = {"id": "abc123", "subject": "Ping"}
    result = _auto_ack_test_email(tmp_path, "@testbranch", message)
    assert result is False


# ---- scan_and_ack_test_emails tests -------------------------


def test_scan_and_ack_test_emails_acks_matching(tmp_path):
    """Returns count of acked test emails."""
    branch_path = tmp_path / "testbranch"
    ai_mail_local = branch_path / ".ai_mail.local"
    ai_mail_local.mkdir(parents=True)
    inbox = {
        "messages": [
            {"id": "t1", "status": "new", "from_email": "@devpulse", "subject": "test", "body": TEST_TOKEN},
            {"id": "n1", "status": "new", "from_email": "@devpulse", "subject": "work", "body": "do something"},
        ]
    }
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox))

    with patch("aipass.ai_mail.apps.handlers.dispatch.test_token.auto_ack_test_email", return_value=True) as mock_ack:
        count = scan_and_ack_test_emails(branch_path, "@testbranch")

    assert count == 1
    mock_ack.assert_called_once()


def test_scan_and_ack_test_emails_skips_closed(tmp_path):
    """Closed messages are not scanned."""
    branch_path = tmp_path / "testbranch"
    ai_mail_local = branch_path / ".ai_mail.local"
    ai_mail_local.mkdir(parents=True)
    inbox = {
        "messages": [
            {"id": "t1", "status": "closed", "from_email": "@devpulse", "subject": "test", "body": TEST_TOKEN},
        ]
    }
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox))

    with patch("aipass.ai_mail.apps.handlers.dispatch.test_token.auto_ack_test_email") as mock_ack:
        count = scan_and_ack_test_emails(branch_path, "@testbranch")

    assert count == 0
    mock_ack.assert_not_called()


def test_scan_and_ack_test_emails_no_inbox(tmp_path):
    """Missing inbox returns 0."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    count = scan_and_ack_test_emails(branch_path, "@testbranch")
    assert count == 0


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
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox))

    # Registry with relative path (real-world format)
    registry = {"branches": [{"email": "@ai_mail", "path": "src/aipass/ai_mail", "status": "active"}]}
    (repo_root / "AIPASS_REGISTRY.json").write_text(json.dumps(registry))

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
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._check_lock", return_value=None),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._is_branch_occupied", return_value=False),
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
    (branch_dir / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox))

    registry = {"branches": [{"email": "@drone", "path": str(branch_dir), "status": "active"}]}
    (repo_root / "AIPASS_REGISTRY.json").write_text(json.dumps(registry))
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
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._check_lock", return_value=None),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._is_branch_occupied", return_value=False),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.scan_and_ack_test_emails", return_value=0),
    ):
        daemon_mod.poll_cycle(config, state)

    assert len(spawned_paths) == 1
    assert spawned_paths[0].is_absolute()
    assert spawned_paths[0] == branch_dir


# ---- _handle_signal tests --------------------------------------


def test_handle_signal_sets_shutdown(monkeypatch):
    """Calling _handle_signal sets SHUTDOWN to True."""
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)

    _handle_signal(15, None)

    assert daemon_mod.SHUTDOWN is True


# ---- _check_lock tests -----------------------------------------


def test_check_lock_no_file(tmp_path):
    """No lock file returns None."""
    result = _check_lock(tmp_path)

    assert result is None


def test_check_lock_alive_pid(tmp_path, monkeypatch):
    """Lock with alive PID returns lock data."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: True)

    result = _check_lock(tmp_path)

    assert result is not None
    assert result["pid"] == 99999


def test_check_lock_dead_pid(tmp_path, monkeypatch):
    """Lock with dead PID is cleaned up."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: False)

    result = _check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_permission_error(tmp_path, monkeypatch):
    """Lock with PermissionError on kill returns lock data (process exists)."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: True)

    result = _check_lock(tmp_path)

    assert result is not None
    assert result["pid"] == 99999


def test_check_lock_stale_over_10min_removed(tmp_path, monkeypatch):
    """Stale lock older than 10 minutes with dead PID is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    old_time = (datetime.now() - timedelta(minutes=15)).isoformat()
    lock_data = {"pid": 99999, "timestamp": old_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: False)

    result = _check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_stale_under_10min_dead_pid_removed(tmp_path, monkeypatch):
    """Stale lock under 10 minutes with dead PID is also removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
    lock_data = {"pid": 99999, "timestamp": recent_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: False)

    result = _check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_corrupt_json_removed(tmp_path):
    """Corrupt lock file is removed and returns None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json!!", encoding="utf-8")

    result = _check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_unparseable_timestamp(tmp_path, monkeypatch):
    """Lock with unparseable timestamp and dead PID is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": "not-a-timestamp"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    def _raise_process_lookup(pid, sig):
        raise ProcessLookupError("No such process")

    monkeypatch.setattr(os, "kill", _raise_process_lookup)

    result = _check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


# ---- _acquire_lock tests ----------------------------------------


def test_acquire_lock_success(tmp_path):
    """New lock file is created atomically."""
    acquired, msg = _acquire_lock(tmp_path, 12345)

    assert acquired is True
    assert msg == "Lock acquired"
    lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
    assert lock_file.exists()
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert data["pid"] == 12345


def test_acquire_lock_file_exists_error(tmp_path):
    """FileExistsError when lock already present returns (False, message)."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text('{"pid": 111}', encoding="utf-8")

    acquired, msg = _acquire_lock(tmp_path, 22222)

    assert acquired is False
    assert "already exists" in msg


def test_acquire_lock_oserror(tmp_path):
    """OSError during lock creation returns (False, message)."""
    with patch("os.open", side_effect=OSError("Permission denied")):
        acquired, msg = _acquire_lock(tmp_path, 12345)

    assert acquired is False
    assert "Lock failed" in msg


# ---- _write_pid_file tests --------------------------------------


def test_write_pid_file_no_existing(tmp_path, monkeypatch):
    """No existing PID file: writes current PID and returns True."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    result = _write_pid_file()

    assert result is True
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_write_pid_file_existing_alive_pid(tmp_path, monkeypatch):
    """Existing PID file with alive process returns False."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    result = _write_pid_file()

    assert result is False


def test_write_pid_file_existing_dead_pid(tmp_path, monkeypatch):
    """Existing PID file with dead process: takes over and returns True."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    def _kill_stub(pid, sig):
        if pid == 999999:
            raise ProcessLookupError("No such process")

    monkeypatch.setattr(os, "kill", _kill_stub)

    result = _write_pid_file()

    assert result is True
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_write_pid_file_existing_permission_error(tmp_path, monkeypatch):
    """Existing PID file with PermissionError on kill returns False."""
    monkeypatch.setattr("sys.platform", "linux")
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("888888", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    def _raise_permission(pid, sig):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "kill", _raise_permission)

    result = _write_pid_file()

    assert result is False


def test_write_pid_file_corrupt_pid_file(tmp_path, monkeypatch):
    """Corrupt PID file is handled gracefully and overwritten."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    result = _write_pid_file()

    assert result is True
    assert int(pid_file.read_text().strip()) == os.getpid()


# ---- _remove_pid_file tests ------------------------------------


def test_remove_pid_file_matching_pid(tmp_path, monkeypatch):
    """PID file with matching PID is removed."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    _remove_pid_file()

    assert not pid_file.exists()


def test_remove_pid_file_different_pid(tmp_path, monkeypatch):
    """PID file with different PID is left alone."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    _remove_pid_file()

    assert pid_file.exists()
    assert pid_file.read_text().strip() == "999999"


def test_remove_pid_file_missing(tmp_path, monkeypatch):
    """Missing PID file does not raise errors."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    _remove_pid_file()

    assert not pid_file.exists()


def test_remove_pid_file_corrupt(tmp_path, monkeypatch):
    """Corrupt PID file is removed."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    _remove_pid_file()

    assert not pid_file.exists()


# ---- _read_session_type tests -----------------------------------


def test_read_session_type_found(monkeypatch):
    """Returns the AIPASS_SESSION_TYPE value when found in /proc."""
    monkeypatch.setattr(sys, "platform", "linux")
    environ_data = b"HOME=/home/user\0AIPASS_SESSION_TYPE=daemon\0PATH=/usr/bin"

    with patch("builtins.open", mock_open(read_data=environ_data)):
        result = _read_session_type("12345")

    assert result == "daemon"


def test_read_session_type_not_found(monkeypatch):
    """Returns 'interactive' when AIPASS_SESSION_TYPE is not in environ."""
    monkeypatch.setattr(sys, "platform", "linux")
    environ_data = b"HOME=/home/user\0PATH=/usr/bin"

    with patch("builtins.open", mock_open(read_data=environ_data)):
        result = _read_session_type("12345")

    assert result == "interactive"


def test_read_session_type_non_linux(monkeypatch):
    """Returns 'interactive' on non-Linux platforms."""
    monkeypatch.setattr(sys, "platform", "darwin")

    result = _read_session_type("12345")

    assert result == "interactive"


def test_read_session_type_oserror(monkeypatch):
    """Returns 'interactive' on OSError when reading /proc."""
    monkeypatch.setattr(sys, "platform", "linux")

    with patch("builtins.open", side_effect=OSError("No such file")):
        result = _read_session_type("12345")

    assert result == "interactive"


# ---- _is_branch_occupied tests -----------------------------------


def test_is_branch_occupied_no_claude_processes(tmp_path):
    """Returns False when pgrep finds no claude processes."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        return_value=mock_result,
    ):
        result = _is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_claude_in_different_dir(tmp_path, monkeypatch):
    """Returns False when claude runs in a different directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value="/some/other/dir"),
    ):
        result = _is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_claude_in_same_dir_interactive(tmp_path, monkeypatch):
    """Returns True when interactive claude session runs in same directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value=str(tmp_path.resolve())),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._read_session_type",
            return_value="interactive",
        ),
    ):
        result = _is_branch_occupied(tmp_path)

    assert result is True


def test_is_branch_occupied_claude_in_same_dir_daemon(tmp_path, monkeypatch):
    """Returns False when daemon claude session runs in same directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value=str(tmp_path.resolve())),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._read_session_type",
            return_value="daemon",
        ),
    ):
        result = _is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_pgrep_failure(tmp_path):
    """Returns False when pgrep raises an exception."""
    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        side_effect=Exception("pgrep unavailable"),
    ):
        result = _is_branch_occupied(tmp_path)

    assert result is False


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    assert state["daily_counts"]["@testbranch"] == 1
    assert state["session_cycles"][str(branch_path)] == 1


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
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is False


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    assert "CLAUDE_API_KEY" not in captured_env
    assert "CLAUDE_MODEL" not in captured_env
    assert "AIPASS_BOT_ID" not in captured_env
    assert captured_env.get("AIPASS_SPAWNED") == "1"
    assert captured_env.get("AIPASS_SESSION_TYPE") == "daemon"


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True
    monitor_cmd = captured_args[0]
    assert "--model" in monitor_cmd
    model_idx = monitor_cmd.index("--model")
    assert monitor_cmd[model_idx + 1] == daemon_mod.DEFAULT_MODEL


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "drone @ai_mail reply abc12345" in prompt
    assert "required" in prompt.lower()


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "@devpulse" in prompt


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        spawn_agent(branch_path, "@testbranch", message, config, state)

    prompt_idx = captured_cmd.index("-p") + 1
    prompt = captured_cmd[prompt_idx]
    assert "reply <id>" in prompt
    assert "required" in prompt.lower()


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
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._remove_pid_file"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.load_config",
            return_value={
                "poll_interval_seconds": 0,
                "kill_switch_path": "/tmp/nope",
                "max_turns_per_wake": 10,
                "max_dispatches_per_branch_per_day": 5,
                "autonomous_branches": [],
            },
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.is_kill_switch_active",
            side_effect=fake_is_kill_switch,
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.time.sleep"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.os.waitpid",
            side_effect=ChildProcessError,
        ),
    ):
        run_daemon()

    assert call_count["n"] >= 2


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
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon._remove_pid_file"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.load_config",
            return_value={
                "poll_interval_seconds": 0,
                "kill_switch_path": "/tmp/nope",
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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._check_lock",
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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._check_lock",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._is_branch_occupied",
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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._check_lock",
            return_value=None,
        ),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon._is_branch_occupied",
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


def test_is_registered_sender_found(tmp_path, monkeypatch):
    """Registered sender returns True."""
    registry = {"branches": [{"email": "@flow"}, {"email": "@backup"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    assert _is_registered_sender("@flow") is True


def test_is_registered_sender_not_found(tmp_path, monkeypatch):
    """Unregistered sender returns False."""
    registry = {"branches": [{"email": "@flow"}]}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    assert _is_registered_sender("@evil") is False


def test_is_registered_sender_missing_registry(tmp_path, monkeypatch):
    """Missing registry fails open (returns True)."""
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", tmp_path / "missing.json")

    assert _is_registered_sender("@anyone") is True


def test_is_registered_sender_empty_branches(tmp_path, monkeypatch):
    """Empty branches list returns False for any sender."""
    registry = {"branches": []}
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "BRANCH_REGISTRY", reg_file)

    assert _is_registered_sender("@flow") is False


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True


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
            "aipass.ai_mail.apps.handlers.dispatch.daemon._acquire_lock",
            return_value=(True, "Lock acquired"),
        ),
        patch("aipass.ai_mail.apps.handlers.dispatch.daemon.log_dispatch"),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.send_notification",
            create=True,
        ),
    ):
        result = spawn_agent(branch_path, "@testbranch", message, config, state)

    assert result is True


# ---- _write_pid_file atomic tests (DPLAN-0159 S5) ----------------


def test_write_pid_file_atomic_no_existing(tmp_path, monkeypatch):
    """Atomic creation succeeds when no PID file exists."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    result = _write_pid_file()

    assert result is True
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) == os.getpid()


def test_write_pid_file_atomic_race_second_loses(tmp_path, monkeypatch):
    """Second daemon loses the race when both try O_CREAT|O_EXCL."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)

    # First daemon wins
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    # Second daemon: file exists, owner is alive → returns False
    result = _write_pid_file()

    assert result is False
