# =================== META ====================
# Name: test_citizen_classes.py
# Description: Integration tests for citizen class system
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-08-07
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


class TestClassRegistry:
    """Tests for apps/handlers/class_registry.py"""

    def test_get_available_classes(self):
        """Returns list containing 'aipass_framework'."""
        from aipass.spawn.apps.handlers.class_registry import get_available_classes

        classes = get_available_classes()
        assert "aipass_framework" in classes

    def test_validate_class_valid(self):
        """Known class names validate as True."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("aipass_framework") is True

    def test_validate_class_invalid(self):
        """Unknown or empty class names validate as False."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("nonexistent") is False
        assert validate_class("") is False

    def test_validate_class_retired_birthright(self):
        """Retired 'birthright' class should validate as False."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("birthright") is False

    def test_get_default_class(self):
        """Default citizen class is 'aipass_framework'."""
        from aipass.spawn.apps.handlers.class_registry import get_default_class

        assert get_default_class() == "aipass_framework"

    def test_get_template_dir_aipass_framework(self):
        """aipass_framework template directory exists and is named 'aipass_framework'."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        path = get_template_dir("aipass_framework")
        assert path.name == "aipass_framework"
        assert path.exists()

    def test_get_template_dir_invalid_raises(self):
        """Requesting an unknown class raises ValueError."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        with pytest.raises(ValueError, match="Unknown citizen class"):
            get_template_dir("nonexistent")

    def test_manager_not_template_selectable(self):
        """'manager' is a real identity class but never a template-selectable class (validate_class)."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("manager") is False

    def test_resolve_template_class_passthrough_for_registered_classes(self):
        """Non-manager registered classes resolve to themselves."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        assert resolve_template_class({"citizen_class": "aipass_framework"}) == "aipass_framework"
        assert resolve_template_class({"citizen_class": "project_agent", "role": "anything"}) == "project_agent"

    def test_resolve_template_class_manager_role_project_agent(self):
        """manager + role=project_agent resolves the project_agent template."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        assert resolve_template_class({"citizen_class": "manager", "role": "project_agent"}) == "project_agent"

    def test_resolve_template_class_manager_other_role_defaults_aipass_framework(self):
        """manager + any non-project_agent role (devpulse: orchestration_hub) resolves aipass_framework."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        assert resolve_template_class({"citizen_class": "manager", "role": "orchestration_hub"}) == "aipass_framework"
        assert resolve_template_class({"citizen_class": "manager"}) == "aipass_framework"

    def test_resolve_template_class_unknown_raises(self):
        """An unregistered citizen_class raises ValueError naming registered classes."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        with pytest.raises(ValueError, match="Unknown citizen_class"):
            resolve_template_class({"citizen_class": "nonexistent"})


class TestCustomConfigReadmeGuide:
    """The custom_config/ README ships the operator-override house pattern (FPLAN-0380)."""

    def _readme(self):
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        return get_template_dir("aipass_framework") / "{{BRANCH}}_json" / "custom_config" / "README.md"

    def test_readme_carries_override_pattern(self):
        """Guide states the four load-bearing rules and names its source of truth."""
        text = self._readme().read_text(encoding="utf-8").lower()

        assert "defaults" in text
        assert "only overrides" in text
        assert "deep-merged" in text
        assert "never write defaults to disk" in text
        assert "json_structure" in text

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

    def test_create_aipass_framework_explicit(self, tmp_path):
        """drone @spawn create aipass_framework @path creates full scaffold."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "framework_agent"
        result = _spawn_agent(str(target), citizen_class="aipass_framework")

        assert result["success"] is True
        assert (target / "apps").exists()
        assert (target / "apps" / "modules").exists()
        assert (target / "apps" / "handlers").exists()

    def test_create_default_is_aipass_framework(self, tmp_path):
        """drone @spawn create @path defaults to aipass_framework."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "default_agent"
        result = _spawn_agent(str(target))

        assert result["success"] is True
        assert (target / "apps").exists()

    def test_create_with_citizen_class_in_passport(self, tmp_path):
        """Created agents should have citizen_class in passport."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "class_test"
        _spawn_agent(str(target), citizen_class="aipass_framework")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "aipass_framework"

    def test_create_aipass_framework_includes_integrations_scaffold(self, tmp_path):
        """aipass_framework creation includes apps/integrations/README.md (DPLAN-0133)."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "integrations_test"
        result = _spawn_agent(str(target), citizen_class="aipass_framework")

        assert result["success"] is True
        assert (target / "apps" / "integrations").is_dir()
        assert (target / "apps" / "integrations" / "README.md").exists()


# =============================================================================
# CLASS-AWARE UPDATE TESTS
# =============================================================================


class TestClassAwareUpdate:
    """Tests for class-aware update behavior."""

    def test_read_citizen_class_aipass_framework(self, tmp_path):
        """aipass_framework branches return 'aipass_framework' class."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "aipass_framework", "role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "aipass_framework"

    def test_read_citizen_class_missing_passport_raises(self, tmp_path):
        """Missing passport is a loud hard error, not a silent 'aipass_framework' default (DPLAN-0262)."""
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

    def test_read_citizen_class_manager_devpulse_shape_resolves_aipass_framework(self, tmp_path):
        """manager + non-project_agent role (e.g. devpulse's orchestration_hub) resolves aipass_framework."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "manager", "role": "orchestration_hub"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "aipass_framework"

    def test_read_citizen_class_manager_project_agent_shape_resolves_project_agent(self, tmp_path):
        """manager + role='project_agent' resolves the project_agent template."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "manager", "role": "project_agent"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "project_agent"

    def test_update_all_requires_class_via_cli(self):
        """update --all without class should return error code."""
        from aipass.spawn.apps.modules.update import handle_update

        result = handle_update(["--all"])
        assert result == 1

    def test_update_cli_accepts_class_with_all(self):
        """update aipass_framework --all should parse correctly and call update_all with class filter."""
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
            result = handle_update(["aipass_framework", "--all", "--dry-run"])

        assert result == 0
        mock_ua.assert_called_once_with(dry_run=True, trace=False, citizen_class="aipass_framework")


# =============================================================================
# TEMPLATE STRUCTURE TESTS
# =============================================================================


class TestTemplateStructure:
    """Tests verifying template directory structure."""

    def test_aipass_framework_template_exists(self):
        """aipass_framework template directory has .trinity/passport.json and apps/."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        tpl = get_template_dir("aipass_framework")
        assert tpl.is_dir()
        assert (tpl / ".trinity" / "passport.json").exists()
        assert (tpl / "apps").is_dir()

    def test_aipass_framework_passport_has_class_placeholder(self):
        """aipass_framework template passport has citizen_class placeholder for rendering."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        tpl = get_template_dir("aipass_framework")
        passport = json.loads((tpl / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "{{CITIZEN_CLASS}}"

    @pytest.mark.parametrize("class_name", ["aipass_framework", "project_agent"])
    def test_template_passport_has_traits_and_email_placeholders(self, class_name):
        """Agent template passports reference TRAITS and EMAIL — unreferenced, both are built and discarded."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        tpl = get_template_dir(class_name)
        passport = json.loads((tpl / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == "{{TRAITS}}"
        assert passport["branch_info"]["email"] == "{{EMAIL}}"

    def test_no_agent_template_dir(self):
        """Old agent.template directory should not exist."""
        spawn_root = Path(__file__).parents[1]
        assert not (spawn_root / "templates" / "agent.template").exists()

    def test_aipass_framework_template_has_no_claude_md(self):
        """aipass_framework template should NOT include CLAUDE.md — project root covers it."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        tpl = get_template_dir("aipass_framework")
        assert not (tpl / "CLAUDE.md").exists()

    def test_aipass_framework_template_has_local_prompt(self):
        """aipass_framework template includes non-empty local prompt."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        tpl = get_template_dir("aipass_framework")
        prompt = tpl / ".aipass" / "aipass_local_prompt.md"
        assert prompt.exists()
        content = prompt.read_text()
        assert len(content) > 100, "Local prompt should have substantial content"
        assert "{{BRANCHNAME}}" in content


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

    def test_created_agent_passport_has_traits(self, tmp_path):
        """Passport should include the agent's traits if provided."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "traits_test"
        _spawn_agent(str(target), role="Analyst", traits="curious, terse", purpose="Reports")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == "curious, terse"

    def test_created_agent_passport_traits_empty_without_flag(self, tmp_path):
        """Omitting traits leaves an empty string — the identity hook skips the line when falsy."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "no_traits_test"
        _spawn_agent(str(target), purpose="Testing default")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["traits"] == ""

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

        for name in ["alpha", "beta", "gamma"]:
            passport = json.loads((tmp_path / name / ".trinity" / "passport.json").read_text())
            assert passport["branch_info"]["branch_name"] == name.upper()
            assert passport["identity"]["citizen_class"] == "aipass_framework"


class TestPassportOwnerField:
    """Tests verifying the owner field in passport.json."""

    def test_first_agent_is_owner(self, tmp_path):
        """First agent created in a project gets owner: true."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))

        passport = json.loads((tmp_path / "first" / ".trinity" / "passport.json").read_text())
        assert passport["citizenship"]["owner"] is True

    def test_second_agent_not_owner(self, tmp_path):
        """Second agent created in a project gets owner: false."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "second"), registry_path=str(reg))

        p1 = json.loads((tmp_path / "first" / ".trinity" / "passport.json").read_text())
        p2 = json.loads((tmp_path / "second" / ".trinity" / "passport.json").read_text())
        assert p1["citizenship"]["owner"] is True
        assert p2["citizenship"]["owner"] is False

    def test_third_agent_not_owner(self, tmp_path):
        """Third agent also gets owner: false."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        for name in ["alpha", "beta", "gamma"]:
            _spawn_agent(str(tmp_path / name), registry_path=str(reg))

        passports = {}
        for name in ["alpha", "beta", "gamma"]:
            passports[name] = json.loads((tmp_path / name / ".trinity" / "passport.json").read_text())

        assert passports["alpha"]["citizenship"]["owner"] is True
        assert passports["beta"]["citizenship"]["owner"] is False
        assert passports["gamma"]["citizenship"]["owner"] is False


class TestRetroactiveOwner:
    """Tests for retroactive owner assignment on legacy projects."""

    def test_retroactive_owner_on_legacy_agents(self, tmp_path):
        """ensure_project_has_owner picks manager passport, falls back to passport owner flag."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        _spawn_agent(str(tmp_path / "alpha"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "beta"), registry_path=str(reg))

        # Strip owner from registry entries to simulate legacy state (no sealed owner)
        # Keep alpha's passport owner=True as the fallback signal
        reg_data = json.loads(reg.read_text())
        for b in reg_data["branches"]:
            b.pop("owner", None)
        reg.write_text(json.dumps(reg_data, indent=2))

        _spawn_agent(str(tmp_path / "zeta"), registry_path=str(reg))

        # Owner now lives in the registry entry — alpha picked via passport fallback
        reg_data = json.loads(reg.read_text())
        entries = {b["name"]: b for b in reg_data["branches"]}
        assert entries["ALPHA"].get("owner") is True
        assert entries["BETA"].get("owner") is not True
        assert entries["ZETA"].get("owner") is not True

    def test_no_retroactive_if_owner_exists(self, tmp_path):
        """If an existing agent already has owner:true, no retroactive change."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        _spawn_agent(str(tmp_path / "first"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "second"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "third"), registry_path=str(reg))

        p1 = json.loads((tmp_path / "first" / ".trinity" / "passport.json").read_text())
        p2 = json.loads((tmp_path / "second" / ".trinity" / "passport.json").read_text())
        p3 = json.loads((tmp_path / "third" / ".trinity" / "passport.json").read_text())
        assert p1["citizenship"]["owner"] is True
        assert p2["citizenship"]["owner"] is False
        assert p3["citizenship"]["owner"] is False

    def test_ensure_project_has_owner_direct(self, tmp_path):
        """Direct call to ensure_project_has_owner sets owner in registry entry."""
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner
        from aipass.spawn.apps.modules.core import _spawn_agent

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        _spawn_agent(str(tmp_path / "agent_x"), registry_path=str(reg))
        _spawn_agent(str(tmp_path / "agent_y"), registry_path=str(reg))

        # Strip owner from passports AND registry entries
        for name in ["agent_x", "agent_y"]:
            pp = tmp_path / name / ".trinity" / "passport.json"
            data = json.loads(pp.read_text())
            data["citizenship"].pop("owner", None)
            pp.write_text(json.dumps(data, indent=2))
        reg_data = json.loads(reg.read_text())
        for b in reg_data["branches"]:
            b.pop("owner", None)
        reg.write_text(json.dumps(reg_data, indent=2))

        # Re-add passport owner on agent_x to simulate fallback signal
        px_pp = tmp_path / "agent_x" / ".trinity" / "passport.json"
        px_data = json.loads(px_pp.read_text())
        px_data["citizenship"]["owner"] = True
        px_pp.write_text(json.dumps(px_data, indent=2))

        result = ensure_project_has_owner(reg)
        assert result is True

        # Owner is now in the registry entry
        reg_data = json.loads(reg.read_text())
        entries = {b["name"]: b for b in reg_data["branches"]}
        assert entries["AGENT_X"].get("owner") is True
        assert entries["AGENT_Y"].get("owner") is not True
