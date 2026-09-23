# =================== META ====================
# Name: test_ignore_pathspec.py
# Description: Tests for pathspec-based ignore matching (gitignore parity)
# Version: 1.3.0
# Created: 2026-06-12
# Modified: 2026-09-22
# =============================================

"""Tests for src/aipass/backup/apps/handlers/ignore/patterns.py and .backupignore spec."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that all ignore and scan files parse and import
# seedgo: no-test-needed(documentation) — handler docstrings and function docs
# seedgo: no-test-needed(constant) — pattern strings and glyphs
# seedgo: no-test-needed(stdlib) — pathspec library's matching behavior

from unittest.mock import patch

import pytest

from aipass.backup.apps.handlers.ignore.patterns import (
    is_ignored,
    load_spec,
)
from aipass.backup.apps.handlers.project import setup
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.modules.all import handle_command
from aipass.backup.apps.modules.snapshot import run_snapshot
from aipass.backup.apps.modules.versioned import run_versioned
from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
from aipass.backup.apps.handlers.path.builder import (
    build_snapshot_path,
    build_versioned_store,
)
from aipass.backup.apps.handlers.report.result import BackupResult


# --- gitignore parity, read through the product's own matcher ---

# Every claim in this section is the gitignore claim it always made, now asserted
# on BACKUP's verdict instead of on a pathspec.PathSpec the test built for itself:
# the pattern is written into a real .backupignore under tmp_path and read back
# through load_spec + is_ignored, the matcher every copy lane and the Drive
# re-filter use. load_spec prepends the built-in "*.tmp" floor ahead of the
# project's lines, so no path asserted here ends in .tmp -- the floor can neither
# satisfy a positive claim nor break a negative one.


class TestGitignoreNegation:
    """Negation re-includes excluded paths."""

    def test_negation_re_includes(self, tmp_path):
        """Negated pattern re-includes a previously excluded file."""
        (tmp_path / ".backupignore").write_text("*.log\n!important.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("logs/debug.log", spec)
        assert not is_ignored("logs/important.log", spec)

    def test_negation_last_match_wins(self, tmp_path):
        """Re-excluding after negation still excludes."""
        (tmp_path / ".backupignore").write_text("*.txt\n!keep.txt\nkeep.txt\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("keep.txt", spec)

    def test_negation_in_subdir(self, tmp_path):
        """Negation works for files inside an excluded directory."""
        (tmp_path / ".backupignore").write_text("logs/\n!logs/audit.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("logs/debug.log", spec)
        assert not is_ignored("logs/audit.log", spec)


class TestGitignoreAnchoring:
    """Leading slash anchors to root."""

    def test_anchored_pattern(self, tmp_path):
        """Leading / anchors pattern to root only."""
        (tmp_path / ".backupignore").write_text("/build\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("build", spec)
        assert not is_ignored("src/build", spec)

    def test_unanchored_matches_anywhere(self, tmp_path):
        """Unanchored dir pattern matches at any depth."""
        (tmp_path / ".backupignore").write_text("build/\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("build/output.o", spec)
        assert is_ignored("src/build/output.o", spec)


class TestGitignoreDirOnly:
    """Trailing / means dir-only."""

    def test_dir_only_pattern(self, tmp_path):
        """Trailing / matches directory contents but not a bare file."""
        (tmp_path / ".backupignore").write_text("logs/\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("logs/app.log", spec)
        assert not is_ignored("logs", spec)


class TestGitignoreWildcard:
    """Wildcard boundary behavior."""

    def test_star_no_slash_cross(self, tmp_path):
        """Single * matches files at any depth for simple extensions."""
        (tmp_path / ".backupignore").write_text("*.py\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("test.py", spec)
        assert is_ignored("src/test.py", spec)

    def test_doublestar_crosses_dirs(self, tmp_path):
        """Double ** explicitly crosses directory boundaries."""
        (tmp_path / ".backupignore").write_text("**/test.py\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("test.py", spec)
        assert is_ignored("a/b/c/test.py", spec)


class TestGitignoreComments:
    """Comment and blank line handling."""

    def test_comments_ignored(self, tmp_path):
        """Lines starting with # are treated as comments."""
        (tmp_path / ".backupignore").write_text("# this is a comment\n*.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("app.log", spec)
        assert not is_ignored("# this is a comment", spec)

    def test_blank_lines_ignored(self, tmp_path):
        """Blank lines do not affect matching."""
        (tmp_path / ".backupignore").write_text("\n*.log\n\n\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("app.log", spec)
        assert not is_ignored("app.txt", spec)


class TestGitignoreLastMatchWins:
    """Last matching rule wins."""

    def test_last_match_wins(self, tmp_path):
        """Negation after exclude re-includes the file."""
        (tmp_path / ".backupignore").write_text("*.txt\n!important.txt\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert not is_ignored("important.txt", spec)
        assert is_ignored("other.txt", spec)

    def test_re_exclude_after_negation(self, tmp_path):
        """Re-excluding after negation excludes again."""
        (tmp_path / ".backupignore").write_text("*.txt\n!important.txt\nimportant.txt\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("important.txt", spec)


# --- load_spec + is_ignored integration ---


class TestLoadSpec:
    """Load spec from .backupignore and match paths."""

    def test_load_from_file(self, tmp_path):
        """Spec loaded from .backupignore matches correctly."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n!important.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("debug.log", spec)
        assert not is_ignored("important.log", spec)

    def test_load_missing_file(self, tmp_path):
        """Missing .backupignore ignores nothing beyond the built-in *.tmp floor."""
        spec = load_spec(str(tmp_path))
        assert not is_ignored("anything.txt", spec)

    def test_comments_and_blanks_pass_through(self, tmp_path):
        """Comments and blanks in the file are handled by pathspec."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("# comment\n\n*.pyc\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("test.pyc", spec)
        assert not is_ignored("test.py", spec)

    def test_negation_works_e2e(self, tmp_path):
        """Negation in .backupignore re-includes files end-to-end."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n!audit.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored("app.log", spec)
        assert not is_ignored("audit.log", spec)

    def test_dir_pattern_e2e(self, tmp_path):
        """Directory pattern matches contents at any depth."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("__pycache__/\n", encoding="utf-8")
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
        f1.write_text("keep", encoding="utf-8")
        f2.write_text("drop", encoding="utf-8")

        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n", encoding="utf-8")
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
        f.write_text("important", encoding="utf-8")

        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.log\n", encoding="utf-8")
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
        ignore.write_text("__pycache__/\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert not is_ignored(".trinity/local.json", spec)
        assert not is_ignored(".ai_mail.local/inbox.json", spec)
        assert not is_ignored(".aipass/prompt.md", spec)
        assert not is_ignored(".chroma/data.bin", spec)
        assert not is_ignored(".claude/settings.json", spec)

    def test_dotfile_can_be_excluded_explicitly(self, tmp_path):
        """Dotfiles can be excluded by adding them to .backupignore."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text(".secret/\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert is_ignored(".secret/key.pem", spec)
        assert not is_ignored(".trinity/local.json", spec)


# --- seed template ---


class TestSeedTemplate:
    """Seed template (backupignore.template) provisions new projects.

    Every claim is made the way a project meets the template: register the
    project, then read the .backupignore the setup wrote into it.
    """

    def _seeded(self, project):
        """Register a fresh project and return the .backupignore it was given."""
        project.mkdir(parents=True, exist_ok=True)
        create_backup_dir(str(project))
        return (project / ".backupignore").read_text(encoding="utf-8")

    def test_seeded_project_gets_ruff_cache(self, tmp_path):
        """A registered project's .backupignore includes .ruff_cache/."""

        assert ".ruff_cache/" in self._seeded(tmp_path / "proj")

    def test_seeded_project_gets_coverage(self, tmp_path):
        """A registered project's .backupignore includes .coverage."""

        assert ".coverage" in self._seeded(tmp_path / "proj")

    def test_seeded_project_gets_logs_dir(self, tmp_path):
        """A registered project's .backupignore excludes logs/ directories."""

        assert "logs/" in self._seeded(tmp_path / "proj")

    def test_seeded_project_gets_git(self, tmp_path):
        """A registered project's .backupignore excludes .git/."""

        assert ".git/" in self._seeded(tmp_path / "proj")

    def test_seeded_project_gets_venv(self, tmp_path):
        """A registered project's .backupignore excludes .venv/."""

        assert ".venv/" in self._seeded(tmp_path / "proj")

    def test_seeded_project_gets_rust_target(self, tmp_path):
        """A registered project's .backupignore excludes target/ — the Rust build dir.

        Regression: baud's generated .backupignore covered build/ and dist/
        but not target/, so an 18GB src-tauri/target tree was walked and
        copied for 7.5h, landing 50GB of .o files in the stores.
        """

        assert "target/" in self._seeded(tmp_path / "proj")

    def test_seeded_target_pattern_matches_a_nested_rust_tree(self, tmp_path):
        """target/ is unanchored, so the seeded spec matches it at any depth.

        baud's tree is app/src-tauri/target, not a top-level target/ — an
        anchored pattern would have been written and still missed it. Read
        back through load_spec, the same matcher every copy lane uses.
        """

        project = tmp_path / "proj"
        project.mkdir()
        create_backup_dir(str(project))

        spec = load_spec(str(project))
        assert is_ignored("app/src-tauri/target/debug/deps/foo.rcgu.o", spec)
        assert is_ignored("target/debug/build.rs", spec)
        assert not is_ignored("app/src/target_resolver.rs", spec)

    def test_seed_content_is_read_from_the_template_file(self, tmp_path, monkeypatch):
        """Editing the template file changes what a new project is seeded with.

        The seed is never a string baked into the handler: point the template
        seam at another file and the project is provisioned from that file.
        """

        project = tmp_path / "proj"
        project.mkdir()
        stand_in = tmp_path / "stand_in.template"
        stand_in.write_text("# stand-in seed\n*.marker\n", encoding="utf-8")
        monkeypatch.setattr(setup, "_TEMPLATE_PATH", stand_in)

        create_backup_dir(str(project))

        written = (project / ".backupignore").read_text(encoding="utf-8")
        assert written == "# stand-in seed\n*.marker\n"

    def test_registering_with_a_missing_template_raises(self, tmp_path, monkeypatch):
        """Missing template raises FileNotFoundError, not empty content."""

        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.setattr(setup, "_TEMPLATE_PATH", tmp_path / "nonexistent.template")

        with pytest.raises(FileNotFoundError):
            create_backup_dir(str(project))

    def test_a_missing_template_raises_and_leaves_no_ignore_file_behind(self, tmp_path, monkeypatch):
        """The raise writes nothing, so the project can still be seeded later.

        Opening the destination before the content was built truncated it
        first: a missing template left a ZERO-BYTE .backupignore, and the
        `if not exists()` guard then made that permanent — the project
        shipped ignoring nothing but the built-in *.tmp floor.
        """

        project = tmp_path / "proj"
        project.mkdir()
        ignore = project / ".backupignore"
        monkeypatch.setattr(setup, "_TEMPLATE_PATH", tmp_path / "nonexistent.template")

        with pytest.raises(FileNotFoundError):
            create_backup_dir(str(project))
        assert not ignore.exists()

        template = tmp_path / "recovered.template"
        template.write_text("target/\n.venv/\n", encoding="utf-8")
        monkeypatch.setattr(setup, "_TEMPLATE_PATH", template)
        create_backup_dir(str(project))
        assert ignore.read_text(encoding="utf-8") == "target/\n.venv/\n"

    def test_seed_writes_only_when_absent(self, tmp_path):
        """Seeding does not overwrite an existing .backupignore."""

        project = tmp_path / "proj"
        project.mkdir()
        create_backup_dir(str(project))
        ignore = project / ".backupignore"
        assert ignore.exists()

        ignore.write_text("# custom\n", encoding="utf-8")
        create_backup_dir(str(project))
        assert ignore.read_text(encoding="utf-8") == "# custom\n"


# --- built-in *.tmp floor (DPLAN-0338) ---

# Both eras of the fleet's json staging temp, plus a bare and a nested one.
_TEMP_SHAPES = ["data_json/.4242_7.tmp", "prax_json/tmpy531wjjf.tmp", "a/b/c.tmp", "root.tmp"]
# Neighbours that only LOOK like temps -- the floor must not widen onto them.
_KEPT_NEIGHBOURS = ["data_json/state.json", "notes.tmpl", "tmp.json", "state.tmp.json", "tmp/data.json"]


def _json_folder_with_temps(root):
    """A *_json folder the way a killed writer leaves it: the real json plus two orphaned temps."""
    folder = root / "data_json"
    folder.mkdir(parents=True)
    real = b'{"ok": true}\n'
    (folder / "state.json").write_bytes(real)
    (folder / ".4242_7.tmp").write_bytes(b'{"ok": tr')
    (folder / "tmpab12cd34.tmp").write_bytes(real)
    return real


class TestBuiltinTmpFloor:
    """*.tmp is ignored by every project, whatever its .backupignore says.

    Measured 2026-09-11: the AIPass store held 498 temp copies in snapshots/
    and 996 in versioned/, all from *_json folders, because no .backupignore
    seeded before the rule named them. The floor lives in load_spec, which
    every copy lane and the Drive re-filter read.
    """

    def test_floor_applies_with_no_backupignore(self, tmp_path):
        """No file at all: temps ignored, their neighbours kept."""
        spec = load_spec(str(tmp_path))
        assert [p for p in _TEMP_SHAPES if not is_ignored(p, spec)] == []
        assert [p for p in _KEPT_NEIGHBOURS if is_ignored(p, spec)] == []

    def test_floor_applies_when_the_file_never_names_tmp(self, tmp_path):
        """The real case: a .backupignore written before the rule still gets it."""
        (tmp_path / ".backupignore").write_text("node_modules/\n*.log\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert [p for p in _TEMP_SHAPES if not is_ignored(p, spec)] == []
        assert [p for p in _KEPT_NEIGHBOURS if is_ignored(p, spec)] == []
        assert is_ignored("app.log", spec) is True

    def test_project_can_re_include_with_negation(self, tmp_path):
        """The floor goes FIRST, so a project's own '!*.tmp' wins (last match wins)."""
        (tmp_path / ".backupignore").write_text("!*.tmp\n", encoding="utf-8")
        spec = load_spec(str(tmp_path))
        assert [p for p in _TEMP_SHAPES if is_ignored(p, spec)] == []

    def test_snapshot_lane_skips_temps_and_keeps_the_json(self, tmp_path):
        """run_snapshot: the temp beside the json is not copied, the json is."""

        root = tmp_path / "proj"
        real = _json_folder_with_temps(root)
        result = run_snapshot(str(root), show_panels=False)

        assert result.success is True
        dest = build_snapshot_path(str(root))
        assert (dest / "data_json" / "state.json").read_bytes() == real
        assert list(dest.rglob("*.tmp")) == []
        # Not vacuous: both temps were in the tree the run walked, and still are.
        assert sorted(p.name for p in (root / "data_json").glob("*.tmp")) == [".4242_7.tmp", "tmpab12cd34.tmp"]

    def test_versioned_lane_skips_temps_and_keeps_the_json(self, tmp_path):
        """run_versioned: no temp reaches the store, as a file-folder or a copy."""

        root = tmp_path / "proj"
        real = _json_folder_with_temps(root)
        result = run_versioned(str(root), show_panels=False)

        assert result.success is True
        store = build_versioned_store(str(root))
        assert (store / "data_json" / "state.json" / "state.json").read_bytes() == real
        # A pre-rule run stored each temp as <name>.tmp/<name>.tmp plus a
        # baseline; rglob('*.tmp') catches the folder and both copies.
        assert list(store.rglob("*.tmp")) == []

    def test_all_lane_skips_temps_in_both_stores(self, tmp_path):
        """'all' shares one scan between both stores; neither gets a temp."""

        root = tmp_path / "proj"
        real = _json_folder_with_temps(root)
        # 'all' calls run_drive_sync unconditionally -- keep the suite off the network.
        with patch("aipass.backup.apps.modules.drive_sync.run_drive_sync", return_value={}):
            assert handle_command("all", [str(root), "--quiet"]) is True

        dest = build_snapshot_path(str(root))
        store = build_versioned_store(str(root))
        assert (dest / "data_json" / "state.json").read_bytes() == real
        assert (store / "data_json" / "state.json" / "state.json").read_bytes() == real
        assert list(dest.rglob("*.tmp")) == []
        assert list(store.rglob("*.tmp")) == []


# --- mirror cleanup uses source-existence, no exceptions ---


class TestMirrorCleanupNoExceptions:
    """Mirror cleanup deletes when source is gone — no exception list."""

    def test_deletes_when_source_gone(self, tmp_path):
        """Files in backup whose source is gone get deleted — the predicate buys no exception.

        The should_ignore callable NAMES gone.txt, and gone.txt is deleted
        anyway: source-existence is the whole decision. A predicate that
        answered the same for every path could not tell that apart from a
        product that never consults the callable at all.
        """

        source = tmp_path / "source"
        source.mkdir()
        backup = tmp_path / "backup"
        backup.mkdir()

        (backup / "gone.txt").write_text("old", encoding="utf-8")
        (source / "kept.txt").write_text("here", encoding="utf-8")
        (backup / "kept.txt").write_text("here", encoding="utf-8")

        result = BackupResult(mode="snapshot", project_root=str(source))
        cleanup_deleted_files(backup, source, lambda p: p.name == "gone.txt", result)
        assert result.files_deleted == 1
        assert not (backup / "gone.txt").exists()
        assert (backup / "kept.txt").exists()


# =============================================
