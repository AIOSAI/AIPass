# ===================AIPASS====================
# META DATA HEADER
# Name: test_lifecycle.py - Integration test for full skill lifecycle
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Integration tests for the full skill lifecycle: create -> discover -> load -> run."""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

skills_root = Path(__file__).resolve().parent.parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))

from skills.apps.handlers.template import copy_template, get_template
from skills.apps.modules.creator import create_skill
from skills.apps.modules.discovery import discover_skills_in_path, parse_frontmatter
from skills.apps.handlers.loader_handler import import_handler, parse_full_skill_md
from skills.apps.modules.runner import run_skill


class TestFullLifecycle:
    """Test the complete create -> discover -> load -> run cycle."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_create_discover_load_markdown_skill(self):
        """Tier 1: Create a markdown skill, discover it, load it, run it."""
        # Create
        result = create_skill("test-md", template_type="markdown_only", target_dir=self.tmpdir)
        assert result["success"] is True
        skill_path = Path(result["path"])
        assert (skill_path / "SKILL.md").exists()

        # Verify placeholder replacement
        content = (skill_path / "SKILL.md").read_text()
        assert "test-md" in content
        assert "{{SKILL_NAME}}" not in content

        # Discover
        skills = discover_skills_in_path(self.tmpdir, "test")
        assert len(skills) == 1
        assert skills[0]["name"] == "test-md"
        assert skills[0]["has_handler"] is False

        # Load (parse full SKILL.md)
        result = parse_full_skill_md(skill_path / "SKILL.md")
        metadata, body = result[0], result[1]
        assert metadata is not None
        assert isinstance(metadata, dict)
        assert metadata["name"] == "test-md"
        assert body is not None

    def test_create_discover_load_handler_skill(self):
        """Tier 2: Create a handler skill, discover it, load handler."""
        # Create
        result = create_skill("test-handler", template_type="with_handler", target_dir=self.tmpdir)
        assert result["success"] is True
        skill_path = Path(result["path"])
        assert (skill_path / "SKILL.md").exists()
        assert (skill_path / "handler.py").exists()

        # Discover
        skills = discover_skills_in_path(self.tmpdir, "test")
        handler_skill = [s for s in skills if s["name"] == "test-handler"]
        assert len(handler_skill) == 1

        # Load handler
        handler = import_handler(skill_path, "test-handler")
        assert handler is not None
        assert hasattr(handler, "run")
        assert hasattr(handler, "get_actions")

        # Execute handler
        actions = handler.get_actions()
        assert isinstance(actions, list)
        assert len(actions) > 0

        # Run an action
        result = handler.run(actions[0], args={}, config={})
        assert isinstance(result, dict)
        assert "success" in result

    def test_create_full_structure(self):
        """Tier 3: Create a full 3-layer skill and verify structure."""
        result = create_skill("test-full", template_type="full", target_dir=self.tmpdir)
        assert result["success"] is True
        skill_path = Path(result["path"])
        assert (skill_path / "SKILL.md").exists()
        assert (skill_path / "apps").is_dir()
        assert (skill_path / "apps" / "modules").is_dir()
        assert (skill_path / "apps" / "handlers").is_dir()


class TestCatalogSkillsLifecycle:
    """Test that built-in catalog skills work through the full lifecycle."""

    def test_github_skill_full_cycle(self):
        """GitHub (Tier 1): discover -> load -> run returns instructions."""
        catalog = Path(__file__).resolve().parent.parent / "catalog"
        skills = discover_skills_in_path(catalog, "builtin")
        github = [s for s in skills if s["name"] == "github"]
        assert len(github) == 1
        assert github[0]["has_handler"] is False

        # Parse full SKILL.md
        result = parse_full_skill_md(github[0]["path"] / "SKILL.md")
        metadata, body = result[0], result[1]
        assert metadata is not None
        assert isinstance(metadata, dict)
        assert metadata["name"] == "github"
        assert body is not None
        assert "gh" in body.lower()

    def test_system_status_full_cycle(self):
        """System status (Tier 2): discover -> load -> run handler."""
        result = run_skill("system_status", action="disk")
        assert result["success"] is True
        assert "Disk Usage" in result["output"]

    def test_drone_commands_full_cycle(self):
        """Drone commands (Tier 3): discover -> load -> run handler."""
        result = run_skill("drone_commands")
        assert result["success"] is True
        assert "Available actions" in result["output"]


class TestTemplates:
    """Test template resolution and copying."""

    def test_get_markdown_template(self):
        result = get_template("markdown_only")
        assert result["success"] is True
        assert result["path"].exists()

    def test_get_handler_template(self):
        result = get_template("with_handler")
        assert result["success"] is True
        assert result["path"].exists()

    def test_get_full_template(self):
        result = get_template("full")
        assert result["success"] is True
        assert result["path"].exists()

    def test_invalid_template_type(self):
        result = get_template("nonexistent")
        assert result["success"] is False
        assert result["error"] is not None

    def test_copy_template_replaces_placeholders(self):
        tmpdir = tempfile.mkdtemp()
        try:
            template = get_template("markdown_only")
            target = Path(tmpdir) / "my-skill"
            result = copy_template(template["path"], target, "my-skill")
            assert result["success"] is True
            content = (target / "SKILL.md").read_text()
            assert "my-skill" in content
            assert "{{SKILL_NAME}}" not in content
        finally:
            shutil.rmtree(tmpdir)

    def test_copy_template_rejects_existing_target(self):
        tmpdir = tempfile.mkdtemp()
        try:
            template = get_template("markdown_only")
            target = Path(tmpdir) / "exists"
            target.mkdir()
            result = copy_template(template["path"], target, "exists")
            assert result["success"] is False
            assert "already exists" in result["error"]
        finally:
            shutil.rmtree(tmpdir)

    def test_copy_template_excludes_pycache(self):
        """copy_template must not include __pycache__ directories in output."""
        tmpdir = tempfile.mkdtemp()
        try:
            template = get_template("full")
            assert template["success"] is True
            # Create a __pycache__ dir inside the template to ensure it gets filtered
            pycache = template["path"] / "__pycache__"
            pycache_existed = pycache.exists()
            if not pycache_existed:
                pycache.mkdir()
                (pycache / "dummy.pyc").write_bytes(b"\x00")
            try:
                target = Path(tmpdir) / "cache-test"
                result = copy_template(template["path"], target, "cache-test")
                assert result["success"] is True
                assert not (target / "__pycache__").exists()
                for f in result["created_files"]:
                    assert "__pycache__" not in f
            finally:
                if not pycache_existed:
                    shutil.rmtree(str(pycache))
        finally:
            shutil.rmtree(tmpdir)
