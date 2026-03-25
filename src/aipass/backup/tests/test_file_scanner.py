"""Tests for file_scanner module - directory scanning and filtering."""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestScanFiles:
    """Tests for scan_files function."""

    def test_scan_files_finds_all_files(self, tmp_path):
        """Returns all files in a simple directory with no ignore rules."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()
        (source / "a.txt").write_text("aaa", encoding="utf-8")
        (source / "b.py").write_text("bbb", encoding="utf-8")
        sub = source / "sub"
        sub.mkdir()
        (sub / "c.md").write_text("ccc", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(source, should_ignore=lambda p: False)

        found_names = {f.name for f in files}
        assert found_names == {"a.txt", "b.py", "c.md"}

    def test_scan_files_applies_ignore(self, tmp_path):
        """should_ignore callback filters out matching files and directories."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()
        (source / "keep.txt").write_text("keep", encoding="utf-8")
        (source / "ignored.log").write_text("skip", encoding="utf-8")
        ignored_dir = source / "ignored_dir"
        ignored_dir.mkdir()
        (ignored_dir / "deep.txt").write_text("deep", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: "ignored" in str(p),
            )

        found_names = {f.name for f in files}
        assert "keep.txt" in found_names
        assert "ignored.log" not in found_names
        assert "deep.txt" not in found_names

    def test_scan_files_returns_tuple(self, tmp_path):
        """Return value is a (list, dict) tuple."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()
        (source / "f.txt").write_text("x", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            result = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], dict)

    def test_scan_files_skipped_dict_has_categories(self, tmp_path):
        """Skipped dict has 'directories', 'files', and 'too_large' keys."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()
        (source / "f.txt").write_text("x", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            _, skipped = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert "directories" in skipped
        assert "files" in skipped
        assert "too_large" in skipped

    def test_scan_files_whitelist_filters(self, tmp_path):
        """Only whitelisted top-level directories are scanned."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()

        allowed = source / "allowed"
        allowed.mkdir()
        (allowed / "good.txt").write_text("yes", encoding="utf-8")

        blocked = source / "blocked"
        blocked.mkdir()
        (blocked / "bad.txt").write_text("no", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: False,
                whitelist=["allowed"],
            )

        found_names = {f.name for f in files}
        assert "good.txt" in found_names
        assert "bad.txt" not in found_names
        assert "blocked" in skipped["directories"]

    def test_scan_files_size_cap(self, tmp_path):
        """Files above max_file_size_mb are placed in the too_large set."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()

        small = source / "small.txt"
        small.write_text("tiny", encoding="utf-8")

        big = source / "huge.bin"
        # Write slightly over 1 MB
        big.write_bytes(b"x" * (1024 * 1024 + 100))

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: False,
                max_file_size_mb=1,
            )

        found_names = {f.name for f in files}
        assert "small.txt" in found_names
        assert "huge.bin" not in found_names

        too_large_names = {entry[0] for entry in skipped["too_large"]}
        assert "huge.bin" in too_large_names

    def test_scan_files_empty_dir(self, tmp_path):
        """Returns empty list for an empty directory."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "empty"
        source.mkdir()

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert files == []

    def test_scan_files_exactly_at_size_cap_included(self, tmp_path):
        """File exactly at max_file_size_mb is included (boundary: > not >=)."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "project"
        source.mkdir()

        exact = source / "exact.bin"
        exact.write_bytes(b"x" * (1024 * 1024))  # exactly 1 MB

        with patch.object(file_scanner, "json_handler"):
            files, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: False,
                max_file_size_mb=1,
            )

        found_names = {f.name for f in files}
        assert "exact.bin" in found_names
        too_large_names = {entry[0] for entry in skipped["too_large"]}
        assert "exact.bin" not in too_large_names


# ─── Contract: return type and structure verification ────


class TestScanFilesReturnTypeContract:
    """Verify scan_files return types match documented contract."""

    def test_returns_tuple_of_two(self, tmp_path):
        """Return value is always a tuple with exactly 2 elements."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "p"
        source.mkdir()
        (source / "a.txt").write_text("x", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            result = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert type(result) is tuple
        assert len(result) == 2

    def test_first_element_is_list_of_paths(self, tmp_path):
        """First element is a list where every item is a Path."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "p"
        source.mkdir()
        (source / "a.txt").write_text("x", encoding="utf-8")
        (source / "b.py").write_text("y", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            files, _ = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert isinstance(files, list)
        for f in files:
            assert isinstance(f, Path)

    def test_second_element_is_dict_with_set_values(self, tmp_path):
        """Second element is a dict with set values for each category."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "p"
        source.mkdir()
        (source / "a.txt").write_text("x", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            _, skipped = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert isinstance(skipped, dict)
        for key in ("directories", "files", "too_large"):
            assert key in skipped
            assert isinstance(skipped[key], set)

    def test_empty_dir_returns_empty_list_not_none(self, tmp_path):
        """Empty directory returns [], not None."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "empty"
        source.mkdir()

        with patch.object(file_scanner, "json_handler"):
            files, _ = file_scanner.scan_files(source, should_ignore=lambda p: False)

        assert files is not None
        assert files == []

    def test_skipped_directories_populated_by_ignore(self, tmp_path):
        """Ignored directories appear in skipped['directories'] set."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "p"
        source.mkdir()
        ignored = source / "__pycache__"
        ignored.mkdir()
        (ignored / "cache.pyc").write_text("c", encoding="utf-8")

        with patch.object(file_scanner, "json_handler"):
            _, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: "__pycache__" in str(p),
            )

        assert len(skipped["directories"]) > 0

    def test_too_large_entries_are_tuples(self, tmp_path):
        """Entries in too_large set are (name, size) tuples."""
        from aipass.backup.apps.handlers.operations import file_scanner

        source = tmp_path / "p"
        source.mkdir()
        big = source / "huge.bin"
        big.write_bytes(b"x" * (1024 * 1024 + 100))

        with patch.object(file_scanner, "json_handler"):
            _, skipped = file_scanner.scan_files(
                source,
                should_ignore=lambda p: False,
                max_file_size_mb=1,
            )

        for entry in skipped["too_large"]:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], int)
