# =================== AIPass ====================
# Name: test_daemon.py
# Description: Tests for dispatch daemon handler
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for dispatch daemon handler -- config loading, state management, inbox scanning."""

import json
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch

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

from aipass.ai_mail.apps.handlers.dispatch.daemon import (  # noqa: E402
    _has_test_token,
    _auto_ack_test_email,
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

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon._auto_ack_test_email", return_value=True) as mock_ack:
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

    with patch("aipass.ai_mail.apps.handlers.dispatch.daemon._auto_ack_test_email") as mock_ack:
        count = scan_and_ack_test_emails(branch_path, "@testbranch")

    assert count == 0
    mock_ack.assert_not_called()


def test_scan_and_ack_test_emails_no_inbox(tmp_path):
    """Missing inbox returns 0."""
    branch_path = tmp_path / "testbranch"
    branch_path.mkdir()
    count = scan_and_ack_test_emails(branch_path, "@testbranch")
    assert count == 0
