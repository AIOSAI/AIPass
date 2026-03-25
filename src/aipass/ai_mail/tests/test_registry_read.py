# =================== AIPass ====================
# Name: test_registry_read.py
# Description: Tests for registry read handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for registry read handler -- branch listing and email derivation."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

import aipass.ai_mail.apps.handlers.registry.read as read_mod
from aipass.ai_mail.apps.handlers.registry.read import (
    _derive_email_from_branch_name,
    get_all_branches,
    get_branch_by_email,
)


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.registry.read.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture
def registry_file(tmp_path, monkeypatch):
    reg_file = tmp_path / "AIPASS_REGISTRY.json"
    monkeypatch.setattr(read_mod, "BRANCH_REGISTRY_PATH", reg_file)
    return reg_file


SAMPLE_REGISTRY = {
    "branches": [
        {"name": "DRONE", "path": "src/aipass/drone"},
        {"name": "AIPASS.admin", "path": "src/aipass/admin"},
        {"name": "BACKUP-SYSTEM", "path": "src/aipass/backup"},
    ]
}


# --- _derive_email_from_branch_name() tests ---------------------------


def test_derive_email_dotted():
    """Dotted name: 'AIPASS.admin' takes part after dot."""
    assert _derive_email_from_branch_name("AIPASS.admin") == "@admin"


def test_derive_email_space():
    """Space-separated name: 'AIPASS Workshop' takes first word."""
    assert _derive_email_from_branch_name("AIPASS Workshop") == "@aipass"


def test_derive_email_aipass_hyphen():
    """AIPASS-prefixed hyphen: 'AIPASS-HELP' takes second part."""
    assert _derive_email_from_branch_name("AIPASS-HELP") == "@help"


def test_derive_email_regular_hyphen():
    """Non-AIPASS hyphen: 'BACKUP-SYSTEM' takes first part."""
    assert _derive_email_from_branch_name("BACKUP-SYSTEM") == "@backup"


def test_derive_email_plain():
    """Plain name: 'DRONE' lowercases whole name."""
    assert _derive_email_from_branch_name("DRONE") == "@drone"


def test_derive_email_lowercase():
    """Mixed case plain name: 'Flow' lowercases."""
    assert _derive_email_from_branch_name("Flow") == "@flow"


# --- get_all_branches() tests ----------------------------------------


def test_get_all_branches_no_registry(tmp_path, monkeypatch):
    """Nonexistent registry file returns empty list."""
    nonexistent = tmp_path / "NO_SUCH_REGISTRY.json"
    monkeypatch.setattr(read_mod, "BRANCH_REGISTRY_PATH", nonexistent)
    result = get_all_branches()
    assert result == []


def test_get_all_branches_valid(registry_file):
    """Valid registry returns branch list with derived emails."""
    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    result = get_all_branches()
    assert isinstance(result, list)
    assert len(result) == 3
    # Verify exact email set -- no extras, no missing
    emails = {b["email"] for b in result}
    assert emails == {"@drone", "@admin", "@backup"}
    # Verify each entry has exactly the expected keys with correct values
    assert result[0] == {"name": "DRONE", "path": "src/aipass/drone", "email": "@drone"}
    assert result[1] == {"name": "AIPASS.admin", "path": "src/aipass/admin", "email": "@admin"}
    assert result[2] == {"name": "BACKUP-SYSTEM", "path": "src/aipass/backup", "email": "@backup"}
    for branch in result:
        assert set(branch.keys()) == {"name", "path", "email"}


def test_get_all_branches_empty_branches(registry_file):
    """Registry with empty branches list returns empty list."""
    registry_file.write_text(json.dumps({"branches": []}), encoding="utf-8")
    result = get_all_branches()
    assert result == []


def test_get_all_branches_skips_incomplete(registry_file):
    """Branch entries missing name or path are skipped."""
    data = {
        "branches": [
            {"name": "DRONE", "path": "src/aipass/drone"},
            {"name": "", "path": "src/aipass/ghost"},
            {"path": "src/aipass/no_name"},
            {"name": "ORPHAN"},
        ]
    }
    registry_file.write_text(json.dumps(data), encoding="utf-8")
    result = get_all_branches()
    assert len(result) == 1
    assert result[0] == {"name": "DRONE", "path": "src/aipass/drone", "email": "@drone"}


# --- get_branch_by_email() tests -------------------------------------


def test_get_branch_by_email_found(registry_file):
    """Existing email returns the correct branch dict."""
    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    result = get_branch_by_email("@admin")
    assert isinstance(result, dict)
    assert result == {"name": "AIPASS.admin", "path": "src/aipass/admin", "email": "@admin"}


def test_get_branch_by_email_not_found(registry_file):
    """Unknown email returns None."""
    registry_file.write_text(json.dumps(SAMPLE_REGISTRY), encoding="utf-8")
    result = get_branch_by_email("@nonexistent")
    assert result is None
