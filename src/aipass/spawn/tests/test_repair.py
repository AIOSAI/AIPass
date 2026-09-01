# =================== AIPass ====================
# Name: test_repair.py
# Description: Tests for repair handler — move, registry path update, pollution cleanup
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""Tests for repair handler — move_branch, update_registry_path, pollution cleanup."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest


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


# ---------------------------------------------------------------------------
# update_registry_path
# ---------------------------------------------------------------------------


class TestUpdateRegistryPath:
    """Tests for update_registry_path — path update without entry re-creation."""

    def test_updates_path_preserves_fields(self, tmp_path):
        """Path updated, creation date and name preserved."""
        from aipass.spawn.apps.handlers.repair_ops import update_registry_path

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = update_registry_path(reg, "NAV", "src/compass/navigator")

        assert result is True
        data = json.loads(reg.read_text())
        entry = data["branches"][0]
        assert entry["path"] == "src/compass/navigator"
        assert entry["created"] == "2026-01-01"
        assert entry["name"] == "NAV"

    def test_not_found_returns_false(self, tmp_path):
        """Unknown branch returns False."""
        from aipass.spawn.apps.handlers.repair_ops import update_registry_path

        _project, reg = _make_project(tmp_path, branches=[])
        result = update_registry_path(reg, "GHOST", "somewhere")
        assert result is False

    def test_case_insensitive_match(self, tmp_path):
        """Lowercase name matches uppercase registry entry."""
        from aipass.spawn.apps.handlers.repair_ops import update_registry_path

        _project, reg = _make_project(tmp_path, branches=[{"name": "POLY", "path": "polyglot"}])
        result = update_registry_path(reg, "poly", "src/aipl/polyglot")
        assert result is True
        data = json.loads(reg.read_text())
        assert data["branches"][0]["path"] == "src/aipl/polyglot"


# ---------------------------------------------------------------------------
# move_branch
# ---------------------------------------------------------------------------


class TestMoveBranch:
    """Tests for move_branch — relocate dir + registry + passport update."""

    def test_moves_dir_updates_registry_and_passport(self, tmp_path):
        """Full move: directory relocated, registry path updated, passport paths updated."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["success"] is True
        assert result["old_path"] == "navigator"
        assert result["new_path"] == "src/compass/navigator"

        assert not (project / "navigator").exists()
        assert (project / "src" / "compass" / "navigator").is_dir()

        data = json.loads(reg.read_text())
        assert data["branches"][0]["path"] == "src/compass/navigator"

        passport_path = project / "src" / "compass" / "navigator" / ".trinity" / "passport.json"
        passport = json.loads(passport_path.read_text())
        assert passport["branch_info"]["path"] == "src/compass/navigator"

    def test_creates_archive(self, tmp_path):
        """Archive created before move contains original files."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        marker = project / "navigator" / "test_file.txt"
        marker.write_text("hello")

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)
        assert result["success"] is True

        archive_dir = Path(result["archive_path"])
        assert archive_dir.is_dir()
        assert (archive_dir / "test_file.txt").read_text() == "hello"

    def test_dry_run_no_changes(self, tmp_path):
        """Dry run reports actions but makes no filesystem or registry changes."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True
        assert len(result["actions"]) > 0

        assert (project / "navigator").is_dir()
        data = json.loads(reg.read_text())
        assert data["branches"][0]["path"] == "navigator"

    def test_source_missing_fails(self, tmp_path):
        """Fails when source directory does not exist on disk."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        shutil.rmtree(project / "navigator")

        result = move_branch("NAV", "src/nav", registry_path=reg)
        assert result["success"] is False
        assert "does not exist" in result["error"]

    def test_target_exists_fails(self, tmp_path):
        """Fails when target directory already exists."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / "src" / "compass" / "navigator").mkdir(parents=True)

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_branch_not_in_registry(self, tmp_path):
        """Fails for branch name not found in registry."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        _project, reg = _make_project(tmp_path, branches=[])
        result = move_branch("GHOST", "somewhere", registry_path=reg)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_outside_project_root_fails(self, tmp_path):
        """Fails when target path escapes project root."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", str(tmp_path / "escape_attempt"), registry_path=reg)
        assert result["success"] is False
        assert "outside project root" in result["error"]


# ---------------------------------------------------------------------------
# detect_pollution
# ---------------------------------------------------------------------------


class TestDetectPollution:
    """Tests for detect_pollution — duplicate nested directory detection."""

    def test_finds_root_duplicate(self, tmp_path):
        """Detects project_name/project_name/ at root level."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

        project = tmp_path / "compass"
        project.mkdir()
        (project / "compass").mkdir()

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert issues[0]["type"] == "duplicate_nested_dir"
        assert issues[0]["path"] == "compass"

    def test_finds_src_duplicate(self, tmp_path):
        """Detects src/pkg/pkg/ duplication."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

        project = tmp_path / "myproj"
        project.mkdir()
        (project / "src" / "mypkg" / "mypkg").mkdir(parents=True)

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert "src/mypkg/mypkg" in issues[0]["path"]

    def test_clean_project_no_issues(self, tmp_path):
        """Clean project returns empty issues list."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

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
        from aipass.spawn.apps.handlers.repair_ops import cleanup_pollution

        project = tmp_path / "compass"
        project.mkdir()
        dup = project / "compass"
        dup.mkdir()
        (dup / "junk.txt").write_text("pollution")

        result = cleanup_pollution(project)
        assert result["success"] is True
        assert result["issues_found"] == 1
        assert len(result["cleaned"]) == 1
        assert not dup.exists()
        assert (project / ".archive" / "pollution").is_dir()

    def test_dry_run_no_changes(self, tmp_path):
        """Dry run reports issues but leaves filesystem unchanged."""
        from aipass.spawn.apps.handlers.repair_ops import cleanup_pollution

        project = tmp_path / "compass"
        project.mkdir()
        dup = project / "compass"
        dup.mkdir()

        result = cleanup_pollution(project, dry_run=True)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["issues_found"] == 1
        assert dup.exists()

    def test_no_pollution_returns_empty(self, tmp_path):
        """Clean project returns zero issues."""
        from aipass.spawn.apps.handlers.repair_ops import cleanup_pollution

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
        from aipass.spawn.apps.handlers.repair_ops import repair_project

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
        from aipass.spawn.apps.handlers.repair_ops import repair_project

        project, _reg = _make_project(tmp_path, branches=[{"name": "AGENT", "path": "agent"}])
        result = repair_project(project)
        assert result["success"] is True
        assert result["total_issues"] == 0

    def test_no_registry_fails(self, tmp_path):
        """Fails when no *_REGISTRY.json found."""
        from aipass.spawn.apps.handlers.repair_ops import repair_project

        project = tmp_path / "empty"
        project.mkdir()

        result = repair_project(project)
        assert result["success"] is False
        assert "REGISTRY" in result["error"]

    def test_nonexistent_path_fails(self, tmp_path):
        """Fails when project path does not exist."""
        from aipass.spawn.apps.handlers.repair_ops import repair_project

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
        from aipass.spawn.apps.spawn import main

        with patch("sys.argv", ["spawn", "repair", "--help"]):
            result = main()
        assert result == 0

    def test_handle_repair_help(self):
        """--help returns exit code 0."""
        from aipass.spawn.apps.modules.repair import handle_repair

        result = handle_repair(["--help"])
        assert result == 0

    def test_handle_repair_no_args(self):
        """No args returns exit code 1."""
        from aipass.spawn.apps.modules.repair import handle_repair

        result = handle_repair([])
        assert result == 1


# ---------------------------------------------------------------------------
# .chroma relocation
# ---------------------------------------------------------------------------


class TestChromaRelocation:
    """Tests for .chroma artifact relocation during branch moves."""

    def test_relocates_chroma_single_branch(self, tmp_path):
        """Moves .chroma/ into branch dir when only 1 branch in registry."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        chroma = project / ".chroma"
        chroma.mkdir()
        (chroma / "data.bin").write_text("vectors")

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is True
        assert not chroma.exists()
        assert (project / "src" / "compass" / "navigator" / ".chroma" / "data.bin").read_text() == "vectors"

    def test_skips_chroma_multiple_branches(self, tmp_path):
        """Does not relocate .chroma/ when more than 1 branch exists."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

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
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        _project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is False

    def test_skips_when_chroma_already_in_branch(self, tmp_path):
        """Does not overwrite existing .chroma/ inside the branch."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()
        (project / "navigator" / ".chroma").mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg, relocate_artifacts=True)

        assert result["success"] is True
        assert result["chroma_relocated"] is False

    def test_no_relocation_without_flag(self, tmp_path):
        """Default relocate_artifacts=False leaves .chroma/ in place."""
        from aipass.spawn.apps.handlers.repair_ops import move_branch

        project, reg = _make_project(tmp_path, branches=[{"name": "NAV", "path": "navigator"}])
        (project / ".chroma").mkdir()

        result = move_branch("NAV", "src/compass/navigator", registry_path=reg)

        assert result["success"] is True
        assert result.get("chroma_relocated") is False
        assert (project / ".chroma").exists()


# ---------------------------------------------------------------------------
# is_protected shared helper
# ---------------------------------------------------------------------------


class TestIsProtected:
    """Tests for is_protected() — shared protection helper across repair and delete."""

    def test_hardcoded_floor_spawn(self, tmp_path):
        """spawn is protected by the hardcoded floor."""
        from aipass.spawn.apps.handlers.registry import is_protected

        protected, reason = is_protected("spawn")
        assert protected is True
        assert "infrastructure" in reason

    def test_hardcoded_floor_case_insensitive(self, tmp_path):
        """Floor check is case-insensitive."""
        from aipass.spawn.apps.handlers.registry import is_protected

        protected, _reason = is_protected("DEVPULSE")
        assert protected is True

    def test_registry_owner_protected(self, tmp_path):
        """Branch with owner:true in registry is protected."""
        from aipass.spawn.apps.handlers.registry import is_protected

        project, reg = _make_project(tmp_path, branches=[{"name": "MYOWNER", "path": "myowner"}])
        reg_data = json.loads(reg.read_text())
        reg_data["branches"][0]["owner"] = True
        reg.write_text(json.dumps(reg_data))

        protected, reason = is_protected("myowner", registry_path=reg)
        assert protected is True
        assert "owner" in reason

    def test_active_passport_protected(self, tmp_path):
        """Branch with citizenship.registered=True passport is protected."""
        from aipass.spawn.apps.handlers.registry import is_protected

        project, reg = _make_project(tmp_path, branches=[{"name": "CITIZEN", "path": "citizen"}])
        protected, reason = is_protected("citizen", registry_path=reg)
        assert protected is True
        assert "citizen" in reason

    def test_no_passport_not_protected(self, tmp_path):
        """Branch without passport (no citizenship.registered) is not protected."""
        from aipass.spawn.apps.handlers.registry import is_protected

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
            )
        )

        protected, _reason = is_protected("ephemeral", registry_path=reg)
        assert protected is False

    def test_minimal_passport_not_protected(self, tmp_path):
        """Passport without citizenship.registered is not protected."""
        from aipass.spawn.apps.handlers.registry import is_protected

        branch = tmp_path / "minimal"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(json.dumps({"name": "MINIMAL", "role": "test"}))

        protected, _reason = is_protected("minimal", branch_dir=branch)
        assert protected is False

    def test_unknown_branch_not_protected(self):
        """Completely unknown branch is not protected."""
        from aipass.spawn.apps.handlers.registry import is_protected

        protected, _reason = is_protected("nonexistent", branch_dir=None, registry_path=None)
        assert protected is False


# ---------------------------------------------------------------------------
# detect_pollution skips protected branches
# ---------------------------------------------------------------------------


class TestDetectPollutionProtection:
    """Tests for detect_pollution skipping protected branches."""

    def test_skips_branch_with_active_passport(self, tmp_path):
        """src/pkg/pkg/ with active passport is NOT flagged as pollution."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

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
            )
        )

        reg = project / "MYPROJ_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "total_branches": 1},
                    "branches": [{"name": "MYPKG", "path": "src/mypkg/mypkg", "status": "active"}],
                }
            )
        )

        issues = detect_pollution(project)
        assert len(issues) == 0

    def test_still_flags_real_pollution(self, tmp_path):
        """src/pkg/pkg/ without passport IS flagged as pollution."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

        project = tmp_path / "myproj"
        project.mkdir()
        (project / "src" / "mypkg" / "mypkg").mkdir(parents=True)

        issues = detect_pollution(project)
        assert len(issues) == 1
        assert issues[0]["type"] == "duplicate_nested_dir"

    def test_skips_owner_branch_at_root(self, tmp_path):
        """project/project/ with owner flag is NOT flagged as pollution."""
        from aipass.spawn.apps.handlers.repair_ops import detect_pollution

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
            )
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
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

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
            )
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
            )
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

    def test_archive_exclude_defined_in_repair_ops(self):
        """ARCHIVE_EXCLUDE is a set in repair_ops."""
        from aipass.spawn.apps.handlers.repair_ops import ARCHIVE_EXCLUDE

        assert isinstance(ARCHIVE_EXCLUDE, set)
        assert ".venv" in ARCHIVE_EXCLUDE
        assert ".git" in ARCHIVE_EXCLUDE

    def test_delete_ops_imports_archive_exclude(self):
        """delete_ops imports ARCHIVE_EXCLUDE from repair_ops (same object)."""
        from aipass.spawn.apps.handlers.delete_ops import ARCHIVE_EXCLUDE as del_exclude
        from aipass.spawn.apps.handlers.repair_ops import ARCHIVE_EXCLUDE as rep_exclude

        assert del_exclude is rep_exclude


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
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        return get_template_dir()

    def test_citizen_gitignore_has_venv(self):
        """The citizen template .gitignore includes the .venv/ entry."""
        content = (self._template() / ".gitignore").read_text()
        assert ".venv/" in content

    def test_requirements_project_exists(self):
        """The citizen template includes requirements.project.txt."""
        req = self._template() / "requirements.project.txt"
        assert req.exists()
        content = req.read_text()
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
    """Make pathlib's glob behave the way a Windows volume does.

    The defect is not in the reader — it is in what the FILESYSTEM hands the
    reader back, so this supplies that listing rather than patching the code
    under test. Matching the pattern with ``re.IGNORECASE`` is exactly what a
    case-insensitive volume does, and it means these pins run RED on the Linux
    dev box instead of only on the Windows gate (@drone's construction, adopted
    here on @devpulse's relay, 2026-08-31).
    """
    import fnmatch
    import pathlib
    import re

    real_glob = pathlib.Path.glob

    def insensitive_glob(self, pattern, *args, **kwargs):
        if "/" in pattern or "**" in pattern:
            return real_glob(self, pattern, *args, **kwargs)
        rx = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        return iter(sorted(p for p in self.iterdir() if rx.match(p.name)))

    monkeypatch.setattr(pathlib.Path, "glob", insensitive_glob)


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
        from aipass.spawn.apps.handlers.repair_ops import _registry_in

        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text(json.dumps({"branches": []}), encoding="utf-8")
        decoy = tmp_path / ".template_registry.json"
        decoy.write_text(json.dumps({"files": {}}), encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        # The decoy sorts first, so an unfiltered first-match returns it.
        assert sorted(p.name for p in tmp_path.glob("*_REGISTRY.json"))[0] == decoy.name

        assert _registry_in(tmp_path) == real

    def test_repair_project_reports_the_real_registry(self, tmp_path, monkeypatch):
        """End-to-end through the call site, not just the helper."""
        from aipass.spawn.apps.handlers.repair_ops import repair_project

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
        from aipass.spawn.apps.handlers.repair_ops import _registry_in

        theirs = tmp_path / "vera_studio_REGISTRY.json"
        theirs.write_text(json.dumps({"branches": []}), encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        assert _registry_in(tmp_path) == theirs

    def test_absence_is_reported_as_absence(self, tmp_path, monkeypatch):
        from aipass.spawn.apps.handlers.repair_ops import _registry_in

        (tmp_path / ".template_registry.json").write_text("{}", encoding="utf-8")

        _case_insensitive_listing(monkeypatch)

        assert _registry_in(tmp_path) is None

    def test_both_call_sites_go_through_the_one_lookup(self):
        """The extraction is the fix — a second inline glob would undo it."""
        import ast
        import inspect

        from aipass.spawn.apps.handlers import repair_ops

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
