# =================== AIPass ====================
# Name: test_discovery.py
# Description: Unit tests for skills discovery
# Version: 1.1.2
# Created: 2026-03-07
# Modified: 2026-11-22
# Category: skills/tests
# =============================================

"""Tests for apps/modules/discovery.py, apps/handlers/discovery_handler.py and the skill discovery they power."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that discovery_handler.py parses and imports
# sentry: no-test-needed(constant) — the "discovery_scan" log-operation name json_handler records

import pytest
import tempfile
from pathlib import Path

from aipass.skills.apps.modules import discovery
from aipass.skills.apps.handlers.discovery_handler import (
    discover_skills_in_path,
    get_search_paths,
    parse_frontmatter,
)


class TestTheListCommand:
    """`list` takes no arguments, so a bare call lists and only a help flag shows the module map."""

    def test_a_bare_list_prints_the_skills_not_the_module_map(self, capsys):
        assert discovery.handle_command("list", []) is True
        out = capsys.readouterr().out
        assert "skill(s):" in out
        assert "discovery Module" not in out

    def test_list_help_prints_the_usage_then_the_module_map(self, capsys):
        assert discovery.handle_command("list", ["--help"]) is True
        out = capsys.readouterr().out
        assert "skills List - Show every discovered skill" in out
        assert "discovery Module" in out


class TestGetSearchPaths:
    def test_returns_three_paths(self):
        paths = get_search_paths()
        assert len(paths) == 3

    def test_path_order(self):
        paths = get_search_paths()
        labels = [label for _, label in paths]
        assert labels == ["project", "global", "builtin"]

    def test_builtin_path_exists(self):
        paths = get_search_paths()
        builtin_path = paths[2][0]
        assert builtin_path.exists()


class TestExtractFrontmatter:
    """Frontmatter extraction through parse_frontmatter(), on the real yaml.safe_load path."""

    def test_valid_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\ndescription: A test skill\n---\n\n# Body", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is not None
        assert result["name"] == "test"
        assert result["description"] == "A test skill"

    def test_no_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# Just a markdown file\nNo frontmatter here.", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is None

    def test_unclosed_frontmatter(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\nno closing delimiter", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is None

    def test_empty_content(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is None

    def test_boolean_values(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\nhas_handler: true\n---\n", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is not None
        assert result["has_handler"] is True

    def test_list_values(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\ntags: [dev, git, ci]\n---\n", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is not None
        assert result["tags"] == ["dev", "git", "ci"]


class TestMalformedFrontmatterIsRefused:
    """A frontmatter block that is not a YAML mapping refuses loudly, naming the file."""

    def test_a_yaml_error_names_the_file(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: [unclosed\n---\n", encoding="utf-8")
        with pytest.raises(ValueError, match=f"Malformed YAML frontmatter in {skill_md}"):
            parse_frontmatter(skill_md)

    def test_a_non_mapping_names_the_file(self, tmp_path):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\n- just\n- a list\n---\n", encoding="utf-8")
        with pytest.raises(ValueError, match=f"Frontmatter in {skill_md} is a list"):
            parse_frontmatter(skill_md)

    def test_an_undecodable_file_names_the_file(self, tmp_path):
        """An unreadable SKILL.md refuses like a malformed one, so it never drops out of discovery unseen."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_bytes(b"---\nname: \xff\xfe\n---\n")
        with pytest.raises(ValueError, match=f"Unreadable SKILL.md at {skill_md}"):
            parse_frontmatter(skill_md)


class TestDiscoverSkillsInPath:
    def test_finds_catalog_skills(self):
        catalog_path = Path(__file__).resolve().parent.parent / "lib"
        skills = discover_skills_in_path(catalog_path, "builtin")
        names = {s["name"] for s in skills}
        assert "github" in names
        assert "system_status" in names
        assert "drone_commands" in names

    def test_nonexistent_path(self, tmp_path):
        skills = discover_skills_in_path(str(tmp_path / "nonexistent" / "path"), "test")
        assert skills == []

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills = discover_skills_in_path(tmpdir, "test")
            assert skills == []

    def test_skill_dict_structure(self):
        catalog_path = Path(__file__).resolve().parent.parent / "lib"
        skills = discover_skills_in_path(catalog_path, "builtin")
        # The floor: without it an empty lib/ makes the loop below a silent pass.
        assert len(skills) == 6, f"lib/ discovery returned {len(skills)} skills, expected 6"
        for skill in skills:
            assert "name" in skill
            assert "description" in skill
            assert "path" in skill
            assert "has_handler" in skill
            assert "source" in skill
            assert "tags" in skill

    def test_has_handler_flag(self):
        catalog_path = Path(__file__).resolve().parent.parent / "lib"
        skills = discover_skills_in_path(catalog_path, "builtin")
        skill_map = {s["name"]: s for s in skills}
        assert skill_map["github"]["has_handler"] is False
        assert skill_map["system_status"]["has_handler"] is True
        assert skill_map["drone_commands"]["has_handler"] is True

    def test_custom_skill_discovery(self):
        """Test that a custom skill directory is discovered correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: my-skill\ndescription: A test\n---\n\n# Test\n", encoding="utf-8"
            )
            skills = discover_skills_in_path(tmpdir, "project")
            assert len(skills) == 1
            assert skills[0]["name"] == "my-skill"
            assert skills[0]["source"] == "project"


class TestParseFrontmatter:
    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(encoding="utf-8", mode="w", suffix=".md", delete=False) as f:
            f.write("---\nname: test\ndescription: Hello\n---\n\n# Body\n")
            f.flush()
            result = parse_frontmatter(f.name)
            assert result is not None
            assert result["name"] == "test"
        Path(f.name).unlink()

    def test_a_missing_file_refuses(self, tmp_path):
        with pytest.raises(ValueError, match="Unreadable SKILL.md at"):
            parse_frontmatter(str(tmp_path / "nonexistent" / "file.md"))
