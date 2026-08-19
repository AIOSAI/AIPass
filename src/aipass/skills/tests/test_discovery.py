# ===================AIPASS====================
# META DATA HEADER
# Name: test_discovery.py - Unit tests for skills discovery
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills discovery module."""

import tempfile
from pathlib import Path

from aipass.skills.apps.handlers.discovery_handler import (
    _extract_frontmatter,
    _parse_simple_value,
    _simple_frontmatter_parse,
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
    def test_valid_frontmatter(self):
        content = "---\nname: test\ndescription: A test skill\n---\n\n# Body"
        result = _extract_frontmatter(content)
        assert result is not None
        assert result["name"] == "test"
        assert result["description"] == "A test skill"

    def test_no_frontmatter(self):
        content = "# Just a markdown file\nNo frontmatter here."
        result = _extract_frontmatter(content)
        assert result is None

    def test_unclosed_frontmatter(self):
        content = "---\nname: test\nno closing delimiter"
        result = _extract_frontmatter(content)
        assert result is None

    def test_empty_content(self):
        result = _extract_frontmatter("")
        assert result is None

    def test_boolean_values(self):
        content = "---\nname: test\nhas_handler: true\n---\n"
        result = _extract_frontmatter(content)
        assert result is not None
        assert result["has_handler"] is True

    def test_list_values(self):
        content = "---\nname: test\ntags: [dev, git, ci]\n---\n"
        result = _extract_frontmatter(content)
        assert result is not None
        assert result["tags"] == ["dev", "git", "ci"]


class TestSimpleFrontmatterParse:
    def test_flat_key_value(self):
        text = "name: my-skill\ndescription: Does a thing"
        result = _simple_frontmatter_parse(text)
        assert result["name"] == "my-skill"
        assert result["description"] == "Does a thing"

    def test_inline_list(self):
        text = "tags: [a, b, c]"
        result = _simple_frontmatter_parse(text)
        assert result["tags"] == ["a", "b", "c"]

    def test_empty_list(self):
        text = "tags: []"
        result = _simple_frontmatter_parse(text)
        assert result["tags"] == []

    def test_boolean_true(self):
        text = "has_handler: true"
        result = _simple_frontmatter_parse(text)
        assert result["has_handler"] is True

    def test_boolean_false(self):
        text = "has_handler: false"
        result = _simple_frontmatter_parse(text)
        assert result["has_handler"] is False

    def test_nested_keys(self):
        text = "requires:\n  pip: [praw]\n  bins: [gh]\n  config: [MY_TOKEN]"
        result = _simple_frontmatter_parse(text)
        assert result["requires"]["pip"] == ["praw"]
        assert result["requires"]["bins"] == ["gh"]
        assert result["requires"]["config"] == ["MY_TOKEN"]

    def test_nested_block_list(self):
        # The no-yaml fallback silently answered "" here, so a skill's declared
        # systemd units read as empty on any runner without PyYAML. That is the
        # CI red of 2026-08-19 (run 32222871212), not a machine-state problem.
        text = "switch:\n  systemd_user:\n    - telegram-bot@api\n    - telegram-bot@base"
        result = _simple_frontmatter_parse(text)
        assert result["switch"]["systemd_user"] == ["telegram-bot@api", "telegram-bot@base"]

    def test_top_level_block_list(self):
        # Same defect one level up, and already live: screen_lock and github
        # both declare when_to_use this way, and both parsed to {} without yaml.
        text = 'when_to_use:\n  - "lock the screen"\n  - "walking away"'
        result = _simple_frontmatter_parse(text)
        assert result["when_to_use"] == ["lock the screen", "walking away"]

    def test_a_block_list_does_not_leak_into_the_next_key(self):
        # The items must land under the key they follow. An earlier draft of
        # this test put no "- " line AFTER the second key, so a parser that
        # never closed the open list still passed it — the leak needs a later
        # item to steal before it is visible.
        # The open list has to be a NESTED inline one: only that branch arms the
        # list cursor, so only that shape can leak. Two earlier drafts of this
        # test used a top-level list and passed against a parser that never
        # closed the cursor at all.
        text = "requires:\n  pip: [praw]\nwhen_to_use:\n  - stolen-if-broken\nversion: 3"
        result = _simple_frontmatter_parse(text)

        assert result["requires"]["pip"] == ["praw"]
        assert result["when_to_use"] == ["stolen-if-broken"]
        assert result["version"] == 3

    def test_an_empty_nested_key_swallows_nothing_from_its_siblings(self):
        # Reaches the undecided-nested-key branch for real: "pip:" carries no
        # value and no list follows, so the parser must leave it empty and let
        # the sibling keys parse normally.
        text = "requires:\n  pip:\n  bins: [gh]\n  config: [TOKEN]"
        result = _simple_frontmatter_parse(text)

        assert not result["requires"]["pip"]
        assert result["requires"]["bins"] == ["gh"]
        assert result["requires"]["config"] == ["TOKEN"]

    def test_an_empty_nested_key_still_takes_its_own_block_list(self):
        text = "switch:\n  systemd_user:\n    - one\n  other: [x]"
        result = _simple_frontmatter_parse(text)

        assert result["switch"]["systemd_user"] == ["one"]
        assert result["switch"]["other"] == ["x"]

    def test_integer_value(self):
        text = "version: 42"
        result = _simple_frontmatter_parse(text)
        assert result["version"] == 42

    def test_quoted_string(self):
        text = 'description: "A quoted value"'
        result = _simple_frontmatter_parse(text)
        assert result["description"] == "A quoted value"


class TestParseSimpleValue:
    def test_empty_list(self):
        assert _parse_simple_value("[]") == []

    def test_inline_list(self):
        assert _parse_simple_value("[a, b]") == ["a", "b"]

    def test_true(self):
        assert _parse_simple_value("true") is True

    def test_false(self):
        assert _parse_simple_value("false") is False

    def test_integer(self):
        assert _parse_simple_value("42") == 42

    def test_float(self):
        assert _parse_simple_value("3.14") == 3.14

    def test_string(self):
        assert _parse_simple_value("hello") == "hello"


class TestDiscoverSkillsInPath:
    def test_finds_catalog_skills(self):
        catalog_path = Path(__file__).resolve().parent.parent / "lib"
        skills = discover_skills_in_path(catalog_path, "builtin")
        names = {s["name"] for s in skills}
        assert "github" in names
        assert "system_status" in names
        assert "drone_commands" in names

    def test_nonexistent_path(self):
        skills = discover_skills_in_path("/nonexistent/path", "test")
        assert skills == []

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills = discover_skills_in_path(tmpdir, "test")
            assert skills == []

    def test_skill_dict_structure(self):
        catalog_path = Path(__file__).resolve().parent.parent / "lib"
        skills = discover_skills_in_path(catalog_path, "builtin")
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
            (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test\n---\n\n# Test\n")
            skills = discover_skills_in_path(tmpdir, "project")
            assert len(skills) == 1
            assert skills[0]["name"] == "my-skill"
            assert skills[0]["source"] == "project"


class TestParseFrontmatter:
    def test_valid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nname: test\ndescription: Hello\n---\n\n# Body\n")
            f.flush()
            result = parse_frontmatter(f.name)
            assert result is not None
            assert result["name"] == "test"
        Path(f.name).unlink()

    def test_invalid_file(self):
        result = parse_frontmatter("/nonexistent/file.md")
        assert result is None
