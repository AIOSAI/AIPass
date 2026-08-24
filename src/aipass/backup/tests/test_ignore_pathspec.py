# =================== AIPass ====================
# Name: test_ignore_pathspec.py
# Description: Tests for pathspec-based ignore matching (gitignore parity)
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Tests for pathspec-based .backupignore — gitignore parity, single-source, seed."""

import pathspec

from aipass.backup.apps.handlers.ignore.patterns import (
    is_ignored,
    load_spec,
)
from aipass.backup.apps.handlers.scan.filter import filter_paths


# --- gitignore parity ---


class TestGitignoreNegation:
    """Negation re-includes excluded paths."""

    def test_negation_re_includes(self):
        """Negated pattern re-includes a previously excluded file."""
        lines = ["*.log", "!important.log"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("debug.log")
        assert not spec.match_file("important.log")

    def test_negation_last_match_wins(self):
        """Re-excluding after negation still excludes."""
        lines = ["*.txt", "!keep.txt", "keep.txt"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("keep.txt")

    def test_negation_in_subdir(self):
        """Negation works for files inside an excluded directory."""
        lines = ["logs/", "!logs/audit.log"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("logs/debug.log")
        assert not spec.match_file("logs/audit.log")


class TestGitignoreAnchoring:
    """Leading slash anchors to root."""

    def test_anchored_pattern(self):
        """Leading / anchors pattern to root only."""
        lines = ["/build"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("build")
        assert not spec.match_file("src/build")

    def test_unanchored_matches_anywhere(self):
        """Unanchored dir pattern matches at any depth."""
        lines = ["build/"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("build/output.o")
        assert spec.match_file("src/build/output.o")


class TestGitignoreDirOnly:
    """Trailing / means dir-only."""

    def test_dir_only_pattern(self):
        """Trailing / matches directory contents but not a bare file."""
        lines = ["logs/"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("logs/app.log")
        assert not spec.match_file("logs")


class TestGitignoreWildcard:
    """Wildcard boundary behavior."""

    def test_star_no_slash_cross(self):
        """Single * matches files at any depth for simple extensions."""
        lines = ["*.py"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("test.py")
        assert spec.match_file("src/test.py")

    def test_doublestar_crosses_dirs(self):
        """Double ** explicitly crosses directory boundaries."""
        lines = ["**/test.py"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("test.py")
        assert spec.match_file("a/b/c/test.py")


class TestGitignoreComments:
    """Comment and blank line handling."""

    def test_comments_ignored(self):
        """Lines starting with # are treated as comments."""
        lines = ["# this is a comment", "*.log"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("app.log")
        assert not spec.match_file("# this is a comment")

    def test_blank_lines_ignored(self):
        """Blank lines do not affect matching."""
        lines = ["", "*.log", "", ""]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("app.log")
        assert not spec.match_file("app.txt")


class TestGitignoreLastMatchWins:
    """Last matching rule wins."""

    def test_last_match_wins(self):
        """Negation after exclude re-includes the file."""
        lines = ["*.txt", "!important.txt"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert not spec.match_file("important.txt")
        assert spec.match_file("other.txt")

    def test_re_exclude_after_negation(self):
        """Re-excluding after negation excludes again."""
        lines = ["*.txt", "!important.txt", "important.txt"]
        spec = pathspec.PathSpec.from_lines("gitignore", lines)
        assert spec.match_file("important.txt")


# --- load_spec + is_ignored integration ---


class TestLoadSpec:
    """Load spec from .backupignore and match paths."""

    def test_load_from_file(self, tmp_path):
        """Spec loaded from .backupignore matches correctly."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n!important.log\n")
        spec = load_spec(str(tmp_path))
        assert is_ignored("debug.log", spec)
        assert not is_ignored("important.log", spec)

    def test_load_missing_file(self, tmp_path):
        """Missing .backupignore yields empty spec (nothing ignored)."""
        spec = load_spec(str(tmp_path))
        assert not is_ignored("anything.txt", spec)

    def test_comments_and_blanks_pass_through(self, tmp_path):
        """Comments and blanks in the file are handled by pathspec."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("# comment\n\n*.pyc\n")
        spec = load_spec(str(tmp_path))
        assert is_ignored("test.pyc", spec)
        assert not is_ignored("test.py", spec)

    def test_negation_works_e2e(self, tmp_path):
        """Negation in .backupignore re-includes files end-to-end."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n!audit.log\n")
        spec = load_spec(str(tmp_path))
        assert is_ignored("app.log", spec)
        assert not is_ignored("audit.log", spec)

    def test_dir_pattern_e2e(self, tmp_path):
        """Directory pattern matches contents at any depth."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("__pycache__/\n")
        spec = load_spec(str(tmp_path))
        assert is_ignored("__pycache__/module.cpython.pyc", spec)
        assert is_ignored("src/__pycache__/module.cpython.pyc", spec)


# --- single source: filter_paths uses spec ---


class TestFilterPathsSpec:
    """Filter paths works with PathSpec instead of pattern list."""

    def test_filter_excludes_ignored(self, tmp_path):
        """Ignored files are excluded from the filtered list."""
        f1 = tmp_path / "keep.txt"
        f2 = tmp_path / "drop.log"
        f1.write_text("keep")
        f2.write_text("drop")

        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n")
        spec = load_spec(str(tmp_path))

        paths = [
            (str(f1), "keep.txt"),
            (str(f2), "drop.log"),
        ]
        filtered = filter_paths(paths, spec, [], 100)
        assert len(filtered) == 1
        assert filtered[0][1] == "keep.txt"

    def test_filter_whitelist_overrides_ignore(self, tmp_path):
        """Whitelisted files survive even when matching an ignore pattern."""
        f = tmp_path / "special.log"
        f.write_text("important")

        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n")
        spec = load_spec(str(tmp_path))

        paths = [(str(f), "special.log")]
        filtered = filter_paths(paths, spec, ["special.log"], 100)
        assert len(filtered) == 1


# --- dotfiles reach Drive (no dotfile filter) ---


class TestDotfilesIncluded:
    """Dotfiles are NOT filtered out — they reach the store and Drive."""

    def test_dotfile_not_ignored_by_default(self, tmp_path):
        """Key dotfile dirs are included when not in .backupignore."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("__pycache__/\n")
        spec = load_spec(str(tmp_path))
        assert not is_ignored(".trinity/local.json", spec)
        assert not is_ignored(".ai_mail.local/inbox.json", spec)
        assert not is_ignored(".aipass/prompt.md", spec)
        assert not is_ignored(".chroma/data.bin", spec)
        assert not is_ignored(".claude/settings.json", spec)

    def test_dotfile_can_be_excluded_explicitly(self, tmp_path):
        """Dotfiles can be excluded by adding them to .backupignore."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text(".secret/\n")
        spec = load_spec(str(tmp_path))
        assert is_ignored(".secret/key.pem", spec)
        assert not is_ignored(".trinity/local.json", spec)


# --- seed template ---


class TestSeedTemplate:
    """Seed template (backupignore.template) provisions new projects."""

    def test_template_has_ruff_cache(self):
        """Seed template includes .ruff_cache/."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert ".ruff_cache/" in content

    def test_template_has_coverage(self):
        """Seed template includes .coverage."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert ".coverage" in content

    def test_template_has_logs_dir(self):
        """Seed template excludes logs/ directories."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "logs/" in content

    def test_template_has_git(self):
        """Seed template excludes .git/."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert ".git/" in content

    def test_template_has_venv(self):
        """Seed template excludes .venv/."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert ".venv/" in content

    def test_template_has_rust_target(self):
        """Seed template excludes target/ — the Rust build-artifact dir.

        Regression: baud's generated .backupignore covered build/ and dist/
        but not target/, so an 18GB src-tauri/target tree was walked and
        copied for 7.5h, landing 50GB of .o files in the stores.
        """
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        content = _TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "target/" in content

    def test_template_target_matches_nested_rust_tree(self):
        """target/ is unanchored, so it matches at any depth.

        baud's tree is app/src-tauri/target, not a top-level target/ — an
        anchored pattern would have been written and still missed it.
        """
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH

        spec = pathspec.PathSpec.from_lines("gitignore", _TEMPLATE_PATH.read_text(encoding="utf-8").splitlines())
        assert spec.match_file("app/src-tauri/target/debug/deps/foo.rcgu.o")
        assert spec.match_file("target/debug/build.rs")
        assert not spec.match_file("app/src/target_resolver.rs")

    def test_build_backupignore_reads_template(self):
        """_build_backupignore returns the template content."""
        from aipass.backup.apps.handlers.project.setup import _TEMPLATE_PATH, _build_backupignore

        content = _build_backupignore()
        assert content == _TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_build_backupignore_raises_on_missing_template(self, tmp_path):
        """Missing template raises FileNotFoundError, not empty content."""
        from unittest.mock import patch

        import pytest

        from aipass.backup.apps.handlers.project import setup

        fake_path = tmp_path / "nonexistent.template"
        with patch.object(setup, "_TEMPLATE_PATH", fake_path), pytest.raises(FileNotFoundError):
            setup._build_backupignore()

    def test_seed_writes_only_when_absent(self, tmp_path):
        """Seeding does not overwrite an existing .backupignore."""
        from aipass.backup.apps.handlers.project.setup import create_backup_dir

        create_backup_dir(str(tmp_path))
        ignore = tmp_path / ".backupignore"
        assert ignore.exists()

        ignore.write_text("# custom\n")
        create_backup_dir(str(tmp_path))
        assert ignore.read_text() == "# custom\n"


# --- mirror cleanup uses source-existence, no exceptions ---


class TestMirrorCleanupNoExceptions:
    """Mirror cleanup deletes when source is gone — no exception list."""

    def test_deletes_when_source_gone(self, tmp_path):
        """Files in backup whose source is gone get deleted."""
        from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
        from aipass.backup.apps.handlers.report.result import BackupResult

        source = tmp_path / "source"
        source.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()

        (backup / "gone.txt").write_text("old")
        (source / "kept.txt").write_text("here")
        (backup / "kept.txt").write_text("here")

        result = BackupResult(mode="snapshot", project_root=str(source))
        cleanup_deleted_files(backup, source, lambda p: False, result)
        assert result.files_deleted == 1
        assert not (backup / "gone.txt").exists()
        assert (backup / "kept.txt").exists()


# =============================================
