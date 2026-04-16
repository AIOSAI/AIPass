# =================== AIPass ====================
# Name: test_commands.py
# Description: Tests for the custom command registry
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Tests for the custom command registry.

Covers:
- CRUD operations (add, remove, update, exists)
- Exact-match lookup
- Multi-word greedy matching
- Registry auto-creation
- List filtering by branch
- Module orchestrator (handle_command)
"""

import json
from pathlib import Path
from typing import Any

import pytest

from aipass.drone.apps.handlers.command_registry import ops, lookup


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the registry at a temp file so tests never touch the real one."""
    registry_file = tmp_path / "drone_command_registry.json"
    monkeypatch.setattr(ops, "REGISTRY_FILE", registry_file)
    return registry_file


def _seed_registry(registry_file: Path, commands: dict[str, Any] | None = None) -> None:
    """Write a registry file with pre-populated commands."""
    if commands is None:
        commands = {}
    data = {
        "commands": commands,
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-03-17",
            "command_count": len(commands),
        },
    }
    registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===================================================================
# 1. Registry auto-creation
# ===================================================================


class TestRegistryAutoCreation:
    def test_load_creates_file_when_missing(self, isolated_registry: Path) -> None:
        """load_registry() creates a new file when none exists."""
        assert not isolated_registry.exists()

        registry = ops.load_registry()

        assert isolated_registry.exists()
        assert isinstance(registry, dict)
        assert "commands" in registry
        assert "metadata" in registry
        assert registry["metadata"]["command_count"] == 0

    def test_load_recreates_on_corrupt_json(self, isolated_registry: Path) -> None:
        """Corrupt JSON triggers auto-recreation."""
        isolated_registry.write_text("{{{bad json", encoding="utf-8")

        registry = ops.load_registry()

        assert registry["commands"] == {}
        assert registry["metadata"]["command_count"] == 0

    def test_load_recreates_on_non_dict(self, isolated_registry: Path) -> None:
        """Non-dict top-level JSON triggers auto-recreation."""
        isolated_registry.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        registry = ops.load_registry()

        assert isinstance(registry, dict)
        assert "commands" in registry

    def test_auto_heals_missing_keys(self, isolated_registry: Path) -> None:
        """Missing 'commands' or 'metadata' keys are auto-healed."""
        isolated_registry.write_text(json.dumps({"other": "data"}), encoding="utf-8")

        registry = ops.load_registry()

        assert "commands" in registry
        assert "metadata" in registry


# ===================================================================
# 2. CRUD operations
# ===================================================================


class TestCRUDOperations:
    def test_add_command(self, isolated_registry: Path) -> None:
        """add_command creates a new entry in the registry."""
        result = ops.add_command(
            name="audit",
            target="@seedgo",
            command="audit",
            args=["aipass"],
            description="Run audit",
            source_branch="seedgo",
        )

        assert result is True

        registry = ops.load_registry()
        assert "audit" in registry["commands"]
        cmd = registry["commands"]["audit"]
        assert cmd["name"] == "audit"
        assert cmd["target"] == "@seedgo"
        assert cmd["command"] == "audit"
        assert cmd["args"] == ["aipass"]
        assert cmd["description"] == "Run audit"
        assert cmd["source_branch"] == "seedgo"

    def test_add_duplicate_returns_false(self, isolated_registry: Path) -> None:
        """Adding a command with an existing name returns False."""
        ops.add_command("audit", "@seedgo", "audit")

        result = ops.add_command("audit", "@prax", "something_else")

        assert result is False

    def test_add_with_default_args(self, isolated_registry: Path) -> None:
        """add_command with no args defaults to empty list."""
        ops.add_command("monitor", "@prax", "monitor")

        registry = ops.load_registry()
        assert registry["commands"]["monitor"]["args"] == []

    def test_remove_command(self, isolated_registry: Path) -> None:
        """remove_command deletes an existing entry."""
        ops.add_command("audit", "@seedgo", "audit")

        result = ops.remove_command("audit")

        assert result is True
        registry = ops.load_registry()
        assert "audit" not in registry["commands"]

    def test_remove_nonexistent_returns_false(self, isolated_registry: Path) -> None:
        """Removing a nonexistent command returns False."""
        result = ops.remove_command("nonexistent")

        assert result is False

    def test_update_command(self, isolated_registry: Path) -> None:
        """update_command modifies fields of an existing entry."""
        ops.add_command("audit", "@seedgo", "audit", description="Old desc")

        result = ops.update_command("audit", description="New desc", target="@prax")

        assert result is True
        registry = ops.load_registry()
        cmd = registry["commands"]["audit"]
        assert cmd["description"] == "New desc"
        assert cmd["target"] == "@prax"

    def test_update_nonexistent_returns_false(self, isolated_registry: Path) -> None:
        """Updating a nonexistent command returns False."""
        result = ops.update_command("ghost", description="nope")

        assert result is False

    def test_update_ignores_disallowed_keys(self, isolated_registry: Path) -> None:
        """update_command ignores keys outside the allowed set."""
        ops.add_command("audit", "@seedgo", "audit")

        ops.update_command("audit", created="1970-01-01")

        registry = ops.load_registry()
        cmd = registry["commands"]["audit"]
        # 'created' is not in the allowed set, so it should NOT be overwritten
        assert cmd["created"] != "1970-01-01"

    def test_command_exists_true(self, isolated_registry: Path) -> None:
        """command_exists returns True for registered commands."""
        ops.add_command("audit", "@seedgo", "audit")

        assert ops.command_exists("audit") is True

    def test_command_exists_false(self, isolated_registry: Path) -> None:
        """command_exists returns False for unregistered commands."""
        assert ops.command_exists("nonexistent") is False

    def test_metadata_command_count_updates(self, isolated_registry: Path) -> None:
        """metadata.command_count tracks the number of commands after each save."""
        ops.add_command("a", "@t", "c1")
        ops.add_command("b", "@t", "c2")

        registry = ops.load_registry()
        assert registry["metadata"]["command_count"] == 2

        ops.remove_command("a")

        registry = ops.load_registry()
        assert registry["metadata"]["command_count"] == 1


# ===================================================================
# 3. Lookup (exact match)
# ===================================================================


class TestLookup:
    def test_lookup_found(self, isolated_registry: Path) -> None:
        """lookup_command returns the command dict for an exact match."""
        ops.add_command("audit", "@seedgo", "audit", ["aipass"], "Run audit", "seedgo")

        result = lookup.lookup_command("audit")

        assert result is not None
        assert result["name"] == "audit"
        assert result["target"] == "@seedgo"

    def test_lookup_not_found(self, isolated_registry: Path) -> None:
        """lookup_command returns None when no match exists."""
        result = lookup.lookup_command("nonexistent")

        assert result is None


# ===================================================================
# 4. Multi-word greedy matching
# ===================================================================


class TestMultiWordMatching:
    def test_single_word_match(self, isolated_registry: Path) -> None:
        """match_command matches a single-word command."""
        ops.add_command("audit", "@seedgo", "audit")

        result = lookup.match_command(["audit", "--verbose"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "audit"
        assert remaining == ["--verbose"]

    def test_multi_word_match(self, isolated_registry: Path) -> None:
        """match_command matches a multi-word command name."""
        ops.add_command("plan create", "@flow", "create")

        result = lookup.match_command(["plan", "create", "my-plan"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "plan create"
        assert remaining == ["my-plan"]

    def test_greedy_longest_match(self, isolated_registry: Path) -> None:
        """match_command prefers the longest matching candidate."""
        ops.add_command("plan", "@flow", "plan_list")
        ops.add_command("plan create", "@flow", "plan_create")

        result = lookup.match_command(["plan", "create", "my-plan"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "plan create"
        assert remaining == ["my-plan"]

    def test_four_word_match(self, isolated_registry: Path) -> None:
        """match_command handles up to 4-word candidates."""
        ops.add_command("a b c d", "@test", "test_cmd")

        result = lookup.match_command(["a", "b", "c", "d", "extra"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "a b c d"
        assert remaining == ["extra"]

    def test_no_match_returns_none(self, isolated_registry: Path) -> None:
        """match_command returns None when no candidate matches."""
        ops.add_command("audit", "@seedgo", "audit")

        result = lookup.match_command(["deploy", "staging"])

        assert result is None

    def test_empty_args_returns_none(self, isolated_registry: Path) -> None:
        """match_command returns None for empty args."""
        result = lookup.match_command([])

        assert result is None

    def test_exact_match_no_remaining(self, isolated_registry: Path) -> None:
        """match_command with no extra args returns empty remaining list."""
        ops.add_command("audit", "@seedgo", "audit")

        result = lookup.match_command(["audit"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "audit"
        assert remaining == []


# ===================================================================
# 5. List and filter by branch
# ===================================================================


class TestListAndFilter:
    def test_list_commands_sorted(self, isolated_registry: Path) -> None:
        """list_commands returns all commands sorted by name."""
        ops.add_command("zebra", "@t", "c1")
        ops.add_command("alpha", "@t", "c2")
        ops.add_command("middle", "@t", "c3")

        result = lookup.list_commands()

        assert len(result) == 3
        names = [c["name"] for c in result]
        assert names == ["alpha", "middle", "zebra"]

    def test_list_commands_empty(self, isolated_registry: Path) -> None:
        """list_commands returns empty list when no commands exist."""
        result = lookup.list_commands()

        assert result == []

    def test_list_by_branch(self, isolated_registry: Path) -> None:
        """list_commands_by_branch filters by source_branch."""
        ops.add_command("audit", "@seedgo", "audit", source_branch="seedgo")
        ops.add_command("monitor", "@prax", "monitor", source_branch="prax")
        ops.add_command("check", "@seedgo", "check", source_branch="seedgo")

        seedgo_cmds = lookup.list_commands_by_branch("seedgo")

        assert len(seedgo_cmds) == 2
        names = [c["name"] for c in seedgo_cmds]
        assert "audit" in names
        assert "check" in names

    def test_list_by_branch_no_match(self, isolated_registry: Path) -> None:
        """list_commands_by_branch returns empty for nonexistent branch."""
        ops.add_command("audit", "@seedgo", "audit", source_branch="seedgo")

        result = lookup.list_commands_by_branch("nonexistent")

        assert result == []


# ===================================================================
# 6. Save validation
# ===================================================================


class TestSaveValidation:
    def test_save_rejects_non_dict(self, isolated_registry: Path) -> None:
        """save_registry rejects data that is not a dict."""
        result = ops.save_registry([1, 2, 3])  # type: ignore[arg-type]

        assert result is False

    def test_save_rejects_missing_commands(self, isolated_registry: Path) -> None:
        """save_registry rejects a dict without 'commands' key."""
        result = ops.save_registry({"metadata": {}})

        assert result is False


# ===================================================================
# 7. Module orchestrator
# ===================================================================


class TestModuleOrchestrator:
    def test_handle_command_introspection(self, isolated_registry: Path) -> None:
        """handle_command with no args triggers introspection."""
        from aipass.drone.apps.modules.commands import handle_command

        result = handle_command()

        assert result is True

    def test_handle_command_add(self, isolated_registry: Path) -> None:
        """handle_command 'add' creates a command."""
        from aipass.drone.apps.modules.commands import handle_command

        result = handle_command("add", ["test_cmd", "@branch", "do_thing", "--desc=A test"])

        assert result is True
        assert ops.command_exists("test_cmd") is True

        registry = ops.load_registry()
        assert registry["commands"]["test_cmd"]["description"] == "A test"

    def test_handle_command_remove(self, isolated_registry: Path) -> None:
        """handle_command 'remove' deletes a command."""
        from aipass.drone.apps.modules.commands import handle_command

        ops.add_command("doomed", "@t", "c")
        result = handle_command("remove", ["doomed"])

        assert result is True
        assert ops.command_exists("doomed") is False

    def test_handle_command_list(self, isolated_registry: Path) -> None:
        """handle_command 'list' succeeds."""
        from aipass.drone.apps.modules.commands import handle_command

        ops.add_command("a", "@t", "c1")
        result = handle_command("list", [])

        assert result is True

    def test_handle_command_unknown(self, isolated_registry: Path) -> None:
        """handle_command with unknown subcommand returns False."""
        from aipass.drone.apps.modules.commands import handle_command

        result = handle_command("unknown_sub", ["arg"])

        assert result is False
