# =================== AIPass ====================
# Name: test_loader.py
# Description: Unit tests for skills loader
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-09-27
# Category: skills/tests
# =============================================

"""Tests for apps/modules/loader.py and the skill loading it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that loader.py and loader_handler.py parse and import
# seedgo: no-test-needed(constant) — the "skill_loaded" log-operation name json_handler records

import sys

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


class TestBrokenHandler:
    def test_a_handler_that_raises_on_import_fails_the_load_and_names_the_error(self, tmp_path, monkeypatch):
        """Pins the shipped defect: an import-time crash loaded as success with handler None."""
        skill_dir = tmp_path / ".aipass" / "skills" / "broken_handler_probe"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: broken_handler_probe\ndescription: probe\nhas_handler: true\n---\n\n# Probe\n",
            encoding="utf-8",
        )
        (skill_dir / "handler.py").write_text('raise RuntimeError("probe import crash")\n', encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = load_skill("broken_handler_probe")

        assert result["success"] is False
        assert result["handler"] is None
        assert "RuntimeError: probe import crash" in result["error"]
        assert "handler.py" in result["error"]
        assert "skills_handler_broken_handler_probe" not in sys.modules
