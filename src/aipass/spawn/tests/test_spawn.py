# =================== META ====================
# Name: test_spawn.py
# Description: Test suite for spawn module
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/core.py (spawn_agent) and apps/handlers/registry.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — docstrings on get_branch_name, normalize_branch_name and detect_profile
# seedgo: no-test-needed(stdlib) — uuid.uuid4()'s randomness, which apps/modules/core.py mints citizen_id from

import json
import shutil
import sys
import pytest

from aipass.spawn import spawn_agent
from aipass.spawn.apps.handlers import mint_ops
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.metadata import get_branch_name, normalize_branch_name, detect_profile
from aipass.spawn.apps.handlers.placeholders import (
    build_replacements_dict,
    replace_placeholders,
    validate_no_placeholders,
)
from aipass.spawn.apps.handlers.registry import (
    load_registry,
    add_to_registry,
    save_registry,
    get_next_citizen_number,
)
from aipass.spawn.apps.modules.core import handle_command


class TestCreateFlags:
    """core.handle_command('create', ...) passes --role, --traits and --purpose through to the passport."""

    def test_role_traits_purpose_land_in_the_passport(self, tmp_agent, tmp_registry):
        """Each flag's value lands in the minted passport's identity block, under its own key.

        Green from its first run on this tree: its proof is its mutants (a flag's
        value dropped or routed to another key in handle_command -> red).
        """

        args = [
            str(tmp_agent),
            "--role",
            "Flag Role",
            "--traits",
            "curious",
            "--purpose",
            "Flag Purpose",
            "--registry",
            str(tmp_registry),
        ]

        assert handle_command("create", args) is True

        identity = json.loads((tmp_agent / ".trinity" / "passport.json").read_text(encoding="utf-8"))["identity"]
        assert identity["role"] == "Flag Role"
        assert identity["traits"] == ["curious"]
        assert identity["purpose"] == "Flag Purpose"


@pytest.fixture
def tmp_agent(tmp_path):
    """Provide a temp path for agent creation and clean up after."""
    agent_path = tmp_path / "test_agent"
    yield agent_path
    if agent_path.exists():
        shutil.rmtree(agent_path)


@pytest.fixture
def tmp_registry(tmp_path):
    """Provide a temp registry path."""
    return tmp_path / "AIPASS_REGISTRY.json"


class TestMetadata:
    def test_get_branch_name(self, tmp_path):
        assert get_branch_name(str(tmp_path / "my_agent")) == "my_agent"

    def test_normalize_upper(self):
        assert normalize_branch_name("my-agent", "upper") == "MY_AGENT"

    def test_normalize_lower(self):
        assert normalize_branch_name("My-Agent", "lower") == "my_agent"

    def test_detect_profile_default(self, tmp_path):
        assert detect_profile(tmp_path / "test") == "AIPass Workshop"


class TestPlaceholders:
    def test_build_replacements(self, tmp_path):
        r = build_replacements_dict(tmp_path / "x", "my_agent", role="Tester")
        assert r["BRANCHNAME"] == "MY_AGENT"
        assert r["branchname"] == "my_agent"
        assert r["ROLE"] == "Tester"

    def test_cwd_placeholder_is_gone(self, tmp_path):
        """{{CWD}} rendered an ABSOLUTE path into a tracked public file.

        It was replaced by {{PATH}} (DPLAN-0319), which renders RELATIVE. The
        engine must not still answer to the old name — a template that kept
        {{CWD}} would silently keep leaking /home/<user>/... into passports.
        """
        r = build_replacements_dict(tmp_path / "x", "my_agent")
        assert "CWD" not in r
        assert "PATH" in r

    def test_dead_placeholders_are_gone(self, tmp_path):
        """KEY_CAPABILITIES / DEPENDS_ON / PROVIDES_TO had zero live consumers."""
        r = build_replacements_dict(tmp_path / "x", "my_agent")
        for dead in ("KEY_CAPABILITIES", "DEPENDS_ON", "PROVIDES_TO", "TRAITS"):
            assert dead not in r, f"{dead} is back in the engine with nothing rendering it"

    def test_validate_clean_dir(self, tmp_path):
        (tmp_path / "clean.txt").write_text("no placeholders here", encoding="utf-8")
        issues = validate_no_placeholders(tmp_path)
        assert issues == []

    def test_validate_catches_placeholders(self, tmp_path):
        (tmp_path / "dirty.txt").write_text("Hello {{NAME}}", encoding="utf-8")
        issues = validate_no_placeholders(tmp_path)
        assert len(issues) == 1
        assert "NAME" in issues[0][1]


class TestRegistry:
    def test_load_missing(self, tmp_registry):
        data = load_registry(tmp_registry)
        assert data["metadata"]["total_branches"] == 0
        assert data["branches"] == []

    def test_add_and_load(self, tmp_path, tmp_registry):
        branch_path = tmp_path / "test"
        branch_path.mkdir()
        result = add_to_registry(tmp_registry, "TEST", str(branch_path), "Workshop", "@test", "A test")
        assert result is True
        data = load_registry(tmp_registry)
        assert len(data["branches"]) == 1
        assert data["branches"][0]["name"] == "TEST"

    def test_no_duplicates(self, tmp_path, tmp_registry):
        branch_path = tmp_path / "x"
        branch_path.mkdir()
        add_to_registry(tmp_registry, "X", str(branch_path), "W", "@x")
        result = add_to_registry(tmp_registry, "X", str(branch_path), "W", "@x")
        assert result is False


class TestSpawnAgent:
    def test_full_spawn(self, tmp_agent, tmp_registry):
        result = spawn_agent(
            str(tmp_agent),
            role="Test Role",
            purpose="Test Purpose",
            registry_path=str(tmp_registry),
        )
        assert result["success"] is True
        assert result["branch_name"] == "TEST_AGENT"
        assert result["files_copied"] > 0
        assert result["registry_updated"] is True
        assert result["validation_issues"] == []

        # Verify key files exist
        assert (tmp_agent / ".trinity" / "passport.json").exists()
        assert (tmp_agent / "DASHBOARD.local.json").exists()
        assert (tmp_agent / "apps" / "test_agent.py").exists()

        # Verify passport content. branch_name renders LOWERCASE in schema 2.0
        # (DPLAN-0319 R1 casing) — the UPPER form survives only as the registry
        # key and this result dict's branch_name, asserted above.
        passport = json.loads((tmp_agent / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["branch_info"]["branch_name"] == "test_agent"
        assert passport["identity"]["role"] == "Test Role"

        # Verify registry
        reg = load_registry(tmp_registry)
        assert len(reg["branches"]) == 1

    def test_newborn_todos_meta_names_its_own_backlog_not_a_placeholder(self, tmp_agent, tmp_registry):
        spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))
        local = json.loads((tmp_agent / ".trinity" / "local.json").read_text(encoding="utf-8"))
        assert ".backup/todo/test_agent/backlog.json" in local["todos_meta"]
        assert "<branch>" not in local["todos_meta"]

    def test_target_already_exists(self, tmp_path, tmp_registry):
        existing = tmp_path / "existing"
        existing.mkdir()
        result = spawn_agent(str(existing), registry_path=str(tmp_registry))
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_template_registry_regenerated(self, tmp_agent, tmp_registry):
        spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))
        reg_file = tmp_agent / ".spawn" / ".template_registry.json"
        assert reg_file.exists()
        data = json.loads(reg_file.read_text(encoding="utf-8"))
        assert data["metadata"]["generated"] is True
        assert len(data["files"]) > 0


class TestReplacePlaceholders:
    """Tests for replace_placeholders()."""

    def test_basic_replacement(self):
        content = "Hello {{NAME}}, welcome to {{PROJECT}}."
        result = replace_placeholders(content, {"NAME": "Alice", "PROJECT": "AIPass"})
        assert result == "Hello Alice, welcome to AIPass."

    def test_no_placeholders(self):
        content = "No placeholders here."
        result = replace_placeholders(content, {"FOO": "bar"})
        assert result == "No placeholders here."

    def test_multiple_occurrences(self):
        content = "{{X}} and {{X}} again"
        result = replace_placeholders(content, {"X": "val"})
        assert result == "val and val again"

    def test_empty_replacements(self):
        content = "{{STAYS}} intact"
        result = replace_placeholders(content, {})
        assert result == "{{STAYS}} intact"

    def test_value_coercion_to_string(self):
        result = replace_placeholders("number={{N}}", {"N": 42})
        assert result == "number=42"


class TestSaveRegistry:
    """Tests for save_registry()."""

    def test_saves_and_sorts_branches(self, tmp_path):
        reg_path = tmp_path / "TEST_REGISTRY.json"
        data = {
            "metadata": {"version": "1.0.0", "total_branches": 2},
            "branches": [
                {"name": "ZEBRA", "path": "zebra"},
                {"name": "ALPHA", "path": "alpha"},
            ],
        }
        save_registry(reg_path, data)
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["branches"][0]["name"] == "ALPHA"
        assert saved["branches"][1]["name"] == "ZEBRA"

    def test_updates_timestamp(self, tmp_path):
        reg_path = tmp_path / "TEST_REGISTRY.json"
        data = {
            "metadata": {"version": "1.0.0", "last_updated": "2020-01-01", "total_branches": 0},
            "branches": [],
        }
        save_registry(reg_path, data)
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["metadata"]["last_updated"] != "2020-01-01"

    def test_handles_dict_branches(self, tmp_path):
        reg_path = tmp_path / "TEST_REGISTRY.json"
        data = {
            "metadata": {"version": "1.0.0", "total_branches": 1},
            "branches": {"MY_AGENT": {"name": "MY_AGENT", "path": "my_agent"}},
        }
        save_registry(reg_path, data)
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert isinstance(saved["branches"], list)
        assert saved["branches"][0]["name"] == "MY_AGENT"


class TestGetNextCitizenNumber:
    """Tests for get_next_citizen_number()."""

    def test_empty_registry(self, tmp_path):
        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}', encoding="utf-8")
        assert get_next_citizen_number(reg_path) == 1

    def test_with_existing_branches(self, tmp_path):
        reg_path = tmp_path / "TEST_REGISTRY.json"
        reg_path.write_text(
            '{"metadata":{"version":"1.0.0","total_branches":2},"branches":[{"name":"A"},{"name":"B"}]}',
            encoding="utf-8",
        )
        assert get_next_citizen_number(reg_path) == 3

    def test_missing_registry(self, tmp_path):
        reg_path = tmp_path / "NONEXISTENT_REGISTRY.json"
        assert get_next_citizen_number(reg_path) == 1


class TestPathContainment:
    """Path containment, observed through add_to_registry() on a tmp_path registry."""

    def test_contained_path_accepted(self, tmp_path):
        """Mutant: containment rejects every path -> red."""
        reg = tmp_path / "TEST_REGISTRY.json"
        branch = tmp_path / "my_agent"
        assert add_to_registry(reg, "MY_AGENT", str(branch), "Test", "@my_agent") is True
        assert [b["name"] for b in load_registry(reg)["branches"]] == ["MY_AGENT"]

    def test_escaped_path_rejected(self, tmp_path):
        """Mutant: containment accepts every path -> red."""
        reg = tmp_path / "TEST_REGISTRY.json"
        escaped = tmp_path.parent / "evil"
        assert add_to_registry(reg, "EVIL", str(escaped), "Test", "@evil") is False
        assert not reg.exists()

    def test_traversal_attack_rejected(self, tmp_path):
        reg = tmp_path / "TEST_REGISTRY.json"
        branch = str(tmp_path / ".." / ".." / "tmp" / "evil")
        assert add_to_registry(reg, "EVIL", branch, "Test", "@evil") is False
        assert not reg.exists()


class TestAtomicWriteAndLocking:
    """Tests for atomic writes and file locking in registry operations."""

    @pytest.mark.skipif(sys.platform == "win32", reason="fcntl-based locking not available on Windows")
    def test_add_to_registry_creates_lock_file(self, tmp_path):
        reg = tmp_path / "TEST_REGISTRY.json"
        branch = tmp_path / "agent_a"
        branch.mkdir()
        add_to_registry(reg, "AGENT_A", str(branch), "W", "@a")
        lock = tmp_path / ".TEST_REGISTRY.lock"
        assert lock.exists()

    def test_atomic_write_not_corrupted(self, tmp_path):
        reg = tmp_path / "TEST_REGISTRY.json"
        branch = tmp_path / "agent_b"
        branch.mkdir()
        add_to_registry(reg, "AGENT_B", str(branch), "W", "@b")
        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["branches"][0]["name"] == "AGENT_B"

    def test_path_containment_blocks_add(self, tmp_path):
        reg = tmp_path / "TEST_REGISTRY.json"
        escaped = tmp_path.parent / "evil"
        result = add_to_registry(reg, "EVIL", str(escaped), "W", "@evil")
        assert result is False
        data = json.loads(reg.read_text(encoding="utf-8")) if reg.exists() else {"branches": []}
        assert len(data.get("branches", [])) == 0


class TestMintRefusals:
    """spawn_agent refuses a mint it cannot finish honestly, and says so."""

    @pytest.mark.parametrize(
        ("flag", "value"),
        [("purpose", 'Say "hi"'), ("role", "C:\\data"), ("purpose", "two\nlines")],
    )
    def test_a_json_breaking_role_or_purpose_refuses_before_anything_is_written(
        self, tmp_agent, tmp_registry, flag, value
    ):
        result = spawn_agent(str(tmp_agent), registry_path=str(tmp_registry), **{flag: value})

        assert result["success"] is False
        assert f"--{flag}" in result["error"]
        assert not tmp_agent.exists()
        assert not tmp_registry.exists()

    def test_a_name_already_registered_refuses_before_any_copy(self, tmp_path, tmp_agent, tmp_registry):
        add_to_registry(tmp_registry, "TEST_AGENT", str(tmp_path / "elsewhere"), "W", "@test_agent")

        result = spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))

        assert result["success"] is False
        assert "already registered" in result["error"]
        assert not tmp_agent.exists()

    def test_a_failed_registry_add_is_an_error_not_a_success(self, tmp_path, tmp_agent, tmp_registry, monkeypatch):
        real_add = mint_ops.add_to_registry

        def racing_add(registry, name, *args, **kwargs):
            # A parallel mint registers the same name between the pre-copy check and this add.
            real_add(registry, name, str(tmp_path / "raced"), "W", "@raced")
            return real_add(registry, name, *args, **kwargs)

        monkeypatch.setattr(mint_ops, "add_to_registry", racing_add)

        result = spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))

        assert result["success"] is False
        assert "NOT registered" in result["error"]

    def test_a_relative_registry_is_the_one_used_not_a_new_one(self, tmp_path, monkeypatch):
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "project-credential"}, "branches": []}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = spawn_agent(str(tmp_path / "newbie"), registry_path="TEST_REGISTRY.json")

        assert result["success"] is True
        assert result["registry_path"] == str(registry)
        passport = json.loads((tmp_path / "newbie" / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "project-credential"
        assert [b["name"] for b in load_registry(registry)["branches"]] == ["NEWBIE"]

    def test_a_retry_after_an_incomplete_mint_refuses_instead_of_adopting(self, tmp_path, tmp_registry):
        template = tmp_path / "tmpl"
        shutil.copytree(get_template_dir(), template)
        manifest = template / ".spawn" / ".template_registry.json"
        claims = json.loads(manifest.read_text(encoding="utf-8"))
        claims["files"]["never_shipped"] = {"path": "never_shipped.md"}
        manifest.write_text(json.dumps(claims), encoding="utf-8")
        target = tmp_path / "partial"

        first = spawn_agent(str(target), template_dir=str(template), registry_path=str(tmp_registry))
        retry = spawn_agent(str(target), template_dir=str(template), registry_path=str(tmp_registry))

        assert "INCOMPLETE MINT" in first["error"]
        assert retry["success"] is False
        assert "refused mint" in retry["error"]
        assert load_registry(tmp_registry)["branches"] == []
