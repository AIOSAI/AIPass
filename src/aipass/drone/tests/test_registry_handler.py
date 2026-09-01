"""Tests for registry loading and credential verification.

Covers:
- load_registry() — valid JSON, missing file, corrupt JSON, metadata parsing
- get_all_branches() — filtering, empty results
- find_registry() — directory walk-up, no registry found
- _verify_registry_credential() — ID match, ID missing, ID mismatch
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import registry_handler
from aipass.drone.apps.handlers.registry_handler import (
    _first_registry_in,
    _registry_matches_credential,
    _validate_branch_path,
    _verify_registry_credential,
    find_registry,
    get_all_branches,
    get_registry_path,
    load_registry,
    reset_registry_path,
    set_registry_path,
)
from aipass.drone.apps.handlers.exceptions import (
    RegistryCorruptError,
    RegistryMismatchError,
    RegistryNotFoundError,
    RegistryPermissionError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_dir() -> Generator[Path, None, None]:
    """Isolated temp directory for registry tests; cleaned up after."""
    d = Path(tempfile.mkdtemp(prefix="reg_test_")).resolve()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _reset_global_path():
    """Ensure the module-level _registry_path is reset between tests."""
    reset_registry_path()
    yield
    reset_registry_path()


def _write_registry(directory: Path, data: dict, name: str = "AIPASS_REGISTRY.json") -> Path:
    """Helper: write a registry JSON file and return its path."""
    p = directory / name
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _write_passport(directory: Path, passport: dict) -> Path:
    """Helper: write a .trinity/passport.json and return its path."""
    trinity = directory / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    p = trinity / "passport.json"
    p.write_text(json.dumps(passport, indent=2), encoding="utf-8")
    return p


def _minimal_registry(*, metadata_id: str | None = None, branches: list | None = None) -> dict:
    """Return a minimal valid registry dict."""
    meta = {"version": "1.0.0"}
    if metadata_id is not None:
        meta["id"] = metadata_id
    if branches is None:
        branches = [
            {
                "name": "Alpha",
                "path": "alpha",
                "type": "library",
                "status": "active",
                "description": "Alpha branch",
            }
        ]
    return {"metadata": meta, "branches": branches}


# ===================================================================
# 1. load_registry() — valid registry
# ===================================================================


class TestLoadRegistry:
    def test_branches_normalised_to_dict(self, registry_dir: Path):
        """List-format branches are converted to a dict keyed by lowercased name."""
        reg = _minimal_registry()
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()

        assert isinstance(result, dict)
        assert "branches" in result
        assert "metadata" in result
        assert isinstance(result["branches"], dict)
        assert "alpha" in result["branches"]
        assert result["branches"]["alpha"]["name"] == "alpha"

    def test_relative_paths_resolved(self, registry_dir: Path):
        """Relative branch paths are resolved against registry location."""
        reg = _minimal_registry()
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()
        branch_path = Path(result["branches"]["alpha"]["path"])

        # The resolved path should be absolute
        assert branch_path.is_absolute()
        # It should be relative to the registry directory
        assert str(branch_path).startswith(str(registry_dir))

    def test_absolute_path_not_re_resolved(self, registry_dir: Path):
        """A branch with an already-absolute path inside project root is preserved as-is."""
        abs_path = str(registry_dir / "my_branch")
        reg = _minimal_registry(
            branches=[
                {
                    "name": "Absolute",
                    "path": abs_path,
                    "type": "library",
                    "status": "active",
                }
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()
        branch_path = result["branches"]["absolute"]["path"]

        assert branch_path == abs_path

    def test_branches_with_empty_name_skipped(self, registry_dir: Path):
        """load_registry() skips branch entries with no name field."""
        reg = _minimal_registry(
            branches=[
                {
                    "name": "Good",
                    "path": "good",
                    "type": "library",
                    "status": "active",
                },
                {
                    "name": "",
                    "path": "empty_name",
                    "type": "library",
                    "status": "active",
                },
                {
                    "path": "missing_name",
                    "type": "library",
                    "status": "active",
                },
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()

        assert len(result["branches"]) == 1
        assert "good" in result["branches"]

    def test_dict_format_branches_preserved(self, registry_dir: Path):
        """If branches is already a dict, it stays a dict."""
        reg = {
            "metadata": {"version": "1.0.0"},
            "branches": {
                "beta": {
                    "name": "beta",
                    "path": "/tmp/beta",
                    "status": "active",
                }
            },
        }
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()
        assert result["branches"]["beta"]["name"] == "beta"

    # ---------------------------------------------------------------
    # 2. load_registry() — missing file
    # ---------------------------------------------------------------

    def test_missing_file_raises_not_found(self, registry_dir: Path):
        """load_registry() raises RegistryNotFoundError when file is absent."""
        set_registry_path(registry_dir / "NONEXISTENT_REGISTRY.json")

        with pytest.raises(RegistryNotFoundError):
            load_registry()

    # ---------------------------------------------------------------
    # 3. load_registry() — corrupt / invalid JSON
    # ---------------------------------------------------------------

    def test_corrupt_json_raises_corrupt_error(self, registry_dir: Path):
        """Invalid JSON content triggers RegistryCorruptError."""
        bad_file = registry_dir / "BAD_REGISTRY.json"
        bad_file.write_text("{not valid json!!!", encoding="utf-8")
        set_registry_path(bad_file)

        with pytest.raises(RegistryCorruptError):
            load_registry()

    def test_non_object_json_raises_corrupt_error(self, registry_dir: Path):
        """Top-level JSON that isn't a dict triggers RegistryCorruptError."""
        bad_file = registry_dir / "LIST_REGISTRY.json"
        bad_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        set_registry_path(bad_file)

        with pytest.raises(RegistryCorruptError):
            load_registry()

    def test_missing_branches_key_raises_corrupt_error(self, registry_dir: Path):
        """Registry dict without 'branches' triggers RegistryCorruptError."""
        no_branches = {"metadata": {"version": "1.0.0"}}
        _write_registry(registry_dir, no_branches)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        with pytest.raises(RegistryCorruptError, match="missing 'branches'"):
            load_registry()

    def test_branches_wrong_type_raises_corrupt_error(self, registry_dir: Path):
        """branches field that is neither list nor dict triggers RegistryCorruptError."""
        bad = {"metadata": {"version": "1.0.0"}, "branches": "not-a-list-or-dict"}
        _write_registry(registry_dir, bad)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        with pytest.raises(RegistryCorruptError):
            load_registry()

    # ---------------------------------------------------------------
    # 4. load_registry() — permission error
    # ---------------------------------------------------------------

    def test_permission_error_raises_registry_permission_error(self, registry_dir: Path):
        """PermissionError when reading the file triggers RegistryPermissionError."""
        reg_file = _write_registry(registry_dir, _minimal_registry())
        set_registry_path(reg_file)

        with patch("builtins.open", side_effect=PermissionError("access denied")):
            with pytest.raises(RegistryPermissionError, match="Permission denied"):
                load_registry()


# ===================================================================
# 4 & 5. get_all_branches()
# ===================================================================


class TestGetAllBranches:
    @pytest.fixture(autouse=True)
    def _isolate_home(self, monkeypatch):
        """Prevent real AIPASS_HOME from leaking into test results."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)

    def test_returns_list_of_branch_dicts(self, registry_dir: Path):
        reg = _minimal_registry()
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        branches = get_all_branches()

        assert isinstance(branches, list)
        assert len(branches) == 1
        assert branches[0]["name"] == "alpha"

    def test_filters_by_status(self, registry_dir: Path):
        """Branches with non-matching status are excluded."""
        reg = _minimal_registry(
            branches=[
                {"name": "Active", "path": "a", "status": "active", "type": "lib"},
                {"name": "Archived", "path": "b", "status": "archived", "type": "lib"},
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        active = get_all_branches(status="active")
        assert len(active) == 1
        assert active[0]["name"] == "active"

        archived = get_all_branches(status="archived")
        assert len(archived) == 1
        assert archived[0]["name"] == "archived"

    def test_filters_by_branch_type(self, registry_dir: Path):
        """branch_type filter limits results."""
        reg = _minimal_registry(
            branches=[
                {"name": "Lib", "path": "l", "status": "active", "type": "library"},
                {"name": "App", "path": "a", "status": "active", "type": "app"},
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        libs = get_all_branches(branch_type="library")
        assert len(libs) == 1
        assert libs[0]["type"] == "library"

    def test_returns_empty_list_when_no_registry(self, registry_dir: Path):
        """When no registry file exists, get_all_branches returns []."""
        set_registry_path(registry_dir / "NONEXISTENT_REGISTRY.json")

        result = get_all_branches()
        assert result == []

    def test_returns_empty_when_no_matching_branches(self, registry_dir: Path):
        """All branches filtered out yields an empty list."""
        reg = _minimal_registry(
            branches=[
                {"name": "Only", "path": "o", "status": "archived", "type": "lib"},
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = get_all_branches(status="active")
        assert result == []


# ===================================================================
# 6 & 7. find_registry() / _first_registry_in()
# ===================================================================


class TestFindRegistry:
    def test_first_registry_in_finds_file(self, registry_dir: Path):
        """_first_registry_in returns path when *_REGISTRY.json exists."""
        _write_registry(registry_dir, _minimal_registry())

        hit = _first_registry_in(registry_dir)
        assert hit is not None
        assert hit.name == "AIPASS_REGISTRY.json"

    def test_first_registry_in_returns_none_when_empty(self, registry_dir: Path):
        """_first_registry_in returns None in an empty directory."""
        assert _first_registry_in(registry_dir) is None

    def test_first_registry_in_alphabetical(self, registry_dir: Path):
        """When multiple registries exist, alphabetically first wins."""
        _write_registry(registry_dir, _minimal_registry(), name="A_REGISTRY.json")
        _write_registry(registry_dir, _minimal_registry(), name="Z_REGISTRY.json")

        hit = _first_registry_in(registry_dir)
        assert hit is not None
        assert hit.name == "A_REGISTRY.json"

    def test_find_registry_from_child_dir(self, registry_dir: Path, monkeypatch):
        """find_registry() walks up from cwd to find registry in ancestor."""
        _write_registry(registry_dir, _minimal_registry())
        child = registry_dir / "level1" / "level2"
        child.mkdir(parents=True)

        monkeypatch.chdir(child)
        result = find_registry()
        assert result.exists()
        assert result.name == "AIPASS_REGISTRY.json"
        assert result.parent == registry_dir

    def test_find_registry_returns_path_when_no_registry(self, registry_dir: Path, monkeypatch):
        """find_registry() returns a fallback path ending with *_REGISTRY.json when nothing found."""
        empty_child = registry_dir / "empty_sub"
        empty_child.mkdir()

        monkeypatch.chdir(empty_child)
        # find_registry never returns None -- it returns a conventional fallback path
        result = find_registry()
        assert isinstance(result, Path)
        # On Windows, case-insensitive glob may match other *_registry.json files
        # during the walk from __file__; accept any *_REGISTRY.json variant
        assert result.name.lower().endswith("_registry.json")

    def test_find_registry_skips_mismatched_continues_up(self, registry_dir: Path, monkeypatch):
        """find_registry() skips a nested registry with wrong credential and finds the correct one above."""
        passport_id = "correct-registry-id"
        wrong_id = "wrong-registry-id"

        _write_registry(registry_dir, _minimal_registry(metadata_id=passport_id))

        nested = registry_dir / "src" / "aipass" / "citizen"
        nested.mkdir(parents=True)
        _write_registry(nested, {"metadata": {"id": wrong_id}, "branches": []}, name="CITIZEN_REGISTRY.json")

        _write_passport(nested, {"citizenship": {"registry_id": passport_id}})

        monkeypatch.chdir(nested)
        result = find_registry()
        assert result.parent == registry_dir
        assert result.name == "AIPASS_REGISTRY.json"

    def test_find_registry_returns_matching_nested(self, registry_dir: Path, monkeypatch):
        """find_registry() returns a nested registry when credentials match."""
        shared_id = "shared-id"

        _write_registry(registry_dir, _minimal_registry(metadata_id="parent-id"))

        nested = registry_dir / "sub"
        nested.mkdir()
        _write_registry(nested, _minimal_registry(metadata_id=shared_id), name="SUB_REGISTRY.json")
        _write_passport(nested, {"citizenship": {"registry_id": shared_id}})

        monkeypatch.chdir(nested)
        result = find_registry()
        assert result.parent == nested
        assert result.name == "SUB_REGISTRY.json"


# ===================================================================
# 7b. _registry_matches_credential()
# ===================================================================


class TestRegistryMatchesCredential:
    def test_returns_true_when_ids_match(self, registry_dir: Path, monkeypatch):
        """Returns True when passport and registry IDs agree."""
        shared_id = "match-id"
        path = _write_registry(registry_dir, _minimal_registry(metadata_id=shared_id))
        _write_passport(registry_dir, {"citizenship": {"registry_id": shared_id}})
        monkeypatch.chdir(registry_dir)
        assert _registry_matches_credential(path) is True

    def test_returns_false_on_mismatch(self, registry_dir: Path, monkeypatch):
        """Returns False when passport and registry IDs disagree."""
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="reg-A"))
        _write_passport(registry_dir, {"citizenship": {"registry_id": "reg-B"}})
        monkeypatch.chdir(registry_dir)
        assert _registry_matches_credential(path) is False

    def test_returns_true_when_registry_has_no_id(self, registry_dir: Path, monkeypatch):
        """Returns True when registry has no metadata.id."""
        path = _write_registry(registry_dir, _minimal_registry())
        _write_passport(registry_dir, {"citizenship": {"registry_id": "some-id"}})
        monkeypatch.chdir(registry_dir)
        assert _registry_matches_credential(path) is True

    def test_returns_true_when_no_passport(self, registry_dir: Path, monkeypatch):
        """Returns True when no passport.json exists."""
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        monkeypatch.chdir(registry_dir)
        assert _registry_matches_credential(path) is True


class TestCredentialCheckWithNoCurrentDirectory:
    """A process whose cwd was deleted has no location, and that is not an error.

    The passport walk starts at the cwd, so ``Path.cwd()`` raising ENOENT used
    to land in the broad ``except`` — which logs "Credential pre-check FAILED"
    at WARNING and returns True. The answer was right by accident and the
    account of it was wrong: nothing failed, there is simply no location to
    infer from, which is the documented no-passport case. @daemon named this
    one as the member of the cwd family where the cwd is not the interesting
    part — a check that reports failure while passing is the fail-open shape
    even when the value it returns is correct.
    """

    @staticmethod
    def _no_cwd(monkeypatch):
        def _raise():
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(Path, "cwd", staticmethod(_raise))

    def test_a_deleted_cwd_is_not_reported_as_a_failed_check(self, registry_dir: Path, monkeypatch):
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        self._no_cwd(monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            result = _registry_matches_credential(path)

        assert result is True
        failures = [c for c in log.warning.call_args_list if "pre-check failed" in str(c).lower()]
        assert not failures, f"an absent location was reported as a failed check: {failures}"

    def test_the_absent_location_is_said_out_loud(self, registry_dir: Path, monkeypatch):
        """Silence would make it indistinguishable from a walk that found nothing."""
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        self._no_cwd(monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            _registry_matches_credential(path)

        assert log.info.called, "no line records that the check had no location to stand in"

    def test_an_unreadable_registry_is_still_a_warning(self, registry_dir: Path, monkeypatch):
        """The broad except keeps its job — only the cwd left through it."""
        monkeypatch.chdir(registry_dir)

        with patch.object(registry_handler, "logger") as log:
            result = _registry_matches_credential(registry_dir)

        assert result is True
        assert log.warning.called, "an unreadable registry must still be reported"

    def test_the_walk_that_calls_it_reaches_it_at_all(self, monkeypatch):
        """The credential fix is worthless if its CALLER raises first.

        ``find_registry`` opens with its own bare ``Path.cwd()``. Guarding only
        the check below it would move the ENOENT up one frame and call the lane
        fixed — the same shape as a flagged list that undercounts. With no
        location the cwd walk is skipped, not attempted: resolution falls
        through to AIPASS_HOME and the package walk, which never needed a cwd.
        """
        self._no_cwd(monkeypatch)

        assert find_registry().name.endswith("_REGISTRY.json")

    def test_verification_does_not_report_a_failure_it_did_not_have(self, monkeypatch):
        """Third site, same species: ``_verify_registry_credential``."""
        self._no_cwd(monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            _verify_registry_credential(Path("/nowhere/AIPASS_REGISTRY.json"), {"metadata": {"id": "some-id"}})

        failures = [c for c in log.warning.call_args_list if "verification failed" in str(c).lower()]
        assert not failures, f"an absent location was reported as a failed verification: {failures}"


# ===================================================================
# 8, 9, 10. _verify_registry_credential()
# ===================================================================


class TestVerifyRegistryCredential:
    def test_passes_when_ids_match(self, registry_dir: Path, monkeypatch):
        """No error when passport.citizenship.registry_id == registry.metadata.id."""
        shared_id = "reg-abc-123"
        registry_data = _minimal_registry(metadata_id=shared_id)
        registry_path = _write_registry(registry_dir, registry_data)
        _write_passport(registry_dir, {"citizenship": {"registry_id": shared_id}})

        monkeypatch.chdir(registry_dir)
        # Should not raise
        _verify_registry_credential(registry_path, registry_data)

    def test_passes_when_registry_id_missing(self, registry_dir: Path, monkeypatch):
        """No error when registry has no metadata.id (migration period)."""
        registry_data = _minimal_registry()  # no metadata_id
        registry_path = _write_registry(registry_dir, registry_data)
        _write_passport(registry_dir, {"citizenship": {"registry_id": "some-id"}})

        monkeypatch.chdir(registry_dir)
        _verify_registry_credential(registry_path, registry_data)

    def test_passes_when_passport_id_missing(self, registry_dir: Path, monkeypatch):
        """No error when passport has no citizenship.registry_id (migration period)."""
        shared_id = "reg-xyz-789"
        registry_data = _minimal_registry(metadata_id=shared_id)
        registry_path = _write_registry(registry_dir, registry_data)
        _write_passport(
            registry_dir,
            {
                "citizenship": {}  # no registry_id
            },
        )

        monkeypatch.chdir(registry_dir)
        _verify_registry_credential(registry_path, registry_data)

    def test_passes_when_no_passport_file(self, registry_dir: Path, monkeypatch):
        """No error when passport.json does not exist at all."""
        shared_id = "reg-000"
        registry_data = _minimal_registry(metadata_id=shared_id)
        registry_path = _write_registry(registry_dir, registry_data)
        # No passport written

        monkeypatch.chdir(registry_dir)
        _verify_registry_credential(registry_path, registry_data)

    def test_raises_on_id_mismatch(self, registry_dir: Path, monkeypatch):
        """RegistryMismatchError raised when IDs differ -- security-critical."""
        registry_data = _minimal_registry(metadata_id="registry-AAA")
        registry_path = _write_registry(registry_dir, registry_data)
        _write_passport(registry_dir, {"citizenship": {"registry_id": "registry-BBB"}})

        monkeypatch.chdir(registry_dir)
        with pytest.raises(RegistryMismatchError, match="mismatch"):
            _verify_registry_credential(registry_path, registry_data)

    def test_mismatch_error_contains_both_ids(self, registry_dir: Path, monkeypatch):
        """Error message includes both the passport and registry IDs for debugging."""
        reg_id = "registry-PROD"
        passport_id = "registry-DEV"
        registry_data = _minimal_registry(metadata_id=reg_id)
        registry_path = _write_registry(registry_dir, registry_data)
        _write_passport(registry_dir, {"citizenship": {"registry_id": passport_id}})

        monkeypatch.chdir(registry_dir)
        with pytest.raises(RegistryMismatchError) as exc_info:
            _verify_registry_credential(registry_path, registry_data)

        msg = str(exc_info.value)
        assert passport_id in msg
        assert reg_id in msg

    def test_passes_when_metadata_key_absent(self, registry_dir: Path, monkeypatch):
        """No error when the entire metadata dict is absent."""
        registry_data = {"branches": []}  # no metadata at all
        registry_path = registry_dir / "FAKE_REGISTRY.json"

        monkeypatch.chdir(registry_dir)
        _verify_registry_credential(registry_path, registry_data)


# ===================================================================
# 11. Metadata parsing
# ===================================================================


class TestMetadataParsing:
    def test_metadata_id_preserved(self, registry_dir: Path, monkeypatch):
        """Registry metadata.id field is available after loading."""
        reg = _minimal_registry(metadata_id="my-unique-id")
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        # chdir to temp so _verify_registry_credential won't find the
        # real project passport (which has a different registry_id).
        monkeypatch.chdir(registry_dir)
        result = load_registry()
        assert result["metadata"]["id"] == "my-unique-id"

    def test_metadata_version_preserved(self, registry_dir: Path):
        """Registry metadata.version field survives loading."""
        reg = _minimal_registry()
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        result = load_registry()
        assert result["metadata"]["version"] == "1.0.0"


# ===================================================================
# Registry path management
# ===================================================================


class TestRegistryPathManagement:
    def test_set_and_get_registry_path(self, registry_dir: Path):
        """set_registry_path() overrides get_registry_path()."""
        custom = registry_dir / "CUSTOM_REGISTRY.json"
        set_registry_path(custom)

        assert get_registry_path() == custom

    def test_reset_clears_override(self, registry_dir: Path):
        """reset_registry_path() clears any previously set override."""
        set_registry_path(registry_dir / "CUSTOM_REGISTRY.json")
        reset_registry_path()

        # After reset, get_registry_path falls through to env / find
        result = get_registry_path()
        assert result != registry_dir / "CUSTOM_REGISTRY.json"

    def test_env_var_takes_precedence_after_reset(self, registry_dir: Path):
        """AIPASS_REGISTRY env var is used when no explicit path is set."""
        env_path = str(registry_dir / "ENV_REGISTRY.json")
        reset_registry_path()

        with patch.dict(os.environ, {"AIPASS_REGISTRY": env_path}):
            result = get_registry_path()
            assert result == Path(env_path)


# ===================================================================
# Path containment validation
# ===================================================================


class TestValidateBranchPath:
    """_validate_branch_path() security boundary checks."""

    def test_valid_path_inside_project(self, registry_dir: Path):
        """Path within project root passes validation."""
        branch = registry_dir / "src" / "aipass" / "trigger"
        branch.mkdir(parents=True)
        assert _validate_branch_path(branch, registry_dir, "trigger") is True

    def test_path_traversal_blocked(self, registry_dir: Path):
        """Path with ../ escaping project root is rejected."""
        evil_path = registry_dir / ".." / ".." / ".." / "tmp" / "evil"
        assert _validate_branch_path(evil_path, registry_dir, "evil") is False

    def test_absolute_path_outside_root_blocked(self, registry_dir: Path):
        """Absolute path outside project root is rejected."""
        assert _validate_branch_path(Path("/tmp/evil"), registry_dir, "evil") is False

    def test_exact_project_root_passes(self, registry_dir: Path):
        """Path equal to project root passes (edge case)."""
        assert _validate_branch_path(registry_dir, registry_dir, "root") is True

    def test_symlink_resolved(self, registry_dir: Path):
        """Symlink pointing outside project root is rejected after resolution."""
        external = Path(tempfile.mkdtemp(prefix="external_"))
        try:
            link = registry_dir / "sneaky_link"
            link.symlink_to(external)
            assert _validate_branch_path(link, registry_dir, "sneaky") is False
        finally:
            shutil.rmtree(external, ignore_errors=True)

    def test_registry_rejects_traversal_entry(self, registry_dir: Path, monkeypatch):
        """A registry entry with path traversal is silently dropped during load."""
        reg = _minimal_registry(
            branches=[
                {"name": "legit", "path": "src/legit", "status": "active", "type": "lib"},
                {"name": "evil", "path": "../../../tmp/evil", "status": "active", "type": "lib"},
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        monkeypatch.chdir(registry_dir)
        result = load_registry()
        branch_names = list(result["branches"].keys())
        assert "legit" in branch_names
        assert "evil" not in branch_names
