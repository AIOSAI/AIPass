# =================== AIPass ====================
# Name: test_file_ops.py
# Description: Tests for file_ops handler
# Version: 1.0.2
# Created: 2026-04-03
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/file_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/file_ops.py parses and imports
# seedgo: no-test-needed(documentation) — docstrings on the file_ops public functions

import hashlib
import json
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.file_ops import (
    SKIP_NAMES,
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
    # {{PATH}} replaced {{CWD}} in DPLAN-0319 and renders RELATIVE, never an
    # absolute /home/... path — the value here mirrors that.
    "PATH": "src/aipass/testagent",
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

    def test_copy_template_binary_fallback(self, tmp_path: Path, mock_json_handler) -> None:
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
    """The template walk, observed through copy_template()."""

    def test_walk_yields_all_items(self, tmp_path: Path, mock_json_handler) -> None:
        """The walk reaches files and nested dirs, but never recurses into .git.

        Mutant: the walk recurses into .git -> red.
        """
        _ = mock_json_handler
        template = tmp_path / "template"
        template.mkdir()
        (template / "a.txt").write_text("a", encoding="utf-8")
        sub = template / "subdir"
        sub.mkdir()
        (sub / "b.txt").write_text("b", encoding="utf-8")

        # .git dir should not be recursed into
        git_dir = template / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert (target / "a.txt").read_text(encoding="utf-8") == "a"
        assert (target / "subdir" / "b.txt").read_text(encoding="utf-8") == "b"
        assert "subdir/ (dir)" in copied
        # .git itself is walked (and skipped) but never recursed into
        assert skipped == [".git"]
        assert not (target / ".git").exists()


# ---------------------------------------------------------------------------
# _should_skip
# ---------------------------------------------------------------------------


class TestShouldSkip:
    """The skip rule, observed through copy_template()."""

    def test_should_skip_pycache(self, tmp_path: Path, mock_json_handler) -> None:
        """__pycache__ in any path component keeps the file out of the copy.

        Mutant: the skip rule never skips -> red.
        """
        _ = mock_json_handler
        template = tmp_path / "template"
        (template / "__pycache__").mkdir(parents=True)
        (template / "some" / "__pycache__").mkdir(parents=True)
        (template / "some" / "__pycache__" / "mod.pyc").write_bytes(b"\x00")

        target = tmp_path / "target"
        target.mkdir()
        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert "__pycache__" in skipped
        assert "some/__pycache__" in skipped
        assert not (target / "__pycache__").exists()
        assert not (target / "some" / "__pycache__").exists()

    def test_should_skip_normal_file(self, tmp_path: Path, mock_json_handler) -> None:
        """Normal paths are copied, not skipped.

        Mutant: the skip rule skips everything -> red.
        """
        _ = mock_json_handler
        template = tmp_path / "template"
        (template / "apps" / "handlers").mkdir(parents=True)
        (template / "apps" / "handlers" / "file_ops.py").write_text("x = 1\n", encoding="utf-8")
        (template / "README.md").write_text("# readme\n", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert skipped == []
        assert (target / "apps" / "handlers" / "file_ops.py").read_text(encoding="utf-8") == "x = 1\n"
        assert (target / "README.md").read_text(encoding="utf-8") == "# readme\n"

    def test_should_skip_all_skip_names(self, tmp_path: Path, mock_json_handler) -> None:
        """Every entry in SKIP_NAMES keeps its file out of the copy.

        Mutant: .ruff_cache dropped from the skip test -> red.
        """
        _ = mock_json_handler
        assert len(SKIP_NAMES) == 6, f"SKIP_NAMES holds {sorted(SKIP_NAMES)} - the sweep below is not the whole set"
        template = tmp_path / "template"
        template.mkdir()
        for name in SKIP_NAMES:
            (template / name).write_text("skip me", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        _copied, skipped = copy_template(template, target, REPLACEMENTS)

        assert sorted(skipped) == sorted(SKIP_NAMES)
        for name in SKIP_NAMES:
            assert not (target / name).exists(), f"{name} should be skipped"


# ---------------------------------------------------------------------------
# _replace_path_placeholders
# ---------------------------------------------------------------------------


class TestReplacePathPlaceholders:
    """Path placeholder replacement, observed through copy_template()."""

    def test_replace_path_placeholders(self, tmp_path: Path, mock_json_handler) -> None:
        """Placeholder tokens in path components are replaced.

        Mutant: path components copied without placeholder replacement -> red.
        """
        _ = mock_json_handler
        template = tmp_path / "template"
        (template / "{{BRANCH}}_json").mkdir(parents=True)
        (template / "{{BRANCH}}_json" / "{{BRANCHNAME}}_config.py").write_text("x", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        copied, _skipped = copy_template(template, target, REPLACEMENTS)

        assert (target / "testagent_json" / "TESTAGENT_config.py").is_file()
        assert "testagent_json/TESTAGENT_config.py" in copied
        assert not (target / "{{BRANCH}}_json").exists()

    def test_replace_path_placeholders_no_match(self, tmp_path: Path, mock_json_handler) -> None:
        """Paths without placeholders pass through unchanged."""
        _ = mock_json_handler
        template = tmp_path / "template"
        (template / "apps" / "handlers").mkdir(parents=True)
        (template / "apps" / "handlers" / "init.py").write_text("x", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        copied, _skipped = copy_template(template, target, REPLACEMENTS)

        assert (target / "apps" / "handlers" / "init.py").is_file()
        assert "apps/handlers/init.py" in copied

    def test_replace_path_placeholders_empty(self, tmp_path: Path, mock_json_handler) -> None:
        """With no replacements, a single-component path keeps its name."""
        _ = mock_json_handler
        template = tmp_path / "template"
        template.mkdir()
        (template / "file.txt").write_text("x", encoding="utf-8")

        target = tmp_path / "target"
        target.mkdir()
        copied, _skipped = copy_template(template, target, {})

        assert copied == ["file.txt"]
        assert (target / "file.txt").is_file()


# ---------------------------------------------------------------------------
# regenerate_template_registry
# ---------------------------------------------------------------------------


class TestRegenerateTemplateRegistry:
    """Tests for regenerate_template_registry()."""

    def test_regenerate_template_registry_creates_json(self, tmp_path: Path) -> None:
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

    def test_regenerate_template_registry_hashes_content(self, tmp_path: Path) -> None:
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

    def test_regenerate_template_registry_detects_placeholders(self, tmp_path: Path) -> None:
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

    def test_regenerate_template_registry_skips_spawn_dir(self, tmp_path: Path) -> None:
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

    def test_regenerate_template_registry_never_enters_a_dropbox_or_archive(self, tmp_path: Path) -> None:
        """A living branch's dropbox and every .archive in it are listed, never entered.

        sync-registry --fix runs this over living branches. The rule is the
        owner of the project's, 09-27 20:42, in paraphrase: nothing looks into
        a dropbox, a sandbox like .archive. The branch stands inside a directory
        named dropbox, so a skip read on the whole path would hide everything.
        Ran red before the walk skipped them (spawn's decision, DPLAN-0354 leg 4).
        """
        branch = tmp_path / "dropbox" / "branch"
        for rel in ("visible.txt", "dropbox/dropped.txt", ".archive/old.txt", "apps/.archive/retired.py"):
            (branch / rel).parent.mkdir(parents=True, exist_ok=True)
            (branch / rel).write_text("content", encoding="utf-8")
        (branch / ".spawn").mkdir()

        regenerate_template_registry(branch)

        data = json.loads((branch / ".spawn" / ".template_registry.json").read_text(encoding="utf-8"))
        assert [v["path"] for v in data["files"].values()] == ["visible.txt"]
        directories = sorted(v["path"] for v in data["directories"].values())
        assert directories == [".archive", "apps", "apps/.archive", "dropbox"]

    def test_regenerate_template_registry_no_spawn_dir_noop(self, tmp_path: Path) -> None:
        """If .spawn/ directory does not exist, function returns early."""
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")

        # Should not raise and should not create anything
        regenerate_template_registry(tmp_path)

        assert not (tmp_path / ".spawn").exists()
