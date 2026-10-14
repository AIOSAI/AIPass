# =================== AIPass ====================
# Name: test_registry_handler.py
# Description: Registry loading, lookup and credential verification
# Version: 1.1.0
# Created: 2026-03-14
# Modified: 2026-10-13
# =============================================

"""Tests for apps/handlers/registry_handler.py: registry loading, lookup and credential verification."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers import registry_handler, router_handler
from aipass.drone.apps.handlers.registry_handler import (
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
                    "path": str(registry_dir / "beta"),
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
        """PermissionError when reading the file triggers RegistryPermissionError.

        The refusal is supplied at registry_handler's one registry read, not by
        replacing builtins.open for the whole process. Mutant killed (runner):
        the PermissionError branch removed, so the refusal reads as corruption.
        """
        reg_file = _write_registry(registry_dir, _minimal_registry())
        set_registry_path(reg_file)

        with patch.object(registry_handler, "_read_registry_json", side_effect=PermissionError("access denied")):
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
    def test_first_registry_in_finds_file(self, registry_dir: Path, monkeypatch):
        """A registry in the cwd itself is found; mutant killed: an empty answer from a directory holding one."""
        _write_registry(registry_dir, _minimal_registry())
        monkeypatch.chdir(registry_dir)

        assert find_registry() == registry_dir / "AIPASS_REGISTRY.json"

    def test_first_registry_in_returns_none_when_empty(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """An empty cwd yields nothing and the walk moves on; mutant killed: an empty directory answering a path."""
        home = tmp_path / "home"
        home.mkdir()
        _write_registry(home, _minimal_registry())
        monkeypatch.chdir(registry_dir)
        monkeypatch.setenv("AIPASS_HOME", str(home))

        assert find_registry() == home / "AIPASS_REGISTRY.json"

    def test_first_registry_in_alphabetical(self, registry_dir: Path, monkeypatch):
        """When multiple registries exist, alphabetically first wins; mutant killed: the last one taken."""
        _write_registry(registry_dir, _minimal_registry(), name="A_REGISTRY.json")
        _write_registry(registry_dir, _minimal_registry(), name="Z_REGISTRY.json")
        monkeypatch.chdir(registry_dir)

        assert find_registry().name == "A_REGISTRY.json"

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
# 7a. resolve_aipass_home() — the home without AIPASS_HOME
# ===================================================================


def _an_aipass_home(directory: Path, branch: str = "api") -> Path:
    """A directory that is an AIPass home: an AIPASS_REGISTRY.json listing one branch."""
    directory.mkdir(parents=True, exist_ok=True)
    _write_registry(directory, {"metadata": {}, "branches": [{"name": branch, "path": str(directory / branch)}]})
    return directory


def _enrol(enrolment: Path, projects: dict[Path, str]) -> Path:
    """Write trusted_projects.json in the shape the install writes, enrolling each path at its time."""
    enrolment.parent.mkdir(parents=True, exist_ok=True)
    record = {str(path): {"enrolled": when, "config_hash": "x", "config_path": ""} for path, when in projects.items()}
    enrolment.write_text(json.dumps({"version": 1, "projects": record}), encoding="utf-8")
    return enrolment


@pytest.fixture
def stranger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A fresh terminal after the install: AIPASS_HOME unset, the cwd in a tree with no registry.

    The interpreter and the enrolment file point into tmp_path; each test puts
    a home in one, both, or neither.
    """
    monkeypatch.delenv("AIPASS_HOME", raising=False)
    monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
    interpreter = tmp_path / "install"
    enrolment = tmp_path / "user" / ".aipass" / "trusted_projects.json"
    monkeypatch.setattr(registry_handler, "_interpreter_home", lambda: interpreter)
    monkeypatch.setattr(registry_handler, "_enrolment_file", lambda: enrolment)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return {"interpreter": interpreter, "enrolment": enrolment, "tmp": tmp_path}


class TestAipassHomeResolution:
    """AIPASS_HOME, else the interpreter's install, else the newest enrolled home; each must hold the registry."""

    def test_the_interpreters_install_is_the_home(self, stranger: dict[str, Path]) -> None:
        """The installed drone runs on <home>/.venv: its parent answers, with nothing set."""
        home = _an_aipass_home(stranger["interpreter"])

        assert registry_handler.resolve_aipass_home() == (home, "interpreter", ())

    def test_an_explicit_aipass_home_beats_the_interpreter(
        self, stranger: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: the AIPASS_HOME read moved below the interpreter check — the guess wins."""
        _an_aipass_home(stranger["interpreter"])
        chosen = _an_aipass_home(stranger["tmp"] / "chosen")
        monkeypatch.setenv("AIPASS_HOME", str(chosen))

        assert registry_handler.resolve_aipass_home().path == chosen

    def test_an_interpreter_parent_without_a_registry_falls_through_to_the_one_enrolled_home(
        self, stranger: dict[str, Path]
    ) -> None:
        """Mutant: the interpreter's parent returned without the registry check — a system Python names /usr."""
        stranger["interpreter"].mkdir()
        enrolled = _an_aipass_home(stranger["tmp"] / "AIPass")
        _enrol(stranger["enrolment"], {enrolled: "2026-10-13T20:00:00+00:00"})

        assert registry_handler.resolve_aipass_home() == (enrolled, "enrolled", ())

    def test_projects_that_are_not_homes_are_skipped_and_the_newest_home_wins(self, stranger: dict[str, Path]) -> None:
        """Mutant: min() for max() — the oldest enrolment answers."""
        older = _an_aipass_home(stranger["tmp"] / "old_checkout")
        newer = _an_aipass_home(stranger["tmp"] / "AIPass")
        project = stranger["tmp"] / "baud"
        project.mkdir()
        _write_registry(project, _minimal_registry(), name="BAUD_REGISTRY.json")
        _enrol(
            stranger["enrolment"],
            {
                older: "2026-09-01T00:00:00+00:00",
                newer: "2026-10-13T20:00:00+00:00",
                project: "2026-10-13T21:00:00+00:00",
            },
        )

        assert registry_handler.resolve_aipass_home().path == newer

    def test_with_both_empty_nothing_resolves_and_the_tip_names_what_was_tried(self, stranger: dict[str, Path]) -> None:
        stranger["interpreter"].mkdir()
        project = stranger["tmp"] / "baud"
        project.mkdir()
        _enrol(stranger["enrolment"], {project: "2026-10-13T20:00:00+00:00"})

        home = registry_handler.resolve_aipass_home()

        assert home.path is None
        assert home.tried == (
            "AIPASS_HOME is unset",
            f"{stranger['interpreter']} (the interpreter's install) holds no AIPASS_REGISTRY.json",
            f"{stranger['enrolment']} enrolls no project holding AIPASS_REGISTRY.json",
        )
        assert registry_handler.missing_home_tip() == (
            "  Tip: no AIPass home found. Tried: " + "; ".join(home.tried) + ".\n"
            "  Set AIPASS_HOME=/path/to/AIPass to reach the core branches."
        )

    def test_an_unreadable_enrolment_file_is_named_not_read_as_empty(self, stranger: dict[str, Path]) -> None:
        stranger["enrolment"].parent.mkdir(parents=True)
        stranger["enrolment"].write_text("{not json", encoding="utf-8")

        home = registry_handler.resolve_aipass_home()

        assert home.path is None
        assert home.tried[-1].startswith(f"{stranger['enrolment']} could not be read (")

    def test_the_tip_is_silent_once_a_home_resolved(self, stranger: dict[str, Path]) -> None:
        _an_aipass_home(stranger["interpreter"])

        assert registry_handler.missing_home_tip() == ""

    def test_a_branch_in_the_home_resolves_from_outside_any_registry(self, stranger: dict[str, Path]) -> None:
        """The stranger's `drone @api ...` from ~: get_branch_by_name finds @api in the interpreter's home."""
        home = _an_aipass_home(stranger["interpreter"])

        assert find_registry() == home / "AIPASS_REGISTRY.json"
        branch = registry_handler.get_branch_by_name("api")
        assert branch is not None
        assert branch["path"] == str(home / "api")

    def test_a_deleted_cwd_still_resolves_through_the_interpreter(
        self, stranger: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _an_aipass_home(stranger["interpreter"])
        TestCredentialCheckWithNoCurrentDirectory._no_cwd(monkeypatch)

        assert find_registry() == home / "AIPASS_REGISTRY.json"


def _with_venv(home: Path, layout: str = "posix") -> Path:
    """Give *home* its own venv python in *layout*, the way setup.sh does; returns that python."""
    directory, name = registry_handler.VENV_LAYOUTS[layout]
    python = home / ".venv" / directory / name
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("", encoding="utf-8")
    return python


class TestBranchInterpreter:
    """A branch app runs on the interpreter of the AIPass home it lives in, not on whichever drone came first."""

    @pytest.fixture(autouse=True)
    def _posix_layout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(registry_handler, "_venv_layout", lambda: registry_handler.VENV_LAYOUTS["posix"])

    def test_an_enrolled_homes_branch_runs_on_the_homes_venv_announced_once(self, stranger: dict[str, Path]) -> None:
        """The sandbox: the uv tool's drone, an enrolled home with its own .venv (mutant: always sys.executable)."""
        home = _an_aipass_home(stranger["tmp"] / "AIPass")
        python = _with_venv(home)
        _enrol(stranger["enrolment"], {home: "2026-10-13T20:00:00+00:00"})

        with patch.object(registry_handler, "logger") as log:
            first = registry_handler.branch_interpreter(home / "src" / "aipass" / "api")
            second = registry_handler.branch_interpreter(home / "src" / "aipass" / "flow")

        assert first == second == str(python.resolve())
        assert log.info.call_count == 1
        assert python.resolve() in log.info.call_args.args
        log.warning.assert_not_called()

    @pytest.mark.parametrize("layout", ["posix", "windows"])
    def test_aipass_home_set_to_another_install_takes_its_venv_in_either_layout(
        self, stranger: dict[str, Path], monkeypatch: pytest.MonkeyPatch, layout: str
    ) -> None:
        home = _an_aipass_home(stranger["tmp"] / "AIPass")
        python = _with_venv(home, layout)
        monkeypatch.setenv("AIPASS_HOME", str(home))
        monkeypatch.setattr(registry_handler, "_venv_layout", lambda: registry_handler.VENV_LAYOUTS[layout])

        assert registry_handler.branch_interpreter(home / "src" / "aipass" / "api") == str(python.resolve())

    def test_a_home_without_a_venv_keeps_sys_executable_and_warns_naming_it(self, stranger: dict[str, Path]) -> None:
        home = _an_aipass_home(stranger["tmp"] / "AIPass")
        _enrol(stranger["enrolment"], {home: "2026-10-13T20:00:00+00:00"})

        with patch.object(registry_handler, "logger") as log:
            chosen = registry_handler.branch_interpreter(home / "src" / "aipass" / "api")

        assert chosen == sys.executable
        assert log.warning.call_count == 1
        assert home.resolve() in log.warning.call_args.args

    def test_the_drones_own_home_keeps_sys_executable_even_with_a_venv(self, stranger: dict[str, Path]) -> None:
        """The exact rule: on a dev checkout the .venv IS this interpreter (mutant: the own-home check removed)."""
        home = _an_aipass_home(stranger["interpreter"])
        _with_venv(home)

        with patch.object(registry_handler, "logger") as log:
            chosen = registry_handler.branch_interpreter(home / "src" / "aipass" / "api")

        assert chosen == sys.executable
        log.warning.assert_not_called()
        log.info.assert_not_called()

    def test_a_branch_outside_the_home_and_no_home_at_all_keep_sys_executable(self, stranger: dict[str, Path]) -> None:
        """A declared root's branch is not the home's (mutant: the inside-the-home check removed)."""
        assert registry_handler.branch_interpreter(stranger["tmp"] / "wren" / "src") == sys.executable

        home = _an_aipass_home(stranger["tmp"] / "AIPass")
        _with_venv(home)
        _enrol(stranger["enrolment"], {home: "2026-10-13T20:00:00+00:00"})

        assert registry_handler.branch_interpreter(stranger["tmp"] / "wren" / "src") == sys.executable


# ===================================================================
# 7b. _registry_matches_credential()
# ===================================================================


class TestRegistryMatchesCredential:
    """find_registry() skips a cwd registry only when both ids exist and disagree."""

    @staticmethod
    def _home(tmp_path: Path, monkeypatch) -> Path:
        """An AIPASS_HOME registry: where the walk lands once the cwd one is skipped."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("AIPASS_HOME", str(home))
        return _write_registry(home, _minimal_registry())

    def test_returns_true_when_ids_match(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """Matching ids keep the cwd registry; mutant killed: a match judged a mismatch."""
        shared_id = "match-id"
        path = _write_registry(registry_dir, _minimal_registry(metadata_id=shared_id))
        _write_passport(registry_dir, {"citizenship": {"registry_id": shared_id}})
        self._home(tmp_path, monkeypatch)
        monkeypatch.chdir(registry_dir)
        assert find_registry() == path

    def test_returns_false_on_mismatch(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """Disagreeing ids skip the cwd registry; mutant killed: a mismatch accepted."""
        _write_registry(registry_dir, _minimal_registry(metadata_id="reg-A"))
        _write_passport(registry_dir, {"citizenship": {"registry_id": "reg-B"}})
        home = self._home(tmp_path, monkeypatch)
        monkeypatch.chdir(registry_dir)
        assert find_registry() == home

    def test_returns_true_when_registry_has_no_id(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """A registry with no metadata.id is kept; mutant killed: a missing registry id refused."""
        path = _write_registry(registry_dir, _minimal_registry())
        _write_passport(registry_dir, {"citizenship": {"registry_id": "some-id"}})
        self._home(tmp_path, monkeypatch)
        monkeypatch.chdir(registry_dir)
        assert find_registry() == path

    def test_returns_true_when_no_passport(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """No passport.json keeps the cwd registry; mutant killed: a walk that finds no passport refusing."""
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        self._home(tmp_path, monkeypatch)
        monkeypatch.chdir(registry_dir)
        assert find_registry() == path


class TestPassportFault:
    """Option C (fleet green leg 7): a PASSPORT fault is accepted and named; a REGISTRY fault is not a passport fault.

    Every file lives under tmp_path; the caller's location comes through the
    router_handler._working_directory seam, never a chdir.
    """

    @staticmethod
    def _stand_in(tmp_path: Path, monkeypatch) -> Path:
        """A project dir the caller stands in, an AIPASS_HOME elsewhere, and no fault recorded yet."""
        project = tmp_path / "project"
        project.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        _write_registry(home, _minimal_registry())
        monkeypatch.setenv("AIPASS_HOME", str(home))
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        monkeypatch.setattr(router_handler, "_working_directory", lambda: project)
        monkeypatch.setattr(registry_handler, "_PASSPORT_FAULT", None)
        return project

    def test_broken_passport_is_accepted_and_named(self, tmp_path: Path, monkeypatch):
        """The cwd registry is kept and the reader names passport and registry.

        Mutants killed: split inverted, record dropped, record handed the registry as the passport.
        """
        project = self._stand_in(tmp_path, monkeypatch)
        registry = _write_registry(project, _minimal_registry(metadata_id="reg-A"))
        passport = _write_passport(project, {})
        passport.write_text("{not json", encoding="utf-8")

        assert find_registry() == registry
        fault = registry_handler.passport_fault() or ""
        assert fault.startswith(f"drone: passport {passport} could not be read (")
        assert fault.endswith(f"); registry {registry} was used without its credential check")

    def test_verify_records_the_same_fault(self, tmp_path: Path, monkeypatch):
        """A set registry path skips the pre-check; _verify_registry_credential records the same line.

        Mutant killed: _verify's record dropped.
        """
        project = self._stand_in(tmp_path, monkeypatch)
        registry = _write_registry(project, _minimal_registry(metadata_id="reg-A"))
        passport = _write_passport(project, {})
        passport.write_text("{not json", encoding="utf-8")
        set_registry_path(registry)

        loaded = load_registry()
        assert "alpha" in loaded["branches"]
        fault = registry_handler.passport_fault() or ""
        assert fault.startswith(f"drone: passport {passport} could not be read (")
        assert fault.endswith(f"registry {registry} was used without its credential check")

    def test_broken_registry_is_no_passport_fault(self, tmp_path: Path, monkeypatch):
        """A registry of broken JSON is kept, records nothing, and load_registry() names it by raising."""
        project = self._stand_in(tmp_path, monkeypatch)
        registry = project / "AIPASS_REGISTRY.json"
        registry.write_text("{not json", encoding="utf-8")
        _write_passport(project, {"citizenship": {"registry_id": "reg-A"}})

        assert find_registry() == registry
        assert registry_handler.passport_fault() is None
        with pytest.raises(RegistryCorruptError):
            load_registry()
        assert registry_handler.passport_fault() is None


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
        """The working directory is gone: supplied beneath caller_cwd, so its guard still runs."""

        def _raise():
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(router_handler, "_working_directory", _raise)

    @staticmethod
    def _cwd_vanishes_after_the_walk_starts(directory: Path, monkeypatch):
        """find_registry reads the cwd, then the directory is deleted before the credential check reads it.

        The check's own no-location arm is reachable through find_registry only
        this way: find_registry skips its walk when it starts with no cwd.
        """
        reads = []

        def _then_gone():
            reads.append(directory)
            if len(reads) > 1:
                raise FileNotFoundError(2, "No such file or directory")
            return directory

        monkeypatch.setattr(router_handler, "_working_directory", _then_gone)

    def test_a_deleted_cwd_is_not_reported_as_a_failed_check(self, registry_dir: Path, monkeypatch):
        """The registry is kept, no pre-check failure logged; mutant killed: the check's no-location arm removed."""
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        self._cwd_vanishes_after_the_walk_starts(registry_dir, monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            result = find_registry()

        assert result == path
        failures = [c for c in log.warning.call_args_list if "pre-check failed" in str(c).lower()]
        assert not failures, f"an absent location was reported as a failed check: {failures}"

    def test_the_absent_location_is_said_out_loud(self, registry_dir: Path, monkeypatch):
        """Silence would make it indistinguishable from a walk that found nothing.

        Mutant killed (runner): the check's no-location arm removed.
        """
        path = _write_registry(registry_dir, _minimal_registry(metadata_id="some-id"))
        self._cwd_vanishes_after_the_walk_starts(registry_dir, monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            find_registry()

        assert log.info.called, "no line records that the check had no location to stand in"
        assert log.info.call_args[0][1] == path

    def test_an_unreadable_registry_is_still_a_warning(self, registry_dir: Path, monkeypatch):
        """A registry fault keeps its WARNING and records no passport fault; mutant killed: the warning removed."""
        unreadable = registry_dir / "AIPASS_REGISTRY.json"
        unreadable.mkdir()  # a directory by the registry's name: open() fails on every OS
        monkeypatch.chdir(registry_dir)
        monkeypatch.setattr(registry_handler, "_PASSPORT_FAULT", None)

        with patch.object(registry_handler, "logger") as log:
            found = find_registry()

        assert found == unreadable
        assert log.warning.called
        assert log.warning.call_args[0][:2] == ("Credential pre-check could not read registry %s: %s", unreadable)
        assert registry_handler.passport_fault() is None

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

    def test_verification_does_not_report_a_failure_it_did_not_have(self, monkeypatch, tmp_path):
        """Third site, same species; mutant killed: the no-location line logged at WARNING."""
        registry_path = _write_registry(tmp_path, _minimal_registry(metadata_id="some-id"))
        set_registry_path(registry_path)
        self._no_cwd(monkeypatch)

        with patch.object(registry_handler, "logger") as log:
            load_registry()

        assert log.warning.call_args_list == [], "an absent location was reported as a failed verification"
        assert log.info.call_args[0][1] == registry_path


# ===================================================================
# 8, 9, 10. _verify_registry_credential()
# ===================================================================


class TestVerifyRegistryCredential:
    """load_registry() refuses a registry whose id disagrees with the caller's passport."""

    @staticmethod
    def _load(registry_dir: Path, monkeypatch) -> dict:
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")
        monkeypatch.chdir(registry_dir)
        return load_registry()

    def test_passes_when_ids_match(self, registry_dir: Path, monkeypatch):
        """Matching ids load; mutant killed: the id comparison inverted."""
        shared_id = "reg-abc-123"
        _write_registry(registry_dir, _minimal_registry(metadata_id=shared_id))
        _write_passport(registry_dir, {"citizenship": {"registry_id": shared_id}})

        assert list(self._load(registry_dir, monkeypatch)["branches"]) == ["alpha"]

    def test_passes_when_registry_id_missing(self, registry_dir: Path, monkeypatch):
        """No metadata.id loads (migration period); mutant killed: the missing-registry-id pass removed."""
        _write_registry(registry_dir, _minimal_registry())
        _write_passport(registry_dir, {"citizenship": {"registry_id": "some-id"}})

        assert list(self._load(registry_dir, monkeypatch)["branches"]) == ["alpha"]

    def test_passes_when_passport_id_missing(self, registry_dir: Path, monkeypatch):
        """No passport registry_id loads (migration period); mutant killed: the missing-passport-id pass removed."""
        _write_registry(registry_dir, _minimal_registry(metadata_id="reg-xyz-789"))
        _write_passport(registry_dir, {"citizenship": {}})

        assert list(self._load(registry_dir, monkeypatch)["branches"]) == ["alpha"]

    def test_passes_when_no_passport_file(self, registry_dir: Path, monkeypatch):
        """No passport.json loads quietly; mutant killed: the no-passport pass removed."""
        _write_registry(registry_dir, _minimal_registry(metadata_id="reg-000"))

        with patch.object(registry_handler, "logger") as log:
            loaded = self._load(registry_dir, monkeypatch)

        assert list(loaded["branches"]) == ["alpha"]
        assert log.warning.call_args_list == []

    def test_raises_on_id_mismatch(self, registry_dir: Path, monkeypatch):
        """RegistryMismatchError raised when IDs differ; mutant killed: the mismatch check disabled."""
        _write_registry(registry_dir, _minimal_registry(metadata_id="registry-AAA"))
        _write_passport(registry_dir, {"citizenship": {"registry_id": "registry-BBB"}})

        with pytest.raises(RegistryMismatchError, match="mismatch"):
            self._load(registry_dir, monkeypatch)

    def test_mismatch_error_contains_both_ids(self, registry_dir: Path, monkeypatch):
        """The error names both ids, for debugging; mutant killed: the mismatch check disabled."""
        reg_id = "registry-PROD"
        passport_id = "registry-DEV"
        _write_registry(registry_dir, _minimal_registry(metadata_id=reg_id))
        _write_passport(registry_dir, {"citizenship": {"registry_id": passport_id}})

        with pytest.raises(RegistryMismatchError) as exc_info:
            self._load(registry_dir, monkeypatch)

        msg = str(exc_info.value)
        assert passport_id in msg
        assert reg_id in msg

    def test_passes_when_metadata_key_absent(self, registry_dir: Path, monkeypatch):
        """A registry with no metadata at all loads quietly; mutant killed: metadata read as a required key."""
        _write_registry(registry_dir, {"branches": []})

        with patch.object(registry_handler, "logger") as log:
            loaded = self._load(registry_dir, monkeypatch)

        assert loaded["branches"] == {}
        assert log.warning.call_args_list == []


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
    """load_registry() drops an entry whose path escapes the project root."""

    @staticmethod
    def _loaded_names(registry_dir: Path, monkeypatch, name: str, path: str) -> list[str]:
        """Load a registry holding one entry at *path*; return the names that survived."""
        _write_registry(
            registry_dir,
            _minimal_registry(branches=[{"name": name, "path": path, "status": "active", "type": "lib"}]),
        )
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")
        monkeypatch.chdir(registry_dir)
        return list(load_registry()["branches"].keys())

    def test_valid_path_inside_project(self, registry_dir: Path, monkeypatch):
        """Path within project root is kept; mutant killed: the containment check refusing everything."""
        (registry_dir / "src" / "aipass" / "trigger").mkdir(parents=True)
        assert self._loaded_names(registry_dir, monkeypatch, "trigger", "src/aipass/trigger") == ["trigger"]

    def test_path_traversal_blocked(self, registry_dir: Path, monkeypatch):
        """A ../ path escaping the project root is dropped; mutant killed: the containment check removed."""
        assert self._loaded_names(registry_dir, monkeypatch, "evil", "src/../../evil") == []

    def test_absolute_path_outside_root_blocked(self, registry_dir: Path, tmp_path: Path, monkeypatch):
        """Absolute path outside project root is dropped; mutant killed: the containment check removed."""
        assert self._loaded_names(registry_dir, monkeypatch, "evil", str(tmp_path / "evil")) == []

    def test_exact_project_root_passes(self, registry_dir: Path, monkeypatch):
        """Path equal to project root is kept; mutant killed: the containment check refusing everything."""
        assert self._loaded_names(registry_dir, monkeypatch, "root", ".") == ["root"]

    def test_symlink_resolved(self, registry_dir: Path, monkeypatch):
        """Symlink pointing outside project root is dropped; mutant killed: the containment check removed."""
        external = Path(tempfile.mkdtemp(prefix="external_"))
        try:
            (registry_dir / "sneaky_link").symlink_to(external)
            assert self._loaded_names(registry_dir, monkeypatch, "sneaky", "sneaky_link") == []
        finally:
            shutil.rmtree(external, ignore_errors=True)

    def test_registry_rejects_traversal_entry(self, registry_dir: Path, monkeypatch):
        """A registry entry with path traversal is silently dropped during load."""
        reg = _minimal_registry(
            branches=[
                {"name": "legit", "path": "src/legit", "status": "active", "type": "lib"},
                {"name": "evil", "path": "../../../outside/evil", "status": "active", "type": "lib"},
            ]
        )
        _write_registry(registry_dir, reg)
        set_registry_path(registry_dir / "AIPASS_REGISTRY.json")

        monkeypatch.chdir(registry_dir)
        result = load_registry()
        branch_names = list(result["branches"].keys())
        assert "legit" in branch_names
        assert "evil" not in branch_names
