# =================== AIPass ====================
# Name: test_registry_read.py
# Description: Tests for registry read handler
# Version: 1.0.2
# Created: 2026-03-24
# Modified: 2026-11-08
# =============================================

"""Tests for apps/handlers/registry/read.py."""

# Branch listing and email derivation.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — get_all_branches()'s broad except Exception fallback on a malformed registry file

import json
import pytest
from unittest.mock import patch

import aipass.ai_mail.apps.handlers.registry.read as read_mod
from aipass.ai_mail.apps.handlers.registry.read import (
    get_all_branches,
    get_branch_by_email,
    get_caller_project_branches,
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
        {"name": "BACKUP", "path": "src/aipass/backup"},
    ]
}


# --- the email derived for a registry row with no email field ---------


def _derived(registry_file, name):
    """The email get_all_branches() derives for a row named `name` with no email field."""
    registry_file.write_text(json.dumps({"branches": [{"name": name, "path": "src/x"}]}), encoding="utf-8")
    return get_all_branches()[0]["email"]


def test_derive_email_dotted(registry_file):
    """Dotted name: 'AIPASS.admin' takes part after dot."""
    assert _derived(registry_file, "AIPASS.admin") == "@admin"


def test_derive_email_space(registry_file):
    """Space-separated name: 'AIPASS Workshop' takes first word."""
    assert _derived(registry_file, "AIPASS Workshop") == "@aipass"


def test_derive_email_aipass_hyphen(registry_file):
    """AIPASS-prefixed hyphen: 'AIPASS-HELP' takes second part."""
    assert _derived(registry_file, "AIPASS-HELP") == "@help"


def test_derive_email_regular_hyphen(registry_file):
    """Non-AIPASS hyphen: 'DATA-LAKE' takes first part."""
    assert _derived(registry_file, "DATA-LAKE") == "@data"


def test_derive_email_plain(registry_file):
    """Plain name: 'DRONE' lowercases whole name."""
    assert _derived(registry_file, "DRONE") == "@drone"


def test_derive_email_lowercase(registry_file):
    """Mixed case plain name: 'Flow' lowercases."""
    assert _derived(registry_file, "Flow") == "@flow"


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
    assert result[2] == {"name": "BACKUP", "path": "src/aipass/backup", "email": "@backup"}
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


# --- get_caller_project_branches() tests -----------------------------


class TestGetCallerProjectBranches:
    """Tests for get_caller_project_branches()."""

    def test_finds_registry_in_cwd(self, tmp_path):
        """Returns email->path mapping from a *_REGISTRY.json in caller_cwd."""
        branch_path = tmp_path / "src" / "strategy"
        branch_path.mkdir(parents=True)
        registry = {"branches": [{"name": "STRATEGY", "email": "@strategy", "path": str(branch_path)}]}
        (tmp_path / "VERA_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        result = get_caller_project_branches(str(tmp_path))
        assert result == {"@strategy": str(branch_path)}

    def test_finds_registry_in_parent(self, tmp_path):
        """Walks up from caller_cwd to find registry in parent."""
        branch_path = tmp_path / "src" / "strategy"
        branch_path.mkdir(parents=True)
        registry = {"branches": [{"name": "STRATEGY", "email": "@strategy", "path": str(branch_path)}]}
        (tmp_path / "VERA_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        subdir = tmp_path / "src" / "strategy" / "apps"
        subdir.mkdir(parents=True)
        result = get_caller_project_branches(str(subdir))
        assert result == {"@strategy": str(branch_path)}

    def test_resolves_relative_paths(self, tmp_path):
        """Resolves relative paths in registry relative to the registry file."""
        branch_path = tmp_path / "src" / "strategy"
        branch_path.mkdir(parents=True)
        registry = {"branches": [{"name": "STRATEGY", "email": "@strategy", "path": "src/strategy"}]}
        (tmp_path / "VERA_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        result = get_caller_project_branches(str(tmp_path))
        assert result == {"@strategy": str(branch_path)}

    def test_handles_dict_format(self, tmp_path):
        """Handles dict-format branches (AIPass format)."""
        branch_path = tmp_path / "src" / "quality"
        branch_path.mkdir(parents=True)
        registry = {"branches": {"quality": {"email": "@quality", "path": str(branch_path)}}}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        result = get_caller_project_branches(str(tmp_path))
        assert result == {"@quality": str(branch_path)}

    def test_returns_empty_when_no_registry(self, tmp_path):
        """Returns empty dict when no *_REGISTRY.json exists."""
        result = get_caller_project_branches(str(tmp_path))
        assert result == {}

    def test_skips_aipass_registry_name(self, tmp_path):
        """Also works with AIPASS_REGISTRY.json -- doesn't skip it (delivery uses all)."""
        branch_path = tmp_path / "branch"
        branch_path.mkdir()
        registry = {"branches": [{"name": "TEST", "email": "@test", "path": str(branch_path)}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        result = get_caller_project_branches(str(tmp_path))
        assert "@test" in result


# --- get_fleet_branches(): every citizen through memory's door -------


def _door_rows(tmp_path):
    """A fleet as the door answers it: one core citizen, one resident, one external at a declared root."""
    return [
        {"name": "FLOW", "path": tmp_path / "aipass" / "flow", "email": "@flow", "residency": "core"},
        {"name": "BAUD", "path": tmp_path / "aipass" / "projects" / "baud", "email": "@baud", "residency": "resident"},
        {"name": "GROW", "path": tmp_path / "seed" / "grow", "email": "@grow", "residency": "external"},
    ]


def test_the_fleet_lists_core_residents_and_externals_with_absolute_string_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(read_mod, "fleet_branches", lambda **kw: _door_rows(tmp_path))

    rows = read_mod.get_fleet_branches()

    assert [(r["email"], r["residency"]) for r in rows] == [
        ("@flow", "core"),
        ("@baud", "resident"),
        ("@grow", "external"),
    ]
    assert rows[2]["path"] == str(tmp_path / "seed" / "grow")


def test_a_namesake_of_an_earlier_address_is_dropped_so_core_keeps_it(tmp_path, monkeypatch):
    rows = _door_rows(tmp_path) + [
        {"name": "FLOW", "path": tmp_path / "seed" / "flow", "email": "@Flow", "residency": "external"}
    ]
    monkeypatch.setattr(read_mod, "fleet_branches", lambda **kw: rows)

    flows = [r for r in read_mod.get_fleet_branches() if r["email"].lower() == "@flow"]

    assert [r["path"] for r in flows] == [str(tmp_path / "aipass" / "flow")]


def test_the_door_is_read_once_per_cache_window(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(read_mod, "fleet_branches", lambda **kw: calls.append(kw) or _door_rows(tmp_path))

    read_mod.get_fleet_branches()
    read_mod.get_fleet_branches()
    assert calls == [{"name_from": "registry"}]

    monkeypatch.setattr(read_mod, "FLEET_CACHE_SECONDS", 0.0)
    read_mod.get_fleet_branches()
    assert len(calls) == 2
