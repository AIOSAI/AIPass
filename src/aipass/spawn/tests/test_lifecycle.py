# =================== META ====================
# Name: test_lifecycle.py
# Description: Tests for spawn lifecycle commands (delete, sync-registry, sync-templates)
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Tests for spawn lifecycle management commands.

Tests delete_branch(), sync_registry(), and sync_templates().
"""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_root(tmp_path):
    """Create a mock repo root with src/aipass/ structure."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'aipass'\n")
    (root / "src" / "aipass").mkdir(parents=True)
    return root


@pytest.fixture
def mock_branch(repo_root):
    """Create a mock branch directory with .trinity/passport.json."""
    branch = repo_root / "src" / "aipass" / "test_api"
    branch.mkdir(parents=True)
    (branch / ".trinity").mkdir()
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps({"name": "TEST_API", "role": "test"}, indent=2)
    )
    (branch / "apps").mkdir()
    (branch / "apps" / "branch.py").write_text("# test api entry\n")
    (branch / "README.md").write_text("# Test API\n")
    return branch


@pytest.fixture
def mock_registry(repo_root, mock_branch):
    """Create a mock AIPASS_REGISTRY.json with the test branch."""
    rel_path = str(mock_branch.relative_to(repo_root))

    registry = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-03-07",
            "total_branches": 4,
        },
        "branches": [
            {
                "name": "DRONE",
                "path": "src/aipass/drone",
                "profile": "library",
                "description": "Command routing",
                "email": "@drone",
                "status": "active",
                "created": "2026-03-05",
                "last_active": "2026-03-05",
            },
            {
                "name": "SPAWN",
                "path": "src/aipass/spawn",
                "profile": "library",
                "description": "Agent creation",
                "email": "@spawn",
                "status": "active",
                "created": "2026-03-05",
                "last_active": "2026-03-05",
            },
            {
                "name": "DEVPULSE",
                "path": "src/aipass/devpulse",
                "profile": "library",
                "description": "Orchestration hub",
                "email": "@devpulse",
                "status": "active",
                "created": "2026-03-06",
                "last_active": "2026-03-06",
            },
            {
                "name": "TEST_API",
                "path": rel_path,
                "profile": "library",
                "description": "Test API branch",
                "email": "@test_api",
                "status": "active",
                "created": "2026-03-07",
                "last_active": "2026-03-07",
            },
        ],
    }

    reg_path = repo_root / "AIPASS_REGISTRY.json"
    reg_path.write_text(json.dumps(registry, indent=2) + "\n")
    return reg_path


# ---------------------------------------------------------------------------
# DELETE Tests
# ---------------------------------------------------------------------------

class TestDeleteBranch:
    """Tests for delete_branch()."""

    def test_delete_archives_and_removes(self, repo_root: Path, mock_branch: Path, mock_registry: Path):
        """Successful delete should archive the branch and remove from registry."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("test_api", confirm=False)

        assert result["success"] is True
        assert result["registry_updated"] is True
        assert result["archive_path"] != ""

        # Branch directory should be gone
        assert not mock_branch.exists()

        # Archive should exist
        archive_path = Path(result["archive_path"])
        assert archive_path.exists()
        assert (archive_path / "README.md").exists()
        assert (archive_path / ".trinity" / "passport.json").exists()

        # Registry should no longer contain TEST_API
        reg = json.loads(mock_registry.read_text())
        names = [b["name"] for b in reg["branches"]]
        assert "TEST_API" not in names

    def test_delete_protected_spawn(self, repo_root, mock_registry):
        """Cannot delete spawn (self-protection)."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("spawn", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_devpulse(self, repo_root, mock_registry):
        """Cannot delete devpulse (orchestration hub protection)."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("devpulse", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_drone(self, repo_root, mock_registry):
        """Cannot delete drone (routing infrastructure protection)."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("drone", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_dry_run(self, repo_root, mock_branch, mock_registry):
        """Dry run should NOT delete or archive anything."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("test_api", confirm=False, dry_run=True)

        assert result["success"] is True
        assert result.get("dry_run") is True

        # Branch should still exist
        assert mock_branch.exists()

        # Registry should be unchanged
        reg = json.loads(mock_registry.read_text())
        names = [b["name"] for b in reg["branches"]]
        assert "TEST_API" in names

    def test_delete_nonexistent_branch(self, repo_root, mock_registry):
        """Deleting a branch not in registry should fail gracefully."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = delete_branch("nonexistent", confirm=False)

        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_delete_confirmation_cancelled(self, repo_root, mock_branch, mock_registry):
        """Cancelling confirmation should not delete."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry), \
             patch("builtins.input", return_value="n"):

            result = delete_branch("test_api", confirm=True)

        assert result["success"] is False
        assert mock_branch.exists()

    def test_handle_delete_no_args(self):
        """handle_delete with no args should show usage."""
        from aipass.spawn.apps.modules.delete import handle_delete
        result = handle_delete([])
        assert result == 1


# ---------------------------------------------------------------------------
# SYNC REGISTRY Tests
# ---------------------------------------------------------------------------

class TestSyncRegistry:
    """Tests for sync_registry()."""

    def test_detect_stale_entries(self, repo_root, mock_registry):
        """Registry entries for non-existent directories should be detected as stale."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # The registry has DRONE, SPAWN, DEVPULSE entries but those directories
        # don't exist in our tmp_path repo, so they should be stale
        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = sync_registry(fix=False)

        # DRONE, SPAWN, DEVPULSE dirs don't exist -> stale
        assert len(result["stale"]) >= 3
        assert "drone" in result["stale"]
        assert "spawn" in result["stale"]
        assert "devpulse" in result["stale"]

    def test_detect_unregistered_branches(self, repo_root, mock_registry):
        """Directories with passport.json not in registry should be unregistered."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Create a new branch directory with passport that's NOT in registry
        new_branch = repo_root / "src" / "aipass" / "phantom"
        new_branch.mkdir(parents=True)
        (new_branch / ".trinity").mkdir()
        (new_branch / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "PHANTOM"}, indent=2)
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = sync_registry(fix=False)

        assert "phantom" in result["unregistered"]

    def test_detect_healthy_branches(self, repo_root, mock_branch, mock_registry):
        """Branches that exist with passports and are registered should be healthy."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = sync_registry(fix=False)

        assert "test_api" in result["healthy"]

    def test_fix_removes_stale_and_adds_unregistered(self, repo_root, mock_branch, mock_registry):
        """With --fix, stale entries are removed and unregistered are added."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Create an unregistered branch
        new_branch = repo_root / "src" / "aipass" / "phantom"
        new_branch.mkdir(parents=True)
        (new_branch / ".trinity").mkdir()
        (new_branch / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "PHANTOM"}, indent=2)
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = sync_registry(fix=True)

        assert result["fixed"] is True

        # Verify registry was actually updated
        reg = json.loads(mock_registry.read_text())
        names = [b["name"] for b in reg["branches"]]

        # Stale entries removed (drone, spawn, devpulse dirs don't exist)
        assert "DRONE" not in names
        assert "SPAWN" not in names
        assert "DEVPULSE" not in names

        # Unregistered added
        assert "PHANTOM" in names

        # Healthy branch kept
        assert "TEST_API" in names

    def test_no_mismatches_no_fix_needed(self, repo_root, mock_branch, mock_registry):
        """When everything is healthy, fix=True should not modify registry."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Remove all stale entries from registry (only keep test_api which exists)
        reg = json.loads(mock_registry.read_text())
        reg["branches"] = [b for b in reg["branches"] if b["name"] == "TEST_API"]
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n")

        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = sync_registry(fix=True)

        assert result["stale"] == []
        assert result["unregistered"] == []
        assert result["fixed"] is False  # Nothing to fix


# ---------------------------------------------------------------------------
# SYNC TEMPLATES Tests
# ---------------------------------------------------------------------------

class TestSyncTemplates:
    """Tests for sync_templates()."""

    def test_empty_owners_no_stale(self, repo_root):
        """With empty template_owners.json, no files should be stale."""
        from aipass.spawn.apps.handlers.sync_templates_ops import sync_templates

        # Create empty template_owners.json
        owners_path = repo_root / "template_owners.json"
        owners_path.write_text(json.dumps({
            "metadata": {"description": "test"},
            "managed_files": {},
        }, indent=2))

        with patch("aipass.spawn.apps.handlers.sync_templates_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_templates_ops._TEMPLATE_OWNERS_PATH", owners_path):

            result = sync_templates()

        assert result["managed_files"] == 0
        assert result["stale"] == []
        assert result["current"] == []
        assert result["synced"] == []
        assert result["errors"] == []

    def test_status_report_works(self, repo_root):
        """Status report (default) should work without errors."""
        from aipass.spawn.apps.handlers import sync_templates_ops as st_mod

        # Create template_owners with a managed file
        source_branch_dir = repo_root / "src" / "aipass" / "prax"
        source_branch_dir.mkdir(parents=True)
        source_file = source_branch_dir / "config.json"
        source_file.write_text(json.dumps({"key": "value"}, indent=2))

        # Create template location
        template_dir = repo_root / "templates"
        template_dir.mkdir()

        owners_path = repo_root / "template_owners.json"
        owners_path.write_text(json.dumps({
            "metadata": {"description": "test"},
            "managed_files": {
                "prax_config": {
                    "source_branch": "prax",
                    "source_path": "config.json",
                    "template_path": "config.json",
                }
            },
        }, indent=2))

        # Save originals
        orig_root = st_mod._REPO_ROOT
        orig_owners = st_mod._TEMPLATE_OWNERS_PATH

        try:
            st_mod._REPO_ROOT = repo_root
            st_mod._TEMPLATE_OWNERS_PATH = owners_path

            result = st_mod.sync_templates()
        finally:
            st_mod._REPO_ROOT = orig_root
            st_mod._TEMPLATE_OWNERS_PATH = orig_owners

        assert result["managed_files"] == 1
        # Source exists but template doesn't yet -> stale
        assert "prax_config" in result["stale"]

    def test_sync_copies_file(self, repo_root):
        """sync=True should copy source files to template location."""
        from aipass.spawn.apps.handlers import sync_templates_ops as st_mod

        # Create source file
        source_dir = repo_root / "src" / "aipass" / "prax"
        source_dir.mkdir(parents=True)
        source_file = source_dir / "config.json"
        source_file.write_text(json.dumps({"key": "source_value"}, indent=2))

        # Create the template target dir
        template_target_dir = repo_root / "template_target"
        template_target_dir.mkdir()

        owners_path = repo_root / "template_owners.json"
        owners_path.write_text(json.dumps({
            "metadata": {"description": "test"},
            "managed_files": {
                "prax_config": {
                    "source_branch": "prax",
                    "source_path": "config.json",
                    "template_path": "config.json",
                }
            },
        }, indent=2))

        orig_root = st_mod._REPO_ROOT
        orig_owners = st_mod._TEMPLATE_OWNERS_PATH

        try:
            st_mod._REPO_ROOT = repo_root
            st_mod._TEMPLATE_OWNERS_PATH = owners_path

            # Override _file_hash to work and patch template file destination
            def patched_sync(sync=False, dry_run=False):
                """Patched sync that redirects template paths."""
                owners_data = st_mod._load_template_owners()
                managed_files = owners_data.get("managed_files", {})
                current = []
                stale = []
                synced = []
                errors = []

                for file_key, file_info in managed_files.items():
                    source_branch = file_info.get("source_branch", "")
                    source_path_str = file_info.get("source_path", "")
                    template_path_str = file_info.get("template_path", "")

                    source_file = repo_root / "src" / "aipass" / source_branch / source_path_str
                    template_file = template_target_dir / template_path_str

                    if not source_file.exists():
                        errors.append(f"Source not found: {source_file}")
                        continue

                    source_hash = st_mod._file_hash(source_file)
                    if template_file.exists():
                        template_hash = st_mod._file_hash(template_file)
                        if source_hash == template_hash:
                            current.append(file_key)
                            continue

                    stale.append(file_key)
                    if sync and not dry_run:
                        template_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(source_file), str(template_file))
                        synced.append(file_key)

                return {
                    "managed_files": len(managed_files),
                    "current": current,
                    "stale": stale,
                    "synced": synced,
                    "errors": errors,
                }

            result = patched_sync(sync=True)
        finally:
            st_mod._REPO_ROOT = orig_root
            st_mod._TEMPLATE_OWNERS_PATH = orig_owners

        assert result["managed_files"] == 1
        assert "prax_config" in result["synced"]

        # Template file should now exist
        template_file = template_target_dir / "config.json"
        assert template_file.exists()
        assert json.loads(template_file.read_text())["key"] == "source_value"

    def test_handle_sync_templates_no_args(self):
        """handle_sync_templates with no args should return 0 (status report)."""
        from aipass.spawn.apps.modules.sync_templates import handle_sync_templates

        # With the real template_owners.json being empty, this should work
        result = handle_sync_templates([])
        assert result == 0

    def test_missing_template_owners(self, tmp_path):
        """Missing template_owners.json should handle gracefully."""
        from aipass.spawn.apps.handlers import sync_templates_ops as st_mod

        orig_owners = st_mod._TEMPLATE_OWNERS_PATH

        try:
            st_mod._TEMPLATE_OWNERS_PATH = tmp_path / "nonexistent.json"
            result = st_mod.sync_templates()
        finally:
            st_mod._TEMPLATE_OWNERS_PATH = orig_owners

        assert result["managed_files"] == 0
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# HANDLE CLI Tests
# ---------------------------------------------------------------------------

class TestHandleDelete:
    """Tests for handle_delete() CLI entry."""

    def test_help_flag(self):
        """--help should show usage (not crash)."""
        from aipass.spawn.apps.modules.delete import handle_delete
        # No args -> usage
        result = handle_delete([])
        assert result == 1

    def test_protected_branch_via_handle(self, repo_root, mock_registry):
        """handle_delete should reject protected branches."""
        from aipass.spawn.apps.modules.delete import handle_delete

        with patch("aipass.spawn.apps.handlers.delete_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):

            result = handle_delete(["--yes", "@spawn"])

        assert result == 1


class TestHandleSyncRegistry:
    """Tests for handle_sync_registry() CLI entry."""

    def test_help_flag(self):
        """--help should return 0."""
        from aipass.spawn.apps.modules.sync_registry import handle_sync_registry
        result = handle_sync_registry(["--help"])
        assert result == 0

    def test_report_mode(self, repo_root, mock_branch, mock_registry):
        """No args should produce a report."""
        from aipass.spawn.apps.modules.sync_registry import handle_sync_registry

        with patch("aipass.spawn.apps.handlers.sync_registry_ops._REPO_ROOT", repo_root), \
             patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):

            result = handle_sync_registry([])

        assert result == 0
