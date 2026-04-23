# =================== META ====================
# Name: test_citizen_classes.py
# Description: Integration tests for citizen class system
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Integration tests for the citizen class template system.

Tests class registry, passport command, class-aware create,
class-aware update, and backward compatibility.
"""

import json
import unittest.mock

import pytest
from pathlib import Path


# =============================================================================
# CLASS REGISTRY TESTS
# =============================================================================


class TestClassRegistry:
    """Tests for apps/handlers/class_registry.py"""

    def test_get_available_classes(self):
        """Returns list containing 'builder' and 'birthright'."""
        from aipass.spawn.apps.handlers.class_registry import get_available_classes

        classes = get_available_classes()
        assert "builder" in classes
        assert "birthright" in classes

    def test_validate_class_valid(self):
        """Known class names validate as True."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("builder") is True
        assert validate_class("birthright") is True

    def test_validate_class_invalid(self):
        """Unknown or empty class names validate as False."""
        from aipass.spawn.apps.handlers.class_registry import validate_class

        assert validate_class("nonexistent") is False
        assert validate_class("") is False

    def test_get_default_class(self):
        """Default citizen class is 'builder'."""
        from aipass.spawn.apps.handlers.class_registry import get_default_class

        assert get_default_class() == "builder"

    def test_get_template_dir_builder(self):
        """Builder template directory exists and is named 'builder'."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        path = get_template_dir("builder")
        assert path.name == "builder"
        assert path.exists()

    def test_get_template_dir_birthright(self):
        """Birthright template directory exists and is named 'birthright'."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        path = get_template_dir("birthright")
        assert path.name == "birthright"
        assert path.exists()

    def test_get_template_dir_invalid_raises(self):
        """Requesting an unknown class raises ValueError."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        with pytest.raises(ValueError, match="Unknown citizen class"):
            get_template_dir("nonexistent")


# =============================================================================
# PASSPORT COMMAND TESTS
# =============================================================================


class TestPassportCommand:
    """Tests for passport granting (birthright citizenship)."""

    def test_grant_passport_creates_trinity(self, tmp_path):
        """Passport grant creates .trinity/ with all identity files."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "test_citizen"
        result = grant_passport(str(target), role="tester", purpose="Testing")

        assert result["success"] is True
        assert result["citizen_class"] == "birthright"
        assert (target / ".trinity" / "passport.json").exists()
        assert (target / ".trinity" / "local.json").exists()
        assert (target / ".trinity" / "observations.json").exists()

    def test_grant_passport_creates_aipass(self, tmp_path):
        """Passport grant creates .aipass/ with local prompt."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "test_citizen"
        result = grant_passport(str(target), role="tester")

        assert result["success"] is True
        assert (target / ".aipass" / "aipass_local_prompt.md").exists()

    def test_grant_passport_creates_readme(self, tmp_path):
        """Passport grant creates README.md in target directory."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "test_citizen"
        result = grant_passport(str(target))

        assert result["success"] is True
        assert (target / "README.md").exists()

    def test_grant_passport_no_apps_dir(self, tmp_path):
        """Birthright should NOT create apps/ scaffold."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "test_citizen"
        grant_passport(str(target))

        assert not (target / "apps").exists()

    def test_grant_passport_passport_content(self, tmp_path):
        """Verify passport has correct citizen_class and role."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "my_branch"
        grant_passport(str(target), role="analyst", purpose="Data analysis")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "birthright"
        assert passport["identity"]["role"] == "analyst"
        assert "MY_BRANCH" in passport["document_metadata"]["document_name"]

    def test_grant_passport_already_citizen(self, tmp_path):
        """Cannot grant passport if .trinity/ already exists."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "existing"
        (target / ".trinity").mkdir(parents=True)

        result = grant_passport(str(target))
        assert result["success"] is False
        assert "Already a citizen" in result["error"]

    def test_grant_passport_creates_directory(self, tmp_path):
        """If target directory doesn't exist, create it."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        target = tmp_path / "brand_new"
        assert not target.exists()

        result = grant_passport(str(target))
        assert result["success"] is True
        assert target.exists()


# =============================================================================
# CLASS-AWARE CREATE TESTS
# =============================================================================


class TestClassAwareCreate:
    """Tests for class-aware agent creation."""

    def test_create_builder_explicit(self, tmp_path):
        """drone @spawn create builder @path creates full scaffold."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "builder_agent"
        result = _spawn_agent(str(target), citizen_class="builder")

        assert result["success"] is True
        assert (target / "apps").exists()
        assert (target / "apps" / "modules").exists()
        assert (target / "apps" / "handlers").exists()

    def test_create_default_is_builder(self, tmp_path):
        """drone @spawn create @path defaults to builder."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "default_agent"
        result = _spawn_agent(str(target))

        assert result["success"] is True
        assert (target / "apps").exists()

    def test_create_with_citizen_class_in_passport(self, tmp_path):
        """Created agents should have citizen_class in passport."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "class_test"
        _spawn_agent(str(target), citizen_class="builder")

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "builder"

    def test_create_builder_includes_integrations_scaffold(self, tmp_path):
        """Builder creation includes apps/integrations/README.md (DPLAN-0133)."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "integrations_test"
        result = _spawn_agent(str(target), citizen_class="builder")

        assert result["success"] is True
        assert (target / "apps" / "integrations").is_dir()
        assert (target / "apps" / "integrations" / "README.md").exists()


# =============================================================================
# CLASS-AWARE UPDATE TESTS
# =============================================================================


class TestClassAwareUpdate:
    """Tests for class-aware update behavior."""

    def test_read_citizen_class_builder(self, tmp_path):
        """Builder branches return 'builder' class."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "builder", "role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "builder"

    def test_read_citizen_class_birthright(self, tmp_path):
        """Birthright branches return 'birthright' class."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"citizen_class": "birthright", "role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "birthright"

    def test_read_citizen_class_missing_passport(self, tmp_path):
        """Missing passport defaults to 'builder'."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        assert _read_citizen_class(tmp_path) == "builder"

    def test_read_citizen_class_no_field(self, tmp_path):
        """Passport without citizen_class field defaults to 'builder'."""
        from aipass.spawn.apps.handlers.update_ops import _read_citizen_class

        passport_dir = tmp_path / ".trinity"
        passport_dir.mkdir()
        passport = {"identity": {"role": "test"}}
        (passport_dir / "passport.json").write_text(json.dumps(passport))

        assert _read_citizen_class(tmp_path) == "builder"

    def test_update_all_requires_class_via_cli(self):
        """update --all without class should return error code."""
        from aipass.spawn.apps.modules.update import handle_update

        result = handle_update(["--all"])
        assert result == 1

    def test_update_cli_accepts_class_with_all(self):
        """update builder --all should parse correctly and call update_all with class filter."""
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
            result = handle_update(["builder", "--all", "--dry-run"])

        assert result == 0
        mock_ua.assert_called_once_with(dry_run=True, trace=False, citizen_class="builder")


# =============================================================================
# TEMPLATE STRUCTURE TESTS
# =============================================================================


class TestTemplateStructure:
    """Tests verifying template directory structure."""

    def test_builder_template_exists(self):
        """Builder template directory has .trinity/passport.json and apps/."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        builder = get_template_dir("builder")
        assert builder.is_dir()
        assert (builder / ".trinity" / "passport.json").exists()
        assert (builder / "apps").is_dir()

    def test_birthright_template_exists(self):
        """Birthright template has .trinity/passport.json but no apps/."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        birthright = get_template_dir("birthright")
        assert birthright.is_dir()
        assert (birthright / ".trinity" / "passport.json").exists()
        assert not (birthright / "apps").exists()

    def test_builder_passport_has_class(self):
        """Builder template passport declares citizen_class='builder'."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        builder = get_template_dir("builder")
        passport = json.loads((builder / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "builder"

    def test_birthright_passport_has_class(self):
        """Birthright template passport declares citizen_class='birthright'."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        birthright = get_template_dir("birthright")
        passport = json.loads((birthright / ".trinity" / "passport.json").read_text())
        assert passport["identity"]["citizen_class"] == "birthright"

    def test_no_agent_template_dir(self):
        """Old agent.template directory should not exist."""
        spawn_root = Path(__file__).parents[1]
        assert not (spawn_root / "templates" / "agent.template").exists()

    def test_builder_template_has_no_claude_md(self):
        """Builder template should NOT include CLAUDE.md — project root covers it."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        builder = get_template_dir("builder")
        assert not (builder / "CLAUDE.md").exists()

    def test_builder_template_has_local_prompt(self):
        """Builder template includes non-empty local prompt."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        builder = get_template_dir("builder")
        prompt = builder / ".aipass" / "aipass_local_prompt.md"
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
            assert passport["identity"]["citizen_class"] == "builder"


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

    def test_birthright_first_agent_is_owner(self, tmp_path):
        """First birthright agent gets owner: true."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        target = tmp_path / "citizen"
        target.mkdir()
        with unittest.mock.patch("aipass.spawn.apps.handlers.passport_ops.find_registry", return_value=reg):
            grant_passport(str(target))

        passport = json.loads((target / ".trinity" / "passport.json").read_text())
        assert passport["citizenship"]["owner"] is True

    def test_birthright_second_agent_not_owner(self, tmp_path):
        """Second birthright agent gets owner: false."""
        from aipass.spawn.apps.handlers.passport_ops import grant_passport

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}')

        first = tmp_path / "first"
        first.mkdir()
        second = tmp_path / "second"
        second.mkdir()

        with unittest.mock.patch("aipass.spawn.apps.handlers.passport_ops.find_registry", return_value=reg):
            grant_passport(str(first))
            grant_passport(str(second))

        p1 = json.loads((first / ".trinity" / "passport.json").read_text())
        p2 = json.loads((second / ".trinity" / "passport.json").read_text())
        assert p1["citizenship"]["owner"] is True
        assert p2["citizenship"]["owner"] is False
