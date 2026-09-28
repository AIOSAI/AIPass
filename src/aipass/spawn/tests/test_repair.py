# =================== AIPass ====================
# Name: test_repair.py
# Description: Tests for repair handler — move, registry path update, pollution cleanup
# Version: 1.0.3
# Created: 2026-05-15
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/repair_ops.py — move_branch, update_registry_path, pollution cleanup."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/handlers/ and apps/modules/ parses and imports
# seedgo: no-test-needed(documentation) — that move_branch, detect_pollution and repair_project carry docstrings

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers import repair_ops
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.delete_ops import ARCHIVE_EXCLUDE as delete_ops_archive_exclude
from aipass.spawn.apps.handlers.delete_ops import delete_branch
from aipass.spawn.apps.handlers.registry import is_protected
from aipass.spawn.apps.handlers.repair_ops import (
    ARCHIVE_EXCLUDE,
    cleanup_pollution,
    detect_pollution,
    move_branch,
    repair_project,
    update_registry_path,
)
from aipass.spawn.apps.modules.repair import handle_repair
from aipass.spawn.apps.spawn import main

# Also exercises apps/spawn.py's CLI routing into the repair module, and the shared
# ARCHIVE_EXCLUDE / is_protected helpers repair_ops and delete_ops both draw on.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path, project_name="testproj", branches=None):
    """Create a minimal project with registry and optional branches."""
    project = tmp_path / project_name
    project.mkdir()

    branch_entries = []
    for b in branches or []:
        name = b["name"]
        rel_path = b.get("path", name)
        branch_dir = project / rel_path
        branch_dir.mkdir(parents=True, exist_ok=True)
        trinity = branch_dir / ".trinity"
        trinity.mkdir()
        passport = {
            "branch_info": {
                "branch_name": name.lower(),
                "path": rel_path,
                "module": f"{project_name}.{name.lower()}",
            },
            "identity": {"citizen_class": "specialist"},
            "citizenship": {"registered": True},
        }
        (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
        branch_entries.append(
            {
                "name": name,
                "path": rel_path,
                "profile": "test",
                "description": b.get("purpose", "test branch"),
                "email": f"@{name.lower()}",
                "status": "active",
                "created": "2026-01-01",
                "last_active": "2026-01-01",
            }
        )

    registry_path = project / f"{project_name.upper()}_REGISTRY.json"
    registry_data = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "total_branches": len(branch_entries),
        },
        "branches": branch_entries,
    }
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")
    return project, registry_path


def _empty_registry(project):
    """Give a tmp project a registry of its own, with no branches.

    Without one, ``is_protected`` falls back to ``find_registry()``, which walks
    up to the LIVE fleet registry — a pollution test must answer from its own
    tmp_path, never from the machine it runs on.
    """
    reg = project / f"{project.name.upper()}_REGISTRY.json"
    reg.write_text(
        json.dumps({"metadata": {"version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    return reg


# ---------------------------------------------------------------------------
# update_registry_path
# ---------------------------------------------------------------------------


class TestUpdateRegistryPath:
    """Tests for update_registry_path — path update without entry re-creation."""

    def test_updates_path_preserves_fields(self, tmp_path):
        """Path updated, creation date and name preserved."""

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = update_registry_path(reg, "NAV", "src/compass/navigator")

        assert result is True
        data = json.loads(reg.read_text(encoding="utf-8"))
        entry = data["branches"][0]
        assert entry["path"] == "src/compass/navigator"
        assert entry["created"] == "2026-01-01"
        assert entry["name"] == "NAV"

    def test_not_found_returns_false(self, tmp_path):
        """Unknown branch returns False."""

        _project, reg = _make_project(tmp_path, branches=[])
        result = update_registry_path(reg, "GHOST", "somewhere")
        assert result is False

    def test_case_insensitive_match(self, tmp_path):
        """Lowercase name matches uppercase registry entry."""

        _project, reg = _make_project(tmp_path, branches=[{"name": "POLY", "path": "polyglot"}])
        result = update_registry_path(reg, "poly", "src/aipl/polyglot")
        assert result is True
        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["branches"][0]["path"] == "src/aipl/polyglot"


# ---------------------------------------------------------------------------
# move_branch
# ---------------------------------------------------------------------------


class TestMoveBranch:
    """Tests for move_branch — relocate dir + registry + passport update."""

    def test_moves_dir_updates_registry_and_passport(self, tmp_path):
        """Full move: directory relocated, registry path updated, passport paths updated."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["success"] is True
        assert result["old_path"] == "navigator"
        assert result["new_path"] == "src/compass/navigator"

        assert not (project / "navigator").exists()
        assert (project / "src" / "compass" / "navigator").is_dir()

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["branches"][0]["path"] == "src/compass/navigator"

        passport_path = project / "src" / "compass" / "navigator" / ".trinity" / "passport.json"
        passport = json.loads(passport_path.read_text(encoding="utf-8"))
        assert passport["branch_info"]["path"] == "src/compass/navigator"

    def test_creates_archive(self, tmp_path):
        """Archive created before move contains original files."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        marker = project / "navigator" / "test_file.txt"
        marker.write_text("hello", encoding="utf-8")

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)
        assert result["success"] is True

        archive_dir = Path(result["archive_path"])
        assert archive_dir.is_dir()
        assert (archive_dir / "test_file.txt").read_text(encoding="utf-8") == "hello"

    def test_dry_run_no_changes(self, tmp_path):
        """Dry run reports actions but makes no filesystem or registry changes."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True
        assert len(result["actions"]) > 0

        assert (project / "navigator").is_dir()
        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["branches"][0]["path"] == "navigator"

    def test_source_missing_fails(self, tmp_path):
        """Fails when source directory does not exist on disk."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        shutil.rmtree(project / "navigator")

        result = move_branch("NAV", "src/nav", registry_path=reg)
        assert result["success"] is False
        assert "does not exist" in result["error"]

    def test_target_exists_fails(self, tmp_path):
        """Fails when target directory already exists."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / "src" / "compass" / "navigator").mkdir(parents=True)

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_branch_not_in_registry(self, tmp_path):
        """Fails for branch name not found in registry."""

        _project, reg = _make_project(tmp_path, branches=[])
        result = move_branch("GHOST", "somewhere", registry_path=reg)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_outside_project_root_fails(self, tmp_path):
        """Fails when target path escapes project root."""

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", str(tmp_path / "escape_attempt"), registry_path=reg)
        assert result["success"] is False
        assert "outside project root" in result["error"]

    def test_an_unreadable_passport_is_reported_as_a_failure_not_a_skip(self, tmp_path):
        """A passport that exists but cannot be read is a failure, and says so.

        False used to stand for both "no passport to update" and "the update
        failed"; spawn's decision (DPLAN-0354 leg 3) is that a failure raises in
        the helper and move_branch reports it under ``passport_error``.
        Mutant: the helper answers False for an unreadable passport -> red.
        """

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / "navigator" / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["success"] is True
        assert result["passport_updated"] is False
        assert "passport" in result["passport_error"]

    def test_a_missing_passport_is_a_skip_with_no_error(self, tmp_path):
        """No passport at all is the skip: False, and no error beside it."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / "navigator" / ".trinity" / "passport.json").unlink()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["passport_updated"] is False
        assert result["passport_error"] is None


# ---------------------------------------------------------------------------
# detect_pollution
# ---------------------------------------------------------------------------


class TestDetectPollution:
    """Tests for detect_pollution — duplicate nested directory detection."""

    def test_finds_root_duplicate(self, tmp_path):
        """Detects project_name/project_name/ at root level."""

        project = tmp_path / "compass"
        project.mkdir()
        (project / "compass").mkdir()
        _empty_registry(project)

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert issues[0]["type"] == "duplicate_nested_dir"
        assert issues[0]["path"] == "compass"

    def test_finds_src_duplicate(self, tmp_path):
        """Detects src/pkg/pkg/ duplication."""

        project = tmp_path / "myproj"
        project.mkdir()
        (project / "src" / "mypkg" / "mypkg").mkdir(parents=True)
        _empty_registry(project)

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert "src/mypkg/mypkg" in issues[0]["path"]

    def test_clean_project_no_issues(self, tmp_path):
        """Clean project returns empty issues list."""

        project = tmp_path / "clean"
        project.mkdir()
        (project / "src" / "pkg" / "agent").mkdir(parents=True)

        issues = detect_pollution(project)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# cleanup_pollution
# ---------------------------------------------------------------------------


class TestCleanupPollution:
    """Tests for cleanup_pollution — archive and remove duplicate dirs."""

    def test_archives_and_removes(self, tmp_path):
        """Pollution dir archived then removed from filesystem."""

        project = tmp_path / "compass"
        project.mkdir()
        dup = project / "compass"
        dup.mkdir()
        (dup / "junk.txt").write_text("pollution", encoding="utf-8")
        _empty_registry(project)

        result = cleanup_pollution(project)
        assert result["success"] is True
        assert result["issues_found"] == 1
        assert len(result["cleaned"]) == 1
        assert not dup.exists()
        assert (project / ".archive" / "pollution").is_dir()

    def test_dry_run_no_changes(self, tmp_path):
        """Dry run reports issues but leaves filesystem unchanged."""

        project = tmp_path / "compass"
        project.mkdir()
        dup = project / "compass"
        dup.mkdir()
        _empty_registry(project)

        result = cleanup_pollution(project, dry_run=True)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["issues_found"] == 1
        assert dup.exists()

    def test_no_pollution_returns_empty(self, tmp_path):
        """Clean project returns zero issues."""

        project = tmp_path / "clean"
        project.mkdir()

        result = cleanup_pollution(project)
        assert result["success"] is True
        assert result["issues_found"] == 0


# ---------------------------------------------------------------------------
# repair_project
# ---------------------------------------------------------------------------


class TestRepairProject:
    """Tests for repair_project — scan and report structural issues."""

    def test_detects_pollution_and_mismatches(self, tmp_path):
        """Finds both pollution and registry mismatches in one scan."""

        project, _reg = _make_project(
            tmp_path,
            project_name="compass",
            branches=[{"name": "NAV", "path": "navigator"}],
        )
        (project / "compass").mkdir()
        shutil.rmtree(project / "navigator")

        result = repair_project(project)
        assert result["success"] is True
        assert result["total_issues"] == 2
        assert len(result["pollution"]) == 1
        assert len(result["registry_mismatches"]) == 1

    def test_clean_project_no_issues(self, tmp_path):
        """Clean project reports zero issues."""

        project, _reg = _make_project(tmp_path, branches=[{"name": "AGENT", "path": "agent"}])
        result = repair_project(project)
        assert result["success"] is True
        assert result["total_issues"] == 0

    def test_no_registry_fails(self, tmp_path):
        """Fails when no *_REGISTRY.json found."""

        project = tmp_path / "empty"
        project.mkdir()

        result = repair_project(project)
        assert result["success"] is False
        assert "REGISTRY" in result["error"]

    def test_nonexistent_path_fails(self, tmp_path):
        """Fails when project path does not exist."""

        result = repair_project(tmp_path / "does_not_exist")
        assert result["success"] is False
        assert "does not exist" in result["error"]


# ---------------------------------------------------------------------------
# CLI routing
# ---------------------------------------------------------------------------


class TestRepairCLI:
    """Tests for repair CLI integration — command routing and arg parsing."""

    def test_repair_command_routes(self):
        """Verify spawn.py routes 'repair' to repair module."""

        with patch("sys.argv", ["spawn", "repair", "--help"]):
            result = main()
        assert result == 0

    def test_handle_repair_help(self):
        """--help returns exit code 0."""

        result = handle_repair(["--help"])
        assert result == 0

    def test_handle_repair_no_args(self):
        """No args returns exit code 1."""

        result = handle_repair([])
        assert result == 1

    def test_relocate_flag_moves_the_branch(self, tmp_path, monkeypatch):
        """--relocate, through handle_repair, moves the branch and rewrites its registry path.

        The world is tmp_path: its own registry, the cwd there, repair_ops's
        find_registry pointed at it, the operations log redirected by conftest.
        Mutant: the --relocate check never matches (the args fall to the scan) -> red.
        """
        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        monkeypatch.chdir(project)
        monkeypatch.setattr(repair_ops, "find_registry", lambda *a, **k: reg)

        assert handle_repair(["--relocate", "@nav", "src/compass/navigator", "--apply"]) == 0

        assert not (project / "navigator").exists()
        assert (project / "src" / "compass" / "navigator").is_dir()
        assert json.loads(reg.read_text(encoding="utf-8"))["branches"][0]["path"] == "src/compass/navigator"

    def test_relocate_artifacts_flag_moves_chroma_into_the_branch(self, tmp_path, monkeypatch):
        """--relocate-artifacts, through handle_repair, carries the root .chroma/ into the branch.

        Mutant: --relocate-artifacts ignored (relocate_artifacts = False) -> red.
        """
        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()
        monkeypatch.chdir(project)
        monkeypatch.setattr(repair_ops, "find_registry", lambda *a, **k: reg)

        args = ["--relocate", "@nav", "src/compass/navigator", "--relocate-artifacts", "--apply"]
        assert handle_repair(args) == 0

        assert not (project / ".chroma").exists()
        assert (project / "src" / "compass" / "navigator" / ".chroma").is_dir()

    def test_clean_pollution_flag_archives_the_duplicate(self, tmp_path, monkeypatch):
        """--clean-pollution, through handle_repair, archives and removes the nested duplicate.

        The project carries its own empty registry, so is_protected answers from
        tmp_path; the registry module's find_registry is pointed there too.
        Mutant: the --clean-pollution check never matches (the args fall to the
        read-only scan) -> red.
        """
        from aipass.spawn.apps.handlers import registry as registry_module

        project = tmp_path / "polluted"
        (project / "polluted").mkdir(parents=True)
        (project / "polluted" / "junk.txt").write_text("dup", encoding="utf-8")
        reg = _empty_registry(project)
        monkeypatch.chdir(project)
        monkeypatch.setattr(registry_module, "find_registry", lambda *a, **k: reg)

        assert handle_repair([str(project), "--clean-pollution", "--apply"]) == 0

        assert not (project / "polluted").exists()
        archived = list((project / ".archive" / "pollution").iterdir())
        assert len(archived) == 1
        assert (archived[0] / "junk.txt").read_text(encoding="utf-8") == "dup"


# ---------------------------------------------------------------------------
# .chroma relocation
# ---------------------------------------------------------------------------


class TestChromaRelocation:
    """Tests for .chroma artifact relocation during branch moves."""

    def test_relocates_chroma_single_branch(self, tmp_path):
        """Moves .chroma/ into branch dir when only 1 branch in registry."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        chroma = project / ".chroma"
        chroma.mkdir()
        (chroma / "data.bin").write_text("vectors", encoding="utf-8")

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is True
        assert not chroma.exists()
        assert (project / "src" / "compass" / "navigator" / ".chroma" / "data.bin").read_text(
            encoding="utf-8"
        ) == "vectors"

    def test_skips_chroma_multiple_branches(self, tmp_path):
        """Does not relocate .chroma/ when more than 1 branch exists."""

        project, reg = _make_project(
            tmp_path,
            branches=[
                {"name": "NAV", "path": "navigator"},
                {"name": "LOG", "path": "logger"},
            ],
        )
        chroma = project / ".chroma"
        chroma.mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is False
        assert chroma.exists()

    def test_skips_when_no_chroma(self, tmp_path):
        """Does not fail when .chroma/ does not exist at project root."""

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is False

    def test_skips_when_chroma_already_in_branch(self, tmp_path):
        """Does not overwrite existing .chroma/ inside the branch."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()
        (project / "navigator" / ".chroma").mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is False

    def test_no_relocation_without_flag(self, tmp_path):
        """Default relocate_artifacts=False leaves .chroma/ in place."""

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["success"] is True
        assert result.get("chroma_relocated") is False
        assert (project / ".chroma").exists()

    def test_a_failed_chroma_move_is_reported_as_a_failure_not_a_skip(self, tmp_path):
        """A .chroma move that raises is named under chroma_error, never a bare False.

        spawn's decision (DPLAN-0354 leg 3): the helper raises on failure and
        move_branch records it; False is left meaning "skipped" only.
        Mutant: the helper swallows the move error and answers False -> red.
        """

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()

        with patch.object(repair_ops, "_move_chroma", side_effect=OSError("device is full")) as move:
            result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        move.assert_called_once_with(
            str(project / ".chroma"), str((project / "src" / "compass" / "navigator").resolve() / ".chroma")
        )
        assert result["success"] is True
        assert result["chroma_relocated"] is False
        assert result["chroma_error"] == "device is full"
        assert (project / ".chroma").is_dir()

    def test_a_skipped_chroma_move_carries_no_error(self, tmp_path):
        """More than one branch is a skip: False, and chroma_error stays None."""

        project, reg = _make_project(
            tmp_path,
            branches=[{"name": "NAV", "path": "navigator"}, {"name": "LOG", "path": "logger"}],
        )
        (project / ".chroma").mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["chroma_relocated"] is False
        assert result["chroma_error"] is None


# ---------------------------------------------------------------------------
# is_protected shared helper
# ---------------------------------------------------------------------------


class TestIsProtected:
    """Tests for is_protected() — shared protection helper across repair and delete."""

    def test_hardcoded_floor_spawn(self, tmp_path):
        """spawn is protected by the hardcoded floor."""

        protected, reason = is_protected("spawn")
        assert protected is True
        assert "infrastructure" in reason

    def test_hardcoded_floor_case_insensitive(self, tmp_path):
        """Floor check is case-insensitive."""

        protected, _reason = is_protected("DEVPULSE")
        assert protected is True

    def test_registry_owner_protected(self, tmp_path):
        """Branch with owner:true in registry is protected."""

        project, reg = _make_project(tmp_path, branches=[{"name": "MYOWNER", "path": "myowner"}])
        reg_data = json.loads(reg.read_text(encoding="utf-8"))
        reg_data["branches"][0]["owner"] = True
        reg.write_text(json.dumps(reg_data), encoding="utf-8")

        protected, reason = is_protected("myowner", registry_path=reg)
        assert protected is True
        assert "owner" in reason

    def test_active_passport_protected(self, tmp_path):
        """Branch with citizenship.registered=True passport is protected."""

        project, reg = _make_project(tmp_path, branches=[{"name": "CITIZEN", "path": "citizen"}])
        protected, reason = is_protected("citizen", registry_path=reg)
        assert protected is True
        assert "citizen" in reason

    def test_no_passport_not_protected(self, tmp_path):
        """Branch without passport (no citizenship.registered) is not protected."""

        project = tmp_path / "proj"
        project.mkdir()
        branch = project / "ephemeral"
        branch.mkdir()

        reg = project / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "total_branches": 1},
                    "branches": [{"name": "EPHEMERAL", "path": "ephemeral", "status": "active"}],
                }
            ),
            encoding="utf-8",
        )

        protected, _reason = is_protected("ephemeral", registry_path=reg)
        assert protected is False

    def test_minimal_passport_not_protected(self, tmp_path):
        """Passport without citizenship.registered is not protected."""

        branch = tmp_path / "minimal"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "MINIMAL", "role": "test"}), encoding="utf-8"
        )

        protected, _reason = is_protected("minimal", branch_dir=branch, registry_path=_empty_registry(tmp_path))
        assert protected is False

    def test_unknown_branch_not_protected(self, tmp_path):
        """Completely unknown branch is not protected."""

        protected, _reason = is_protected("nonexistent", branch_dir=None, registry_path=_empty_registry(tmp_path))
        assert protected is False


# ---------------------------------------------------------------------------
# detect_pollution skips protected branches
# ---------------------------------------------------------------------------


class TestDetectPollutionProtection:
    """Tests for detect_pollution skipping protected branches."""

    def test_skips_branch_with_active_passport(self, tmp_path):
        """src/pkg/pkg/ with active passport is NOT flagged as pollution."""

        project = tmp_path / "myproj"
        project.mkdir()
        src_pkg = project / "src" / "mypkg" / "mypkg"
        src_pkg.mkdir(parents=True)

        trinity = src_pkg / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "mypkg"},
                    "identity": {"citizen_class": "specialist"},
                    "citizenship": {"registered": True},
                }
            ),
            encoding="utf-8",
        )

        reg = project / "MYPROJ_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "total_branches": 1},
                    "branches": [{"name": "MYPKG", "path": "src/mypkg/mypkg", "status": "active"}],
                }
            ),
            encoding="utf-8",
        )

        issues = detect_pollution(project)
        assert len(issues) == 0

    def test_still_flags_real_pollution(self, tmp_path):
        """src/pkg/pkg/ without passport IS flagged as pollution."""

        project = tmp_path / "myproj"
        project.mkdir()
        (project / "src" / "mypkg" / "mypkg").mkdir(parents=True)
        _empty_registry(project)

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert issues[0]["type"] == "duplicate_nested_dir"

    def test_skips_owner_branch_at_root(self, tmp_path):
        """project/project/ with owner flag is NOT flagged as pollution."""

        project = tmp_path / "compass"
        project.mkdir()
        nested = project / "compass"
        nested.mkdir()

        reg = project / "COMPASS_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "total_branches": 1},
                    "branches": [{"name": "COMPASS", "path": "compass", "status": "active", "owner": True}],
                }
            ),
            encoding="utf-8",
        )

        issues = detect_pollution(project)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# delete_branch refuses owner branches
# ---------------------------------------------------------------------------


class TestDeleteOwnerProtection:
    """Tests for delete_branch refusing registry-owner branches."""

    def test_delete_owner_refused(self, tmp_path):
        """Cannot delete a branch with owner:true in registry."""
        project = tmp_path / "repo"
        project.mkdir()
        branch = project / "src" / "aipass" / "aipass_branch"
        branch.mkdir(parents=True)
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "identity": {"citizen_class": "manager"},
                    "citizenship": {"registered": True},
                }
            ),
            encoding="utf-8",
        )

        reg = project / "AIPASS_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "total_branches": 1},
                    "branches": [
                        {
                            "name": "AIPASS_BRANCH",
                            "path": "src/aipass/aipass_branch",
                            "status": "active",
                            "owner": True,
                            "email": "@aipass_branch",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=reg):
            result = delete_branch("aipass_branch", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()
        assert "owner" in result.get("error", "").lower()
        assert branch.exists()


# ---------------------------------------------------------------------------
# ARCHIVE_EXCLUDE shared constant
# ---------------------------------------------------------------------------


class TestArchiveExclude:
    """Tests for ARCHIVE_EXCLUDE constant shared between repair_ops and delete_ops."""

    def test_archive_exclude_defined_in_repair_ops(self, tmp_path):
        """ARCHIVE_EXCLUDE is a set in repair_ops, and the pollution archive honours it.

        Mutant: cleanup_pollution copies without the ARCHIVE_EXCLUDE ignore -> red.
        """

        assert isinstance(ARCHIVE_EXCLUDE, set)
        assert ".venv" in ARCHIVE_EXCLUDE
        assert ".git" in ARCHIVE_EXCLUDE

        project = tmp_path / "compass"
        dup = project / "compass"
        (dup / ".venv").mkdir(parents=True)
        (dup / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        (dup / "junk.txt").write_text("pollution", encoding="utf-8")
        _empty_registry(project)

        result = cleanup_pollution(project)

        archive = Path(result["cleaned"][0]["archive"])
        assert sorted(p.name for p in archive.iterdir()) == ["junk.txt"]

    def test_delete_ops_imports_archive_exclude(self):
        """delete_ops imports ARCHIVE_EXCLUDE from repair_ops (same object)."""
        assert delete_ops_archive_exclude is ARCHIVE_EXCLUDE


# ---------------------------------------------------------------------------
# Template file checks
# ---------------------------------------------------------------------------


class TestTemplateFiles:
    """Tests for template file additions — .gitignore and requirements.project.txt.

    The class-named template dirs are gone (DPLAN-0319 R3): manager and specialist
    mint from the ONE ``templates/citizen/`` dir, so these read the live template
    through ``get_template_dir()`` rather than hardcoding a directory name that a
    future rename can silently point at nothing.
    """

    def _template(self):

        return get_template_dir()

    def test_citizen_gitignore_has_venv(self):
        """The citizen template .gitignore includes the .venv/ entry."""
        content = (self._template() / ".gitignore").read_text(encoding="utf-8")
        assert ".venv/" in content

    def test_requirements_project_exists(self):
        """The citizen template includes requirements.project.txt."""
        req = self._template() / "requirements.project.txt"
        assert req.exists()
        content = req.read_text(encoding="utf-8")
        assert "Project-specific" in content

    def test_retired_class_named_template_dirs_are_archived_not_live(self):
        """R3: the class-named template dirs were ARCHIVED, never straight-deleted.

        Two halves with different reach: nothing-mints-from-a-class-named-dir is
        the shipped contract and holds everywhere; the archived-trees-still-on-disk
        half is a LIVE-MACHINE fact — .archive/ is gitignored by design, so a
        clean checkout legitimately has none. Absent archive = environment fact,
        skipped loudly, never scored as a deletion (the clean-checkout
        discriminator; this exact test was CI-red on a tree that never carried
        the archive).
        """
        templates = Path(__file__).resolve().parent.parent / "templates"

        for retired in ("aipass_framework", "project_agent"):
            assert not (templates / retired).exists(), f"templates/{retired}/ is live again"

        assert (templates / "citizen").is_dir()

        archive = templates / ".archive"
        if not archive.is_dir():
            pytest.skip("templates/.archive/ absent — clean checkout; the archive half is a live-machine fact")
        for retired in ("aipass_framework", "project_agent"):
            assert (archive / retired).is_dir(), f"templates/{retired}/ was deleted, not archived"


# ---------------------------------------------------------------------------
# Case-insensitive volumes: the glob is not a filter everywhere it runs
# ---------------------------------------------------------------------------


def _case_insensitive_listing(monkeypatch):
    """Make repair_ops's registry listing behave the way a Windows volume does.

    The defect is not in the reader — it is in what the FILESYSTEM hands the
    reader back, so this supplies that listing rather than patching the code
    under test. Matching the pattern with ``re.IGNORECASE`` is exactly what a
    case-insensitive volume does, and it means these pins run RED on the Linux
    dev box instead of only on the Windows gate (@drone's construction, adopted
    here on @devpulse's relay, 2026-08-31).

    It patches the listing seam ``_list_registry_candidates`` (whose body is
    exactly the glob), not ``pathlib.Path.glob`` process-wide (spawn's decision,
    DPLAN-0354 leg 3). Returns the list of roots the seam was asked to list.
    """
    import fnmatch
    import re

    calls = []
    rx = re.compile(fnmatch.translate("*" + repair_ops.REGISTRY_SUFFIX), re.IGNORECASE)

    def insensitive_listing(root):
        calls.append(root)
        return iter(sorted(p for p in root.iterdir() if rx.match(p.name)))

    monkeypatch.setattr(repair_ops, "_list_registry_candidates", insensitive_listing)
    return calls


class TestRegistryLookupIsCaseSensitive:
    """A repair lane must never read a template counter as the registry.

    ``.template_registry.json`` (every branch has one) and the ten ``flow_json``
    plan counters are lowercase, and ``pathlib``'s ``*`` matches dotted names
    unlike a shell glob. On a case-insensitive volume the glob returns them, and
    a dotted name sorts FIRST — so the unfiltered lookup handed
    ``.template_registry.json`` to the code that repairs registries.

    Both pins below are red without the suffix filter and green with it.
    """

    def test_a_lowercase_lookalike_is_not_served_as_the_registry(self, tmp_path, monkeypatch):
        """The lookup reads the listing seam and filters what it lists.

        Mutant: _registry_in globs inline instead of calling the seam -> red.
        """

        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text(json.dumps({"branches": []}), encoding="utf-8")
        decoy = tmp_path / ".template_registry.json"
        decoy.write_text(json.dumps({"files": {}}), encoding="utf-8")

        calls = _case_insensitive_listing(monkeypatch)

        # The decoy sorts first, so an unfiltered first-match returns it.
        assert sorted(p.name for p in repair_ops._list_registry_candidates(tmp_path))[0] == decoy.name
        calls.clear()

        # Reached through repair_project, the public door onto the one lookup.
        # Mutant: the lookup drops its case-sensitive suffix check -> red.
        assert repair_project(tmp_path, dry_run=True)["registry"] == real.name
        # The lookup asked the seam (once for the scan, once for the pollution
        # check), so the stand-in listing is what it read.
        # Mutant: _registry_in globs inline instead of calling the seam -> red.
        assert calls == [tmp_path.resolve(), tmp_path.resolve()]

    def test_repair_project_reports_the_real_registry(self, tmp_path, monkeypatch):
        """End-to-end through the call site, not just the helper."""

        project = tmp_path / "someproj"
        project.mkdir()
        (project / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        (project / ".template_registry.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        (project / "flow_plans_registry.json").write_text("{}", encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        result = repair_project(project, dry_run=True)

        assert result["success"] is True
        assert result["registry"] == "AIPASS_REGISTRY.json"

    def test_an_external_lowercase_stem_is_still_a_registry(self, tmp_path, monkeypatch):
        """Suffix only, never the stem — external projects name their own."""

        theirs = tmp_path / "vera_studio_REGISTRY.json"
        theirs.write_text(json.dumps({"branches": []}), encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        assert repair_project(tmp_path, dry_run=True)["registry"] == theirs.name

    def test_absence_is_reported_as_absence(self, tmp_path, monkeypatch):

        (tmp_path / ".template_registry.json").write_text("{}", encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        result = repair_project(tmp_path, dry_run=True)
        assert result["success"] is False
        assert result["error"] == f"No *_REGISTRY.json found in {tmp_path.resolve()}"

    def test_both_call_sites_go_through_the_one_lookup(self):
        """The extraction is the fix — a second inline glob would undo it."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(repair_ops))
        inline = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"glob", "rglob"}
            and any(
                isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.upper().endswith("_REGISTRY.JSON")
                for a in node.args
            )
        ]
        assert inline == [], (
            "an unfiltered registry glob is back at line(s) "
            f"{inline} — route it through _registry_in, which case-checks the name"
        )
