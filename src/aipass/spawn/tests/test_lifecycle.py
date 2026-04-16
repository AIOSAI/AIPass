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
    (branch / ".trinity" / "passport.json").write_text(json.dumps({"name": "TEST_API", "role": "test"}, indent=2))
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

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
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

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("spawn", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_devpulse(self, repo_root, mock_registry):
        """Cannot delete devpulse (orchestration hub protection)."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("devpulse", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_drone(self, repo_root, mock_registry):
        """Cannot delete drone (routing infrastructure protection)."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("drone", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_dry_run(self, repo_root, mock_branch, mock_registry):
        """Dry run should NOT delete or archive anything."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
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

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("nonexistent", confirm=False)

        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_delete_confirmation_cancelled(self, repo_root, mock_branch, mock_registry):
        """Cancelling confirmation should not delete."""
        from aipass.spawn.apps.handlers.delete_ops import delete_branch

        with (
            patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry),
            patch("builtins.input", return_value="n"),
        ):
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
        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
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
        (new_branch / ".trinity" / "passport.json").write_text(json.dumps({"name": "PHANTOM"}, indent=2))

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=False)

        assert "phantom" in result["unregistered"]

    def test_detect_healthy_branches(self, repo_root, mock_branch, mock_registry):
        """Branches that exist with passports and are registered should be healthy."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=False)

        assert "test_api" in result["healthy"]

    def test_fix_removes_stale_and_adds_unregistered(self, repo_root, mock_branch, mock_registry):
        """With --fix, stale entries are removed and unregistered are added."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Create an unregistered branch
        new_branch = repo_root / "src" / "aipass" / "phantom"
        new_branch.mkdir(parents=True)
        (new_branch / ".trinity").mkdir()
        (new_branch / ".trinity" / "passport.json").write_text(json.dumps({"name": "PHANTOM"}, indent=2))

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
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

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=True)

        assert result["stale"] == []
        assert result["unregistered"] == []
        assert result["fixed"] is False  # Nothing to fix


# ---------------------------------------------------------------------------
# CWD-AWARE SYNC Tests (external projects)
# ---------------------------------------------------------------------------


class TestSyncRegistryCwdAware:
    """Tests for CWD-aware sync_registry — external project support."""

    def test_finds_root_level_agents(self, tmp_path):
        """Agents at project root (project/agent/) should be discovered."""
        from aipass.spawn.apps.handlers.sync_registry_ops import _scan_for_branches

        agent = tmp_path / "my_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "MY_AGENT"}')

        result = _scan_for_branches(tmp_path)
        assert "my_agent" in result
        assert result["my_agent"] == agent

    def test_finds_src_level_agents(self, tmp_path):
        """Agents at src/ level (project/src/agent/) should be discovered."""
        from aipass.spawn.apps.handlers.sync_registry_ops import _scan_for_branches

        agent = tmp_path / "src" / "my_agent"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "MY_AGENT"}')

        result = _scan_for_branches(tmp_path)
        assert "my_agent" in result

    def test_finds_nested_src_agents(self, tmp_path):
        """Agents at src/namespace/agent/ (AIPass-style) should be discovered."""
        from aipass.spawn.apps.handlers.sync_registry_ops import _scan_for_branches

        agent = tmp_path / "src" / "aipass" / "drone"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "DRONE"}')

        result = _scan_for_branches(tmp_path)
        assert "drone" in result

    def test_skips_dotdirs_and_dunder(self, tmp_path):
        """Directories starting with . or __ should be skipped."""
        from aipass.spawn.apps.handlers.sync_registry_ops import _scan_for_branches

        for name in [".hidden", "__pycache__"]:
            d = tmp_path / name
            d.mkdir()
            (d / ".trinity").mkdir()
            (d / ".trinity" / "passport.json").write_text("{}")

        result = _scan_for_branches(tmp_path)
        assert len(result) == 0

    def test_skips_dirs_without_passport(self, tmp_path):
        """Directories without .trinity/passport.json should be skipped."""
        from aipass.spawn.apps.handlers.sync_registry_ops import _scan_for_branches

        (tmp_path / "no_passport").mkdir()
        (tmp_path / "no_passport" / "README.md").write_text("# hi")

        result = _scan_for_branches(tmp_path)
        assert len(result) == 0

    def test_external_project_sync(self, tmp_path):
        """sync_registry should work with an external project registry."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Set up external project structure
        registry = {
            "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
            "branches": [],
        }
        reg_path = tmp_path / "MYPROJECT_REGISTRY.json"
        reg_path.write_text(json.dumps(registry, indent=2))

        # Create an agent in src/
        agent = tmp_path / "src" / "navigator"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "NAVIGATOR", "identity": {"citizen_class": "builder"}})
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=False)

        assert "navigator" in result["unregistered"]
        assert result["stale"] == []

    def test_external_project_fix_registers(self, tmp_path):
        """sync_registry --fix should register unregistered agents in external project."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        registry = {
            "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
            "branches": [],
        }
        reg_path = tmp_path / "DAEMON_REGISTRY.json"
        reg_path.write_text(json.dumps(registry, indent=2))

        agent = tmp_path / "src" / "daemon"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "DAEMON", "identity": {"citizen_class": "builder"}})
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=True)

        assert result["fixed"] is True
        reg = json.loads(reg_path.read_text())
        names = [b["name"] for b in reg["branches"]]
        assert "DAEMON" in names

        # Verify relative path stored
        daemon_entry = next(b for b in reg["branches"] if b["name"] == "DAEMON")
        assert daemon_entry["path"] == "src/daemon"


# ---------------------------------------------------------------------------
# ADOPT EXISTING Tests
# ---------------------------------------------------------------------------


class TestAdoptExisting:
    """Tests for _spawn_agent adopting existing directories with passports."""

    def test_adopt_existing_with_passport(self, tmp_path):
        """Target with .trinity/passport.json should be adopted, not rejected."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        # Create existing agent directory with passport
        agent = tmp_path / "my_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "my_agent"},
                    "identity": {"citizen_class": "builder", "purpose": "Test agent"},
                }
            )
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
                    "branches": [],
                }
            )
        )

        result = _spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        assert result["adopted"] is True
        assert result["branch_name"] == "MY_AGENT"
        assert result["registry_updated"] is True

        # Verify registered in registry
        reg = json.loads(reg_path.read_text())
        names = [b["name"] for b in reg["branches"]]
        assert "MY_AGENT" in names

    def test_existing_without_passport_still_fails(self, tmp_path):
        """Target that exists but has NO passport should still fail."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        agent = tmp_path / "no_passport"
        agent.mkdir()
        (agent / "README.md").write_text("# just a dir")

        result = _spawn_agent(str(agent))

        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_adopt_reads_purpose_from_passport(self, tmp_path):
        """Adopted agent should pick up purpose from passport when not provided."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        agent = tmp_path / "smart_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "smart_agent"},
                    "identity": {"citizen_class": "builder", "purpose": "Process reports daily"},
                }
            )
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
                    "branches": [],
                }
            )
        )

        result = _spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        reg = json.loads(reg_path.read_text())
        entry = next(b for b in reg["branches"] if b["name"] == "SMART_AGENT")
        assert entry["description"] == "Process reports daily"

    def test_adopt_existing_fixes_registry_id(self, tmp_path):
        """Adoption fixes mismatched registry_id in passport."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        agent = tmp_path / "id_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "id_agent"},
                    "identity": {"citizen_class": "builder", "purpose": "Test"},
                    "citizenship": {"registry_id": "old-uuid-1234"},
                }
            )
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "id": "new-uuid-5678",
                        "version": "1.0.0",
                        "last_updated": "2026-04-11",
                        "total_branches": 0,
                    },
                    "branches": [],
                }
            )
        )

        result = _spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        passport = json.loads((agent / ".trinity" / "passport.json").read_text())
        assert passport["citizenship"]["registry_id"] == "new-uuid-5678"

    def test_adopt_skips_registry_id_fix_when_already_correct(self, tmp_path):
        """Adoption does not modify passport when registry_id already matches."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        agent = tmp_path / "matched_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "matched_agent"},
                    "identity": {"citizen_class": "builder", "purpose": "Test"},
                    "citizenship": {"registry_id": "correct-uuid-9999"},
                }
            )
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "id": "correct-uuid-9999",
                        "version": "1.0.0",
                        "last_updated": "2026-04-11",
                        "total_branches": 0,
                    },
                    "branches": [],
                }
            )
        )

        # Get mtime before adoption to detect writes
        before_mtime = (agent / ".trinity" / "passport.json").stat().st_mtime

        result = _spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        after_mtime = (agent / ".trinity" / "passport.json").stat().st_mtime
        # File should NOT have been rewritten (ids already match)
        assert before_mtime == after_mtime


# ---------------------------------------------------------------------------
# FIX PASSPORT REGISTRY ID Tests
# ---------------------------------------------------------------------------


class TestFixPassportRegistryId:
    """Tests for fix_passport_registry_id() in registry.py."""

    def test_fixes_mismatched_id(self, tmp_path):
        """Updates passport when registry_id doesn't match."""
        from aipass.spawn.apps.handlers.registry import fix_passport_registry_id

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "old-id"},
                }
            )
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "new-id"}, "branches": []}))

        result = fix_passport_registry_id(branch, reg)

        assert result is True
        passport = json.loads((branch / ".trinity" / "passport.json").read_text())
        assert passport["citizenship"]["registry_id"] == "new-id"

    def test_skips_when_already_correct(self, tmp_path):
        """Returns False when ids already match (no write needed)."""
        from aipass.spawn.apps.handlers.registry import fix_passport_registry_id

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "same-id"},
                }
            )
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "same-id"}, "branches": []}))

        result = fix_passport_registry_id(branch, reg)

        assert result is False

    def test_handles_missing_passport(self, tmp_path):
        """Returns False gracefully when passport doesn't exist."""
        from aipass.spawn.apps.handlers.registry import fix_passport_registry_id

        branch = tmp_path / "npassport"
        branch.mkdir()

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "some-id"}, "branches": []}))

        result = fix_passport_registry_id(branch, reg)
        assert result is False

    def test_handles_registry_with_no_id(self, tmp_path):
        """Returns False when registry has no metadata.id."""
        from aipass.spawn.apps.handlers.registry import fix_passport_registry_id

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "old-id"},
                }
            )
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {}, "branches": []}))  # No id field

        result = fix_passport_registry_id(branch, reg)
        assert result is False

    def test_sync_registry_fix_repairs_ids(self, tmp_path, monkeypatch):
        """sync_registry --fix calls fix_passport_registry_id on healthy branches."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Set up a project with one healthy branch that has wrong registry_id
        project = tmp_path / "project"
        project.mkdir()

        reg_path = project / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "id": "correct-uuid-abc",
                        "version": "1.0.0",
                        "last_updated": "2026-04-11",
                        "total_branches": 1,
                    },
                    "branches": [
                        {
                            "name": "MYAGENT",
                            "path": "myagent",
                            "profile": "library",
                            "description": "Test",
                            "email": "@myagent",
                            "status": "active",
                            "created": "2026-04-11",
                            "last_active": "2026-04-11",
                        }
                    ],
                }
            )
        )

        agent_dir = project / "myagent"
        agent_dir.mkdir()
        (agent_dir / ".trinity").mkdir()
        passport_path = agent_dir / ".trinity" / "passport.json"
        passport_path.write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "old-stale-uuid"},
                }
            )
        )

        monkeypatch.chdir(project)

        result = sync_registry(fix=True)

        assert "myagent" in result.get("ids_fixed", [])
        passport = json.loads(passport_path.read_text())
        assert passport["citizenship"]["registry_id"] == "correct-uuid-abc"


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
        owners_path.write_text(
            json.dumps(
                {
                    "metadata": {"description": "test"},
                    "managed_files": {},
                },
                indent=2,
            )
        )

        with (
            patch("aipass.spawn.apps.handlers.sync_templates_ops._REPO_ROOT", repo_root),
            patch("aipass.spawn.apps.handlers.sync_templates_ops._TEMPLATE_OWNERS_PATH", owners_path),
        ):
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
        owners_path.write_text(
            json.dumps(
                {
                    "metadata": {"description": "test"},
                    "managed_files": {
                        "prax_config": {
                            "source_branch": "prax",
                            "source_path": "config.json",
                            "template_path": "config.json",
                        }
                    },
                },
                indent=2,
            )
        )

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
        owners_path.write_text(
            json.dumps(
                {
                    "metadata": {"description": "test"},
                    "managed_files": {
                        "prax_config": {
                            "source_branch": "prax",
                            "source_path": "config.json",
                            "template_path": "config.json",
                        }
                    },
                },
                indent=2,
            )
        )

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

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
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

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = handle_sync_registry([])

        assert result == 0
