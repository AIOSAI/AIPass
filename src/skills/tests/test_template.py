# =================== AIPass ====================
# Name: test_template.py
# Description: Tests for skill template management
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for template.py — template resolution, placeholder replacement, copy logic.

Covers: get_template, _replace_placeholder_in_file, copy_template
(valid/invalid types, placeholder replacement, binary skip, error paths,
target exists, cleanup on failure, __pycache__ exclusion).
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

from skills.apps.handlers.template import (
    TEMPLATES_DIR,
    VALID_TYPES,
    _replace_placeholder_in_file,
    copy_template,
    get_template,
)


# ===================================================================
# 1. get_template — template path resolution
# ===================================================================


class TestGetTemplate:
    """Tests for get_template — resolve template directories."""

    def test_markdown_only_returns_valid_path(self):
        result = get_template("markdown_only")
        assert result["success"] is True
        assert result["path"].exists()
        assert result["path"].is_dir()
        assert result["error"] is None

    def test_with_handler_returns_valid_path(self):
        result = get_template("with_handler")
        assert result["success"] is True
        assert result["path"].exists()

    def test_full_returns_valid_path(self):
        result = get_template("full")
        assert result["success"] is True
        assert result["path"].exists()

    def test_invalid_type_fails(self):
        result = get_template("bogus")
        assert result["success"] is False
        assert result["path"] is None
        assert "Unknown template type" in result["error"]
        assert "bogus" in result["error"]

    def test_error_lists_valid_types(self):
        result = get_template("wrong")
        for vt in VALID_TYPES:
            assert vt in result["error"]

    def test_missing_directory_fails(self, monkeypatch):
        """If template dir doesn't exist on disk, should fail gracefully."""
        _tpl_mod = sys.modules["skills.apps.handlers.template"]

        monkeypatch.setattr(
            _tpl_mod,
            "TEMPLATES_DIR",
            Path("/nonexistent/templates"),
        )
        result = get_template("markdown_only")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_templates_dir_points_to_real_directory(self):
        assert TEMPLATES_DIR.exists()
        assert TEMPLATES_DIR.is_dir()

    def test_all_valid_types_have_directories(self):
        for vt in VALID_TYPES:
            assert (TEMPLATES_DIR / vt).exists(), f"Missing template dir: {vt}"


# ===================================================================
# 2. _replace_placeholder_in_file — in-file substitution
# ===================================================================


class TestReplacePlaceholder:
    """Tests for _replace_placeholder_in_file — {{SKILL_NAME}} replacement."""

    def test_replaces_placeholder_in_text(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("name: {{SKILL_NAME}}\ndesc: {{SKILL_NAME}} is great")
        _replace_placeholder_in_file(f, "my-tool")
        content = f.read_text()
        assert "my-tool" in content
        assert "{{SKILL_NAME}}" not in content

    def test_no_placeholder_leaves_file_unchanged(self, tmp_path):
        f = tmp_path / "noop.txt"
        original = "no placeholders here"
        f.write_text(original)
        _replace_placeholder_in_file(f, "anything")
        assert f.read_text() == original

    def test_skips_binary_file(self, tmp_path):
        """Binary files with UnicodeDecodeError should be silently skipped."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x80\x81\x82\xff{{SKILL_NAME}}")
        # Should not raise
        _replace_placeholder_in_file(f, "test")
        # File should still be binary (unchanged or at least not crash)
        assert f.exists()

    def test_empty_file_no_error(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        _replace_placeholder_in_file(f, "test")
        assert f.read_text() == ""

    def test_multiple_placeholders_all_replaced(self, tmp_path):
        f = tmp_path / "multi.md"
        f.write_text("A={{SKILL_NAME}} B={{SKILL_NAME}} C={{SKILL_NAME}}")
        _replace_placeholder_in_file(f, "x")
        content = f.read_text()
        assert content == "A=x B=x C=x"


# ===================================================================
# 3. copy_template — full template copy pipeline
# ===================================================================


class TestCopyTemplate:
    """Tests for copy_template — copy + placeholder replacement."""

    def test_copy_markdown_template(self, tmp_path):
        src = get_template("markdown_only")
        target = tmp_path / "new-skill"
        result = copy_template(src["path"], target, "new-skill")
        assert result["success"] is True
        assert target.exists()
        assert len(result["created_files"]) > 0
        assert result["error"] is None

    def test_created_files_are_sorted(self, tmp_path):
        src = get_template("with_handler")
        target = tmp_path / "sorted-test"
        result = copy_template(src["path"], target, "sorted-test")
        assert result["created_files"] == sorted(result["created_files"])

    def test_placeholders_replaced_in_all_files(self, tmp_path):
        src = get_template("with_handler")
        target = tmp_path / "placeholder-test"
        copy_template(src["path"], target, "placeholder-test")
        for f in target.rglob("*"):
            if f.is_file():
                try:
                    content = f.read_text(encoding="utf-8")
                    assert "{{SKILL_NAME}}" not in content, f"Unreplaced in {f.name}"
                except UnicodeDecodeError:
                    pass  # skip binary

    def test_target_already_exists_fails(self, tmp_path):
        target = tmp_path / "exists"
        target.mkdir()
        src = get_template("markdown_only")
        result = copy_template(src["path"], target, "exists")
        assert result["success"] is False
        assert "already exists" in result["error"]
        assert result["created_files"] == []

    def test_invalid_source_fails(self, tmp_path):
        target = tmp_path / "bad-src"
        result = copy_template(Path("/nonexistent/template"), target, "bad")
        assert result["success"] is False
        assert "Failed to create skill" in result["error"]

    def test_cleanup_on_failure(self, tmp_path):
        """If copy fails mid-way, target dir should be cleaned up."""
        target = tmp_path / "cleanup-test"
        result = copy_template(Path("/nonexistent"), target, "test")
        assert result["success"] is False
        # Target should not exist after cleanup
        assert not target.exists()

    def test_pycache_excluded(self, tmp_path):
        """__pycache__ directories must not appear in output."""
        src = get_template("full")
        assert src["success"]
        # Inject a __pycache__ into the template temporarily
        pycache = src["path"] / "__pycache__"
        created = False
        if not pycache.exists():
            pycache.mkdir()
            (pycache / "cached.pyc").write_bytes(b"\x00")
            created = True
        try:
            target = tmp_path / "no-cache"
            result = copy_template(src["path"], target, "no-cache")
            assert result["success"] is True
            assert not (target / "__pycache__").exists()
            for f in result["created_files"]:
                assert "__pycache__" not in f
        finally:
            if created:
                shutil.rmtree(str(pycache))

    def test_full_template_has_apps_structure(self, tmp_path):
        src = get_template("full")
        target = tmp_path / "full-test"
        result = copy_template(src["path"], target, "full-test")
        assert result["success"] is True
        assert (target / "apps").is_dir()
        assert (target / "apps" / "modules").is_dir()
        assert (target / "apps" / "handlers").is_dir()

    def test_logs_template_copied_operation(self, tmp_path):
        _tpl_mod = sys.modules["skills.apps.handlers.template"]

        with patch.object(_tpl_mod, "json_handler") as mock_jh:
            src = get_template("markdown_only")
            target = tmp_path / "log-test"
            copy_template(src["path"], target, "log-test")
            mock_jh.log_operation.assert_called_once()
            call_args = mock_jh.log_operation.call_args
            assert call_args[0][0] == "template_copied"
            assert call_args[0][1]["files_count"] > 0
