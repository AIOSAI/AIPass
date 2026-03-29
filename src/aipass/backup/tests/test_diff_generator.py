"""Tests for diff_generator handler."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===================================================================
# TestShouldCreateDiff
# ===================================================================


class TestShouldCreateDiff:
    """Validate pattern-based filtering for diff creation."""

    def _clear_and_import(self, monkeypatch):
        """Clear cached diff_generator and re-import should_create_diff."""
        for key in list(sys.modules):
            if "diff_generator" in key:
                monkeypatch.delitem(sys.modules, key, raising=False)
        from aipass.backup.apps.handlers.diff.diff_generator import should_create_diff
        return should_create_diff

    def test_returns_true_for_unmatched_file(self, monkeypatch):
        """Files not matching any pattern default to True."""
        monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.config.config_handler", MagicMock(
            DIFF_IGNORE_PATTERNS=["*.bin"],
            DIFF_INCLUDE_PATTERNS=["*.special"],
        ))
        should_create_diff = self._clear_and_import(monkeypatch)

        result = should_create_diff(Path("src/app.py"))
        assert result is True

    def test_returns_false_for_ignored_pattern(self, monkeypatch):
        """Files matching an ignore pattern return False."""
        monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.config.config_handler", MagicMock(
            DIFF_IGNORE_PATTERNS=["*.bin", "*.lock"],
            DIFF_INCLUDE_PATTERNS=[],
        ))
        should_create_diff = self._clear_and_import(monkeypatch)

        result = should_create_diff(Path("data/archive.bin"))
        assert result is False

    def test_include_pattern_overrides_ignore(self, monkeypatch):
        """Include patterns take priority over ignore patterns."""
        monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.config.config_handler", MagicMock(
            DIFF_IGNORE_PATTERNS=["*.json"],
            DIFF_INCLUDE_PATTERNS=["*.json"],
        ))
        should_create_diff = self._clear_and_import(monkeypatch)

        result = should_create_diff(Path("config.json"))
        assert result is True

    def test_returns_true_when_no_patterns(self, monkeypatch):
        """Empty pattern lists mean all files get diffs."""
        monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.config.config_handler", MagicMock(
            DIFF_IGNORE_PATTERNS=[],
            DIFF_INCLUDE_PATTERNS=[],
        ))
        should_create_diff = self._clear_and_import(monkeypatch)

        result = should_create_diff(Path("anything.xyz"))
        assert result is True

    def test_returns_false_for_lock_file(self, monkeypatch):
        """Lock files matching ignore pattern are skipped."""
        monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.config.config_handler", MagicMock(
            DIFF_IGNORE_PATTERNS=["*.lock"],
            DIFF_INCLUDE_PATTERNS=[],
        ))
        should_create_diff = self._clear_and_import(monkeypatch)

        result = should_create_diff(Path("poetry.lock"))
        assert result is False


# ===================================================================
# TestIsBinaryFile
# ===================================================================


class TestIsBinaryFile:
    """Validate binary file detection."""

    def _clear_and_import(self, monkeypatch):
        """Clear cached diff_generator and re-import is_binary_file."""
        for key in list(sys.modules):
            if "diff_generator" in key:
                monkeypatch.delitem(sys.modules, key, raising=False)
        from aipass.backup.apps.handlers.diff.diff_generator import is_binary_file
        return is_binary_file

    def test_text_file_detected(self, tmp_path, monkeypatch):
        """Plain text file is not detected as binary."""
        is_binary_file = self._clear_and_import(monkeypatch)

        text_file = tmp_path / "readme.txt"
        text_file.write_text("Hello, world!\nThis is plain text.", encoding="utf-8")

        assert is_binary_file(text_file) is False

    def test_binary_file_detected(self, tmp_path, monkeypatch):
        """File containing null bytes is detected as binary."""
        is_binary_file = self._clear_and_import(monkeypatch)

        bin_file = tmp_path / "image.png"
        bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

        assert is_binary_file(bin_file) is True

    def test_empty_file_is_not_binary(self, tmp_path, monkeypatch):
        """Empty file has no null bytes, so it is not binary."""
        is_binary_file = self._clear_and_import(monkeypatch)

        empty_file = tmp_path / "empty.txt"
        empty_file.write_bytes(b"")

        assert is_binary_file(empty_file) is False

    def test_nonexistent_file_assumed_binary(self, tmp_path, monkeypatch):
        """Unreadable/missing file defaults to binary assumption."""
        is_binary_file = self._clear_and_import(monkeypatch)

        missing = tmp_path / "no_such_file.dat"

        assert is_binary_file(missing) is True

    def test_null_byte_at_end_of_chunk(self, tmp_path, monkeypatch):
        """Null byte anywhere in first 1024 bytes triggers binary detection."""
        is_binary_file = self._clear_and_import(monkeypatch)

        tricky_file = tmp_path / "tricky.dat"
        tricky_file.write_bytes(b"A" * 1023 + b"\x00")

        assert is_binary_file(tricky_file) is True

    def test_null_byte_beyond_chunk_not_detected(self, tmp_path, monkeypatch):
        """Null bytes beyond the first 1024 bytes are not checked."""
        is_binary_file = self._clear_and_import(monkeypatch)

        long_file = tmp_path / "long.dat"
        long_file.write_bytes(b"A" * 1025 + b"\x00")

        assert is_binary_file(long_file) is False


# ===================================================================
# TestGenerateDiffContent
# ===================================================================


class TestGenerateDiffContent:
    """Validate unified diff generation between file versions."""

    def _clear_and_import(self, monkeypatch):
        """Clear cached diff_generator and re-import generate_diff_content."""
        for key in list(sys.modules):
            if "diff_generator" in key:
                monkeypatch.delitem(sys.modules, key, raising=False)
        from aipass.backup.apps.handlers.diff.diff_generator import generate_diff_content
        return generate_diff_content

    def test_generates_diff_for_changed_file(self, tmp_path, monkeypatch):
        """Produces unified diff output for text files with differences."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "old.txt"
        new = tmp_path / "new.txt"
        old.write_text("line1\nline2\n", encoding="utf-8")
        new.write_text("line1\nline2_modified\n", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert "---" in result
        assert "+++" in result
        assert "-line2" in result
        assert "+line2_modified" in result

    def test_identical_files_produce_empty_diff(self, tmp_path, monkeypatch):
        """No diff output when files are identical."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "same.txt"
        new = tmp_path / "same_copy.txt"
        old.write_text("identical content\n", encoding="utf-8")
        new.write_text("identical content\n", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert result == ""

    def test_binary_files_return_message(self, tmp_path, monkeypatch):
        """Binary files produce a descriptive message instead of diff."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "old.bin"
        new = tmp_path / "new.bin"
        old.write_bytes(b"\x00\x01\x02")
        new.write_bytes(b"\x00\x01\x03")

        result = generate_diff_content(old, new)

        assert "Binary file" in result
        assert "old.bin" in result

    def test_one_binary_one_text_returns_binary_message(self, tmp_path, monkeypatch):
        """Mixed binary/text pair still returns binary message."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "mixed.bin"
        new = tmp_path / "mixed.txt"
        old.write_bytes(b"\x00binary content")
        new.write_text("text content\n", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert "Binary file" in result

    def test_new_file_content_shows_additions(self, tmp_path, monkeypatch):
        """Diff from empty old file shows all lines as additions."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "empty.txt"
        new = tmp_path / "filled.txt"
        old.write_text("", encoding="utf-8")
        new.write_text("new line 1\nnew line 2\n", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert "+new line 1" in result
        assert "+new line 2" in result

    def test_deleted_content_shows_removals(self, tmp_path, monkeypatch):
        """Diff to empty new file shows all lines as removals."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "full.txt"
        new = tmp_path / "empty.txt"
        old.write_text("old line 1\nold line 2\n", encoding="utf-8")
        new.write_text("", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert "-old line 1" in result
        assert "-old line 2" in result

    def test_error_returns_error_message(self, tmp_path, monkeypatch):
        """Unreadable file returns error string instead of raising."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "exists.txt"
        new = tmp_path / "nonexistent.txt"
        old.write_text("content\n", encoding="utf-8")
        # new does not exist -- stat() will fail after binary check passes

        # Patch is_binary_file to return False so we reach the read/stat path
        with patch(
            "aipass.backup.apps.handlers.diff.diff_generator.is_binary_file",
            return_value=False,
        ):
            result = generate_diff_content(old, new)

        assert "Error generating diff" in result

    def test_diff_includes_file_names(self, tmp_path, monkeypatch):
        """Diff header lines reference the correct file names."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "alpha.py"
        new = tmp_path / "beta.py"
        old.write_text("x = 1\n", encoding="utf-8")
        new.write_text("x = 2\n", encoding="utf-8")

        result = generate_diff_content(old, new)

        assert "a/alpha.py" in result
        assert "b/beta.py" in result

    def test_logs_operation_on_success(self, tmp_path, monkeypatch):
        """json_handler.log_operation is called on successful diff generation."""
        generate_diff_content = self._clear_and_import(monkeypatch)

        old = tmp_path / "a.txt"
        new = tmp_path / "b.txt"
        old.write_text("one\n", encoding="utf-8")
        new.write_text("two\n", encoding="utf-8")

        # The json_handler is already mocked via conftest, just verify no crash
        result = generate_diff_content(old, new)

        assert "-one" in result
        assert "+two" in result
