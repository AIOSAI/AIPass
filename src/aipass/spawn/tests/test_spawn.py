# =================== META ====================
# Name: test_spawn.py
# Description: Test suite for spawn module
# Version: 1.4.3
# Created: 2026-03-05
# Modified: 2026-11-22
# =============================================

"""Tests for apps/modules/core.py (spawn_agent) and apps/handlers/registry.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(documentation) — docstrings on get_branch_name, normalize_branch_name and detect_profile
# sentry: no-test-needed(stdlib) — uuid.uuid4()'s randomness, which apps/modules/core.py mints citizen_id from

import json
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aipass.spawn import restore_citizen, spawn_agent
from aipass.spawn.apps.handlers.seed_ops import export_seeds
from aipass.spawn.apps.handlers import mint_ops
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.metadata import (
    BRANCH_NAME_RULE,
    branch_name_refusal,
    get_branch_name,
    normalize_branch_name,
    detect_profile,
)
from aipass.spawn.apps.handlers.project_defaults import PROJECT_TEMPLATE_DIR, stamp_onboarding
from aipass.spawn.apps.handlers.update_ignore import is_ignored, read_ignore
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
from aipass.spawn.apps.handlers.repair_ops import rename_branch
from aipass.spawn.apps.handlers.sync_registry_ops import sync_registry
from aipass.spawn.apps.modules.core import handle_command
from aipass.spawn.apps.spawn import handle_create


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

    @pytest.mark.parametrize("shape", ["list", "dict"])
    def test_a_name_differing_only_in_case_is_a_duplicate(self, tmp_path, tmp_registry, shape):
        """A mixed registry holds FLOW and flow as one agent. Mutant: the guard compares exact case -> red."""
        branch_path = tmp_path / "flow"
        branch_path.mkdir()
        row = {"name": "FLOW", "path": "flow"}
        branches = [row] if shape == "list" else {"FLOW": row}
        tmp_registry.write_text(json.dumps({"metadata": {}, "branches": branches}), encoding="utf-8")

        assert add_to_registry(tmp_registry, "flow", str(branch_path), "W", "@flow") is False
        assert len(json.loads(tmp_registry.read_text(encoding="utf-8"))["branches"]) == 1


class TestSpawnAgent:
    def test_a_newborn_certificate_names_its_owner_in_lowercase(self, tmp_agent, tmp_registry):
        """Mutant: the certificate template's owner back on the capital token -> red."""
        assert spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))["success"] is True

        certificate = json.loads((tmp_agent / "artifacts" / "birth_certificate.json").read_text(encoding="utf-8"))
        assert certificate["owner"] == "test_agent"

    def test_full_spawn(self, tmp_agent, tmp_registry):
        result = spawn_agent(
            str(tmp_agent),
            role="Test Role",
            purpose="Test Purpose",
            registry_path=str(tmp_registry),
        )
        assert result["success"] is True
        assert result["branch_name"] == "test_agent"
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

    @pytest.mark.parametrize("stored", ["test_agent", "TEST_AGENT"])
    def test_a_name_registered_in_either_case_refuses_before_any_copy(self, tmp_path, tmp_agent, tmp_registry, stored):
        """The pre-copy guard ignores case. Mutant: it compares exact case -> red on the other spelling."""
        add_to_registry(tmp_registry, stored, str(tmp_path / "elsewhere"), "W", "@test_agent")

        result = spawn_agent(str(tmp_agent), registry_path=str(tmp_registry))

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
        assert [b["name"] for b in load_registry(registry)["branches"]] == ["newbie"]

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


def first_seat(tmp_path, arrival=None):
    """Mint a project's first seat at <project>/grow and return (project root, seat, result)."""
    seat = tmp_path / "grow"
    result = spawn_agent(str(seat), registry_path=str(tmp_path / "SEED_REGISTRY.json"), arrival=arrival)
    assert result["success"] is True, result.get("error")
    return tmp_path, seat, result


class TestArrivalDefaults:
    """A named arrival stamps the project's defaults and the seat's First wake; no arrival stamps nothing."""

    @pytest.fixture(autouse=True)
    def aipass_home(self, tmp_path):
        """Every stamp's AIPass home is a tmp folder beside the project, never the live one."""
        home = SimpleNamespace(path=tmp_path.parent / f"{tmp_path.name}_home", source="test", tried=())
        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            yield home.path

    def test_a_fresh_seat_gets_the_fresh_defaults(self, tmp_path):
        """Mutant: the First wake is never stamped -> red."""
        root, seat, result = first_seat(tmp_path, "fresh")

        assert result["arrival"]["first_wake"] == "stamped (fresh)"
        assert result["arrival"]["updateignore"] == "stamped (fresh)"
        assert result["validation_issues"] == []
        prompt = (seat / ".aipass" / "aipass_local_prompt.md").read_text(encoding="utf-8")
        assert prompt.split("\n")[2] == "# First wake"
        assert "born with you" in prompt and "Edit this section out of this prompt" in prompt
        assert (root / ".updateignore").read_text(encoding="utf-8") == (
            PROJECT_TEMPLATE_DIR / "updateignore_fresh"
        ).read_text(encoding="utf-8")

    def test_a_prompt_that_resolves_outside_the_seat_is_refused_never_followed(self, tmp_path):
        """Mutant: the containment check is dropped -> the outside file's text is read into the seat -> red."""
        seat = tmp_path / "seat"
        (seat / ".aipass").mkdir(parents=True)
        outside = tmp_path / "elsewhere.md"
        outside.write_text("# not the seat's\nprivate\n", encoding="utf-8")
        (seat / ".aipass" / "aipass_local_prompt.md").symlink_to(outside)

        with pytest.raises(PermissionError, match="resolves outside the seat"):
            stamp_onboarding(seat, "fresh")

        assert outside.read_text(encoding="utf-8") == "# not the seat's\nprivate\n"
        assert (seat / ".aipass" / "aipass_local_prompt.md").is_symlink()

    def test_a_seat_that_is_not_a_directory_is_answered_not_stamped(self, tmp_path):
        """No filesystem call touches the raw seat path (CodeQL); a file seat has no prompt to stamp.

        Mutant: the prompt's is_file check is dropped -> reading under a file raises -> red."""
        not_a_seat = tmp_path / "file.txt"
        not_a_seat.write_text("", encoding="utf-8")

        assert stamp_onboarding(not_a_seat, "fresh").startswith("not stamped")
        assert not_a_seat.read_text(encoding="utf-8") == ""

    def test_the_stamped_rows_hold_every_seats_own_files_and_nothing_else(self, tmp_path):
        """The proof that stamping protects: the update lane's own matcher reads the stamped file."""
        root, _, _ = first_seat(tmp_path, "adopted")
        rows = read_ignore(root)

        held = ["AGENTS.md", ".gitignore", ".aipass/tier1_navmap.md", "grow/.aipass/aipass_local_prompt.md"]
        held += ["src/pkg/scout/.aipass/aipass_local_prompt.md", "grow/docs.local/draft.md", "src/pkg/scout/.gitignore"]
        assert [rel for rel in held if not is_ignored(rel, rows)] == []
        free = ["grow/apps/grow.py", ".aipass/tier0_kernel.md", "grow/README.md", "src/product/main.ts"]
        assert [rel for rel in free if is_ignored(rel, rows)] == []

    def test_an_adopted_seat_gets_the_adopted_defaults_below_a_header_only_file(self, tmp_path):
        """Mutant: a header-only file is overwritten, losing its text -> red."""
        header = "# Owner-protected: header only, no rows yet.\n"
        (tmp_path / ".updateignore").write_text(header, encoding="utf-8")

        root, seat, _ = first_seat(tmp_path, "adopted")

        stamped = (root / ".updateignore").read_text(encoding="utf-8")
        assert stamped.startswith(header)
        assert ".gitignore" in read_ignore(root)
        assert "alive before you" in (seat / ".aipass" / "aipass_local_prompt.md").read_text(encoding="utf-8")

    def test_the_owners_rows_are_never_touched(self, tmp_path):
        """Mutant: the row check is dropped and the default stamped over the owner's file -> red."""
        (tmp_path / ".updateignore").write_text("CHANGELOG.md\n", encoding="utf-8")

        root, _, result = first_seat(tmp_path, "adopted")

        assert (root / ".updateignore").read_text(encoding="utf-8") == "CHANGELOG.md\n"
        assert result["arrival"]["updateignore"] == "kept: the owner's 1 row(s)"

    def test_no_arrival_stamps_nothing(self, tmp_path):
        """Mutant: the defaults stamp without an arrival -> red."""
        root, seat, result = first_seat(tmp_path)

        assert result["arrival"] == {}
        assert not (root / ".updateignore").exists()
        assert "# First wake" not in (seat / ".aipass" / "aipass_local_prompt.md").read_text(encoding="utf-8")

    def test_an_unknown_arrival_is_refused_before_any_write(self, tmp_path):
        """Mutant: the arrival check is dropped -> the mint reads a template that does not exist -> red."""
        result = spawn_agent(str(tmp_path / "grow"), registry_path=str(tmp_path / "SEED_REGISTRY.json"), arrival="x")

        assert result["success"] is False and "--arrival must be one of fresh, adopted" in result["error"]
        assert list(tmp_path.iterdir()) == []

    def test_a_core_citizen_takes_no_arrival(self, tmp_path):
        """Mutant: the core guard is dropped -> the AIPass tree's own .updateignore is stamped -> red."""
        home = SimpleNamespace(path=tmp_path, source="test", tried=())
        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            result = spawn_agent(
                str(tmp_path / "src" / "aipass" / "scout"),
                registry_path=str(tmp_path / "AIPASS_REGISTRY.json"),
                arrival="fresh",
            )

        assert result["success"] is False and "core citizen" in result["error"]
        assert not (tmp_path / ".updateignore").exists()

    def test_an_external_seat_keeps_a_durable_seed_copy_under_the_home(self, tmp_path, aipass_home):
        """Mutant: the mint skips the home copy -> a reclone loses the seat's identity -> red."""
        root, seat, result = first_seat(tmp_path, "adopted")

        home_copy = aipass_home / ".aipass" / "vault" / root.name / "grow.passport.vault.json"
        assert result["arrival"]["home_seed"] == f"copied to {home_copy}"
        assert home_copy.read_bytes() == (seat / ".aipass" / "passport.vault.json").read_bytes()

    def test_a_rewritten_seed_rewrites_its_home_copy(self, tmp_path, aipass_home):
        """Mutant: export-vault stops refreshing the home copy -> restore would read a stale identity -> red."""
        root, seat, _ = first_seat(tmp_path, "adopted")
        passport_file = seat / ".trinity" / "passport.json"
        passport = json.loads(passport_file.read_text(encoding="utf-8"))
        passport["identity"]["role"] = "product_steward"
        passport_file.write_text(json.dumps(passport, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        receipt = export_seeds(root, confirm=True)

        home_copy = aipass_home / ".aipass" / "vault" / root.name / "grow.passport.vault.json"
        assert receipt["errors"] == []
        assert json.loads(home_copy.read_text(encoding="utf-8"))["identity"]["role"] == "product_steward"

    def test_a_reclone_restores_the_seat_from_its_home_copy(self, tmp_path):
        """Mutant: restore stops reading the home copy -> the seedless refusal -> red."""
        root, seat, _ = first_seat(tmp_path, "adopted")
        before = json.loads((seat / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        (seat / ".trinity" / "passport.json").unlink()
        (seat / ".aipass" / "passport.vault.json").unlink()

        written = restore_citizen("grow", root / "SEED_REGISTRY.json")

        restored = json.loads((seat / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert written == ["passport.json(seed)"]
        assert restored["identity"] == before["identity"]
        assert (seat / ".aipass" / "passport.vault.json").is_file()

    def test_an_external_project_gets_a_test_policy_that_is_off_and_named(self, tmp_path):
        """Mutant: the policy is never stamped -> the gate fail-closes with a missing-policy error -> red."""
        root, _, result = first_seat(tmp_path, "fresh")

        policy = json.loads((root / ".aipass" / "test_write_policy.json").read_text(encoding="utf-8"))
        assert result["arrival"]["test_policy"] == "stamped (off)"
        assert (policy["agent_test_writing"], policy["allow"], policy["block_test_edits"]) == ("off", [], False)
        assert "owner flips this per project" in policy["note"]

    def test_an_existing_test_policy_is_never_touched(self, tmp_path):
        """Mutant: the stamp overwrites the owner's policy -> the owner's 'on' is lost -> red."""
        (tmp_path / ".aipass").mkdir()
        (tmp_path / ".aipass" / "test_write_policy.json").write_text('{"agent_test_writing": "on"}', encoding="utf-8")

        root, _, result = first_seat(tmp_path, "adopted")

        assert (root / ".aipass" / "test_write_policy.json").read_text(encoding="utf-8") == (
            '{"agent_test_writing": "on"}'
        )
        assert result["arrival"]["test_policy"] == "kept: the owner's file"


def _passported(root, name="probe", registered=True, lane="passport"):
    """A tmp project with a citizen folder at root/<name>: a passport or only a vault, a row or none."""
    target = root / name
    if lane == "passport":
        (target / ".trinity").mkdir(parents=True)
        (target / ".trinity" / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "specialist", "purpose": "Live agent"}}), encoding="utf-8"
        )
    else:
        (target / ".aipass").mkdir(parents=True)
        (target / ".aipass" / "passport.vault.json").write_text("{}", encoding="utf-8")
    rows = [{"name": name.upper(), "path": name}] if registered else []
    reg = root / "TEST_REGISTRY.json"
    reg.write_text(json.dumps({"metadata": {"id": "cred"}, "branches": rows}), encoding="utf-8")
    return target, reg


def _tree(root):
    """Every file under root, relative path -> bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class TestCreateOverALiveAgent:
    """A passport plus a row for the target's path makes it live: create refuses and points at update and repair."""

    def test_a_registered_agent_is_refused_and_nothing_is_written(self, tmp_path):
        """Mutant: the live-row check in spawn_at skipped -> adopt rewrites the tree and the registry -> red."""
        target, reg = _passported(tmp_path)
        before, reg_before = _tree(target), reg.read_bytes()

        result = spawn_agent(str(target), registry_path=str(reg))

        assert result["success"] is False
        assert "drone @spawn update @probe" in result["error"]
        assert "drone @spawn repair" in result["error"]
        assert _tree(target) == before
        assert reg.read_bytes() == reg_before

    def test_the_cli_refusal_exits_non_zero_and_never_says_created(self, tmp_path, capsys):
        target, reg = _passported(tmp_path)

        assert handle_create([str(target), "--registry", str(reg)]) == 1
        said = "".join(capsys.readouterr())
        assert "already registered" in said and "Agent created" not in said

    def test_a_registered_seat_with_only_a_vault_still_takes_the_vault_lane(self, tmp_path):
        """No passport is no live agent: a cloned seat is born from its vault (docs/birth.md).

        Mutant: the live-row check also runs for a vault-only seat -> refused as live -> red."""
        target, reg = _passported(tmp_path, lane="vault")

        result = spawn_agent(str(target), registry_path=str(reg))

        assert "already registered" not in result["error"]
        assert result["error"].startswith("VAULT REFUSED")

    def test_a_passported_folder_with_no_row_still_adopts(self, tmp_path):
        """Mutant: the check refuses every passported folder -> the create @existing lane dies -> red."""
        target, reg = _passported(tmp_path, registered=False)

        result = spawn_agent(str(target), registry_path=str(reg))

        assert result["success"] is True and result["adopted"] is True
        assert [b["name"] for b in load_registry(reg)["branches"]] == ["probe"]


BAD_NAMES = ["probe bad", "ProbeCap", "probé", "p" * 200, "-probe_dash"]


class TestBranchNameRule:
    """One name rule, checked before create writes anything, on every lane create takes."""

    @pytest.mark.parametrize("name", ["probe", "ai_mail", "my-agent", "p" * 32])
    def test_good_names_pass(self, name):
        assert branch_name_refusal(name) == ""

    @pytest.mark.parametrize("name", [*BAD_NAMES, "p" * 33])
    def test_bad_names_are_refused_with_the_rule_quoted(self, name):
        """Mutant: the 32-char cap dropped from the pattern -> the long names pass -> red."""
        assert BRANCH_NAME_RULE in branch_name_refusal(name)

    @pytest.mark.parametrize("lane", ["mint", "passport", "vault"])
    @pytest.mark.parametrize("name", BAD_NAMES)
    def test_create_refuses_a_bad_name_before_any_write(self, tmp_path, lane, name):
        """Mutant: the name check in spawn_at removed -> mint, adopt or seed birth goes ahead -> red."""
        if lane == "mint":
            target, reg = tmp_path / name, tmp_path / "TEST_REGISTRY.json"
            reg.write_text(json.dumps({"metadata": {"id": "cred"}, "branches": []}), encoding="utf-8")
        else:
            target, reg = _passported(tmp_path, name=name, registered=False, lane=lane)
        before, reg_before = _tree(tmp_path), reg.read_bytes()

        result = spawn_agent(str(target), registry_path=str(reg))

        assert result["success"] is False
        assert BRANCH_NAME_RULE in result["error"]
        assert _tree(tmp_path) == before and reg.read_bytes() == reg_before
        assert target.exists() is (lane != "mint")


class TestMixedRegistry:
    """Until the conversion runs, a registry holds capital rows beside lowercase ones; every writer must hold."""

    def test_mint_adopt_sync_and_rename_on_a_mixed_registry(self, tmp_path):
        """Each writer adds lowercase, none doubles the capital row, and the capital row keeps its flags.

        Mutant: a writer stores capitals again, or a duplicate guard compares exact case -> red."""
        project = tmp_path / "mixed"
        reg = project / "MIXED_REGISTRY.json"
        capital = {"name": "KEEPER", "path": "keeper", "registry_id": "cid-cap", "owner": True, "admin": True}
        (project / "keeper" / ".trinity").mkdir(parents=True)
        (project / "keeper" / ".trinity" / "passport.json").write_text(
            json.dumps({"citizenship": {"citizen_id": "cid-cap"}}), encoding="utf-8"
        )
        reg.write_text(json.dumps({"metadata": {"id": "cred"}, "branches": [capital]}), encoding="utf-8")
        for seat in ("adoptee", "stray"):
            (project / seat / ".trinity").mkdir(parents=True)
            (project / seat / ".trinity" / "passport.json").write_text(
                json.dumps({"identity": {"citizen_class": "specialist", "purpose": "Live agent"}}), encoding="utf-8"
            )

        def rows():
            return {r["name"]: r for r in json.loads(reg.read_text(encoding="utf-8"))["branches"]}

        assert spawn_agent(str(project / "fresh"), registry_path=str(reg))["success"] is True
        assert "already registered" in spawn_agent(str(project / "other" / "keeper"), registry_path=str(reg))["error"]
        assert spawn_agent(str(project / "adoptee"), registry_path=str(reg))["adopted"] is True
        assert sync_registry(fix=True, registry_path=reg)["fixed"] is True
        assert set(rows()) == {"KEEPER", "fresh", "adoptee", "stray"}

        shutil.move(str(project / "keeper"), str(project / "kept"))
        assert rename_branch("@keeper", "@kept", registry_path=reg, dry_run=False)["success"] is True

        assert set(rows()) == {"kept", "fresh", "adoptee", "stray"}
        kept = rows()["kept"]
        assert (kept["path"], kept["registry_id"], kept["owner"], kept["admin"]) == ("kept", "cid-cap", True, True)
