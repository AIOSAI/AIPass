# ===================AIPASS====================
# META DATA HEADER
# Name: test_loader.py - Unit tests for skills loader
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills loader module."""

from aipass.skills.apps.modules.loader import load_skill


class TestLoadSkill:
    def test_load_github_markdown_only(self):
        result = load_skill("github")
        assert result["success"] is True
        assert result["metadata"]["name"] == "github"
        assert result["handler"] is None
        assert result["body"] is not None
        assert len(result["body"]) > 0

    def test_load_system_status_with_handler(self):
        result = load_skill("system_status")
        assert result["success"] is True
        assert result["metadata"]["name"] == "system_status"
        assert result["handler"] is not None
        assert hasattr(result["handler"], "run")
        assert hasattr(result["handler"], "get_actions")

    def test_load_drone_commands_full(self):
        result = load_skill("drone_commands")
        assert result["success"] is True
        assert result["handler"] is not None
        assert hasattr(result["handler"], "run")

    def test_load_nonexistent(self):
        result = load_skill("nonexistent_skill_xyz")
        assert result["success"] is False
        assert result["error"] is not None
        assert "not found" in result["error"].lower()
        assert result["metadata"] is None
        assert result["handler"] is None

    def test_metadata_has_expected_keys(self):
        result = load_skill("github")
        metadata = result["metadata"]
        assert "name" in metadata
        assert "description" in metadata
        # Verify actual values, not just key existence
        assert metadata["name"] == "github"
        assert isinstance(metadata["description"], str)
        assert len(metadata["description"]) > 0

    def test_body_is_markdown_content(self):
        result = load_skill("github")
        body = result["body"]
        # The old `or` was two facts about the same body, so either half
        # carried it. The real contract is the split: the body is what sits
        # BELOW the frontmatter, so the H1 opens it and no frontmatter key
        # survives into it.
        assert body.startswith("# GitHub Skill")
        assert "## When to Use" in body
        assert "name: github" not in body
        assert result["metadata"]["description"] not in body

    def test_handler_contract(self):
        """Verify handler follows the run(action, args, config) contract."""
        result = load_skill("system_status")
        handler = result["handler"]
        # Must have run() and get_actions()
        assert callable(handler.run)
        assert callable(handler.get_actions)
        # get_actions returns a list
        actions = handler.get_actions()
        assert isinstance(actions, list)
        assert len(actions) > 0
