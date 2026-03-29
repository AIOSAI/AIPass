# =================== META ====================
# Name: test_handlers.py
# Description: Tests for spawn update handler modules
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""Tests for spawn handler modules: meta_ops, reconcile, change_detection, json_ops."""

import json
import pytest
from pathlib import Path


# =============================================================================
# meta_ops tests
# =============================================================================

class TestComputeFileHash:
    """Tests for compute_file_hash()."""

    def test_returns_12_char_hex_string(self, tmp_path):
        """Hash result should be exactly 12 hex characters."""
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")

        result = compute_file_hash(test_file)

        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_content_same_hash(self, tmp_path):
        """Same content should produce same hash."""
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("identical content", encoding="utf-8")
        file_b.write_text("identical content", encoding="utf-8")

        assert compute_file_hash(file_a) == compute_file_hash(file_b)

    def test_different_content_different_hash(self, tmp_path):
        """Different content should produce different hashes."""
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("content A", encoding="utf-8")
        file_b.write_text("content B", encoding="utf-8")

        assert compute_file_hash(file_a) != compute_file_hash(file_b)

    def test_nonexistent_file_returns_empty(self, tmp_path):
        """Non-existent file should return empty string."""
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        result = compute_file_hash(tmp_path / "nonexistent.txt")
        assert result == ""

    def test_directory_returns_empty(self, tmp_path):
        """Directory (not file) should return empty string."""
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        result = compute_file_hash(tmp_path)
        assert result == ""


class TestGenerateBranchMeta:
    """Tests for generate_branch_meta()."""

    def test_produces_valid_structure(self, tmp_path):
        """Generated meta should have metadata, file_tracking, directory_tracking."""
        from aipass.spawn.apps.handlers.meta_ops import generate_branch_meta

        # Create a mock branch directory with some files
        branch_dir = tmp_path / "test_branch"
        branch_dir.mkdir()
        (branch_dir / "README.md").write_text("# Test", encoding="utf-8")
        apps_dir = branch_dir / "apps"
        apps_dir.mkdir()
        (apps_dir / "__init__.py").write_text("", encoding="utf-8")

        # Template registry that matches some of these files
        template_registry = {
            "metadata": {"version": "1.0.0"},
            "files": {
                "f001": {
                    "current_name": "README.md",
                    "path": "README.md",
                    "content_hash": "aabbccddee11",
                },
                "f002": {
                    "current_name": "__init__.py",
                    "path": "apps/__init__.py",
                    "content_hash": "e3b0c44298fc",
                },
            },
            "directories": {
                "d001": {
                    "current_name": "apps",
                    "path": "apps",
                },
            },
        }

        result = generate_branch_meta(branch_dir, template_registry)

        # Check top-level structure
        assert "metadata" in result
        assert "file_tracking" in result
        assert "directory_tracking" in result

        # Check metadata fields
        assert result["metadata"]["version"] == "1.0.0"
        assert result["metadata"]["template_version"] == "1.0.0"
        assert result["metadata"]["branch_name"] == "test_branch"
        assert "last_updated" in result["metadata"]

    def test_matches_files_by_path(self, tmp_path):
        """Files matching template paths should be tracked with correct IDs."""
        from aipass.spawn.apps.handlers.meta_ops import generate_branch_meta

        branch_dir = tmp_path / "my_branch"
        branch_dir.mkdir()
        (branch_dir / "README.md").write_text("# Hello", encoding="utf-8")

        template_registry = {
            "metadata": {"version": "1.0.0"},
            "files": {
                "f021": {
                    "current_name": "README.md",
                    "path": "README.md",
                    "content_hash": "aabbccddee11",
                },
            },
            "directories": {},
        }

        result = generate_branch_meta(branch_dir, template_registry)

        assert "f021" in result["file_tracking"]
        assert result["file_tracking"]["f021"]["current_name"] == "README.md"
        assert result["file_tracking"]["f021"]["current_path"] == "README.md"
        assert len(result["file_tracking"]["f021"]["content_hash"]) == 12

    def test_matches_directories(self, tmp_path):
        """Directories matching template paths should be tracked."""
        from aipass.spawn.apps.handlers.meta_ops import generate_branch_meta

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()
        (branch_dir / "apps").mkdir()
        (branch_dir / "tests").mkdir()

        template_registry = {
            "metadata": {"version": "1.0.0"},
            "files": {},
            "directories": {
                "d001": {"current_name": "apps", "path": "apps"},
                "d002": {"current_name": "tests", "path": "tests"},
            },
        }

        result = generate_branch_meta(branch_dir, template_registry)

        assert "d001" in result["directory_tracking"]
        assert "d002" in result["directory_tracking"]
        assert result["directory_tracking"]["d001"]["current_path"] == "apps"


class TestLoadSaveBranchMeta:
    """Tests for load_branch_meta() and save_branch_meta()."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """Saved metadata should load back identically."""
        from aipass.spawn.apps.handlers.meta_ops import load_branch_meta, save_branch_meta

        meta = {
            "metadata": {"version": "1.0.0", "branch_name": "test"},
            "file_tracking": {"f001": {"current_name": "a.txt", "content_hash": "abc123def456"}},
            "directory_tracking": {},
        }

        assert save_branch_meta(tmp_path, meta) is True

        loaded = load_branch_meta(tmp_path)
        assert loaded is not None
        assert loaded["metadata"]["branch_name"] == "test"
        assert loaded["file_tracking"]["f001"]["content_hash"] == "abc123def456"

    def test_load_missing_returns_none(self, tmp_path):
        """Loading from directory without .branch_meta.json should return None."""
        from aipass.spawn.apps.handlers.meta_ops import load_branch_meta

        result = load_branch_meta(tmp_path)
        assert result is None


class TestGetTemplateDir:
    """Tests for get_template_dir()."""

    def test_returns_path(self):
        """Should return a Path object pointing to builder template."""
        from aipass.spawn.apps.handlers.meta_ops import get_template_dir

        result = get_template_dir()
        assert isinstance(result, Path)
        assert result.name == "builder"


# =============================================================================
# deep_merge tests
# =============================================================================

class TestDeepMerge:
    """Tests for deep_merge()."""

    def test_preserves_existing_values(self):
        """Existing scalar values should be kept over template defaults."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"name": "default", "status": "new"}
        existing = {"name": "my_custom_name", "status": "active"}

        result = deep_merge(template, existing)

        assert result["name"] == "my_custom_name"
        assert result["status"] == "active"

    def test_adds_template_keys(self):
        """Keys in template but not in existing should be added."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"name": "", "version": "1.0.0", "new_field": "default_val"}
        existing = {"name": "mine"}

        result = deep_merge(template, existing)

        assert result["name"] == "mine"
        assert result["version"] == "1.0.0"
        assert result["new_field"] == "default_val"

    def test_keeps_extra_existing_keys(self):
        """Keys in existing but not in template should be preserved."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"name": ""}
        existing = {"name": "mine", "custom_key": "custom_value"}

        result = deep_merge(template, existing)

        assert result["name"] == "mine"
        assert result["custom_key"] == "custom_value"

    def test_nested_dict_merge(self):
        """Nested dicts should be merged recursively."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"metadata": {"version": "2.0", "new_key": "new_default"}}
        existing = {"metadata": {"version": "1.0", "user_key": "user_val"}}

        result = deep_merge(template, existing)

        assert result["metadata"]["version"] == "1.0"  # preserved
        assert result["metadata"]["new_key"] == "new_default"  # added
        assert result["metadata"]["user_key"] == "user_val"  # kept

    def test_lists_keep_existing(self):
        """Non-empty existing lists should be preserved."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"items": ["a", "b"]}
        existing = {"items": ["x", "y", "z"]}

        result = deep_merge(template, existing)

        assert result["items"] == ["x", "y", "z"]

    def test_empty_existing_list_uses_template(self):
        """Empty existing list should use template list if non-empty."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"items": ["default_item"]}
        existing = {"items": []}

        result = deep_merge(template, existing)

        assert result["items"] == ["default_item"]

    def test_none_existing_uses_template(self):
        """None existing should return template data."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"key": "value"}
        result = deep_merge(template, None)

        assert result == {"key": "value"}

    def test_empty_string_existing_uses_template(self):
        """Empty string existing with non-empty template should use template."""
        from aipass.spawn.apps.handlers.json_ops import deep_merge

        template = {"name": "template_default"}
        existing = {"name": ""}

        result = deep_merge(template, existing)

        assert result["name"] == "template_default"


# =============================================================================
# detect_changes tests
# =============================================================================

class TestDetectChanges:
    """Tests for detect_changes()."""

    def test_detects_additions(self, tmp_path):
        """Files in template but not in branch should be additions."""
        from aipass.spawn.apps.handlers.change_detection import detect_changes

        template_registry = {
            "files": {
                "f001": {"current_name": "old.txt", "path": "old.txt", "content_hash": "aaa111"},
                "f002": {"current_name": "new.txt", "path": "new.txt", "content_hash": "bbb222"},
            },
            "directories": {},
        }

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "old.txt",
                    "current_name": "old.txt",
                    "current_path": "old.txt",
                    "content_hash": "aaa111",
                },
            },
            "directory_tracking": {},
        }

        result = detect_changes(template_registry, branch_meta, tmp_path)

        assert len(result["additions"]) == 1
        assert result["additions"][0]["file_id"] == "f002"
        assert result["additions"][0]["template_path"] == "new.txt"

    def test_detects_pruned(self, tmp_path):
        """Files in branch but not in template should be pruned."""
        from aipass.spawn.apps.handlers.change_detection import detect_changes

        template_registry = {
            "files": {
                "f001": {"current_name": "kept.txt", "path": "kept.txt", "content_hash": "aaa"},
            },
            "directories": {},
        }

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "kept.txt",
                    "current_name": "kept.txt",
                    "current_path": "kept.txt",
                    "content_hash": "aaa",
                },
                "f099": {
                    "template_name": "removed.txt",
                    "current_name": "removed.txt",
                    "current_path": "removed.txt",
                    "content_hash": "zzz",
                },
            },
            "directory_tracking": {},
        }

        result = detect_changes(template_registry, branch_meta, tmp_path)

        assert len(result["pruned"]) == 1
        assert result["pruned"][0]["file_id"] == "f099"

    def test_detects_updates(self, tmp_path):
        """Files with same ID but different hashes should be updates."""
        from aipass.spawn.apps.handlers.change_detection import detect_changes

        template_registry = {
            "files": {
                "f001": {"current_name": "config.json", "path": "config.json", "content_hash": "newhash12345"},
            },
            "directories": {},
        }

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "config.json",
                    "current_name": "config.json",
                    "current_path": "config.json",
                    "content_hash": "oldhash67890",
                },
            },
            "directory_tracking": {},
        }

        result = detect_changes(template_registry, branch_meta, tmp_path)

        assert len(result["updates"]) == 1
        assert result["updates"][0]["file_id"] == "f001"
        assert result["updates"][0]["template_hash"] == "newhash12345"
        assert result["updates"][0]["branch_hash"] == "oldhash67890"

    def test_detects_renames(self, tmp_path):
        """Files with same ID but different template paths should be renames."""
        from aipass.spawn.apps.handlers.change_detection import detect_changes

        template_registry = {
            "files": {
                "f001": {
                    "current_name": "new_name.txt",
                    "path": "docs/new_name.txt",
                    "content_hash": "samehash1234",
                },
            },
            "directories": {},
        }

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "docs/old_name.txt",
                    "current_name": "old_name.txt",
                    "current_path": "docs/old_name.txt",
                    "content_hash": "samehash1234",
                },
            },
            "directory_tracking": {},
        }

        result = detect_changes(template_registry, branch_meta, tmp_path)

        assert len(result["renames"]) == 1
        assert result["renames"][0]["file_id"] == "f001"
        assert result["renames"][0]["old_name"] == "docs/old_name.txt"
        assert result["renames"][0]["new_name"] == "docs/new_name.txt"

    def test_no_changes(self, tmp_path):
        """Identical template and branch should produce no changes."""
        from aipass.spawn.apps.handlers.change_detection import detect_changes

        template_registry = {
            "files": {
                "f001": {"current_name": "a.txt", "path": "a.txt", "content_hash": "abc123"},
            },
            "directories": {
                "d001": {"current_name": "apps", "path": "apps"},
            },
        }

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "a.txt",
                    "current_name": "a.txt",
                    "current_path": "a.txt",
                    "content_hash": "abc123",
                },
            },
            "directory_tracking": {
                "d001": {
                    "template_name": "apps",
                    "current_name": "apps",
                    "current_path": "apps",
                },
            },
        }

        result = detect_changes(template_registry, branch_meta, tmp_path)

        assert result["additions"] == []
        assert result["updates"] == []
        assert result["renames"] == []
        assert result["pruned"] == []


# =============================================================================
# reconcile_branch_state tests
# =============================================================================

class TestReconcileBranchState:
    """Tests for reconcile_branch_state()."""

    def test_detects_missing_files(self, tmp_path):
        """Files tracked in meta but not on disk should be reported as missing."""
        from aipass.spawn.apps.handlers.reconcile import reconcile_branch_state

        # Branch with no actual files
        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "README.md",
                    "current_name": "README.md",
                    "current_path": "README.md",
                    "content_hash": "abc123def456",
                },
            },
            "directory_tracking": {},
        }

        result = reconcile_branch_state(branch_dir, branch_meta)

        assert result["needs_update"] is True
        assert len(result["missing_files"]) == 1
        assert result["missing_files"][0]["file_id"] == "f001"
        assert result["missing_files"][0]["path"] == "README.md"

    def test_detects_hash_mismatches(self, tmp_path):
        """Files with changed content should be reported as hash mismatches."""
        from aipass.spawn.apps.handlers.reconcile import reconcile_branch_state
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        # Create file with known content
        readme = branch_dir / "README.md"
        readme.write_text("modified content", encoding="utf-8")
        actual_hash = compute_file_hash(readme)

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "README.md",
                    "current_name": "README.md",
                    "current_path": "README.md",
                    "content_hash": "differenthash",  # stale hash
                },
            },
            "directory_tracking": {},
        }

        result = reconcile_branch_state(branch_dir, branch_meta)

        assert result["needs_update"] is True
        assert len(result["hash_mismatches"]) == 1
        assert result["hash_mismatches"][0]["file_id"] == "f001"
        assert result["hash_mismatches"][0]["current_hash"] == actual_hash

    def test_clean_state_no_update_needed(self, tmp_path):
        """Consistent state should report needs_update=False."""
        from aipass.spawn.apps.handlers.reconcile import reconcile_branch_state
        from aipass.spawn.apps.handlers.meta_ops import compute_file_hash

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        readme = branch_dir / "README.md"
        readme.write_text("stable content", encoding="utf-8")
        actual_hash = compute_file_hash(readme)

        branch_meta = {
            "file_tracking": {
                "f001": {
                    "template_name": "README.md",
                    "current_name": "README.md",
                    "current_path": "README.md",
                    "content_hash": actual_hash,
                },
            },
            "directory_tracking": {},
        }

        result = reconcile_branch_state(branch_dir, branch_meta)

        assert result["needs_update"] is False
        assert result["missing_files"] == []
        assert result["hash_mismatches"] == []

    def test_detects_missing_directories(self, tmp_path):
        """Tracked directories missing from disk should be reported."""
        from aipass.spawn.apps.handlers.reconcile import reconcile_branch_state

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        branch_meta = {
            "file_tracking": {},
            "directory_tracking": {
                "d001": {
                    "template_name": "apps",
                    "current_name": "apps",
                    "current_path": "apps",
                },
            },
        }

        result = reconcile_branch_state(branch_dir, branch_meta)

        assert result["needs_update"] is True
        assert len(result["missing_dirs"]) == 1
        assert result["missing_dirs"][0]["dir_id"] == "d001"


# =============================================================================
# backup_json tests
# =============================================================================

class TestBackupJson:
    """Tests for backup_json()."""

    def test_creates_backup_file(self, tmp_path):
        """Backup should create a copy in .recovery/ directory."""
        from aipass.spawn.apps.handlers.json_ops import backup_json

        source = tmp_path / "data.json"
        source.write_text('{"key": "value"}', encoding="utf-8")

        backup_path = backup_json(source)

        assert backup_path.exists()
        assert ".recovery" in str(backup_path)
        assert "data.json" in backup_path.name
        assert ".backup" in backup_path.name

        # Content should match
        assert backup_path.read_text(encoding="utf-8") == '{"key": "value"}'

    def test_raises_on_missing_source(self, tmp_path):
        """Should raise FileNotFoundError for non-existent source."""
        from aipass.spawn.apps.handlers.json_ops import backup_json

        with pytest.raises(FileNotFoundError):
            backup_json(tmp_path / "nonexistent.json")
