# =================== AIPass ====================
# Name: test_discovery.py
# Description: Unit tests for skills discovery
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-10-22
# Category: skills/tests
# =============================================

"""Tests for apps/handlers/discovery_handler.py and the skill discovery it powers."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that discovery_handler.py and module_paths.py parse and import
# seedgo: no-test-needed(constant) — the "discovery_scan" log-operation name json_handler records

import pytest
import tempfile
from pathlib import Path

from aipass.skills.apps.handlers import discovery_handler
from aipass.skills.apps.handlers.discovery_handler import (
    discover_skills_in_path,
    get_search_paths,
    parse_frontmatter,
)


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


class TestSimpleFrontmatterParse:
    """The no-yaml fallback parser, forced by patching `yaml` to None (PyYAML would intercept otherwise)."""

    @pytest.fixture(autouse=True)
    def _force_no_yaml(self, monkeypatch):
        monkeypatch.setattr(discovery_handler, "yaml", None)

    @staticmethod
    def _parse(tmp_path, frontmatter_text):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(f"---\n{frontmatter_text}\n---\n", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is not None
        return result

    def test_flat_key_value(self, tmp_path):
        result = self._parse(tmp_path, "name: my-skill\ndescription: Does a thing")
        assert result["name"] == "my-skill"
        assert result["description"] == "Does a thing"

    def test_inline_list(self, tmp_path):
        result = self._parse(tmp_path, "tags: [a, b, c]")
        assert result["tags"] == ["a", "b", "c"]

    def test_empty_list(self, tmp_path):
        result = self._parse(tmp_path, "tags: []")
        assert result["tags"] == []

    def test_boolean_true(self, tmp_path):
        result = self._parse(tmp_path, "has_handler: true")
        assert result["has_handler"] is True

    def test_boolean_false(self, tmp_path):
        result = self._parse(tmp_path, "has_handler: false")
        assert result["has_handler"] is False

    def test_nested_keys(self, tmp_path):
        result = self._parse(tmp_path, "requires:\n  pip: [praw]\n  bins: [gh]\n  config: [MY_TOKEN]")
        assert result["requires"]["pip"] == ["praw"]
        assert result["requires"]["bins"] == ["gh"]
        assert result["requires"]["config"] == ["MY_TOKEN"]

    def test_nested_block_list(self, tmp_path):
        # Without this, declared systemd units read as empty on any runner lacking PyYAML.
        result = self._parse(tmp_path, "switch:\n  systemd_user:\n    - telegram-bot@api\n    - telegram-bot@base")
        assert result["switch"]["systemd_user"] == ["telegram-bot@api", "telegram-bot@base"]

    def test_top_level_block_list(self, tmp_path):
        # screen_lock and github declare when_to_use this way.
        result = self._parse(tmp_path, 'when_to_use:\n  - "lock the screen"\n  - "walking away"')
        assert result["when_to_use"] == ["lock the screen", "walking away"]

    def test_a_block_list_does_not_leak_into_the_next_key(self, tmp_path):
        # Needs a NESTED inline list (only it arms the list cursor) and a later "- " item to steal,
        # or a parser that never closes the cursor still passes.
        result = self._parse(tmp_path, "requires:\n  pip: [praw]\nwhen_to_use:\n  - stolen-if-broken\nversion: 3")

        assert result["requires"]["pip"] == ["praw"]
        assert result["when_to_use"] == ["stolen-if-broken"]
        assert result["version"] == 3

    def test_an_empty_nested_key_swallows_nothing_from_its_siblings(self, tmp_path):
        result = self._parse(tmp_path, "requires:\n  pip:\n  bins: [gh]\n  config: [TOKEN]")

        assert not result["requires"]["pip"]
        assert result["requires"]["bins"] == ["gh"]
        assert result["requires"]["config"] == ["TOKEN"]

    def test_an_empty_nested_key_still_takes_its_own_block_list(self, tmp_path):
        result = self._parse(tmp_path, "switch:\n  systemd_user:\n    - one\n  other: [x]")

        assert result["switch"]["systemd_user"] == ["one"]
        assert result["switch"]["other"] == ["x"]

    def test_integer_value(self, tmp_path):
        result = self._parse(tmp_path, "version: 42")
        assert result["version"] == 42

    def test_quoted_string(self, tmp_path):
        result = self._parse(tmp_path, 'description: "A quoted value"')
        assert result["description"] == "A quoted value"


class TestParseSimpleValue:
    """The no-yaml fallback's value parser, reached through parse_frontmatter() on one keyed line."""

    @pytest.fixture(autouse=True)
    def _force_no_yaml(self, monkeypatch):
        monkeypatch.setattr(discovery_handler, "yaml", None)

    @staticmethod
    def _value_for(tmp_path, raw_value):
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(f"---\nvalue: {raw_value}\n---\n", encoding="utf-8")
        result = parse_frontmatter(skill_md)
        assert result is not None
        return result["value"]

    def test_empty_list(self, tmp_path):
        assert self._value_for(tmp_path, "[]") == []

    def test_inline_list(self, tmp_path):
        assert self._value_for(tmp_path, "[a, b]") == ["a", "b"]

    def test_true(self, tmp_path):
        assert self._value_for(tmp_path, "true") is True

    def test_false(self, tmp_path):
        assert self._value_for(tmp_path, "false") is False

    def test_integer(self, tmp_path):
        assert self._value_for(tmp_path, "42") == 42

    def test_float(self, tmp_path):
        assert self._value_for(tmp_path, "3.14") == 3.14

    def test_string(self, tmp_path):
        assert self._value_for(tmp_path, "hello") == "hello"


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

    def test_invalid_file(self, tmp_path):
        result = parse_frontmatter(str(tmp_path / "nonexistent" / "file.md"))
        assert result is None
