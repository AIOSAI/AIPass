# =================== META ====================
# Name: test_citizen_classes.py
# Description: Integration tests for citizen class system
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-08-08
# =============================================

"""Integration tests for the citizen class template system.

Tests class registry, class-aware create,
class-aware update, and backward compatibility.
"""

import json
from pathlib import Path

import pytest

# =============================================================================
# CLASS REGISTRY TESTS
# =============================================================================


# The two live classes, and the one template directory they both mint from
# (DPLAN-0319 R3/R4). Spelled out literally rather than read from the registry:
# a test that asks the code under test what it should contain cannot catch the
# roster changing.
LIVE_CLASSES = ["manager", "specialist"]
RETIRED_CLASSES = {"aipass_framework": "specialist", "builder": "specialist", "project_agent": "manager"}
TEMPLATE_DIR_NAME = "citizen"


class TestClassRegistry:
    """Tests for apps/handlers/class_registry.py"""

    def test_get_available_classes(self):
        """The roster is exactly manager + specialist — nothing more, nothing less."""
        from aipass.spawn.apps.handlers.class_registry import get_available_classes

        assert get_available_classes() == LIVE_CLASSES

    def test_validate_class_valid(self):
        """Both live class names validate as True."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("specialist") is True
        assert validate_class("manager") is True

    def test_validate_class_invalid(self):
        """Unknown or empty class names validate as False."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("nonexistent") is False
        assert validate_class("") is False

    def test_validate_class_retired_birthright(self):
        """Retired 'birthright' class should validate as False."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("birthright") is False

    @pytest.mark.parametrize("retired", sorted(RETIRED_CLASSES))
    def test_validate_class_retired_names(self, retired):
        """The DPLAN-0319 R4 renames answer False — they are not classes any more."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class(retired) is False

    def test_get_default_class(self):
        """Default citizen class is 'specialist' — the class most citizens are."""
        from aipass.spawn.apps.handlers.class_registry import get_default_class

        assert get_default_class() == "specialist"

    def test_get_template_dir_is_the_one_citizen_dir(self):
        """CONTRACT CHANGED (R3): the template dir is named for what it is, not a class.

        This used to pin ``get_template_dir("aipass_framework").name ==
        "aipass_framework"``. A class-named template dir became wrong by
        construction the moment two classes shared one template, so both classes
        now resolve the SAME directory and its name is neutral.
        """
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        paths = {cls: get_template_dir(cls) for cls in LIVE_CLASSES}
        assert {p.name for p in paths.values()} == {TEMPLATE_DIR_NAME}
        assert len(set(paths.values())) == 1, f"classes forked the template again: {paths}"
        assert paths["manager"].is_dir()

    def test_get_template_dirs_deduplicates(self):
        """Iterating classes to do per-template work would do it twice, one dir."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dirs

        dirs = get_template_dirs()
        assert len(dirs) == 1
        assert dirs[0].name == TEMPLATE_DIR_NAME

    def test_get_template_dir_invalid_raises(self):
        """Requesting an unknown class raises ValueError."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        with pytest.raises(ValueError, match="Unknown citizen class"):
            get_template_dir("nonexistent")

    @pytest.mark.parametrize("retired,replacement", sorted(RETIRED_CLASSES.items()))
    def test_get_template_dir_refuses_retired_names_loudly(self, retired, replacement):
        """A retired name is REFUSED by name, never silently mapped to its replacement.

        A silent map would let a caller that still types the old name keep working
        while the passport spawn writes says something else — the exact drift this
        rework exists to end.
        """
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        with pytest.raises(ValueError) as exc:
            get_template_dir(retired)

        message = str(exc.value)
        assert retired in message
        assert replacement in message
        assert "retired" in message.lower()

    def test_manager_is_now_template_selectable(self):
        """CONTRACT INVERTED (R4): 'manager' used to be identity-only.

        It had no template of its own, so ``validate_class("manager")`` was False
        and the CLI could not accept it. It is a first-class registered class now.
        """
        from aipass.spawn.apps.handlers.class_registry import (
            CITIZEN_CLASSES,
            IDENTITY_CITIZEN_CLASSES,
            validate_class,
        )

        assert validate_class("manager") is True
        assert "manager" in CITIZEN_CLASSES
        # The identity set used to be a strict SUPERSET of the template set; the
        # superset collapsed to equality when manager got a template.
        assert set(IDENTITY_CITIZEN_CLASSES) == set(CITIZEN_CLASSES) == set(LIVE_CLASSES)

    @pytest.mark.parametrize("citizen_class", LIVE_CLASSES)
    def test_resolve_template_class_passthrough_for_registered_classes(self, citizen_class):
        """Every registered class resolves to itself, unchanged."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        assert resolve_template_class({"citizen_class": citizen_class}) == citizen_class

    def test_resolve_template_class_ignores_free_text_role(self):
        """CONTRACT REMOVED (R3): the ``role == "project_agent"`` tiebreaker died.

        It existed to pick between two template shapes for a manager. There is one
        shape left, so reading a passport's free-text role to choose one would be
        inventing a distinction — and "project_agent" is a retired word besides.
        The class alone decides, whatever the role says.
        """
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        assert resolve_template_class({"citizen_class": "manager", "role": "project_agent"}) == "manager"
        assert resolve_template_class({"citizen_class": "manager", "role": "orchestration_hub"}) == "manager"
        assert resolve_template_class({"citizen_class": "manager"}) == "manager"
        assert resolve_template_class({"citizen_class": "specialist", "role": "project_agent"}) == "specialist"

    def test_resolve_template_class_unknown_raises(self):
        """An unregistered citizen_class raises ValueError naming registered classes."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        with pytest.raises(ValueError, match="Unknown citizen_class"):
            resolve_template_class({"citizen_class": "nonexistent"})

    @pytest.mark.parametrize("retired,replacement", sorted(RETIRED_CLASSES.items()))
    def test_resolve_template_class_refuses_a_retired_passport(self, retired, replacement):
        """A passport still on a retired class reads as "migrate me", not as a silent update."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        with pytest.raises(ValueError) as exc:
            resolve_template_class({"citizen_class": retired, "role": "anything"})

        assert replacement in str(exc.value)

    @pytest.mark.parametrize("retired,replacement", sorted(RETIRED_CLASSES.items()))
    def test_refuse_legacy_class_is_the_one_message(self, retired, replacement):
        """Every entry point quotes the same sentence, from the same table."""
        from aipass.spawn.apps.handlers.class_registry import LEGACY_CLASSES, refuse_legacy_class

        assert LEGACY_CLASSES[retired] == replacement
        assert refuse_legacy_class(retired) == refuse_legacy_class(retired.upper())
        assert refuse_legacy_class("specialist") == ""
        assert refuse_legacy_class("manager") == ""
        assert refuse_legacy_class(None) == ""


class TestMintTimeClass:
    """R3: the class is DERIVED at mint from the citizen number, not typed.

    A project's first citizen manages it; everyone after is a specialist. The
    signal (``get_next_citizen_number``) already existed at mint time, so routing
    it into class selection removes one thing a caller can get wrong. An explicit
    caller-supplied class still wins — that is the seam @aipass's ``new_project``
    sits on while its own fix lands.
    """

    @staticmethod
    def _fresh_registry(tmp_path):
        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}', encoding="utf-8")
        return reg

    @staticmethod
    def _class_of(branch_dir):
        return json.loads((branch_dir / ".trinity" / "passport.json").read_text())["identity"]["citizen_class"]

    def test_class_for_citizen_number_is_the_rule_itself(self):
        """The pure function, pinned literally — one citizen number, one class."""
        from aipass.spawn.apps.handlers.class_registry import class_for_citizen_number

        assert class_for_citizen_number(1) == "manager"
        for later in (2, 3, 17, 4000):
            assert class_for_citizen_number(later) == "specialist"

    def test_first_agent_mints_manager_second_mints_specialist(self, tmp_path):
        """The rule through a real mint, in a project that starts empty."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = self._fresh_registry(tmp_path)

        first = _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))
        second = _spawn_agent(str(tmp_path / "second"), registry_path=str(reg))
        third = _spawn_agent(str(tmp_path / "third"), registry_path=str(reg))

        assert first["citizen_number"] == 1
        assert second["citizen_number"] == 2
        assert third["citizen_number"] == 3
        assert self._class_of(tmp_path / "first") == "manager"
        assert self._class_of(tmp_path / "second") == "specialist"
        assert self._class_of(tmp_path / "third") == "specialist"

    @pytest.mark.parametrize("explicit", LIVE_CLASSES)
    def test_explicit_caller_class_still_wins(self, tmp_path, explicit):
        """An explicit class overrides the number-derived one, in both directions."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = self._fresh_registry(tmp_path)

        # citizen #1 would derive "manager"; citizen #2 would derive "specialist".
        _spawn_agent(str(tmp_path / "one"), registry_path=str(reg), citizen_class=explicit)
        _spawn_agent(str(tmp_path / "two"), registry_path=str(reg), citizen_class=explicit)

        assert self._class_of(tmp_path / "one") == explicit
        assert self._class_of(tmp_path / "two") == explicit

    def test_cli_create_without_a_class_lets_the_mint_decide(self, tmp_path):
        """REGRESSION (found by this deliverable, fixed in apps/spawn.py).

        ``handle_create`` seeded ``citizen_class = get_default_class()`` when the
        caller typed no class, and an explicit class always wins — so the CLI, the
        primary entry point, handed _spawn_agent an explicit "specialist" every
        time and the mint-time decision could never fire. A fresh project's first
        citizen was born a specialist with no manager anywhere in it.
        """
        from unittest.mock import patch

        from aipass.spawn.apps.spawn import handle_create

        registry = tmp_path / "AIPASS_REGISTRY.json"
        with patch("aipass.spawn.apps.spawn.console"):
            assert handle_create([str(tmp_path / "firstborn"), "--registry", str(registry)]) == 0
            assert handle_create([str(tmp_path / "sibling"), "--registry", str(registry)]) == 0

        assert self._class_of(tmp_path / "firstborn") == "manager"
        assert self._class_of(tmp_path / "sibling") == "specialist"

    def test_cli_create_with_an_explicit_class_still_wins(self, tmp_path):
        """Typing the class must still beat the derived one — even for citizen #1."""
        from unittest.mock import patch

        from aipass.spawn.apps.spawn import handle_create

        registry = tmp_path / "AIPASS_REGISTRY.json"
        with patch("aipass.spawn.apps.spawn.console"):
            assert handle_create(["specialist", str(tmp_path / "firstborn"), "--registry", str(registry)]) == 0

        assert self._class_of(tmp_path / "firstborn") == "specialist"


class TestCustomConfigReadmeGuide:
    """The custom_config/ README ships the S193 self-heal doctrine (DPLAN-0283 WS-C)."""

    def _readme(self):
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        return get_template_dir() / "{{BRANCH}}_json" / "custom_config" / "README.md"

    def test_readme_carries_self_heal_doctrine(self):
        """Guide states the five load-bearing rules and names its source of truth."""
        text = self._readme().read_text(encoding="utf-8").lower()

        assert "runtime authority" in text
        assert "default_config" in text
        assert "regenerat" in text
        assert "deep-merged" in text
        assert "json_structure" in text

    def test_readme_does_not_carry_reversed_never_snapshot_rule(self):
        """S193 reversed never-snapshot — the retired wording must not creep back in."""
        text = self._readme().read_text(encoding="utf-8").lower()

        assert "never write defaults to disk" not in text
        assert "missing file = defaults = safe" not in text

    def test_readme_placeholders_resolve(self):
        """Every placeholder in the guide is one the scaffolder actually substitutes."""
        from aipass.spawn.apps.handlers.placeholders import replace_placeholders

        rendered = replace_placeholders(
            self._readme().read_text(encoding="utf-8"),
            {"BRANCHNAME": "TESTBRANCH", "branchname": "testbranch", "BRANCH": "testbranch"},
        )
        assert "{{" not in rendered
        assert "TESTBRANCH" in rendered


# =============================================================================
# CLASS-AWARE CREATE TESTS
# =============================================================================


class TestClassAwareCreate:
    """Tests for class-aware agent creation."""

    @pytest.mark.parametrize("citizen_class", LIVE_CLASSES)
    def test_create_explicit_class_creates_full_scaffold(self, tmp_path, citizen_class):
        """drone @spawn create <class> @path creates the full scaffold, either class."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"{citizen_class}_agent"
        result = _spawn_agent(str(target), citizen_class=citizen_class)

        assert result["success"] is True, result.get("error")
        assert (target / "apps").exists()
        assert (target / "apps" / "modules").exists()
        assert (target / "apps" / "handlers").exists()

    def test_create_without_a_class_still_creates(self, tmp_path):
        """drone @spawn create @path needs no class — the mint decides it."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "default_agent"
        result = _spawn_agent(str(target))

        assert result["success"] is True
        assert (target / "apps").exists()

    @pytest.mark.parametrize("citizen_class", LIVE_CLASSES)
    def test_create_with_citizen_class_in_passport(self, tmp_path, citizen_class):
        """Created agents carry the class they were minted with, verbatim."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"class_test_{citizen_class}"
        _spawn_agent(str(target), citizen_class=citizen_class)

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == citizen_class

    def test_create_includes_integrations_scaffold(self, tmp_path):
        """Creation includes apps/integrations/README.md (DPLAN-0133)."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "integrations_test"
        result = _spawn_agent(str(target), citizen_class="specialist")

        assert result["success"] is True
        assert (target / "apps" / "integrations").is_dir()
        assert (target / "apps" / "integrations" / "README.md").exists()

    @pytest.mark.parametrize("retired", sorted(RETIRED_CLASSES))
    def test_create_refuses_a_retired_class_and_builds_nothing(self, tmp_path, retired):
        """The Python API door: refused by name, before any filesystem work.

        @aipass's new_project still passes citizen_class="project_agent" today —
        a loud refusal is the correct answer until its parallel fix lands, not a
        quiet substitution that would write a passport disagreeing with the call.
        """
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"legacy_{retired}"
        result = _spawn_agent(str(target), citizen_class=retired)

        assert result["success"] is False
        assert retired in result["error"]
        assert not target.exists()


# =============================================================================
# CLASS-AWARE UPDATE TESTS
# =============================================================================


class TestClassAwareUpdate:
    """Tests for class-aware update behavior."""

    @pytest.mark.parametrize("citizen_class", LIVE_CLASSES)
    def test_read_citizen_class_returns_what_the_passport_claims(self, tmp_path, citizen_class):
        """Both live classes read back unchanged."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": citizen_class, "role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == citizen_class

    @pytest.mark.parametrize("retired,replacement", sorted(RETIRED_CLASSES.items()))
    def test_read_citizen_class_refuses_an_unmigrated_passport(self, tmp_path, retired, replacement):
        """An un-migrated passport surfaces as "migrate this", not a silent update
        against a class it no longer claims."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": retired, "role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        with pytest.raises(ValueError) as exc:
            _read_citizen_class(tmp_path)

        assert replacement in str(exc.value)

    def test_read_citizen_class_missing_passport_raises(self, tmp_path):
        """Missing passport is a loud hard error, not a silent default class (DPLAN-0262)."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        with pytest.raises(FileNotFoundError, match="No passport.json"):
            _read_citizen_class(tmp_path)

    def test_read_citizen_class_no_field_raises(self, tmp_path):
        """Passport without citizen_class field is a loud hard error, not a silent default."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        with pytest.raises(ValueError, match="Unknown citizen_class"):
            _read_citizen_class(tmp_path)

    def test_read_citizen_class_corrupt_passport_raises(self, tmp_path):
        """Corrupt passport JSON is a loud hard error naming the passport path."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        (passport_dir / "passport.json").write_text("{not valid json")

        with pytest.raises(ValueError, match="Corrupt or unreadable passport.json"):
            _read_citizen_class(tmp_path)

    @pytest.mark.parametrize("role", ["orchestration_hub", "project_agent", ""])
    def test_read_citizen_class_never_reads_the_role(self, tmp_path, role):
        """CONTRACT REMOVED (R3): a manager's free-text role used to pick the template.

        ``role == "project_agent"`` resolved the project_agent template and any
        other role resolved aipass_framework. Both targets are gone and there is
        one template shape, so the role is not consulted at all — a manager is a
        manager whatever it wrote in its own role field.
        """
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "manager", "role": role}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "manager"

    def test_update_all_requires_class_via_cli(self):
        """update --all without class should return error code."""
        from aipass.spawn.apps.modules.update import handle_update

        result = handle_update(["--all"])
        assert result == 1

    def test_update_cli_accepts_class_with_all(self):
        """update specialist --all should parse correctly and call update_all with class filter."""
        from unittest.mock import patch

        from aipass.spawn.apps.modules.update import handle_update

        # Mock update_all to isolate from real branch state
        mock_results = [
            {
                "branch": "test",
                "success": True,
                "additions": 0,
                "renames": 0,
                "updates": 0,
                "pruned": 0,
                "skipped_py": 0,
                "errors": [],
                "dry_run": True,
            }
        ]
        with patch("aipass.spawn.apps.modules.update.update_all", return_value=mock_results) as mock_ua:
            result = handle_update(["specialist", "--all", "--dry-run"])

        assert result == 0
        mock_ua.assert_called_once_with(dry_run=True, trace=False, citizen_class="specialist")


# =============================================================================
# TEMPLATE STRUCTURE TESTS
# =============================================================================


class TestTemplateStructure:
    """Tests verifying template directory structure."""

    def _template(self):
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        return get_template_dir()

    def test_citizen_template_exists(self):
        """The citizen template directory has .trinity/passport.json and apps/."""
        tpl = self._template()
        assert tpl.is_dir()
        assert (tpl / ".trinity" / "passport.json").exists()
        assert (tpl / "apps").is_dir()

    def test_citizen_passport_has_class_placeholder(self):
        """The template passport has the citizen_class placeholder for rendering."""
        passport = json.loads((self._template() / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "{{CITIZEN_CLASS}}"

    def test_template_passport_traits_is_an_empty_list_not_a_placeholder(self):
        """CONTRACT INVERTED (R7): identity.traits used to be the string "{{TRAITS}}".

        The 2.0 field set makes traits/what_i_do/what_i_dont_do LISTS, and the
        {{TRAITS}} placeholder is gone from the engine entirely. ``--traits`` is
        written post-render by core.py instead (see TestAgentScaffoldContent) —
        without that write the flag would be accepted and silently dropped.
        """
        passport = json.loads((self._template() / ".trinity" / "passport.json").read_text())

        assert passport["identity"]["traits"] == []
        assert passport["identity"]["what_i_do"] == []
        assert passport["identity"]["what_i_dont_do"] == []
        assert "{{TRAITS}}" not in (self._template() / ".trinity" / "passport.json").read_text()

    def test_template_passport_placeholder_set_is_the_2_0_one(self):
        """{{CWD}} (absolute, leaked $HOME) became {{PATH}}; {{RESIDENCY}} is new."""
        raw = (self._template() / ".trinity" / "passport.json").read_text()
        passport = json.loads(raw)

        assert passport["branch_info"]["email"] == "{{EMAIL}}"
        assert passport["branch_info"]["path"] == "{{PATH}}"
        assert passport["citizenship"]["residency"] == "{{RESIDENCY}}"
        assert "{{CWD}}" not in raw

    def test_no_agent_template_dir(self):
        """Old agent.template directory should not exist."""
        spawn_root = Path(__file__).parents[1]
        assert not (spawn_root / "templates" / "agent.template").exists()

    def test_citizen_template_has_no_claude_md(self):
        """The template should NOT include CLAUDE.md — project root covers it."""
        assert not (self._template() / "CLAUDE.md").exists()

    def test_citizen_template_has_local_prompt(self):
        """The template includes a non-empty local prompt."""
        prompt = self._template() / ".aipass" / "aipass_local_prompt.md"
        assert prompt.exists()
        content = prompt.read_text()
        assert len(content) > 100, "Local prompt should have substantial content"
        assert "{{BRANCHNAME}}" in content

    def test_template_carries_no_class_specific_prose(self):
        """One template, two classes: it may not hardcode either class's language.

        The retired project_agent template's README and local prompt hardcoded
        "manager" prose. Shipping that from the shared template would tell every
        specialist it manages the project.
        """
        tpl = self._template()
        offenders = []
        for rel in ("README.md", ".aipass/aipass_local_prompt.md"):
            text = (tpl / rel).read_text(encoding="utf-8").lower()
            for word in ("aipass_framework", "project_agent"):
                if word in text:
                    offenders.append(f"{rel}: {word}")
        assert offenders == [], f"retired class names still in template prose: {offenders}"


# =============================================================================
# AGENT SCAFFOLD CONTENT TESTS
# =============================================================================


class TestAgentScaffoldContent:
    """Tests verifying created agents have useful content."""

    def test_created_agent_has_no_claude_md(self, tmp_path):
        """Branches should NOT have CLAUDE.md — project root covers it."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "content_test"
        _spawn_agent(str(target), role="Tester", purpose="Testing scaffold")

        assert not (target / "CLAUDE.md").exists()

    def test_created_agent_local_prompt_has_content(self, tmp_path):
        """Created agent's local prompt should reference branch identity."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "prompt_agent"
        _spawn_agent(str(target), purpose="Testing prompt")

        prompt = target / ".aipass" / "aipass_local_prompt.md"
        assert prompt.exists()
        content = prompt.read_text()
        assert "PROMPT_AGENT" in content
        assert len(content) > 100

    def test_created_agent_passport_has_role(self, tmp_path):
        """Passport should include the agent's role if provided."""
        import json

        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "role_test"
        _spawn_agent(str(target), role="Data Analyst", purpose="Reports")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["role"] == "Data Analyst"

    def test_created_agent_passport_has_traits_as_a_list(self, tmp_path):
        """CONTRACT CHANGED (R7): traits lands as a LIST, not the string it was.

        The template no longer renders {{TRAITS}}, so core.py writes the caller's
        value into identity.traits AFTER the render. A bare string becomes a
        one-element list rather than being stored as a string in a list field.
        """
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "traits_test"
        _spawn_agent(str(target), role="Analyst", traits="curious, terse", purpose="Reports")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == ["curious, terse"]

    def test_created_agent_passport_traits_accepts_a_real_list(self, tmp_path):
        """A caller who already has a list gets it stored as-is, not re-wrapped."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "traits_list_test"
        _spawn_agent(str(target), traits=["curious", "terse"], purpose="Reports")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == ["curious", "terse"]

    def test_created_agent_passport_traits_empty_without_flag(self, tmp_path):
        """Omitting traits leaves the template's empty LIST — the identity hook
        skips the line when falsy, and [] is falsy just as "" was."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "no_traits_test"
        _spawn_agent(str(target), purpose="Testing default")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == []

    def test_created_agent_passport_has_email(self, tmp_path):
        """Passport carries the branch address, so identity does not render 'Email: unknown'."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "email_test"
        _spawn_agent(str(target), purpose="Testing email")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["branch_info"]["email"] == "@email_test"


# =============================================================================
# MULTI-AGENT COEXISTENCE TESTS
# =============================================================================


class TestMultiAgentCoexistence:
    """Tests verifying multiple agents can coexist in the same registry."""

    def test_two_agents_same_registry(self, tmp_path):
        """Two agents created with the same registry both register."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        r1 = _spawn_agent(str(tmp_path / "agent_a"), registry_path=str(reg))
        r2 = _spawn_agent(str(tmp_path / "agent_b"), registry_path=str(reg))

        assert r1["success"] is True
        assert r2["success"] is True

        data = json.loads(reg.read_text())
        names = [b["name"] for b in data["branches"]]
        assert "AGENT_A" in names
        assert "AGENT_B" in names
        assert data["metadata"]["total_branches"] == 2

    def test_three_agents_distinct_identities(self, tmp_path):
        """Three agents in same registry have distinct passports."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        for name in ["alpha", "beta", "gamma"]:
            _spawn_agent(str(tmp_path / name), registry_path=str(reg), purpose=f"{name} purpose")

        # branch_name renders LOWERCASE in schema 2.0 (R1 casing), and the class
        # is derived from the citizen number (R3) rather than being one value for
        # everybody — alpha is the project's first citizen, so alpha manages it.
        expected_class = {"alpha": "manager", "beta": "specialist", "gamma": "specialist"}
        for name in ["alpha", "beta", "gamma"]:
            passport = json.loads((tmp_path / name / ".trinity" / "passport.json").read_text())
            assert passport["branch_info"]["branch_name"] == name
            assert passport["identity"]["citizen_class"] == expected_class[name]


def _fresh_registry(tmp_path):
    reg = tmp_path / "TEST_REGISTRY.json"
    reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}', encoding="utf-8")
    return reg


class TestPassportOwnerFieldIsGone:
    """CONTRACT DELETED (R8): citizenship.owner is not written at birth any more.

    This class used to pin ``passport["citizenship"]["owner"] is True`` for the
    first citizen and ``False`` for everyone after. The field is out of the 2.0
    schema entirely: a passport is SELF-DECLARED and ownership is not, so a copy
    of the answer sitting in the file the citizen itself can edit was a second,
    weaker source of truth for a fact the sealed registry already holds.

    The rewrite keeps the same coverage on the other side of the seam — the
    registry ENTRY's ``owner: true`` flag, which is a DIFFERENT field and stays.
    """

    def test_newborn_passport_has_no_owner_field(self, tmp_path):
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))

        passport = json.loads((tmp_path / "first" / ".trinity" / "passport.json").read_text())
        assert "owner" not in passport["citizenship"], passport["citizenship"]

    def test_no_citizen_ever_gets_an_owner_field(self, tmp_path):
        """Not the first, not the fifth — the field is gone for everybody."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        for name in ["alpha", "beta", "gamma", "delta", "epsilon"]:
            _spawn_agent(str(tmp_path / name), registry_path=str(reg))

        for name in ["alpha", "beta", "gamma", "delta", "epsilon"]:
            passport = json.loads((tmp_path / name / ".trinity" / "passport.json").read_text())
            assert "owner" not in passport["citizenship"], f"{name} was born with a self-declared owner flag"

    def test_the_registry_entry_still_seats_exactly_one_owner(self, tmp_path):
        """The authority that replaced it: one owner:true, on the first citizen."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "second"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "third"), registry_path=str(reg))

        entries = {b["name"]: b for b in json.loads(reg.read_text())["branches"]}
        assert entries["FIRST"].get("owner") is True
        assert entries["SECOND"].get("owner") is not True
        assert entries["THIRD"].get("owner") is not True


class TestRetroactiveOwner:
    """Tests for retroactive owner assignment on legacy projects.

    ``pick_owner_branch`` lost its middle step with R8 — it used to read the
    passport's ``citizenship.owner`` between "prefer a manager" and "oldest by
    created date". Both surviving steps are pinned here, plus the deleted one
    staying deleted.
    """

    def test_retroactive_owner_prefers_the_manager(self, tmp_path):
        """Step 1: alpha is the project's first citizen, so alpha is its manager."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "alpha"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "beta"), registry_path=str(reg))

        # Strip owner from the registry entries to simulate legacy state (no sealed owner)
        reg_data = json.loads(reg.read_text())
        for b in reg_data["branches"]:
            b.pop("owner", None)
        reg.write_text(json.dumps(reg_data, indent=2))

        _spawn_agent(str(tmp_path / "zeta"), registry_path=str(reg))

        entries = {b["name"]: b for b in json.loads(reg.read_text())["branches"]}
        assert entries["ALPHA"].get("owner") is True
        assert entries["BETA"].get("owner") is not True
        assert entries["ZETA"].get("owner") is not True

    def test_a_passport_can_no_longer_declare_itself_owner(self, tmp_path):
        """The DELETED step, pinned as deleted.

        beta plants ``citizenship.owner: true`` on itself and is NOT the manager.
        Under the old step 2 that flag won. It must not win now — otherwise any
        citizen could seat itself by editing its own file.
        """
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "alpha"), registry_path=str(reg))  # citizen #1 -> manager
        _spawn_agent(str(tmp_path / "beta"), registry_path=str(reg))  # citizen #2 -> specialist

        beta_passport = tmp_path / "beta" / ".trinity" / "passport.json"
        beta_data = json.loads(beta_passport.read_text())
        beta_data["citizenship"]["owner"] = True
        beta_passport.write_text(json.dumps(beta_data, indent=2))

        reg_data = json.loads(reg.read_text())
        for b in reg_data["branches"]:
            b.pop("owner", None)
        reg.write_text(json.dumps(reg_data, indent=2))

        assert ensure_project_has_owner(reg) is True

        entries = {b["name"]: b for b in json.loads(reg.read_text())["branches"]}
        assert entries["ALPHA"].get("owner") is True, "a self-declared passport flag beat the manager"
        assert entries["BETA"].get("owner") is not True

    def test_created_date_fallback_when_nobody_is_a_manager(self, tmp_path):
        """Step 2 (the last one): oldest ``created`` wins when no manager exists."""
        from aipass.spawn.apps.handlers.registry import pick_owner_branch

        for name in ("older", "newer"):
            trinity = tmp_path / name / ".trinity"
            trinity.mkdir(parents=True)
            (trinity / "passport.json").write_text(
                json.dumps({"identity": {"citizen_class": "specialist"}, "citizenship": {}}), encoding="utf-8"
            )

        branches = [
            {"name": "NEWER", "path": "newer", "created": "2026-03-01"},
            {"name": "OLDER", "path": "older", "created": "2026-01-01"},
        ]

        picked = pick_owner_branch(branches, tmp_path)
        assert picked is not None
        assert picked["name"] == "OLDER"

    def test_no_retroactive_change_when_an_owner_is_already_seated(self, tmp_path):
        """A registry that already seats an owner is left exactly as it is."""
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "second"), registry_path=str(reg))
        before = reg.read_text()

        assert ensure_project_has_owner(reg) is False
        assert reg.read_text() == before

    def test_ensure_project_has_owner_direct(self, tmp_path):
        """Direct call to ensure_project_has_owner sets owner in the registry entry."""
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = _fresh_registry(tmp_path)
        _spawn_agent(str(tmp_path / "agent_x"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "agent_y"), registry_path=str(reg))

        reg_data = json.loads(reg.read_text())
        for b in reg_data["branches"]:
            b.pop("owner", None)
        reg.write_text(json.dumps(reg_data, indent=2))

        assert ensure_project_has_owner(reg) is True

        entries = {b["name"]: b for b in json.loads(reg.read_text())["branches"]}
        assert entries["AGENT_X"].get("owner") is True
        assert entries["AGENT_Y"].get("owner") is not True


# =============================================================================
# BIRTH CERTIFICATE SCHEMA TESTS
# =============================================================================


class TestBirthCertificateSchema:
    """Every mint must be born on the current cert schema.

    The fleet's birth certificates carry ``metadata.template`` — the AIPass
    profile the citizen was registered under. They used to carry
    ``metadata.citizen_class`` instead, holding the value ``builder``, a class
    that was retired when the fleet migrated builder -> aipass_framework (see
    the legacy path in ``sync_registry_ops``). The two keys are different
    concepts, not a rename: the passport is the authoritative home for
    citizen_class, and a birth record repeating a retired class value preserves
    stale data forever.

    ``artifacts/birth_certificate.json`` is on the never-update list, so a
    template that mints the old shape cannot be corrected later by an update —
    every citizen born from it carries the old schema for life. That makes this
    a template-level canary rather than a data check.
    """

    @pytest.mark.parametrize("class_name", LIVE_CLASSES)
    def test_mint_carries_metadata_template(self, tmp_path, class_name):
        """A real create must render metadata.template with the detected profile."""
        from aipass.spawn.apps.handlers.metadata import detect_profile
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"cert_{class_name}"
        result = _spawn_agent(str(target), citizen_class=class_name)
        assert result["success"] is True, result

        cert = json.loads((target / "artifacts" / "birth_certificate.json").read_text(encoding="utf-8"))

        assert cert["metadata"]["template"] == detect_profile(target)
        assert "citizen_class" not in cert["metadata"], (
            f"{class_name} mints a retired citizen_class into the birth record: {cert['metadata']}"
        )

    @pytest.mark.parametrize("class_name", LIVE_CLASSES)
    def test_mint_description_matches_metadata(self, tmp_path, class_name):
        """The prose must name the same template the metadata records."""
        from aipass.spawn.apps.handlers.metadata import detect_profile
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / f"desc_{class_name}"
        result = _spawn_agent(str(target), citizen_class=class_name)
        assert result["success"] is True, result

        cert = json.loads((target / "artifacts" / "birth_certificate.json").read_text(encoding="utf-8"))

        assert f"registered using '{detect_profile(target)}' template" in cert["description"]
        assert "class." not in cert["description"], cert["description"]
