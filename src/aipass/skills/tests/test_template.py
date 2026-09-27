# =================== AIPass ====================
# Name: test_template.py
# Description: Tests for skill template management
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/template.py: resolution, placeholder replacement, copy."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that template.py and module_paths.py parse and import
# seedgo: no-test-needed(documentation) — that get_template and copy_template carry docstrings

import shutil
import sys
from unittest.mock import patch

from aipass.skills.apps.handlers.template import (
    TEMPLATES_DIR,
    VALID_TYPES,
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
        # The floor: an emptied VALID_TYPES would make the loop below pass
        # having read nothing out of the error string.
        assert VALID_TYPES == ("markdown_only", "with_handler", "full")
        for vt in VALID_TYPES:
            assert vt in result["error"]

    def test_missing_directory_fails(self, monkeypatch, tmp_path):
        """If template dir doesn't exist on disk, should fail gracefully."""
        _tpl_mod = sys.modules["aipass.skills.apps.handlers.template"]

        monkeypatch.setattr(
            _tpl_mod,
            "TEMPLATES_DIR",
            tmp_path / "nonexistent" / "templates",
        )
        result = get_template("markdown_only")
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_templates_dir_points_to_real_directory(self):
        assert TEMPLATES_DIR.exists()
        assert TEMPLATES_DIR.is_dir()

    def test_all_valid_types_have_directories(self):
        assert VALID_TYPES == ("markdown_only", "with_handler", "full")
        for vt in VALID_TYPES:
            assert (TEMPLATES_DIR / vt).exists(), f"Missing template dir: {vt}"


# ===================================================================
# 2. Placeholder substitution — reached through copy_template's copy step
# ===================================================================


class TestReplacePlaceholder:
    """Placeholder substitution ({{SKILL_NAME}} replacement), reached through
    copy_template() on a template dir built under tmp_path (item 10) rather
    than by calling the private in-file replacer directly."""

    @staticmethod
    def _copied(tmp_path, files, skill_name="my-tool"):
        """Build a one-off template dir under tmp_path holding `files`, copy it
        via copy_template, and return the target directory it was copied to."""
        src = tmp_path / "src-template"
        src.mkdir()
        for name, content in files.items():
            path = src / name
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        target = tmp_path / "target"
        result = copy_template(src, target, skill_name)
        assert result["success"] is True
        return target

    def test_replaces_placeholder_in_text(self, tmp_path):
        target = self._copied(tmp_path, {"test.md": "name: {{SKILL_NAME}}\ndesc: {{SKILL_NAME}} is great"})
        content = (target / "test.md").read_text(encoding="utf-8")
        assert "my-tool" in content
        assert "{{SKILL_NAME}}" not in content

    def test_no_placeholder_leaves_file_unchanged(self, tmp_path):
        original = "no placeholders here"
        target = self._copied(tmp_path, {"noop.txt": original})
        assert (target / "noop.txt").read_text(encoding="utf-8") == original

    def test_skips_binary_file(self, tmp_path):
        """Binary files with UnicodeDecodeError should be silently skipped."""
        # Should not raise, and copy_template (asserted success inside _copied)
        # must still complete the rest of the copy.
        target = self._copied(tmp_path, {"binary.bin": b"\x80\x81\x82\xff{{SKILL_NAME}}"})
        # File should still be binary (unchanged or at least not crash)
        assert (target / "binary.bin").exists()

    def test_empty_file_no_error(self, tmp_path):
        target = self._copied(tmp_path, {"empty.md": ""})
        assert (target / "empty.md").read_text(encoding="utf-8") == ""

    def test_multiple_placeholders_all_replaced(self, tmp_path):
        target = self._copied(
            tmp_path,
            {"multi.md": "A={{SKILL_NAME}} B={{SKILL_NAME}} C={{SKILL_NAME}}"},
            skill_name="x",
        )
        content = (target / "multi.md").read_text(encoding="utf-8")
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
        files = [p for p in target.rglob("*") if p.is_file()]
        # The floor. The old shape put the assert under `if f.is_file()` with
        # no else, so a target that laid down nothing passed. The
        # except UnicodeDecodeError below it was dead too: the with_handler
        # template is two utf-8 files and no binary (measured), so it only
        # stood ready to swallow a real failure.
        #
        # Compared as a set, not a sorted list: sorting Paths compares
        # case-insensitively on Windows and byte-wise on POSIX, so
        # ["handler.py", "SKILL.md"] and ["SKILL.md", "handler.py"] are both
        # "sorted" depending on the platform. Which two files exist is the
        # claim; their filesystem listing order never is.
        assert {f.name for f in files} == {"SKILL.md", "handler.py"}
        for f in files:
            content = f.read_text(encoding="utf-8")
            assert "{{SKILL_NAME}}" not in content, f"Unreplaced in {f.name}"

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
        result = copy_template(tmp_path / "nonexistent" / "template", target, "bad")
        assert result["success"] is False
        assert "Failed to create skill" in result["error"]

    def test_cleanup_on_failure(self, tmp_path):
        """If copy fails mid-way, target dir should be cleaned up."""
        target = tmp_path / "cleanup-test"
        result = copy_template(tmp_path / "nonexistent", target, "test")
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
        _tpl_mod = sys.modules["aipass.skills.apps.handlers.template"]

        with patch.object(_tpl_mod, "json_handler") as mock_jh:
            src = get_template("markdown_only")
            target = tmp_path / "log-test"
            copy_template(src["path"], target, "log-test")
            mock_jh.log_operation.assert_called_once()
            call_args = mock_jh.log_operation.call_args
            assert call_args[0][0] == "template_copied"
            assert call_args[0][1]["files_count"] > 0
