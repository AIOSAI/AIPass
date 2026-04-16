# =================== AIPass ====================
# Name: test_regenerate_registry_ops.py
# Description: Tests for regenerate_registry_ops handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for regenerate_registry_ops: template registry regeneration, ID preservation, scanning."""

import json
from pathlib import Path
from unittest.mock import patch

from aipass.spawn.apps.handlers.regenerate_registry_ops import (
    regenerate_template_registry,
    _scan_template_directory,
    _next_id,
)


# =============================================================================
# Helpers
# =============================================================================


def _make_template(tmp_path: Path, files: dict[str, str] | None = None, dirs: list[str] | None = None) -> Path:
    """Create a minimal template directory with given files and sub-directories.

    Args:
        tmp_path: Pytest tmp_path root.
        files: Mapping of relative path -> file content.
        dirs: List of relative directory paths to create (empty dirs).

    Returns:
        Path to the template directory.
    """
    tpl = tmp_path / "my_template"
    tpl.mkdir(parents=True, exist_ok=True)

    for rel, content in (files or {}).items():
        fp = tpl / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")

    for d in dirs or []:
        (tpl / d).mkdir(parents=True, exist_ok=True)

    return tpl


def _hash_for(_content: str) -> str:
    """Return a deterministic fake 12-char hex hash for the given content key."""
    import hashlib

    return hashlib.sha256(_content.encode()).hexdigest()[:12]


# =============================================================================
# regenerate_template_registry — fresh generation
# =============================================================================


class TestRegenerateFreshTemplate:
    """Test 1 — create template dir with files+dirs, no existing registry."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_fresh_template(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "aabbccdd1122"

        tpl = _make_template(
            tmp_path,
            files={"main.py": "print('hi')", "apps/utils.py": "# util"},
            dirs=["apps", "apps/handlers"],
        )

        result = regenerate_template_registry(tpl)

        assert "files" in result
        assert "directories" in result
        assert "stats" in result
        assert "metadata" in result

        # Verify the registry JSON was written to disk
        registry_path = tpl / ".spawn" / ".template_registry.json"
        assert registry_path.exists()

        persisted = json.loads(registry_path.read_text(encoding="utf-8"))
        assert "files" in persisted
        assert "directories" in persisted
        assert "metadata" in persisted


# =============================================================================
# ID preservation — hash match
# =============================================================================


class TestPreservesIdsByHash:
    """Test 2 — existing registry with hash->ID, same content at different path."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_preserves_ids_by_hash(self, mock_hash, mock_load, tmp_path):
        # Existing registry: f001 lives at "old/main.py" with hash "aabbccdd1122"
        mock_load.return_value = {
            "files": {
                "f001": {
                    "path": "old/main.py",
                    "name": "main.py",
                    "content_hash": "aabbccdd1122",
                },
            },
            "directories": {},
        }
        # New file produces the same hash but at a different path
        mock_hash.return_value = "aabbccdd1122"

        tpl = _make_template(tmp_path, files={"new_location/main.py": "print('hi')"})

        result = regenerate_template_registry(tpl)

        # The existing ID f001 should be preserved via hash match
        assert "f001" in result["files"]
        assert result["files"]["f001"]["path"] == "new_location/main.py"


# =============================================================================
# ID preservation — path match
# =============================================================================


class TestPreservesIdsByPath:
    """Test 3 — same path, different content -> ID preserved via path match."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_preserves_ids_by_path(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f005": {
                    "path": "config.yaml",
                    "name": "config.yaml",
                    "content_hash": "oldoldhash12",
                },
            },
            "directories": {},
        }
        # New content -> different hash, but same path
        mock_hash.return_value = "newnewnew123"

        tpl = _make_template(tmp_path, files={"config.yaml": "new content here"})

        result = regenerate_template_registry(tpl)

        assert "f005" in result["files"]
        assert result["files"]["f005"]["content_hash"] == "newnewnew123"


# =============================================================================
# New ID assignment
# =============================================================================


class TestAssignsNewIds:
    """Test 4 — file matching neither hash nor path gets a new sequential ID."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_assigns_new_ids(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f001": {
                    "path": "existing.py",
                    "name": "existing.py",
                    "content_hash": "existhash123",
                },
            },
            "directories": {},
        }
        # Completely new file — different hash and different path
        mock_hash.return_value = "brandnew1234"

        tpl = _make_template(tmp_path, files={"totally_new.py": "new stuff"})

        result = regenerate_template_registry(tpl)

        # f001 is already in the existing registry (not matched), so the new
        # file should get f001 since f001 was not claimed by hash or path match
        # Actually f001 won't be claimed because the existing file is gone.
        # The new file gets f001 as first available.
        file_ids = list(result["files"].keys())
        assert len(file_ids) == 1
        assert file_ids[0] == "f001"


# =============================================================================
# Skip __pycache__
# =============================================================================


class TestSkipsPycache:
    """Test 5 — __pycache__ directory and its contents should be excluded."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_skips_pycache(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "abc123def456"

        tpl = _make_template(
            tmp_path,
            files={
                "main.py": "print(1)",
                "__pycache__/main.cpython-312.pyc": "bytecode",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert not any("__pycache__" in p for p in all_paths)

        all_dir_paths = [d["path"] for d in result["directories"].values()]
        assert not any("__pycache__" in p for p in all_dir_paths)


# =============================================================================
# Skip spawn tracking files
# =============================================================================


class TestSkipsSpawnTrackingFiles:
    """Test 6 — .template_registry.json and .branch_meta.json inside .spawn/ are skipped."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_skips_spawn_tracking_files(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "aabb11223344"

        tpl = _make_template(
            tmp_path,
            files={
                "main.py": "print(1)",
                ".spawn/.template_registry.json": "{}",
                ".spawn/.branch_meta.json": "{}",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert ".spawn/.template_registry.json" not in all_paths
        assert ".spawn/.branch_meta.json" not in all_paths


# =============================================================================
# Allow .spawn/README.md
# =============================================================================


class TestAllowsSpawnReadme:
    """Test 7 — .spawn/README.md is NOT a tracking file and should be included."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_allows_spawn_readme(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "readmehash12"

        tpl = _make_template(
            tmp_path,
            files={
                ".spawn/README.md": "# Spawn docs",
            },
        )

        result = regenerate_template_registry(tpl)

        all_paths = [f["path"] for f in result["files"].values()]
        assert ".spawn/README.md" in all_paths


# =============================================================================
# Non-existent directory
# =============================================================================


class TestNonexistentDir:
    """Test 8 — pass nonexistent path, verify returns error dict."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    def test_regenerate_nonexistent_dir(self, mock_load, tmp_path):
        bogus = tmp_path / "does_not_exist"

        result = regenerate_template_registry(bogus)

        assert "error" in result
        mock_load.assert_not_called()


# =============================================================================
# Placeholder filename detection
# =============================================================================


class TestDetectsPlaceholderFilenames:
    """Test 9 — file named {{BRANCH}}.py should have has_branch_placeholder=True."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_detects_placeholder_filenames(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = None
        mock_hash.return_value = "placeholder12"

        tpl = _make_template(
            tmp_path,
            files={
                "{{BRANCH}}.py": "# branch-specific file",
                "normal.py": "# regular file",
            },
        )

        result = regenerate_template_registry(tpl)

        # Find the placeholder file
        placeholder_entry = None
        normal_entry = None
        for entry in result["files"].values():
            if "{{BRANCH}}" in entry["path"]:
                placeholder_entry = entry
            elif entry["path"] == "normal.py":
                normal_entry = entry

        assert placeholder_entry is not None
        assert placeholder_entry["has_branch_placeholder"] is True

        assert normal_entry is not None
        assert normal_entry["has_branch_placeholder"] is False


# =============================================================================
# Directory ID preservation by path
# =============================================================================


class TestDirectoryIdPreservation:
    """Test 10 — existing dir IDs preserved by path match."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_directory_id_preservation(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {},
            "directories": {
                "d010": {
                    "path": "apps/handlers",
                    "name": "handlers",
                    "has_branch_placeholder": False,
                },
            },
        }
        mock_hash.return_value = "filehash1234"

        tpl = _make_template(
            tmp_path,
            files={"apps/handlers/main.py": "code"},
            dirs=["apps", "apps/handlers"],
        )

        result = regenerate_template_registry(tpl)

        # d010 should be preserved for "apps/handlers" via path match
        assert "d010" in result["directories"]
        assert result["directories"]["d010"]["path"] == "apps/handlers"


# =============================================================================
# Directory name fallback
# =============================================================================


class TestDirectoryNameFallback:
    """Test 11 — dir ID preserved by name when path changes."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_directory_name_fallback(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {},
            "directories": {
                "d007": {
                    "path": "old_location/utils",
                    "name": "utils",
                    "has_branch_placeholder": False,
                },
            },
        }
        mock_hash.return_value = "filehash1234"

        # "utils" now at a different path — should still match by name
        tpl = _make_template(
            tmp_path,
            files={"new_location/utils/helper.py": "code"},
            dirs=["new_location", "new_location/utils"],
        )

        result = regenerate_template_registry(tpl)

        assert "d007" in result["directories"]
        assert result["directories"]["d007"]["name"] == "utils"


# =============================================================================
# Stats accuracy
# =============================================================================


class TestStatsAccuracy:
    """Test 12 — verify stats dict has correct file/dir counts and template_name."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_stats_accuracy(self, mock_hash, mock_load, tmp_path):
        mock_load.return_value = {
            "files": {
                "f001": {"path": "old.py", "name": "old.py", "content_hash": "oldhash12345"},
                "f002": {"path": "old2.py", "name": "old2.py", "content_hash": "oldhash22222"},
            },
            "directories": {
                "d001": {"path": "olddir", "name": "olddir"},
            },
        }
        mock_hash.return_value = "newhash12345"

        tpl = _make_template(
            tmp_path,
            files={
                "a.py": "aaa",
                "b.py": "bbb",
                "c.py": "ccc",
            },
            dirs=["subdir1", "subdir2"],
        )

        result = regenerate_template_registry(tpl)
        stats = result["stats"]

        assert stats["files_tracked"] == 3
        assert stats["directories_tracked"] == 2
        assert stats["previous_files"] == 2
        assert stats["previous_directories"] == 1
        assert stats["template_name"] == "my_template"


# =============================================================================
# Hash length compatibility (16-char -> 12-char)
# =============================================================================


class TestHashLengthCompat:
    """Test 13 — existing 16-char hashes match against new 12-char hashes by prefix."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.load_template_registry")
    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_regenerate_hash_length_compat(self, mock_hash, mock_load, tmp_path):
        # Existing registry has a 16-char hash
        mock_load.return_value = {
            "files": {
                "f042": {
                    "path": "legacy.py",
                    "name": "legacy.py",
                    "content_hash": "aabbccdd11223344",  # 16 chars
                },
            },
            "directories": {},
        }
        # New hash is the 12-char prefix of the old one
        mock_hash.return_value = "aabbccdd1122"  # 12 chars

        tpl = _make_template(tmp_path, files={"moved/legacy.py": "content"})

        result = regenerate_template_registry(tpl)

        # ID should be preserved because the 12-char prefix is indexed
        assert "f042" in result["files"]
        assert result["files"]["f042"]["path"] == "moved/legacy.py"


# =============================================================================
# _next_id tests
# =============================================================================


class TestNextId:
    """Tests 14-16 — _next_id function."""

    def test_next_id_basic(self):
        """Test 14 — empty claimed set returns prefix + 001."""
        assert _next_id("f", set()) == "f001"

    def test_next_id_skips_claimed(self):
        """Test 15 — skips past consecutively claimed IDs."""
        assert _next_id("f", {"f001", "f002"}) == "f003"

    def test_next_id_fills_gaps(self):
        """Test 16 — fills gaps in the sequence."""
        assert _next_id("f", {"f001", "f003"}) == "f002"

    def test_next_id_directory_prefix(self):
        """Bonus — works with 'd' prefix for directories."""
        assert _next_id("d", set()) == "d001"
        assert _next_id("d", {"d001"}) == "d002"


# =============================================================================
# Scan ordering consistency
# =============================================================================


class TestScanTemplateDirectoryOrdering:
    """Test 17 — files and dirs come from sorted rglob, verify consistent output."""

    @patch("aipass.spawn.apps.handlers.regenerate_registry_ops.compute_file_hash")
    def test_scan_template_directory_ordering(self, mock_hash, tmp_path):
        # Return different hashes per file so we can verify ordering
        call_count = 0

        def _sequential_hash(_path):
            nonlocal call_count
            call_count += 1
            return f"{call_count:012d}"

        mock_hash.side_effect = _sequential_hash

        tpl = _make_template(
            tmp_path,
            files={
                "z_last.py": "z",
                "a_first.py": "a",
                "m_middle.py": "m",
            },
            dirs=["z_dir", "a_dir"],
        )

        files, directories = _scan_template_directory(tpl, None)

        # Files should have been scanned in sorted order (a_, m_, z_)
        file_paths = [entry["path"] for entry in files.values()]
        assert file_paths == sorted(file_paths)

        # Directories should also be in sorted order
        dir_paths = [entry["path"] for entry in directories.values()]
        assert dir_paths == sorted(dir_paths)
