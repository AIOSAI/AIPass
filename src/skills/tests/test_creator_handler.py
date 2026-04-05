# =================== AIPass ====================
# Name: test_creator_handler.py
# Description: Tests for skill creation handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for creator_handler.py — skill name validation and create_skill logic.

Covers: is_valid_name, create_skill (success paths, validation failures,
template failures, target_dir default, json logging).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.apps.handlers.creator_handler import create_skill, is_valid_name


# ===================================================================
# 1. is_valid_name — name validation
# ===================================================================


class TestIsValidName:
    """Tests for is_valid_name — skill name validation rules."""

    def test_simple_lowercase_name(self):
        assert is_valid_name("my-skill") is True

    def test_single_letter(self):
        assert is_valid_name("a") is True

    def test_lowercase_with_numbers(self):
        assert is_valid_name("skill2") is True

    def test_underscores_allowed(self):
        assert is_valid_name("my_skill") is True

    def test_hyphens_allowed(self):
        assert is_valid_name("my-skill") is True

    def test_mixed_separators(self):
        assert is_valid_name("my-skill_v2") is True

    def test_rejects_empty_string(self):
        assert is_valid_name("") is False

    def test_rejects_none(self):
        """None is falsy — short-circuits to False via 'not name'."""
        assert is_valid_name(None) is False

    def test_rejects_starts_with_number(self):
        assert is_valid_name("2skill") is False

    def test_rejects_starts_with_hyphen(self):
        assert is_valid_name("-skill") is False

    def test_rejects_uppercase(self):
        assert is_valid_name("MySkill") is False

    def test_rejects_mixed_case(self):
        assert is_valid_name("mySkill") is False

    def test_rejects_spaces(self):
        assert is_valid_name("my skill") is False

    def test_rejects_special_chars(self):
        assert is_valid_name("my.skill") is False

    def test_rejects_slash(self):
        assert is_valid_name("my/skill") is False


# ===================================================================
# 2. create_skill — skill creation orchestration
# ===================================================================


class TestCreateSkill:
    """Tests for create_skill — full creation pipeline."""

    def test_create_markdown_skill_succeeds(self, tmp_path):
        result = create_skill("test-md", template_type="markdown_only", target_dir=tmp_path)
        assert result["success"] is True
        assert result["path"] is not None
        assert Path(result["path"]).exists()
        assert (Path(result["path"]) / "SKILL.md").exists()

    def test_create_handler_skill_succeeds(self, tmp_path):
        result = create_skill("test-hnd", template_type="with_handler", target_dir=tmp_path)
        assert result["success"] is True
        assert (Path(result["path"]) / "handler.py").exists()

    def test_create_full_skill_succeeds(self, tmp_path):
        result = create_skill("test-full", template_type="full", target_dir=tmp_path)
        assert result["success"] is True
        assert (Path(result["path"]) / "apps").is_dir()

    def test_returns_created_files_list(self, tmp_path):
        result = create_skill("test-files", template_type="markdown_only", target_dir=tmp_path)
        assert isinstance(result["files"], list)
        assert len(result["files"]) > 0
        assert "SKILL.md" in result["files"]

    def test_empty_name_fails(self):
        result = create_skill("", template_type="markdown_only")
        assert result["success"] is False
        assert result["error"] == "Skill name is required."
        assert result["path"] is None
        assert result["files"] == []

    def test_invalid_name_fails(self):
        result = create_skill("Bad Name!", template_type="markdown_only")
        assert result["success"] is False
        assert "Invalid skill name" in result["error"]

    def test_invalid_template_type_fails(self, tmp_path):
        result = create_skill("valid-name", template_type="nonexistent", target_dir=tmp_path)
        assert result["success"] is False
        assert "Unknown template type" in result["error"]

    def test_default_target_dir_uses_cwd(self, monkeypatch, tmp_path):
        """When target_dir is None, uses CWD/.aipass/skills/."""
        monkeypatch.chdir(tmp_path)
        result = create_skill("cwd-test", template_type="markdown_only")
        assert result["success"] is True
        expected_parent = tmp_path / ".aipass" / "skills"
        assert str(expected_parent) in result["path"]

    def test_duplicate_name_fails(self, tmp_path):
        """Creating a skill that already exists should fail."""
        create_skill("dupe-test", template_type="markdown_only", target_dir=tmp_path)
        result = create_skill("dupe-test", template_type="markdown_only", target_dir=tmp_path)
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_placeholder_replacement(self, tmp_path):
        """Skill name replaces {{SKILL_NAME}} in created files."""
        result = create_skill("my-replaced", template_type="markdown_only", target_dir=tmp_path)
        content = (Path(result["path"]) / "SKILL.md").read_text()
        assert "my-replaced" in content
        assert "{{SKILL_NAME}}" not in content

    def test_logs_json_operation_on_success(self, tmp_path):
        _mod = sys.modules["skills.apps.handlers.creator_handler"]

        with patch.object(_mod, "json_handler") as mock_jh:
            create_skill("log-test", template_type="markdown_only", target_dir=tmp_path)
            mock_jh.log_operation.assert_called_once()
            call_args = mock_jh.log_operation.call_args
            assert call_args[0][0] == "skill_scaffold"
            assert call_args[0][1]["success"] is True

    def test_logs_json_operation_on_failure(self, tmp_path):
        _mod = sys.modules["skills.apps.handlers.creator_handler"]

        # Use a duplicate-name scenario so validation passes but copy fails,
        # which is the only failure path that reaches json_handler.log_operation.
        create_skill("dup-log", template_type="markdown_only", target_dir=tmp_path)

        with patch.object(_mod, "json_handler") as mock_jh:
            create_skill("dup-log", template_type="markdown_only", target_dir=tmp_path)
            mock_jh.log_operation.assert_called_once()
            call_args = mock_jh.log_operation.call_args
            assert call_args[0][1]["success"] is False
