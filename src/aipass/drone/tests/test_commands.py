# =================== AIPass ====================
# Name: test_commands.py
# Description: Tests for the custom command registry
# Version: 1.0.5
# Created: 2026-03-17
# Modified: 2026-10-23
# =============================================

"""Tests for apps/modules/commands.py and the command registry handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

import json
from pathlib import Path
from typing import Any

import pytest

from aipass.drone.apps.handlers.command_registry import ops, lookup
from aipass.prax import json_handler as prax_json
from aipass.drone.apps.modules import RegistryError
from aipass.drone.apps.modules.commands import handle_command, list_all


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


@pytest.fixture
def unreadable_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """ops' own ``open`` refuses every read; writes go to the real open.

    The stand-in is a module global of ops only, never the builtin, so nothing
    else in the process is touched. No mode bit: the refusal is this test's.
    """
    real_open = open

    def refusing_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "r" in mode:
            raise OSError("stand-in: this registry cannot be read")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(ops, "open", refusing_open, raising=False)


class TestUnreadableRegistry:
    """An existing registry that cannot be read raises naming it; a missing one is still created (fleet green leg 7)."""

    def test_an_existing_unreadable_registry_raises_and_is_not_overwritten(
        self, isolated_registry: Path, unreadable_reads: None
    ) -> None:
        """Mutant killed: the raise replaced by the old recreate (an empty registry saved over the commands)."""
        _seed_registry(isolated_registry, {"audit": {"name": "audit", "target": "@seedgo"}})
        before = isolated_registry.read_text(encoding="utf-8")

        with pytest.raises(RegistryError) as raised:
            ops.load_registry()

        assert str(isolated_registry) in str(raised.value)
        assert "stand-in: this registry cannot be read" in str(raised.value)
        assert isolated_registry.read_text(encoding="utf-8") == before

    def test_control_a_missing_registry_is_empty(self, isolated_registry: Path, unreadable_reads: None) -> None:
        """Control: under the same stand-in, a file that does not exist is an empty registry, never refused."""
        registry = ops.load_registry()

        assert registry["commands"] == {}


class TestRegistryAutoCreation:
    def test_load_of_a_missing_file_writes_nothing(self, isolated_registry: Path) -> None:
        """A read never writes: a missing file is an empty registry and stays missing."""
        assert not isolated_registry.exists()

        registry = ops.load_registry()

        assert not isolated_registry.exists()
        assert isinstance(registry, dict)
        assert "commands" in registry
        assert "metadata" in registry
        assert registry["metadata"]["command_count"] == 0

    def test_a_registry_that_is_not_json_raises_and_is_not_overwritten(self, isolated_registry: Path) -> None:
        """Not JSON raises naming the path and the parser's own text; the file is byte-equal after.

        The parser's text is asked of this interpreter, never written down.
        """
        broken = b'{"commands": {"audit": '
        isolated_registry.write_bytes(broken)
        with pytest.raises(json.JSONDecodeError) as parsed:
            json.loads(broken.decode("utf-8"))

        with pytest.raises(RegistryError) as raised:
            ops.load_registry()

        assert str(isolated_registry) in str(raised.value)
        assert str(parsed.value) in str(raised.value)
        assert isolated_registry.read_bytes() == broken

    def test_a_registry_that_is_not_a_dict_raises_and_is_not_overwritten(self, isolated_registry: Path) -> None:
        """JSON that is a list raises naming the path and the type; the file is byte-equal after."""
        listed = json.dumps([{"name": "audit"}]).encode("utf-8")
        isolated_registry.write_bytes(listed)

        with pytest.raises(RegistryError) as raised:
            ops.load_registry()

        assert str(isolated_registry) in str(raised.value)
        assert str(raised.value).endswith("is not a JSON object (list)")
        assert isolated_registry.read_bytes() == listed

    def test_auto_heals_missing_keys(self, isolated_registry: Path) -> None:
        """Missing 'commands' or 'metadata' keys are auto-healed."""
        isolated_registry.write_text(json.dumps({"other": "data"}), encoding="utf-8")

        registry = ops.load_registry()

        assert "commands" in registry
        assert "metadata" in registry


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

    def test_a_failed_save_leaves_the_old_file_whole(
        self, isolated_registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The save is staged and replaced: when the replace fails the old registry is byte-equal."""
        _seed_registry(isolated_registry, {"audit": {"name": "audit", "target": "@seedgo"}})
        before = isolated_registry.read_bytes()

        def refuse(source: str, destination: str) -> None:
            raise OSError("stand-in: replace refused")

        monkeypatch.setattr(prax_json, "replace_with_retry", refuse)

        assert ops.add_command("list", "@t", "list") is False
        assert isolated_registry.read_bytes() == before

    @pytest.mark.skipif(ops.fcntl is None, reason="no flock on this platform")
    def test_add_waits_for_the_registry_lock(self, isolated_registry: Path) -> None:
        """A second writer blocks on the lock instead of interleaving load+save."""
        import threading

        fcntl = ops.fcntl
        lock_file = isolated_registry.with_name(isolated_registry.name + ".lock")
        with open(lock_file, "a", encoding="utf-8") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            writer = threading.Thread(target=ops.add_command, args=("audit", "@seedgo", "audit"))
            writer.start()
            writer.join(timeout=0.3)
            assert writer.is_alive()
            assert not isolated_registry.exists()
            fcntl.flock(held, fcntl.LOCK_UN)
        writer.join(timeout=5)
        assert "audit" in ops.load_registry()["commands"]

    def test_metadata_command_count_updates(self, isolated_registry: Path) -> None:
        """metadata.command_count tracks the number of commands after each save."""
        ops.add_command("a", "@t", "c1")
        ops.add_command("b", "@t", "c2")

        registry = ops.load_registry()
        assert registry["metadata"]["command_count"] == 2

        ops.remove_command("a")

        registry = ops.load_registry()
        assert registry["metadata"]["command_count"] == 1


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

    def test_registry_load_failure_raises_not_no_match(
        self, isolated_registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A registry that cannot load raises, never reads as "no match"; mutant: the except returns None."""

        def unreadable() -> dict[str, Any]:
            raise RegistryError("registry unreadable")

        monkeypatch.setattr(lookup, "load_registry", unreadable)

        with pytest.raises(RegistryError, match="registry unreadable"):
            lookup.match_command(["audit"])

    def test_exact_match_no_remaining(self, isolated_registry: Path) -> None:
        """match_command with no extra args returns empty remaining list."""
        ops.add_command("audit", "@seedgo", "audit")

        result = lookup.match_command(["audit"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "audit"
        assert remaining == []


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


class TestSaveValidation:
    def test_save_rejects_non_dict(self, isolated_registry: Path) -> None:
        """save_registry rejects data that is not a dict."""
        result = ops.save_registry([1, 2, 3])  # type: ignore[arg-type]

        assert result is False

    def test_save_rejects_missing_commands(self, isolated_registry: Path) -> None:
        """save_registry rejects a dict without 'commands' key."""
        result = ops.save_registry({"metadata": {}})

        assert result is False


class TestModuleOrchestrator:
    def test_handle_command_introspection(self, isolated_registry: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """handle_command with no args triggers introspection; mutant killed: introspection skipped."""

        result = handle_command()

        assert result is True
        assert "commands Module" in capsys.readouterr().out

    def test_handle_command_add(self, isolated_registry: Path) -> None:
        """handle_command 'add' creates a command."""

        result = handle_command("add", ["test_cmd", "@branch", "do_thing", "--desc=A test"])

        assert result is True
        assert "test_cmd" in ops.load_registry()["commands"]

        registry = ops.load_registry()
        assert registry["commands"]["test_cmd"]["description"] == "A test"

    def test_handle_command_remove(self, isolated_registry: Path) -> None:
        """handle_command 'remove' deletes a command."""

        ops.add_command("doomed", "@t", "c")
        result = handle_command("remove", ["doomed"])

        assert result is True
        assert "doomed" not in ops.load_registry()["commands"]

    def test_handle_command_list(self, isolated_registry: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """handle_command 'list' prints each command; mutant killed: the list loop printing nothing."""

        ops.add_command("a", "@t", "c1")
        result = handle_command("list", [])

        assert result is True
        assert "a -> @t c1" in capsys.readouterr().out

    def test_handle_command_unknown(self, isolated_registry: Path) -> None:
        """handle_command with unknown subcommand returns False."""

        result = handle_command("unknown_sub", ["arg"])

        assert result is False


class TestListAll:
    """Tests for the list_all() module-level function."""

    def test_list_all_empty(self, isolated_registry: Path) -> None:
        """list_all returns empty list when no commands registered."""

        result = list_all()
        assert result == []

    def test_list_all_returns_sorted(self, isolated_registry: Path) -> None:
        """list_all returns commands sorted by name."""
        ops.add_command("zebra", "@t", "c1")
        ops.add_command("alpha", "@t", "c2")
        ops.add_command("middle", "@t", "c3")

        result = list_all()
        names = [c["name"] for c in result]
        assert names == ["alpha", "middle", "zebra"]

    def test_list_all_returns_all_fields(self, isolated_registry: Path) -> None:
        """list_all returns full command dicts with expected keys."""
        ops.add_command("audit", "@seedgo", "audit", ["aipass"], "Run audit", "seedgo")

        result = list_all()
        assert len(result) == 1
        cmd = result[0]
        assert cmd["name"] == "audit"
        assert cmd["target"] == "@seedgo"
        assert cmd["command"] == "audit"
        assert cmd["args"] == ["aipass"]
