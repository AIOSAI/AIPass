# =================== AIPass ====================
# Name: test_identity.py
# Description: Tests for the per-branch identity handler
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-04-11
# =============================================

"""Tests for per-branch identity handler (DPLAN-0121 Phase 5).

Bypass entries for architecture and encapsulation are in .seedgo/bypass.json.
"""

import json
import pytest
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.email.identity import (
    create_identity,
    read_identity,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.identity.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- create_identity() tests --------------------------------


def test_create_identity_writes_file(tmp_path):
    """create_identity writes identity.json with correct fields."""
    ok = create_identity(tmp_path, "devpulse", "AIPass")
    assert ok is True

    identity_file = tmp_path / ".ai_mail.local" / "identity.json"
    assert identity_file.exists()

    with open(identity_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["branch"] == "devpulse"
    assert data["project"] == "AIPass"
    assert data["inbox"] == str(tmp_path / ".ai_mail.local" / "inbox.json")


def test_create_identity_lowercases_name(tmp_path):
    """create_identity stores branch name in lowercase."""
    create_identity(tmp_path, "DEVPULSE", "AIPass")
    identity_file = tmp_path / ".ai_mail.local" / "identity.json"
    with open(identity_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["branch"] == "devpulse"


def test_create_identity_creates_parent_dirs(tmp_path):
    """create_identity creates .ai_mail.local/ if it does not exist."""
    branch_path = tmp_path / "nested" / "branch"
    # Directory does not exist yet
    assert not branch_path.exists()

    ok = create_identity(branch_path, "newbranch", "AIPass")
    assert ok is True
    assert (branch_path / ".ai_mail.local" / "identity.json").exists()


def test_create_identity_overwrites_existing(tmp_path):
    """create_identity overwrites an existing identity.json."""
    create_identity(tmp_path, "alpha", "OldProject")
    create_identity(tmp_path, "alpha", "NewProject")

    identity_file = tmp_path / ".ai_mail.local" / "identity.json"
    with open(identity_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["project"] == "NewProject"


# ---- read_identity() tests ----------------------------------


def test_read_identity_reads_back(tmp_path):
    """read_identity returns the dict written by create_identity."""
    create_identity(tmp_path, "devpulse", "AIPass")
    result = read_identity(tmp_path)

    assert result is not None
    assert result["branch"] == "devpulse"
    assert result["project"] == "AIPass"
    assert "inbox" in result


def test_read_identity_missing_file(tmp_path):
    """read_identity returns None when identity.json does not exist."""
    result = read_identity(tmp_path)
    assert result is None


def test_read_identity_corrupted_json(tmp_path):
    """read_identity returns None when identity.json is invalid JSON."""
    mail_dir = tmp_path / ".ai_mail.local"
    mail_dir.mkdir(parents=True)
    (mail_dir / "identity.json").write_text("not json", encoding="utf-8")

    result = read_identity(tmp_path)
    assert result is None
