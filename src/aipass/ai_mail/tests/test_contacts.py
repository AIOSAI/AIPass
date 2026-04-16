# =================== AIPass ====================
# Name: test_contacts.py
# Description: Tests for the contacts address book handler
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-04-11
# =============================================

"""Tests for contacts address book handler (DPLAN-0121 Phase 5)."""

import json
import pytest
from unittest.mock import patch

import aipass.ai_mail.apps.handlers.email.contacts as contacts_mod
from aipass.ai_mail.apps.handlers.email.contacts import (
    get_contact,
    register_contact,
    all_contacts,
    _load_contacts,
)


# ---- Fixtures ------------------------------------------------

@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.contacts.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture
def isolated_contacts(tmp_path, monkeypatch):
    """Point CONTACTS_FILE to a tmp_path location for test isolation."""
    contacts_file = tmp_path / ".ai_mail.local" / "contacts.json"
    monkeypatch.setattr(contacts_mod, "CONTACTS_FILE", contacts_file)
    return contacts_file


# ---- _load_contacts() tests --------------------------------

def test_load_contacts_missing_file(isolated_contacts):
    """Missing contacts.json returns default empty structure."""
    result = _load_contacts()
    assert result == {"contacts": {}}


def test_load_contacts_invalid_json(isolated_contacts):
    """Corrupted contacts.json returns default empty structure."""
    isolated_contacts.parent.mkdir(parents=True, exist_ok=True)
    isolated_contacts.write_text("not json", encoding="utf-8")
    result = _load_contacts()
    assert result == {"contacts": {}}


def test_load_contacts_missing_key(isolated_contacts):
    """contacts.json without 'contacts' key returns default empty structure."""
    isolated_contacts.parent.mkdir(parents=True, exist_ok=True)
    isolated_contacts.write_text(json.dumps({"other": {}}), encoding="utf-8")
    result = _load_contacts()
    assert result == {"contacts": {}}


# ---- get_contact() tests -----------------------------------

def test_get_contact_empty(isolated_contacts):
    """get_contact with no contacts returns None."""
    result = get_contact("devpulse")
    assert result is None


def test_get_contact_strips_at_sign(isolated_contacts):
    """get_contact strips leading @ before lookup."""
    register_contact("devpulse", "AIPass", "/some/inbox.json")
    result = get_contact("@devpulse")
    assert result is not None
    assert result["inbox"] == "/some/inbox.json"


def test_get_contact_case_insensitive(isolated_contacts):
    """get_contact normalises to lowercase for lookup."""
    register_contact("devpulse", "AIPass", "/some/inbox.json")
    result = get_contact("DEVPULSE")
    assert result is not None


def test_get_contact_not_found(isolated_contacts):
    """get_contact returns None for unknown branch."""
    register_contact("devpulse", "AIPass", "/some/inbox.json")
    result = get_contact("unknown")
    assert result is None


# ---- register_contact() tests ------------------------------

def test_register_contact_creates_entry(isolated_contacts):
    """register_contact writes a new entry with correct fields."""
    ok = register_contact("devpulse", "AIPass", "/path/to/inbox.json")
    assert ok is True

    result = get_contact("devpulse")
    assert result is not None
    assert result["project"] == "AIPass"
    assert result["inbox"] == "/path/to/inbox.json"
    assert "last_seen" in result


def test_register_contact_updates_existing(isolated_contacts):
    """register_contact updates last_seen on second registration."""
    register_contact("devpulse", "AIPass", "/path/to/inbox.json")
    first = get_contact("devpulse")
    assert first is not None
    assert "last_seen" in first

    # Re-register with new path
    register_contact("devpulse", "AIPass", "/new/path/inbox.json")
    updated = get_contact("devpulse")
    assert updated is not None
    assert updated["inbox"] == "/new/path/inbox.json"
    # last_seen should be present (may or may not change within same second)
    assert "last_seen" in updated


def test_register_contact_strips_at_sign(isolated_contacts):
    """register_contact strips leading @ from branch name."""
    ok = register_contact("@devpulse", "AIPass", "/inbox.json")
    assert ok is True
    result = get_contact("devpulse")
    assert result is not None


def test_register_contact_persists_to_disk(isolated_contacts):
    """register_contact writes JSON to disk that can be read back."""
    register_contact("testbranch", "TestProject", "/test/inbox.json")

    assert isolated_contacts.exists()
    with open(isolated_contacts, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "contacts" in data
    assert "testbranch" in data["contacts"]
    assert data["contacts"]["testbranch"]["project"] == "TestProject"


# ---- all_contacts() tests ----------------------------------

def test_all_contacts_empty(isolated_contacts):
    """all_contacts returns empty dict when no contacts registered."""
    result = all_contacts()
    assert result == {}


def test_all_contacts_returns_all(isolated_contacts):
    """all_contacts returns all registered contacts."""
    register_contact("alpha", "AIPass", "/alpha/inbox.json")
    register_contact("beta", "AIPass", "/beta/inbox.json")

    result = all_contacts()
    assert "alpha" in result
    assert "beta" in result
    assert len(result) == 2
