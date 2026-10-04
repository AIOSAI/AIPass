# =================== AIPass ====================
# Name: test_daemon.py
# Description: Tests for dispatch daemon handler
# Version: 1.0.2
# Created: 2026-03-29
# Modified: 2026-10-04
# =============================================

"""Tests for apps/handlers/dispatch/daemon.py -- config loading, state management, inbox scanning."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — cold_start_prompt/wake_prompt's exact text; only presence is asserted

import json
import os
import sys
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
import aipass.ai_mail.apps.handlers.dispatch.pid_lock as pid_lock_mod
from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    load_config,
    load_daemon_state,
    save_daemon_state,
    is_kill_switch_active,
    get_registered_branches,
    check_inbox_for_dispatch,
    is_protected_branch,
    check_lock,
    acquire_lock,
    poll_cycle,
    is_branch_occupied,
    spawn_agent,
    run_daemon,
)
from aipass.ai_mail.apps.handlers.dispatch.test_token import (
    has_test_token as _has_test_token,
    auto_ack_test_email as _auto_ack_test_email,
    scan_and_ack_test_emails,
    TEST_TOKEN,
)
from aipass.ai_mail.apps.handlers.dispatch.wake import JsonUnreadable


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


# Read and written through the daemon state file's public load and save, not
# called directly (ai_mail, leg 14).


def _state_read_from(monkeypatch, state_file):
    """load_daemon_state() with its state file at `state_file`."""
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", state_file)
    return daemon_mod.load_daemon_state()


def _state_saved_to(monkeypatch, state_file, state) -> dict:
    """save_daemon_state(state) into `state_file`; the file as written, its stamp set aside."""
    monkeypatch.setattr(daemon_mod, "DAEMON_STATE_FILE", state_file)
    daemon_mod.save_daemon_state(state)
    written = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(written) - set(state) == set(), "save writes exactly the state it was handed"
    written.pop("last_updated")
    return written


def test_read_json_valid_file(tmp_path, monkeypatch):
    """Valid JSON file returns parsed dict."""
    target = tmp_path / "data.json"
    stored = {"daily_counts": {"@flow": 2}, "session_cycles": {}, "date": str(date.today())}
    target.write_text(json.dumps(stored), encoding="utf-8")

    result = _state_read_from(monkeypatch, target)

    assert result == stored


def test_read_json_missing_file(tmp_path, monkeypatch):
    """Nonexistent file returns None: the state starts empty."""
    result = _state_read_from(monkeypatch, tmp_path / "does_not_exist.json")

    assert result == {"daily_counts": {}, "session_cycles": {}, "date": str(date.today())}


def test_read_json_invalid_json(tmp_path, monkeypatch):
    """Corrupt JSON raises JsonUnreadable, distinct from a missing file (ai_mail, leg 13)."""
    target = tmp_path / "bad.json"
    target.write_text("{not valid json!!!", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        _state_read_from(monkeypatch, target)


def test_read_json_empty_file(tmp_path, monkeypatch):
    """An empty file is unreadable too, not absent (ai_mail, leg 13)."""
    target = tmp_path / "empty.json"
    target.write_text("", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        _state_read_from(monkeypatch, target)


# ---- _write_json tests ----------------------------------------


def test_write_json_creates_file(tmp_path, monkeypatch):
    """Writing data creates the file with correct content."""
    target = tmp_path / "output.json"

    written = _state_saved_to(monkeypatch, target, {"branches": ["@flow", "@backup"]})

    assert written == {"branches": ["@flow", "@backup"]}


def test_write_json_creates_parent_dirs(tmp_path, monkeypatch):
    """Writing to a nested path creates intermediate directories."""
    target = tmp_path / "deep" / "nested" / "file.json"

    written = _state_saved_to(monkeypatch, target, {"ok": True})

    assert written == {"ok": True}


def test_write_json_unicode(tmp_path, monkeypatch):
    """Unicode content is preserved (ensure_ascii=False)."""
    target = tmp_path / "unicode.json"
    data = {"message": "Hello from branch \u2014 done"}

    _state_saved_to(monkeypatch, target, data)

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
        "kill_switch_path": str(tmp_path / "test_pause"),
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
    assert result["kill_switch_path"] == str(tmp_path / "test_pause")


def test_load_config_corrupt_json_refuses(tmp_path):
    """A corrupt safety config raises, never the defaults (ai_mail, leg 13).

    The defaults are the less safe side: autonomous_branches [] means every
    branch is autonomous, and the kill switch path is the default one.
    """
    config_file = tmp_path / "safety_config.json"
    config_file.write_text("{{broken", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        load_config()


def test_load_daemon_state_corrupt_refuses(tmp_path):
    """A corrupt state file raises: an empty state would reset today's dispatch counts (ai_mail, leg 13)."""
    (tmp_path / "daemon_state.json").write_text("{{broken", encoding="utf-8")

    with pytest.raises(JsonUnreadable):
        load_daemon_state()


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


def test_kill_switch_uses_default_path_when_key_missing(tmp_path, monkeypatch):
    """With no kill_switch_path key it consults <repo root>/.aipass/autonomous_pause.

    The assertion here was ``isinstance(result, bool)`` — true of every possible
    implementation, including one that ignored the default path entirely and
    returned False forever. It was also a fact about the AUTHOR'S MACHINE: the
    real repo root was consulted, so the answer depended on whether a pause file
    happened to exist. The default is aimed at tmp_path now, which makes both
    answers observable and the result the same on any machine.
    """
    monkeypatch.setattr(daemon_mod, "_REPO_ROOT", tmp_path)
    default_path = tmp_path / ".aipass" / "autonomous_pause"

    assert is_kill_switch_active({}) is False

    default_path.parent.mkdir(parents=True)
    default_path.touch()

    assert is_kill_switch_active({}) is True


# ---- get_registered_branches tests -----------------------------


def test_get_registered_branches_valid(tmp_path):
    """Returns branch list from registry file."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    flow_path = str(tmp_path / "flow")
    backup_path = str(tmp_path / "backup")
    branches = [
        {"email": "@flow", "path": flow_path},
        {"email": "@backup", "path": backup_path},
    ]
    registry.write_text(json.dumps({"branches": branches}), encoding="utf-8")

    result = get_registered_branches()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["email"] == "@flow"
    assert result[0]["path"] == flow_path
    assert result[1]["email"] == "@backup"
    assert result[1]["path"] == backup_path


def test_get_registered_branches_no_file():
    """Missing registry returns empty list."""
    result = get_registered_branches()

    assert result == []
    assert isinstance(result, list)


def test_get_registered_branches_unreadable_polls_none(tmp_path):
    """An unreadable registry answers no branches: nothing is polled, nothing spawned (ai_mail, leg 13)."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")

    assert get_registered_branches() == []


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


def test_an_unreadable_inbox_yields_no_dispatch_and_no_ack(tmp_path):
    """An unreadable inbox spawns nothing and acks nothing; neither scan raises (ai_mail, leg 13)."""
    inbox = tmp_path / ".ai_mail.local" / "inbox.json"
    inbox.parent.mkdir(parents=True)
    inbox.write_text("{not json", encoding="utf-8")

    assert check_inbox_for_dispatch(tmp_path) is None
    assert scan_and_ack_test_emails(tmp_path, "@testbranch") == 0


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
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

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
    (ai_mail_local / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

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
def test_the_registered_stop_signal_sets_shutdown(monkeypatch, signame):
    """The handler the daemon registers for a stop signal sets SHUTDOWN.

    Reached through the handler table the import fills, not by name, and
    called directly: no signal is sent to the test process (ai_mail, leg 14).
    """
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", False)
    signum = getattr(daemon_mod.signal, signame)
    handler = daemon_mod.signal.getsignal(signum)
    assert callable(handler)

    handler(signum, None)

    assert daemon_mod.SHUTDOWN is True


# ---- check_lock tests ------------------------------------------


def test_check_lock_no_file(tmp_path):
    """No lock file returns None."""
    result = check_lock(tmp_path)

    assert result is None


def test_check_lock_alive_pid(tmp_path, monkeypatch):
    """Lock with alive PID returns lock data."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=True)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is not None
    assert result["pid"] == 99999
    alive.assert_called_once_with(99999)


def test_check_lock_dead_pid(tmp_path, monkeypatch):
    """Lock with dead PID is cleaned up."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_stale_over_10min_removed(tmp_path, monkeypatch):
    """Stale lock older than 10 minutes with dead PID is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    old_time = (datetime.now() - timedelta(minutes=15)).isoformat()
    lock_data = {"pid": 99999, "timestamp": old_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_stale_under_10min_dead_pid_removed(tmp_path, monkeypatch):
    """Stale lock under 10 minutes with dead PID is also removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
    lock_data = {"pid": 99999, "timestamp": recent_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_fresh_corrupt_json_is_held(tmp_path):
    """A corrupt lock younger than the grace is a writer mid-write: held, not removed (ai_mail, leg 13)."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json!!", encoding="utf-8")

    result = check_lock(tmp_path)

    assert result is not None
    assert lock_file.exists()


def test_check_lock_old_corrupt_json_removed(tmp_path):
    """A corrupt lock an hour old is a crashed writer's leftover: removed, None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json!!", encoding="utf-8")
    hour_ago = lock_file.stat().st_mtime - 3600
    os.utime(lock_file, (hour_ago, hour_ago))

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_zombie_holder_is_dead(tmp_path, monkeypatch):
    """A lock held by a linux zombie is reclaimed: the wake's liveness rule (ai_mail, leg 13)."""
    monkeypatch.setattr(sys, "platform", "linux")
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(pid_lock_mod, "_is_zombie_linux", lambda pid: pid == 4242)

    result = check_lock(tmp_path)

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

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


# ---- acquire_lock tests -----------------------------------------


def test_acquire_lock_success(tmp_path):
    """New lock file is created atomically."""
    acquired, msg = acquire_lock(tmp_path, 12345)

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

    acquired, msg = acquire_lock(tmp_path, 22222)

    assert acquired is False
    assert "already exists" in msg


def test_acquire_lock_oserror(tmp_path):
    """OSError during lock creation returns (False, message)."""
    with patch("os.open", side_effect=OSError("Permission denied")):
        acquired, msg = acquire_lock(tmp_path, 12345)

    assert acquired is False
    assert "Lock failed" in msg


# ---- _write_pid_file tests --------------------------------------


def _start_daemon(tmp_path, monkeypatch, pid_file, while_running=None):
    """Run run_daemon with SHUTDOWN set, so it stops right after start-up.

    Returns what the pid file held when config loaded; [] means the daemon
    never started. while_running stands in for whatever touches the pid file
    during the run (ai_mail, leg 14).
    """
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)
    pid_at_start = []

    def config_after_pid():
        pid_at_start.append(pid_file.read_text(encoding="utf-8").strip())
        if while_running is not None:
            while_running()
        return {"poll_interval_seconds": 0, "kill_switch_path": str(tmp_path / "pause"), "autonomous_branches": []}

    monkeypatch.setattr(daemon_mod, "load_config", config_after_pid)
    run_daemon()
    return pid_at_start


def test_write_pid_file_no_existing(tmp_path, monkeypatch):
    """No existing PID file: the daemon writes its own PID and starts."""
    pid_file = tmp_path / "daemon.pid"

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


def test_write_pid_file_existing_alive_pid(tmp_path, monkeypatch):
    """Existing PID file with alive process: the daemon does not start."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []


def test_write_pid_file_existing_dead_pid(tmp_path, monkeypatch):
    """Existing PID file with dead process: the daemon takes over and starts."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")

    def _kill_stub(pid, sig):
        if pid == 999999:
            raise ProcessLookupError("No such process")

    monkeypatch.setattr(os, "kill", _kill_stub)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


def test_write_pid_file_existing_permission_error(tmp_path, monkeypatch):
    """Existing PID file with PermissionError on kill: the daemon does not start."""
    monkeypatch.setattr("sys.platform", "linux")
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("888888", encoding="utf-8")

    def _raise_permission(pid, sig):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "kill", _raise_permission)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []


def test_write_pid_file_corrupt_pid_file(tmp_path, monkeypatch):
    """Corrupt PID file is overwritten and the daemon starts."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


# ---- _write_pid_file: the Windows delete-pending denial -------------
#
# Windows answers an exclusive create against a pid file another process is
# still releasing (delete pending) with PermissionError, not FileExistsError.
# POSIX unlinks the name at once, so no Linux or macOS run can produce it:
# every case below MANUFACTURES the Windows answer by scripting os.open.

_REAL_OS_OPEN = os.open


@pytest.fixture
def fake_clock(monkeypatch):
    """time.monotonic that moves only when the code sleeps - no real waiting."""
    clock = {"now": 1000.0, "sleeps": 0}

    def fake_sleep(seconds):
        clock["now"] += seconds
        clock["sleeps"] += 1

    monkeypatch.setattr(daemon_mod.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(daemon_mod.time, "sleep", fake_sleep)
    return clock


def _denial(path):
    """The Windows delete-pending answer, as Python raises it (EACCES)."""
    return PermissionError(13, "Access is denied", str(path))


def _scripted_pid_open(pid_file, script, calls):
    """os.open that answers the pid file from *script*, then for real.

    A script step is an exception to raise, a callable run before the real
    create (it may raise), or None for the real create. Other paths open for real.
    """

    def fake_open(path, flags, mode=0o777, *args, **kwargs):
        if str(path) != str(pid_file):
            return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)
        calls.append(flags)
        step = script.pop(0) if script else None
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            step()
        return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)

    return fake_open


def test_write_pid_file_first_create_denied_once_then_lands(tmp_path, monkeypatch, fake_clock):
    """The first create, denied once (a previous daemon's file still releasing), is polled and lands."""
    pid_file = tmp_path / "daemon.pid"
    calls = []
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [_denial(pid_file)], calls))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert len(calls) == 2
    assert fake_clock["sleeps"] == 1


def test_write_pid_file_retake_denied_once_then_lands(tmp_path, monkeypatch, fake_clock):
    """The create right after unlinking a stale pid file - our own delete still pending - is polled and lands."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    alive = MagicMock(return_value=False)
    monkeypatch.setattr(daemon_mod, "_pid_alive", alive)
    calls = []
    # real (exists) -> denied (the unlink we just made is still pending) -> real
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [None, _denial(pid_file)], calls))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert len(calls) == 3
    alive.assert_called_once_with(999999)


def test_write_pid_file_stale_unlink_denied_create_waits_it_out(tmp_path, monkeypatch, fake_clock):
    """Unlinking a stale pid file someone else already deleted is denied too; the create waits the release out."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    alive = MagicMock(return_value=False)
    monkeypatch.setattr(daemon_mod, "_pid_alive", alive)
    real_unlink = daemon_mod.Path.unlink
    denied = []

    def unlink_denied(self, missing_ok=False):
        # Denied once: the stale file's release. The stop's own unlink lands.
        if self == pid_file and not denied:
            denied.append(self)
            raise _denial(self)
        return real_unlink(self, missing_ok=missing_ok)

    def pending_delete_completes():
        real_unlink(pid_file)
        raise _denial(pid_file)

    monkeypatch.setattr(daemon_mod.Path, "unlink", unlink_denied)
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [None, pending_delete_completes], []))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert denied == [pid_file]
    alive.assert_called_once_with(999999)


def test_stale_unlink_failing_otherwise_than_denied_escapes(tmp_path, monkeypatch):
    """Only a DENIED unlink of the stale pid file is left to the create.

    Any other failure escapes run_daemon as itself: caught, the create would
    meet the stale file still standing and report "another daemon raced us",
    a race that never happened. The error is this stand-in's own. Green on the
    tree from its first run; its proof is the mutant that widens the catch to
    OSError (ai_mail, leg 15).
    """
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "_pid_alive", MagicMock(return_value=False))
    stuck = OSError(30, "Read-only file system", str(pid_file))
    real_unlink = daemon_mod.Path.unlink

    def unlink_fails(self, missing_ok=False):
        if self == pid_file:
            raise stuck
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(daemon_mod.Path, "unlink", unlink_fails)

    with pytest.raises(OSError) as raised:
        _start_daemon(tmp_path, monkeypatch, pid_file)
    assert raised.value is stuck


def test_write_pid_file_denial_that_never_clears_raises_at_budget(tmp_path, monkeypatch, fake_clock):
    """A denial that outlasts the wait raises - naming the wait, the denial as cause - and never loops forever."""
    pid_file = tmp_path / "daemon.pid"
    denial = _denial(pid_file)
    attempts = []

    def always_denied(path, flags, mode=0o777, *args, **kwargs):
        if str(path) != str(pid_file):
            return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)
        attempts.append(path)
        if len(attempts) > 10_000:
            raise AssertionError("retried past any budget - the wait is not bounded")
        raise denial

    monkeypatch.setattr(daemon_mod.os, "open", always_denied)
    start = fake_clock["now"]

    with pytest.raises(PermissionError) as excinfo:
        _start_daemon(tmp_path, monkeypatch, pid_file)

    assert excinfo.value is not denial
    assert excinfo.value.__cause__ is denial
    assert f"{daemon_mod.PID_DENIED_WAIT_SECONDS}s" in str(excinfo.value)
    assert fake_clock["now"] - start >= daemon_mod.PID_DENIED_WAIT_SECONDS
    assert not pid_file.exists()


def test_run_daemon_starts_after_a_denied_pid_create(tmp_path, monkeypatch, fake_clock):
    """The daemon starts after one delete-pending denial: the pid file is on disk when config loads."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [_denial(pid_file)], []))
    pid_at_start = []

    def config_after_pid():
        pid_at_start.append(pid_file.read_text(encoding="utf-8").strip())
        return {"poll_interval_seconds": 0, "kill_switch_path": str(tmp_path / "pause"), "autonomous_branches": []}

    monkeypatch.setattr(daemon_mod, "load_config", config_after_pid)

    run_daemon()

    assert pid_at_start == [str(os.getpid())]
    assert not pid_file.exists()  # a clean stop removes its own pid file


# ---- _remove_pid_file tests ------------------------------------


def test_remove_pid_file_matching_pid(tmp_path, monkeypatch):
    """A clean stop removes the daemon's own PID file."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file)

    assert not pid_file.exists()


def test_remove_pid_file_different_pid(tmp_path, monkeypatch):
    """A PID file another daemon took over during the run is left alone at stop."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.write_text("999999", encoding="utf-8"))

    assert pid_file.read_text(encoding="utf-8").strip() == "999999"


def test_remove_pid_file_missing(tmp_path, monkeypatch):
    """A PID file gone during the run does not break the stop."""
    pid_file = tmp_path / "daemon.pid"
    moved = tmp_path / "moved.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.rename(moved))

    assert not pid_file.exists()
    assert moved.exists()


def test_remove_pid_file_corrupt(tmp_path, monkeypatch):
    """A PID file corrupted during the run is removed at stop."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.write_text("not-a-number", encoding="utf-8"))

    assert not pid_file.exists()


# ---- is_branch_occupied tests ------------------------------------
# The daemon has used pid_lock's is_branch_occupied and its process readers since
# leg 12; their own tests, the darwin lanes among them, live in test_wake.py
# (ai_mail, leg 12; todo 39).


def test_is_branch_occupied_no_claude_processes(tmp_path):
    """Returns False when pgrep finds no claude processes."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        return_value=mock_result,
    ):
        result = is_branch_occupied(tmp_path)

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
        result = is_branch_occupied(tmp_path)

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
            "aipass.ai_mail.apps.handlers.dispatch.pid_lock._read_session_type",
            return_value="interactive",
        ),
    ):
        result = is_branch_occupied(tmp_path)

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
            "aipass.ai_mail.apps.handlers.dispatch.pid_lock._read_session_type",
            return_value="daemon",
        ),
    ):
        result = is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_pgrep_failure(tmp_path):
    """Returns False when pgrep cannot run.

    Since leg 12 this is wake's body, which catches what subprocess.run raises
    for a missing or failing tool (OSError, SubprocessError) and nothing wider;
    the daemon's copy caught every Exception (ai_mail, leg 12).
    """
    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        side_effect=OSError("pgrep unavailable"),
    ):
        result = is_branch_occupied(tmp_path)

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


# ---- _write_pid_file atomic tests (DPLAN-0159 S5) ----------------


def test_write_pid_file_atomic_race_second_loses(tmp_path, monkeypatch):
    """Stale PID file, but another daemon re-creates it first: the retry's O_EXCL loses and returns False.

    Mutant: the retry's `return False` after "raced us" turned to `return True` - two daemons start.
    """
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: pid != 999999)
    create_calls = []

    def _create_always_loses():
        create_calls.append(1)
        return False

    monkeypatch.setattr(daemon_mod, "_create_pid_file", _create_always_loses)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []
    assert len(create_calls) == 2
