# =================== META ====================
# Name: test_lifecycle.py
# Description: Tests for spawn lifecycle commands (delete, sync-registry)
# Version: 1.1.3
# Created: 2026-03-07
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/delete_ops.py and apps/handlers/sync_registry_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/handlers/ and apps/modules/ parses and imports
# seedgo: no-test-needed(documentation) — that delete_branch, sync_registry and spawn_agent carry docstrings

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers.delete_ops import delete_branch
from aipass.spawn.apps.handlers.registry import fix_passport_registry_id
from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry
from aipass.spawn.apps.modules.core import spawn_agent
from aipass.spawn.apps.modules.delete import handle_delete
from aipass.spawn.apps.modules.sync_registry import handle_sync_registry

# Also exercises apps/modules/delete.py's and apps/modules/sync_registry.py's CLI entry points,
# apps/modules/core.py's spawn_agent() adopt-existing path, and apps/handlers/registry.py's
# fix_passport_registry_id().

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_root(tmp_path):
    """Create a mock repo root with src/aipass/ structure."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'aipass'\n", encoding="utf-8")
    (root / "src" / "aipass").mkdir(parents=True)
    return root


@pytest.fixture
def mock_branch(repo_root):
    """Create a mock branch directory with .trinity/passport.json."""
    branch = repo_root / "src" / "aipass" / "test_api"
    branch.mkdir(parents=True)
    (branch / ".trinity").mkdir()
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps({"name": "TEST_API", "role": "test"}, indent=2), encoding="utf-8"
    )
    (branch / "apps").mkdir()
    (branch / "apps" / "branch.py").write_text("# test api entry\n", encoding="utf-8")
    (branch / "README.md").write_text("# Test API\n", encoding="utf-8")
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
    reg_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return reg_path


# ---------------------------------------------------------------------------
# DELETE Tests
# ---------------------------------------------------------------------------


class TestDeleteBranch:
    """Tests for delete_branch()."""

    def test_delete_archives_and_removes(self, repo_root: Path, mock_branch: Path, mock_registry: Path):
        """Successful delete should archive the branch and remove from registry."""

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
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        names = [b["name"] for b in reg["branches"]]
        assert "TEST_API" not in names

    def test_delete_protected_spawn(self, repo_root, mock_registry):
        """Cannot delete spawn (self-protection)."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("spawn", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_devpulse(self, repo_root, mock_registry):
        """Cannot delete devpulse (orchestration hub protection)."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("devpulse", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_protected_drone(self, repo_root, mock_registry):
        """Cannot delete drone (routing infrastructure protection)."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("drone", confirm=False)

        assert result["success"] is False
        assert "protected" in result.get("error", "").lower()

    def test_delete_dry_run(self, repo_root, mock_branch, mock_registry):
        """Dry run should NOT delete or archive anything."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("test_api", confirm=False, dry_run=True)

        assert result["success"] is True
        assert result.get("dry_run") is True

        # Branch should still exist
        assert mock_branch.exists()

        # Registry should be unchanged
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        names = [b["name"] for b in reg["branches"]]
        assert "TEST_API" in names

    def test_delete_nonexistent_branch(self, repo_root, mock_registry):
        """Deleting a branch not in registry should fail gracefully."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("nonexistent", confirm=False)

        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_delete_confirmation_cancelled(self, repo_root, mock_branch, mock_registry, monkeypatch):
        """Cancelling confirmation should not delete.

        The answer arrives on stdin (the sanctioned edge), not by replacing input().
        Mutant: the prompt accepts any answer but "y" -> red.
        """

        monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("test_api", confirm=True)

        assert result["success"] is False
        assert result["error"] == "Cancelled by user"
        assert mock_branch.exists()

    @pytest.mark.parametrize("where", ["outside", "root"])
    def test_delete_refuses_a_row_that_escapes_the_project(self, tmp_path, repo_root, mock_registry, where):
        """A row resolving outside the project, or to the root itself, is refused before any archive or rmtree."""

        victim = tmp_path / "outside_project" if where == "outside" else repo_root
        victim.mkdir(exist_ok=True)
        (victim / "keep.txt").write_text("survives\n", encoding="utf-8")
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        reg["branches"].append(
            {"name": "ESCAPEE", "path": str(victim) if where == "outside" else ".", "status": "active"}
        )
        mock_registry.write_text(json.dumps(reg, indent=2), encoding="utf-8")

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = delete_branch("escapee", confirm=False)

        assert result["success"] is False
        assert "outside the project" in result["error"]
        assert (victim / "keep.txt").read_text(encoding="utf-8") == "survives\n"
        assert not (repo_root / ".archive").exists()
        names = [b["name"] for b in json.loads(mock_registry.read_text(encoding="utf-8"))["branches"]]
        assert "ESCAPEE" in names

    def test_handle_delete_no_args(self):
        """handle_delete with no args should show usage."""

        result = handle_delete([])
        assert result == 1


# ---------------------------------------------------------------------------
# SYNC REGISTRY Tests
# ---------------------------------------------------------------------------


class TestSyncRegistry:
    """Tests for sync_registry()."""

    def test_detect_stale_entries(self, repo_root, mock_registry):
        """Registry entries for non-existent directories should be detected as stale."""

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

        # Create a new branch directory with passport that's NOT in registry
        new_branch = repo_root / "src" / "aipass" / "phantom"
        new_branch.mkdir(parents=True)
        (new_branch / ".trinity").mkdir()
        (new_branch / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "PHANTOM"}, indent=2), encoding="utf-8"
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=False)

        assert "phantom" in result["unregistered"]

    def test_detect_healthy_branches(self, repo_root, mock_branch, mock_registry):
        """Branches that exist with passports and are registered should be healthy."""

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=False)

        assert "test_api" in result["healthy"]

    def test_fix_removes_stale_and_adds_unregistered(self, repo_root, mock_branch, mock_registry):
        """With --fix, stale entries are removed and unregistered are added."""

        # Create an unregistered branch
        new_branch = repo_root / "src" / "aipass" / "phantom"
        new_branch.mkdir(parents=True)
        (new_branch / ".trinity").mkdir()
        (new_branch / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "PHANTOM"}, indent=2), encoding="utf-8"
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=True)

        assert result["fixed"] is True

        # Verify registry was actually updated
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
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

        # Remove all stale entries from registry (only keep test_api which exists)
        reg = json.loads(mock_registry.read_text(encoding="utf-8"))
        reg["branches"] = [b for b in reg["branches"] if b["name"] == "TEST_API"]
        mock_registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = sync_registry(fix=True)

        assert result["stale"] == []
        assert result["unregistered"] == []
        assert result["fixed"] is False  # Nothing to fix


# ---------------------------------------------------------------------------
# CWD-AWARE SYNC Tests (external projects)
# ---------------------------------------------------------------------------


def _scan_through_sync(project, monkeypatch, fix=False):
    """Discover branches the way the command does: sync_registry from inside the project.

    The project gets an empty registry of its own and the CWD moves into it, so
    find_registry() resolves to the tmp registry and never walks up to the live one.
    Every discovered branch is therefore reported as unregistered.
    """
    reg = project / "SCAN_REGISTRY.json"
    reg.write_text(
        json.dumps({"metadata": {"version": "1.0.0", "total_branches": 0}, "branches": []}), encoding="utf-8"
    )
    monkeypatch.chdir(project)
    return sync_registry(fix=fix), reg


class TestSyncRegistryCwdAware:
    """Tests for CWD-aware sync_registry — external project support."""

    def test_finds_root_level_agents(self, tmp_path, monkeypatch):
        """Agents at project root (project/agent/) should be discovered, at their own path.

        Mutant: the root-level scan is dropped -> red.
        """

        agent = tmp_path / "my_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "MY_AGENT"}', encoding="utf-8")

        result, reg = _scan_through_sync(tmp_path, monkeypatch, fix=True)
        assert result["unregistered"] == ["my_agent"]
        entries = json.loads(reg.read_text(encoding="utf-8"))["branches"]
        assert [(e["name"], e["path"]) for e in entries] == [("MY_AGENT", "my_agent")]

    def test_finds_src_level_agents(self, tmp_path, monkeypatch):
        """Agents at src/ level (project/src/agent/) should be discovered."""

        agent = tmp_path / "src" / "my_agent"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "MY_AGENT"}', encoding="utf-8")

        result, _reg = _scan_through_sync(tmp_path, monkeypatch)
        assert result["unregistered"] == ["my_agent"]

    def test_finds_nested_src_agents(self, tmp_path, monkeypatch):
        """Agents at src/namespace/agent/ (AIPass-style) should be discovered."""

        agent = tmp_path / "src" / "aipass" / "drone"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text('{"name": "DRONE"}', encoding="utf-8")

        result, _reg = _scan_through_sync(tmp_path, monkeypatch)
        assert result["unregistered"] == ["drone"]

    def test_skips_dotdirs_and_dunder(self, tmp_path, monkeypatch):
        """Directories starting with . or __ should be skipped."""

        for name in [".hidden", "__pycache__"]:
            d = tmp_path / name
            d.mkdir()
            (d / ".trinity").mkdir()
            (d / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")

        result, _reg = _scan_through_sync(tmp_path, monkeypatch)
        assert result["unregistered"] == []

    def test_skips_dirs_without_passport(self, tmp_path, monkeypatch):
        """Directories without .trinity/passport.json should be skipped."""

        (tmp_path / "no_passport").mkdir()
        (tmp_path / "no_passport" / "README.md").write_text("# hi", encoding="utf-8")

        result, _reg = _scan_through_sync(tmp_path, monkeypatch)
        assert result["unregistered"] == []

    def test_external_project_sync(self, tmp_path):
        """sync_registry should work with an external project registry."""

        # Set up external project structure
        registry = {
            "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
            "branches": [],
        }
        reg_path = tmp_path / "MYPROJECT_REGISTRY.json"
        reg_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

        # Create an agent in src/
        agent = tmp_path / "src" / "navigator"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "NAVIGATOR", "identity": {"citizen_class": "specialist"}}), encoding="utf-8"
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=False)

        assert "navigator" in result["unregistered"]
        assert result["stale"] == []

    def test_external_project_fix_registers(self, tmp_path):
        """sync_registry --fix should register unregistered agents in external project."""

        registry = {
            "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
            "branches": [],
        }
        reg_path = tmp_path / "DAEMON_REGISTRY.json"
        reg_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

        agent = tmp_path / "src" / "daemon"
        agent.mkdir(parents=True)
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "DAEMON", "identity": {"citizen_class": "specialist"}}), encoding="utf-8"
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=True)

        assert result["fixed"] is True
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        names = [b["name"] for b in reg["branches"]]
        assert "DAEMON" in names

        # Verify relative path stored
        daemon_entry = next(b for b in reg["branches"] if b["name"] == "DAEMON")
        assert daemon_entry["path"] == "src/daemon"

    def test_escaped_paths_detected_as_stale(self, tmp_path):
        """Registry entries with ../paths that escape project root should be stale."""

        # Simulate external project with stale cross-project entries
        project = tmp_path / "myproject"
        project.mkdir()

        # Create a real agent that exists OUTSIDE this project (simulates AIPass branches)
        external = tmp_path / "AIPass" / "src" / "aipass" / "ai_mail"
        external.mkdir(parents=True)
        (external / ".trinity").mkdir()
        (external / ".trinity" / "passport.json").write_text('{"name": "AI_MAIL"}', encoding="utf-8")

        # Create a local agent that belongs to this project
        local_agent = project / "src" / "polyglot"
        local_agent.mkdir(parents=True)
        (local_agent / ".trinity").mkdir()
        (local_agent / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "POLYGLOT", "identity": {"citizen_class": "specialist"}}), encoding="utf-8"
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
            ),
            encoding="utf-8",
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=False)

        assert "ai_mail" in result["stale"]
        assert "polyglot" in result["healthy"]

    def test_escaped_paths_pruned_on_fix(self, tmp_path):
        """sync_registry --fix should remove entries with ../paths escaping project root."""

        project = tmp_path / "myproject"
        project.mkdir()

        # External directory exists with passport (would fool old code)
        external = tmp_path / "AIPass" / "src" / "aipass" / "flow"
        external.mkdir(parents=True)
        (external / ".trinity").mkdir()
        (external / ".trinity" / "passport.json").write_text('{"name": "FLOW"}', encoding="utf-8")

        # Local agent
        local = project / "src" / "myagent"
        local.mkdir(parents=True)
        (local / ".trinity").mkdir()
        (local / ".trinity" / "passport.json").write_text(
            json.dumps({"name": "MYAGENT", "identity": {"citizen_class": "specialist"}}), encoding="utf-8"
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
            ),
            encoding="utf-8",
        )

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=reg_path):
            result = sync_registry(fix=True)

        assert result["fixed"] is True
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        names = [b["name"] for b in reg["branches"]]
        assert "FLOW" not in names
        assert "MYAGENT" in names
        assert reg["metadata"]["total_branches"] == 1


# ---------------------------------------------------------------------------
# ADOPT EXISTING Tests
# ---------------------------------------------------------------------------


class TestAdoptExisting:
    """Tests for spawn_agent adopting existing directories with passports."""

    def test_adopt_existing_with_passport(self, tmp_path):
        """Target with .trinity/passport.json should be adopted, not rejected."""

        # Create existing agent directory with passport
        agent = tmp_path / "my_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "my_agent"},
                    "identity": {"citizen_class": "specialist", "purpose": "Test agent"},
                }
            ),
            encoding="utf-8",
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )

        result = spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        assert result["adopted"] is True
        assert result["branch_name"] == "MY_AGENT"
        assert result["registry_updated"] is True

        # Verify registered in registry
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        names = [b["name"] for b in reg["branches"]]
        assert "MY_AGENT" in names

    def test_existing_without_passport_still_fails(self, tmp_path):
        """Target that exists but has NO passport should still fail."""

        agent = tmp_path / "no_passport"
        agent.mkdir()
        (agent / "README.md").write_text("# just a dir", encoding="utf-8")

        result = spawn_agent(str(agent))

        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_adopt_reads_purpose_from_passport(self, tmp_path):
        """Adopted agent should pick up purpose from passport when not provided."""

        agent = tmp_path / "smart_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "smart_agent"},
                    "identity": {"citizen_class": "specialist", "purpose": "Process reports daily"},
                }
            ),
            encoding="utf-8",
        )

        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-04-09", "total_branches": 0},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )

        result = spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        entry = next(b for b in reg["branches"] if b["name"] == "SMART_AGENT")
        assert entry["description"] == "Process reports daily"

    def test_adopt_existing_fixes_registry_id(self, tmp_path):
        """Adoption fixes mismatched registry_id in passport."""

        agent = tmp_path / "id_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "id_agent"},
                    "identity": {"citizen_class": "specialist", "purpose": "Test"},
                    "citizenship": {"registry_id": "old-uuid-1234"},
                }
            ),
            encoding="utf-8",
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
            ),
            encoding="utf-8",
        )

        result = spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        passport = json.loads((agent / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "new-uuid-5678"

    def test_adopt_skips_registry_id_fix_when_already_correct(self, tmp_path, monkeypatch):
        """Adoption does not modify passport when registry_id already matches.

        The template-update step after registration heals passports on its own
        allowlist, a separate writer; it is replaced by a recorder here so the
        mtime answers for fix_passport_registry_id alone, and the recorder is
        asserted so the step is still proven to run.
        Mutant: fix_passport_registry_id writes even when the ids match -> red.
        """
        updated = []
        monkeypatch.setattr(
            "aipass.spawn.apps.handlers.update_ops.update_branch",
            lambda name, *a, **k: updated.append(name) or {"additions": 0},
        )

        agent = tmp_path / "matched_agent"
        agent.mkdir()
        (agent / ".trinity").mkdir()
        (agent / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "matched_agent"},
                    "identity": {"citizen_class": "specialist", "purpose": "Test"},
                    "citizenship": {"registry_id": "correct-uuid-9999"},
                }
            ),
            encoding="utf-8",
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
            ),
            encoding="utf-8",
        )

        # Get mtime before adoption to detect writes
        before_mtime = (agent / ".trinity" / "passport.json").stat().st_mtime

        result = spawn_agent(str(agent), registry_path=str(reg_path))

        assert result["success"] is True
        after_mtime = (agent / ".trinity" / "passport.json").stat().st_mtime
        # File should NOT have been rewritten (ids already match)
        assert before_mtime == after_mtime
        assert updated == ["matched_agent"]


def _twin_project(root: Path, registered: bool) -> tuple[Path, Path]:
    """A tmp project root holding TEST_REGISTRY.json and a passported ``twin`` branch."""
    branch = root / "twin"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {"branch_name": "twin"},
                "identity": {"citizen_class": "specialist", "purpose": "Twin agent"},
            }
        ),
        encoding="utf-8",
    )
    entries = [{"name": "TWIN", "path": "twin"}] if registered else []
    reg = root / "TEST_REGISTRY.json"
    reg.write_text(
        json.dumps(
            {
                "metadata": {"version": "1.0.0", "last_updated": "2026-09-27", "total_branches": len(entries)},
                "branches": entries,
            }
        ),
        encoding="utf-8",
    )
    return branch, reg


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under root, relative path -> bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_adoption_update_touches_the_branch_of_the_registry_handed_in(tmp_path, monkeypatch):
    """Adoption's template update resolves the branch through the registry adopt was handed.

    Two tmp projects, one branch name in both. The CWD sits in project B, so a
    lookup through find_registry() from the CWD would land on B's twin. Adopting
    A's twin must update A's twin and leave B's twin byte-equal (spawn's
    decision, DPLAN-0354 leg 3: the registry path travels to update_branch).
    Mutant: adopt_existing calls update_branch without registry_path -> red.
    Mutant: update_branch drops registry_path on its _resolve_branch_path call -> red.
    """
    twin_a, reg_a = _twin_project(tmp_path / "proj_a", registered=False)
    twin_b, _reg_b = _twin_project(tmp_path / "proj_b", registered=True)
    before_a = _tree_bytes(twin_a)
    before_b = _tree_bytes(twin_b)
    monkeypatch.chdir(tmp_path / "proj_b")

    result = spawn_agent(str(twin_a), registry_path=str(reg_a))

    assert result["success"] is True
    assert result["registry_path"] == str(reg_a)
    assert result["files_copied"] > 0
    assert _tree_bytes(twin_a) != before_a
    assert _tree_bytes(twin_b) == before_b


# ---------------------------------------------------------------------------
# FIX PASSPORT REGISTRY ID Tests
# ---------------------------------------------------------------------------


class TestFixPassportRegistryId:
    """Tests for fix_passport_registry_id() in registry.py."""

    def test_fixes_mismatched_id(self, tmp_path):
        """Updates passport when registry_id doesn't match."""

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "old-id"},
                }
            ),
            encoding="utf-8",
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "new-id"}, "branches": []}), encoding="utf-8")

        result = fix_passport_registry_id(branch, reg)

        assert result is True
        passport = json.loads((branch / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "new-id"

    def test_skips_when_already_correct(self, tmp_path):
        """Returns False when ids already match (no write needed)."""

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "same-id"},
                }
            ),
            encoding="utf-8",
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "same-id"}, "branches": []}), encoding="utf-8")

        result = fix_passport_registry_id(branch, reg)

        assert result is False

    def test_handles_missing_passport(self, tmp_path):
        """Returns False gracefully when passport doesn't exist."""

        branch = tmp_path / "npassport"
        branch.mkdir()

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {"id": "some-id"}, "branches": []}), encoding="utf-8")

        result = fix_passport_registry_id(branch, reg)
        assert result is False

    def test_handles_registry_with_no_id(self, tmp_path):
        """Returns False when registry has no metadata.id."""

        branch = tmp_path / "myagent"
        branch.mkdir()
        (branch / ".trinity").mkdir()
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps(
                {
                    "citizenship": {"registry_id": "old-id"},
                }
            ),
            encoding="utf-8",
        )

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(json.dumps({"metadata": {}, "branches": []}), encoding="utf-8")  # No id field

        result = fix_passport_registry_id(branch, reg)
        assert result is False

    def test_sync_registry_fix_repairs_ids(self, tmp_path, monkeypatch):
        """sync_registry --fix calls fix_passport_registry_id on healthy branches."""

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
            ),
            encoding="utf-8",
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
            ),
            encoding="utf-8",
        )

        monkeypatch.chdir(project)

        result = sync_registry(fix=True)

        assert "myagent" in result.get("ids_fixed", [])
        passport = json.loads(passport_path.read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "correct-uuid-abc"


# ---------------------------------------------------------------------------
# HANDLE CLI Tests
# ---------------------------------------------------------------------------


class TestHandleDelete:
    """Tests for handle_delete() CLI entry."""

    def test_help_flag(self, capsys):
        """--help should show usage (not crash) and exit 0, unlike the no-args usage error.

        Mutant: the --help intercept is removed -> red.
        """

        result = handle_delete(["--help"])
        assert result == 0
        assert "Usage: drone @spawn delete <@branch>" in capsys.readouterr().out

    def test_protected_branch_via_handle(self, repo_root, mock_registry):
        """handle_delete should reject protected branches."""

        with patch("aipass.spawn.apps.handlers.delete_ops.find_registry", return_value=mock_registry):
            result = handle_delete(["--yes", "@spawn"])

        assert result == 1

    def test_failed_dry_run_prints_no_raw_markup(self, capsys, repo_root, mock_registry):
        """The failure line must not leak literal Rich tags.

        error() writes plain text, so the dry-run mode marker built for console.print()
        surfaced as '[dim](dry-run)[/dim]' on every failed preview (DPLAN-0291 audit).
        """

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

        result = handle_sync_registry(["--help"])
        assert result == 0

    def test_report_mode(self, repo_root, mock_branch, mock_registry):
        """No args should produce a report."""

        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=mock_registry):
            result = handle_sync_registry([])

        assert result == 0
