# =================== AIPass ====================
# Name: test_file_ops.py
# Description: Tests for file_ops handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Comprehensive tests for aipass.spawn.apps.handlers.file_ops module."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.spawn.apps.handlers.file_ops import (
    SKIP_NAMES,
    _replace_path_placeholders,
    _should_skip,
    _walk,
    copy_template,
    ensure_directory,
    regenerate_template_registry,
    rename_placeholder_paths,
)

# ---------------------------------------------------------------------------
# Standard replacements dict used across copy_template tests
# ---------------------------------------------------------------------------

REPLACEMENTS = {
    "BRANCHNAME": "TESTAGENT",
    "branchname": "testagent",
    "BRANCH": "testagent",
    "DATE": "2026-01-01",
    "MODULE": "testagent",
    "CWD": "/tmp/test",
}


# ---------------------------------------------------------------------------
# ensure_directory
# ---------------------------------------------------------------------------


class TestEnsureDirectory:
    """Tests for ensure_directory()."""

    def test_ensure_directory_creates_nested(self, tmp_path: Path) -> None:
        """Verify mkdir -p behaviour: deeply nested path is created."""
        target = tmp_path / "a" / "b" / "c"
        assert not target.exists()

        ensure_directory(target)

        assert target.exists()
        assert target.is_dir()

    def test_ensure_directory_existing_noop(self, tmp_path: Path) -> None:
        """Calling on an existing directory raises no error."""
        target = tmp_path / "already_here"
        target.mkdir()
        assert target.exists()

        # Should not raise
        ensure_directory(target)

        assert target.exists()
        assert target.is_dir()

    def test_ensure_directory_none_raises_valueerror(self) -> None:
        """Passing None raises ValueError with clear message."""
        with pytest.raises(ValueError, match="ensure_directory received None path"):
            ensure_directory(None)


# ---------------------------------------------------------------------------
# copy_template
# ---------------------------------------------------------------------------


class TestCopyTemplate:
    """Tests for copy_template()."""

    def test_copy_template_basic(self, tmp_path: Path, mock_json_handler) -> None:
        """Template file with placeholder is copied with content replaced."""
        template = tmp_path / "template"
        template.mkdir()
        (template / "readme.txt").write_text(
            "Hello {{BRANCHNAME}} created on {{DATE}}",
            encoding="utf-8",
        )

        target = tmp_path / "target"
        target.mkdir()

        copied, _skipped = copy_template(template, target, REPLACEMENTS)

        result = (target / "readme.txt").read_text(encoding="utf-8")
        assert result == "Hello TESTAGENT created on 2026-01-01"
        assert "readme.txt" in copied
        mock_json_handler.assert_called_once()

    def test_copy_template_skips_pycache(self, tmp_path: Path, mock_json_handler) -> None:
        """__pycache__ directories and their contents are skipped."""
        _ = mock_json_handler
        template = tmp_path / "template"
        pycache = template / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "mod.cpython-312.pyc").write_bytes(b"\x00\x01\x02")

        target = tmp_path / "target"
        target.mkdir()

        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert not (target / "__pycache__").exists()
        assert any("__pycache__" in s for s in skipped)

    def test_copy_template_skips_template_registry(self, tmp_path: Path, mock_json_handler) -> None:
        """.template_registry.json is skipped during copy."""
        _ = mock_json_handler
        template = tmp_path / "template"
        template.mkdir()
        (template / ".template_registry.json").write_text("{}", encoding="utf-8")
        (template / "keep.txt").write_text("keep", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()

        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert not (target / ".template_registry.json").exists()
        assert (target / "keep.txt").exists()
        assert any(".template_registry.json" in s for s in skipped)

    def test_copy_template_creates_directories(self, tmp_path: Path, mock_json_handler) -> None:
        """Subdirectories inside the template are created in the target."""
        _ = mock_json_handler
        template = tmp_path / "template"
        sub = template / "apps" / "handlers"
        sub.mkdir(parents=True)
        (sub / "init.py").write_text("# init", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()

        copied, _skipped = copy_template(template, target, REPLACEMENTS)

        assert (target / "apps" / "handlers").is_dir()
        assert (target / "apps" / "handlers" / "init.py").exists()
        # Directory entries recorded
        assert any("apps/" in c and "(dir)" in c for c in copied)

    def test_copy_template_skips_existing_files(self, tmp_path: Path, mock_json_handler) -> None:
        """Existing files in the target directory are not overwritten."""
        _ = mock_json_handler
        template = tmp_path / "template"
        template.mkdir()
        (template / "config.txt").write_text("new content", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        (target / "config.txt").write_text("original", encoding="utf-8")

        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        content = (target / "config.txt").read_text(encoding="utf-8")
        assert content == "original"
        assert any("config.txt" in s and "exists" in s for s in skipped)

    @patch("aipass.spawn.apps.handlers.file_ops.logger")
    def test_copy_template_binary_fallback(self, _mock_logger, tmp_path: Path, mock_json_handler) -> None:
        """Binary files trigger fallback to shutil.copy2."""
        _ = mock_json_handler
        template = tmp_path / "template"
        template.mkdir()
        binary_data = bytes(range(256))
        (template / "image.bin").write_bytes(binary_data)

        target = tmp_path / "target"
        target.mkdir()

        copied, _skipped = copy_template(template, target, REPLACEMENTS)

        result = (target / "image.bin").read_bytes()
        assert result == binary_data
        assert any("image.bin" in c and "binary" in c for c in copied)


# ---------------------------------------------------------------------------
# rename_placeholder_paths
# ---------------------------------------------------------------------------


class TestRenamePlaceholderPaths:
    """Tests for rename_placeholder_paths()."""

    def test_rename_placeholder_paths_dirs(self, tmp_path: Path) -> None:
        """Directories containing {{BRANCH}} in their name are renamed."""
        target = tmp_path / "branch"
        (target / "{{BRANCH}}_json").mkdir(parents=True)

        renamed = rename_placeholder_paths(target, "MyAgent")

        assert (target / "myagent_json").is_dir()
        assert not (target / "{{BRANCH}}_json").exists()
        assert len(renamed) == 1
        assert "myagent_json" in renamed[0]

    def test_rename_placeholder_paths_files(self, tmp_path: Path) -> None:
        """Files containing {{BRANCH}} in their name are renamed."""
        target = tmp_path / "branch"
        target.mkdir(parents=True)
        (target / "{{BRANCH}}_config.json").write_text("{}", encoding="utf-8")

        renamed = rename_placeholder_paths(target, "MyAgent")

        assert (target / "myagent_config.json").exists()
        assert not (target / "{{BRANCH}}_config.json").exists()
        assert len(renamed) == 1

    def test_rename_placeholder_paths_no_overwrite(self, tmp_path: Path) -> None:
        """If the renamed target already exists, the rename is skipped."""
        target = tmp_path / "branch"
        target.mkdir(parents=True)

        # Pre-create the destination
        (target / "myagent_data").mkdir()
        # Create the placeholder source
        (target / "{{BRANCH}}_data").mkdir()

        renamed = rename_placeholder_paths(target, "MyAgent")

        # Both dirs still exist since rename was skipped
        assert (target / "myagent_data").is_dir()
        assert (target / "{{BRANCH}}_data").is_dir()
        assert len(renamed) == 0


# ---------------------------------------------------------------------------
# _walk
# ---------------------------------------------------------------------------


class TestWalk:
    """Tests for _walk()."""

    def test_walk_yields_all_items(self, tmp_path: Path) -> None:
        """_walk yields files and dirs, but skips recursing into .git."""
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "b.txt").write_text("b", encoding="utf-8")

        # .git dir should not be recursed into
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

        items = list(_walk(tmp_path))
        names = [item.name for item in items]

        assert "a.txt" in names
        assert "subdir" in names
        assert "b.txt" in names
        # .git itself is yielded but not recursed into
        assert ".git" in names
        # HEAD inside .git should NOT appear
        assert "HEAD" not in names


# ---------------------------------------------------------------------------
# _should_skip
# ---------------------------------------------------------------------------


class TestShouldSkip:
    """Tests for _should_skip()."""

    def test_should_skip_pycache(self) -> None:
        """__pycache__ in any path component triggers skip."""
        assert _should_skip(Path("__pycache__"))
        assert _should_skip(Path("some" / Path("__pycache__") / Path("mod.pyc")))

    def test_should_skip_normal_file(self) -> None:
        """Normal paths are not skipped."""
        assert not _should_skip(Path("apps/handlers/file_ops.py"))
        assert not _should_skip(Path("README.md"))

    def test_should_skip_all_skip_names(self) -> None:
        """Every entry in SKIP_NAMES triggers a skip."""
        for name in SKIP_NAMES:
            assert _should_skip(Path(name)), f"{name} should be skipped"


# ---------------------------------------------------------------------------
# _replace_path_placeholders
# ---------------------------------------------------------------------------


class TestReplacePathPlaceholders:
    """Tests for _replace_path_placeholders()."""

    def test_replace_path_placeholders(self) -> None:
        """Placeholder tokens in path components are replaced."""
        rel = Path("{{BRANCH}}_json") / "{{BRANCHNAME}}_config.py"
        result = _replace_path_placeholders(rel, REPLACEMENTS)

        assert result == Path("testagent_json") / "TESTAGENT_config.py"

    def test_replace_path_placeholders_no_match(self) -> None:
        """Paths without placeholders pass through unchanged."""
        rel = Path("apps") / "handlers" / "init.py"
        result = _replace_path_placeholders(rel, REPLACEMENTS)

        assert result == rel

    def test_replace_path_placeholders_empty(self) -> None:
        """Single-component path with no parts returns original."""
        rel = Path("file.txt")
        result = _replace_path_placeholders(rel, {})

        assert result == Path("file.txt")


# ---------------------------------------------------------------------------
# regenerate_template_registry
# ---------------------------------------------------------------------------


class TestRegenerateTemplateRegistry:
    """Tests for regenerate_template_registry()."""

    @patch("aipass.spawn.apps.handlers.file_ops.logger")
    def test_regenerate_template_registry_creates_json(self, mock_logger, tmp_path: Path) -> None:
        """Running regeneration creates .spawn/.template_registry.json."""
        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()
        (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")

        regenerate_template_registry(tmp_path)

        registry_file = spawn_dir / ".template_registry.json"
        assert registry_file.exists()

        data = json.loads(registry_file.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "files" in data
        assert "directories" in data
        assert data["metadata"]["generated"] is True

    @patch("aipass.spawn.apps.handlers.file_ops.logger")
    def test_regenerate_template_registry_hashes_content(self, mock_logger, tmp_path: Path) -> None:
        """SHA-256 hashes in the registry match actual file content."""
        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()

        content = "test content for hashing"
        (tmp_path / "hashme.txt").write_text(content, encoding="utf-8")

        regenerate_template_registry(tmp_path)

        registry_file = spawn_dir / ".template_registry.json"
        data = json.loads(registry_file.read_text(encoding="utf-8"))

        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

        # Find the file entry
        files = data["files"]
        assert len(files) == 1
        entry = list(files.values())[0]
        assert entry["path"] == "hashme.txt"
        assert entry["content_hash"] == expected_hash

    @patch("aipass.spawn.apps.handlers.file_ops.logger")
    def test_regenerate_template_registry_detects_placeholders(self, mock_logger, tmp_path: Path) -> None:
        """Files containing {{BRANCH}} are flagged with has_branch_placeholder."""
        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()

        (tmp_path / "with_placeholder.txt").write_text("Name: {{BRANCH}}", encoding="utf-8")
        (tmp_path / "no_placeholder.txt").write_text("Just plain text", encoding="utf-8")

        regenerate_template_registry(tmp_path)

        registry_file = spawn_dir / ".template_registry.json"
        data = json.loads(registry_file.read_text(encoding="utf-8"))

        files_by_name = {v["name"]: v for v in data["files"].values()}

        assert files_by_name["with_placeholder.txt"]["has_branch_placeholder"] is True
        assert files_by_name["no_placeholder.txt"]["has_branch_placeholder"] is False

    @patch("aipass.spawn.apps.handlers.file_ops.logger")
    def test_regenerate_template_registry_skips_spawn_dir(self, mock_logger, tmp_path: Path) -> None:
        """.spawn/ internal files are excluded from the registry."""
        spawn_dir = tmp_path / ".spawn"
        spawn_dir.mkdir()
        (spawn_dir / "internal.json").write_text("{}", encoding="utf-8")

        (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")

        regenerate_template_registry(tmp_path)

        registry_file = spawn_dir / ".template_registry.json"
        data = json.loads(registry_file.read_text(encoding="utf-8"))

        all_paths = [v["path"] for v in data["files"].values()]
        assert "visible.txt" in all_paths
        # No .spawn/ files should appear
        assert not any(".spawn" in p for p in all_paths)

    def test_regenerate_template_registry_no_spawn_dir_noop(self, tmp_path: Path) -> None:
        """If .spawn/ directory does not exist, function returns early."""
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        # Should not raise and should not create anything
        regenerate_template_registry(tmp_path)

        assert not (tmp_path / ".spawn").exists()
