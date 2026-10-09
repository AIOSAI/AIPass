# =================== AIPass ====================
# Name: test_daemon_inbox.py
# Description: Tests for the dispatch daemon's registry read and inbox scan for dispatch mail
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/dispatch/daemon.py -- the registered branches and the inbox scan for a dispatch to run."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — scan_and_ack_test_emails()'s acks, read here once: tests/test_daemon_guards.py

import json
import pytest
from datetime import datetime, timedelta

from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    get_registered_branches,
    check_inbox_for_dispatch,
)
from aipass.ai_mail.apps.handlers.dispatch.test_token import scan_and_ack_test_emails

pytestmark = pytest.mark.usefixtures("daemon_json_silenced", "daemon_paths_in_tmp")


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
