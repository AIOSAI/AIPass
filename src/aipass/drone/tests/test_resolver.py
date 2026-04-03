"""Tests for branch resolution (@name -> path).

Covers resolve_branch(), list_branches(), branch_exists(), get_branch_info(),
normalize helpers, and handle_command() routing.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aipass.drone.apps.handlers.exceptions import BranchNotFoundError
from aipass.drone.apps.handlers.registry_handler import (
    reset_registry_path,
    set_registry_path,
)
from aipass.drone.apps.modules.resolver import (
    branch_exists,
    get_branch_info,
    handle_command,
    list_branches,
    normalize_branch_arg,
    normalize_branch_name,
    resolve_branch,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_registry(
    registry_path: Path,
    branches: List[Dict[str, Any]],
    *,
    metadata: Dict[str, Any] | None = None,
) -> Path:
    """Write a registry file with the given branches list."""
    registry = {
        "metadata": metadata or {"version": "1.0.0"},
        "branches": branches,
    }
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path


def _make_branch(
    name: str,
    path: str,
    *,
    status: str = "active",
    branch_type: str = "library",
    description: str = "",
) -> Dict[str, Any]:
    """Build a branch entry dict."""
    return {
        "name": name,
        "path": path,
        "profile": branch_type,
        "type": branch_type,
        "description": description or f"{name} branch",
        "email": f"@{name.lower()}",
        "status": status,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_dir(temp_test_dir: Path):
    """Set registry path for the duration of a test, then reset."""
    registry_path = temp_test_dir / "AIPASS_REGISTRY.json"
    set_registry_path(registry_path)
    yield temp_test_dir
    reset_registry_path()


@pytest.fixture
def populated_registry(registry_dir: Path) -> Path:
    """Create a registry with several branches of varying status/type."""
    branch_alpha = registry_dir / "alpha"
    branch_beta = registry_dir / "beta"
    branch_gamma = registry_dir / "gamma"

    registry_path = registry_dir / "AIPASS_REGISTRY.json"
    _write_registry(
        registry_path,
        [
            _make_branch("ALPHA", str(branch_alpha), status="active", branch_type="library"),
            _make_branch("BETA", str(branch_beta), status="active", branch_type="service"),
            _make_branch("GAMMA", str(branch_gamma), status="archived", branch_type="library"),
        ],
    )
    return registry_path


@pytest.fixture
def single_branch_registry(registry_dir: Path, temp_test_dir: Path) -> Path:
    """Registry with exactly one active branch — uses the conftest sample layout."""
    branch_path = temp_test_dir / "test_branch"
    registry_path = registry_dir / "AIPASS_REGISTRY.json"
    _write_registry(
        registry_path,
        [
            _make_branch("TEST_BRANCH", str(branch_path)),
        ],
    )
    return registry_path


@pytest.fixture
def empty_registry(registry_dir: Path) -> Path:
    """Registry with an empty branches list."""
    registry_path = registry_dir / "AIPASS_REGISTRY.json"
    _write_registry(registry_path, [])
    return registry_path


# ---------------------------------------------------------------------------
# normalize helpers
# ---------------------------------------------------------------------------

class TestNormalizeBranchName:
    def test_strips_at_prefix(self):
        assert normalize_branch_name("@FOO") == "FOO"

    def test_no_prefix_unchanged(self):
        assert normalize_branch_name("FOO") == "FOO"

    def test_empty_string(self):
        assert normalize_branch_name("") == ""

    def test_double_at_strips_one(self):
        assert normalize_branch_name("@@FOO") == "@FOO"


class TestNormalizeBranchArg:
    def test_strips_at_and_lowercases(self):
        assert normalize_branch_arg("@FOO") == "foo"

    def test_no_prefix_lowercases(self):
        assert normalize_branch_arg("FOO") == "foo"

    def test_multiple_at_stripped(self):
        # lstrip removes all leading '@' characters
        assert normalize_branch_arg("@@FOO") == "foo"


# ---------------------------------------------------------------------------
# resolve_branch
# ---------------------------------------------------------------------------

class TestResolveBranch:
    def test_resolve_with_at_prefix(self, populated_registry):
        path = resolve_branch("@ALPHA")
        assert Path(path).name == "alpha"

    def test_resolve_without_at_prefix_rejected(self, populated_registry):
        """Bare branch names without @ prefix are rejected."""
        with pytest.raises(BranchNotFoundError, match="must use @ prefix"):
            resolve_branch("ALPHA")

    def test_returns_absolute_path(self, populated_registry):
        path = resolve_branch("@ALPHA")
        assert Path(path).is_absolute()

    def test_case_insensitive_lookup(self, populated_registry):
        """Resolver lowercases the name, registry normalizes names to lower."""
        path_upper = resolve_branch("@ALPHA")
        path_lower = resolve_branch("@alpha")
        path_mixed = resolve_branch("@Alpha")
        assert path_upper == path_lower == path_mixed

    def test_invalid_branch_raises(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            resolve_branch("@NONEXISTENT")

    def test_invalid_branch_without_prefix_raises(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            resolve_branch("NONEXISTENT")

    def test_empty_name_raises(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            resolve_branch("")

    def test_at_only_raises(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            resolve_branch("@")

    def test_resolve_each_branch(self, populated_registry):
        """Every branch in the registry should resolve."""
        for name in ("ALPHA", "BETA", "GAMMA"):
            path = resolve_branch(f"@{name}")
            assert Path(path).name == name.lower()

    def test_empty_registry_raises(self, empty_registry):
        with pytest.raises(BranchNotFoundError):
            resolve_branch("@ALPHA")


# ---------------------------------------------------------------------------
# branch_exists
# ---------------------------------------------------------------------------

class TestBranchExists:
    def test_exists_for_valid_branch(self, populated_registry):
        assert branch_exists("@ALPHA") is True

    def test_exists_without_prefix(self, populated_registry):
        assert branch_exists("ALPHA") is True

    def test_not_exists_for_unknown(self, populated_registry):
        assert branch_exists("@NOPE") is False

    def test_case_insensitive(self, populated_registry):
        assert branch_exists("@alpha") is True
        assert branch_exists("@Alpha") is True

    def test_empty_registry(self, empty_registry):
        assert branch_exists("@ALPHA") is False

    def test_archived_branch_exists(self, populated_registry):
        """branch_exists uses get_branch_by_name — no status filter."""
        assert branch_exists("@GAMMA") is True


# ---------------------------------------------------------------------------
# get_branch_info
# ---------------------------------------------------------------------------

class TestGetBranchInfo:
    def test_contains_expected_keys(self, populated_registry):
        info = get_branch_info("@ALPHA")
        assert "name" in info
        assert "path" in info
        assert "status" in info
        assert info["status"] == "active"
        assert Path(info["path"]).name == "alpha"

    def test_name_is_lowercased_in_result(self, populated_registry):
        info = get_branch_info("@ALPHA")
        assert info["name"] == "alpha"

    def test_path_matches_resolve(self, populated_registry):
        info = get_branch_info("@BETA")
        path = resolve_branch("@BETA")
        assert info["path"] == path

    def test_case_insensitive(self, populated_registry):
        info_upper = get_branch_info("@ALPHA")
        info_lower = get_branch_info("@alpha")
        assert info_upper == info_lower

    def test_invalid_raises(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            get_branch_info("@NONEXISTENT")

    def test_without_prefix_raises_for_invalid(self, populated_registry):
        with pytest.raises(BranchNotFoundError):
            get_branch_info("NONEXISTENT")

    def test_empty_registry_raises(self, empty_registry):
        with pytest.raises(BranchNotFoundError):
            get_branch_info("@ALPHA")


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------

class TestListBranches:
    def test_default_status_active(self, populated_registry):
        """Default status='active' should exclude archived branches."""
        result = list_branches()
        names_lower = [b.lower() for b in result]
        assert "@alpha" in names_lower
        assert "@beta" in names_lower
        assert "@gamma" not in names_lower  # archived

    def test_all_active_returned(self, populated_registry):
        result = list_branches()
        assert len(result) == 2

    def test_filter_by_archived_status(self, populated_registry):
        result = list_branches(status="archived")
        assert len(result) == 1
        assert result[0].lower() == "@gamma"

    def test_filter_by_type(self, populated_registry):
        result = list_branches(branch_type="service")
        assert len(result) == 1
        assert result[0].lower() == "@beta"

    def test_filter_by_type_and_status(self, populated_registry):
        result = list_branches(branch_type="library", status="active")
        assert len(result) == 1
        assert result[0].lower() == "@alpha"

    def test_entries_have_at_prefix(self, populated_registry):
        result = list_branches()
        for entry in result:
            assert entry.startswith("@")

    def test_empty_registry(self, empty_registry):
        result = list_branches()
        assert result == []

    def test_no_matching_type(self, populated_registry):
        result = list_branches(branch_type="nonexistent_type")
        assert result == []


# ---------------------------------------------------------------------------
# handle_command routing
# ---------------------------------------------------------------------------

class TestHandleCommand:
    def test_resolve_command_success(self, populated_registry):
        assert handle_command("resolve", ["@ALPHA"]) is True

    def test_resolve_command_no_args(self, populated_registry):
        assert handle_command("resolve", []) is False

    def test_exists_command_success(self, populated_registry):
        assert handle_command("exists", ["@ALPHA"]) is True

    def test_exists_command_no_args(self, populated_registry):
        assert handle_command("exists", []) is False

    def test_info_command_success(self, populated_registry):
        assert handle_command("info", ["@ALPHA"]) is True

    def test_info_command_no_args(self, populated_registry):
        assert handle_command("info", []) is False

    def test_list_command(self, populated_registry):
        assert handle_command("list", []) is True

    def test_resolve_nonexistent_returns_false(self, populated_registry):
        assert handle_command("resolve", ["@NONEXISTENT"]) is False

    def test_info_nonexistent_returns_false(self, populated_registry):
        assert handle_command("info", ["@NONEXISTENT"]) is False

    def test_unknown_command(self, populated_registry):
        assert handle_command("bogus", []) is False


# ---------------------------------------------------------------------------
# sample_registry conftest fixture
# ---------------------------------------------------------------------------

class TestWithSampleRegistry:
    """Tests using the sample_registry fixture from conftest.py."""

    def test_resolve_via_sample(self, sample_registry):
        set_registry_path(sample_registry)
        try:
            path = resolve_branch("@TEST_BRANCH")
            assert "test_branch" in path
        finally:
            reset_registry_path()

    def test_branch_exists_via_sample(self, sample_registry):
        set_registry_path(sample_registry)
        try:
            assert branch_exists("@TEST_BRANCH") is True
            assert branch_exists("@MISSING") is False
        finally:
            reset_registry_path()

    def test_list_branches_via_sample(self, sample_registry):
        set_registry_path(sample_registry)
        try:
            result = list_branches()
            assert len(result) == 1
            assert result[0].lower() == "@test_branch"
        finally:
            reset_registry_path()

    def test_get_info_via_sample(self, sample_registry):
        set_registry_path(sample_registry)
        try:
            info = get_branch_info("@TEST_BRANCH")
            assert info["name"] == "test_branch"
            assert info["status"] == "active"
        finally:
            reset_registry_path()
