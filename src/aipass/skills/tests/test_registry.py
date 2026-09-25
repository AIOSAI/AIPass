# ===================AIPASS====================
# META DATA HEADER
# Name: test_registry.py - Unit tests for skills registry
# Date: 2026-03-10
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills registry handler."""

import sys
import tempfile
from pathlib import Path

skills_root = Path(__file__).resolve().parent.parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))

from aipass.skills.apps.handlers.registry import build_registry, get_skill, get_skill_names


class TestBuildRegistry:
    def _make_discover_fn(self, skills_by_path):
        """Helper: returns a discover_fn that returns skills based on path."""

        def discover_fn(path, source_label):
            return skills_by_path.get(str(path), [])

        return discover_fn

    def test_empty_search_paths(self):
        registry = build_registry([], lambda p, s: [])
        assert registry == []

    def test_nonexistent_path_skipped(self):
        def discover_fn(p, s):
            return [{"name": "should-not-appear"}]

        registry = build_registry(
            [("/nonexistent/path/xyz_abc_123", "test")],
            discover_fn,
        )
        assert registry == []

    def test_discovers_skills_from_valid_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill = {"name": "alpha", "description": "A skill", "source": "test"}
            discover_fn = self._make_discover_fn({tmpdir: [skill]})
            registry = build_registry([(tmpdir, "test")], discover_fn)
            assert len(registry) == 1
            assert registry[0]["name"] == "alpha"
            assert registry[0]["description"] == "A skill"

    def test_first_match_wins_dedup(self):
        """When two paths contain a skill with the same name, first path wins."""
        with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
            skill_v1 = {"name": "dupe", "description": "First", "source": "project"}
            skill_v2 = {"name": "dupe", "description": "Second", "source": "builtin"}
            discover_fn = self._make_discover_fn(
                {
                    dir1: [skill_v1],
                    dir2: [skill_v2],
                }
            )
            registry = build_registry(
                [(dir1, "project"), (dir2, "builtin")],
                discover_fn,
            )
            assert len(registry) == 1
            assert registry[0]["description"] == "First"
            assert registry[0]["source"] == "project"

    def test_different_names_both_included(self):
        with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
            skill_a = {"name": "alpha", "description": "A"}
            skill_b = {"name": "beta", "description": "B"}
            discover_fn = self._make_discover_fn(
                {
                    dir1: [skill_a],
                    dir2: [skill_b],
                }
            )
            registry = build_registry(
                [(dir1, "project"), (dir2, "builtin")],
                discover_fn,
            )
            assert len(registry) == 2
            names = {s["name"] for s in registry}
            assert names == {"alpha", "beta"}

    def test_multiple_skills_from_single_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills = [
                {"name": "one", "description": "First"},
                {"name": "two", "description": "Second"},
                {"name": "three", "description": "Third"},
            ]
            discover_fn = self._make_discover_fn({tmpdir: skills})
            registry = build_registry([(tmpdir, "test")], discover_fn)
            assert len(registry) == 3

    def test_discover_fn_is_called_with_path_and_label(self):
        """Verify discover_fn receives Path object and source label."""
        calls = []

        def tracking_fn(path, source_label):
            calls.append((path, source_label))
            return []

        with tempfile.TemporaryDirectory() as tmpdir:
            build_registry([(tmpdir, "my_source")], tracking_fn)
            assert len(calls) == 1
            assert isinstance(calls[0][0], Path)
            assert calls[0][1] == "my_source"


class TestGetSkill:
    def test_found(self):
        registry = [
            {"name": "alpha", "description": "A"},
            {"name": "beta", "description": "B"},
        ]
        result = get_skill("beta", registry)
        assert result is not None
        assert result["name"] == "beta"
        assert result["description"] == "B"

    def test_not_found(self):
        registry = [{"name": "alpha", "description": "A"}]
        result = get_skill("nonexistent", registry)
        assert result is None

    def test_empty_registry(self):
        result = get_skill("anything", [])
        assert result is None

    def test_returns_first_match(self):
        """If registry somehow has duplicates, returns the first one."""
        registry = [
            {"name": "dup", "description": "First"},
            {"name": "dup", "description": "Second"},
        ]
        result = get_skill("dup", registry)
        assert result is not None
        assert result["description"] == "First"


class TestGetSkillNames:
    def test_returns_sorted_names(self):
        registry = [
            {"name": "charlie"},
            {"name": "alpha"},
            {"name": "bravo"},
        ]
        names = get_skill_names(registry)
        assert names == ["alpha", "bravo", "charlie"]

    def test_empty_registry(self):
        names = get_skill_names([])
        assert names == []

    def test_single_skill(self):
        registry = [{"name": "only"}]
        names = get_skill_names(registry)
        assert names == ["only"]
