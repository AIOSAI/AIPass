# =================== META ====================
# Name: test_lifecycle.py
# Description: Tests for spawn lifecycle commands (delete, sync-registry)
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Tests for spawn lifecycle management commands.

Tests delete_branch() and sync_registry().
"""

import json
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
            json.dumps({"name": "NAVIGATOR", "identity": {"citizen_class": "aipass_framework"}})
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
            json.dumps({"name": "DAEMON", "identity": {"citizen_class": "aipass_framework"}})
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

    def test_escaped_paths_detected_as_stale(self, tmp_path):
        """Registry entries with ../paths that escape project root should be stale."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        # Simulate external project with stale cross-project entries
        project = tmp_path / "myproject"
        project.mkdir()

        # Create a real agent that exists OUTSIDE this project (simulates AIPass branches)
        external = tmp_path / "AIPass" / "src" / "aipass" / "ai_mail"
        external.mkdir(parents=True)
        (external / ".trinity").mkdir()
        (external / ".trinity" / "passport.json").write_text('{"name": "AI_MAIL"}')

        # Create a local agent that belongs to this project
        local_agent = project / "src" / "polyglot"
        local_agent.mkdir(parents=True)
        (local_agent / ".trinity").mkdir()
        (local_agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "POLYGLOT", "identity": {"citizen_class": "aipass_framework"}})
        )

        reg_path = project / "MYPROJECT_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-05-15", "total_branches": 2},
                    "branches": [
                        {
                            "name": "AI_MAIL",
                            "path": "../AIPass/src/aipass/ai_mail",
                            "profile": "library",
                            "description": "Mail system",
                            "email": "@ai_mail",
                            "status": "active",
                            "created": "2026-05-01",
                            "last_active": "2026-05-01",
                        },
                        {
                            "name": "POLYGLOT",
                            "path": "src/polyglot",
                            "profile": "library",
                            "description": "Local agent",
                            "email": "@polyglot",
                            "status": "active",
                            "created": "2026-05-01",
                            "last_active": "2026-05-01",
                        },
                    ],
                }
            )
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=False)

        assert "ai_mail" in result["stale"]
        assert "polyglot" in result["healthy"]

    def test_escaped_paths_pruned_on_fix(self, tmp_path):
        """sync_registry --fix should remove entries with ../paths escaping project root."""
        from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry

        project = tmp_path / "myproject"
        project.mkdir()

        # External directory exists with passport (would fool old code)
        external = tmp_path / "AIPass" / "src" / "aipass" / "flow"
        external.mkdir(parents=True)
        (external / ".trinity").mkdir()
        (external / ".trinity" / "passport.json").write_text('{"name": "FLOW"}')

        # Local agent
        local = project / "src" / "myagent"
        local.mkdir(parents=True)
        (local / ".trinity").mkdir()
        (local / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "MYAGENT", "identity": {"citizen_class": "aipass_framework"}})
        )

        reg_path = project / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-05-15", "total_branches": 2},
                    "branches": [
                        {
                            "name": "FLOW",
                            "path": "../AIPass/src/aipass/flow",
                            "profile": "library",
                            "description": "Flow",
                            "email": "@flow",
                            "status": "active",
                            "created": "2026-05-01",
                            "last_active": "2026-05-01",
                        },
                        {
                            "name": "MYAGENT",
                            "path": "src/myagent",
                            "profile": "library",
                            "description": "Local",
                            "email": "@myagent",
                            "status": "active",
                            "created": "2026-05-01",
                            "last_active": "2026-05-01",
                        },
                    ],
                }
            )
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=True)

        assert result["fixed"] is True
        reg = json.loads(reg_path.read_text())
        names = [b["name"] for b in reg["branches"]]
        assert "FLOW" not in names
        assert "MYAGENT" in names
        assert reg["metadata"]["total_branches"] == 1


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
                    "identity": {"citizen_class": "aipass_framework", "purpose": "Test agent"},
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
                    "identity": {"citizen_class": "aipass_framework", "purpose": "Process reports daily"},
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
                    "identity": {"citizen_class": "aipass_framework", "purpose": "Test"},
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
                    "identity": {"citizen_class": "aipass_framework", "purpose": "Test"},
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

    def test_failed_dry_run_prints_no_raw_markup(self, capsys, repo_root, mock_registry):
        """The failure line must not leak literal Rich tags.

        error() writes plain text, so the dry-run mode marker built for console.print()
        surfaced as '[dim](dry-run)[/dim]' on every failed preview (DPLAN-0291 audit).
        """
        from aipass.spawn.apps.modules.delete import handle_delete

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            handle_delete(["--dry-run", "--yes", "@spawn"])

        combined = "".join(capsys.readouterr())
        assert "Delete FAILED" in combined
        assert "[dim]" not in combined
        assert "[/dim]" not in combined
        assert "(dry-run)" in combined


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
