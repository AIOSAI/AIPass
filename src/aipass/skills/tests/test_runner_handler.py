# ===================AIPASS====================
# META DATA HEADER
# Name: test_runner_handler.py - Unit tests for runner_handler (empty body, etc.)
# Date: 2026-03-10
# Version: 1.0.0
# Category: skills/tests
# =============================================

"""Tests for the skills runner handler, focusing on run_markdown edge cases."""

import sys
from pathlib import Path

skills_root = Path(__file__).resolve().parent.parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))

from aipass.skills.apps.handlers.runner_handler import run_markdown, run_handler


class TestRunMarkdownEmptyBody:
    def test_empty_body_returns_success(self):
        result = run_markdown("empty-skill", {"description": "test"}, "")
        assert result["success"] is True

    def test_empty_body_output_mentions_no_instructions(self):
        result = run_markdown("empty-skill", {}, "")
        assert "no instructions body" in result["output"].lower()
        assert "empty-skill" in result["output"]

    def test_none_body_returns_no_instructions(self):
        result = run_markdown("test-skill", {}, None)
        assert result["success"] is True
        assert "no instructions body" in result["output"].lower()

    def test_empty_body_no_error(self):
        result = run_markdown("test-skill", {}, "")
        assert result["error"] is None


class TestRunMarkdownWithBody:
    def test_body_included_in_output(self):
        result = run_markdown("my-skill", {"description": "A skill"}, "# Instructions\nDo stuff.")
        assert result["success"] is True
        assert "# Instructions" in result["output"]
        assert "Do stuff." in result["output"]

    def test_header_includes_skill_name(self):
        result = run_markdown("my-skill", {}, "body content")
        assert "=== Skill: my-skill ===" in result["output"]

    def test_header_includes_description(self):
        result = run_markdown("my-skill", {"description": "Does things"}, "body")
        assert "Does things" in result["output"]

    def test_no_description_still_works(self):
        result = run_markdown("my-skill", {}, "body")
        assert result["success"] is True
        assert "=== Skill: my-skill ===" in result["output"]


class TestRunHandler:
    def test_no_action_with_get_actions(self):
        """When action is None and handler has get_actions, list them."""

        class MockHandler:
            def get_actions(self):
                return ["disk", "memory"]

        result = run_handler(MockHandler(), "test-skill", None, {}, {})
        assert result["success"] is True
        assert "disk" in result["output"]
        assert "memory" in result["output"]

    def test_no_action_without_get_actions(self):
        """When action is None and handler lacks get_actions, return error."""

        class MockHandler:
            pass

        result = run_handler(MockHandler(), "test-skill", None, {}, {})
        assert result["success"] is False
        assert "no action specified" in result["error"].lower()

    def test_handler_no_run_function(self):
        class MockHandler:
            pass

        result = run_handler(MockHandler(), "test-skill", "do_stuff", {}, {})
        assert result["success"] is False
        assert "no run() function" in result["error"].lower()

    def test_handler_returns_dict(self):
        class MockHandler:
            def run(self, action, args=None, config=None):
                return {"success": True, "output": "done", "error": None}

        result = run_handler(MockHandler(), "test-skill", "go", {}, {})
        assert result["success"] is True
        assert result["output"] == "done"

    def test_handler_returns_non_dict(self):
        class MockHandler:
            def run(self, action, args=None, config=None):
                return "just a string"

        result = run_handler(MockHandler(), "test-skill", "go", {}, {})
        assert result["success"] is True
        assert result["output"] == "just a string"

    def test_handler_raises_exception(self):
        class MockHandler:
            def run(self, action, args=None, config=None):
                raise ValueError("boom")

        result = run_handler(MockHandler(), "test-skill", "go", {}, {})
        assert result["success"] is False
        assert "boom" in result["error"]
