# =================== META ====================
# Name: test_versioned_engine.py
# Description: Tests for versioned engine — baseline, diff, skip, never-delete, restore
# Version: 2.0.0
# Created: 2026-06-12
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/copy/versioned.py and the restore route in apps/modules/restore.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under apps/handlers/copy, diff and path parses and imports
# seedgo: no-test-needed(documentation) — that the public handler and module functions carry docstrings
# seedgo: no-test-needed(constant) — BACKUP_DIR's ".backup" text and the store's "versioned" directory name
# seedgo: no-test-needed(stdlib) — hashlib.md5's digest and shutil.copy2's mtime-preserving copy
# seedgo: no-test-needed(generated) — the date inside a baseline name and the timestamp inside a diff name

import tempfile
import time
from pathlib import Path

from aipass.backup.apps.handlers.copy.versioned import copy_versioned
from aipass.backup.apps.handlers.diff.generator import generate_diff_content, is_binary_file, should_create_diff
from aipass.backup.apps.handlers.diff.restore import list_versions, restore_file
from aipass.backup.apps.handlers.path.builder import build_versioned_file_path, build_versioned_store
from aipass.backup.apps.modules import restore as restore_module
from aipass.cli.apps.modules import command_failed

# Inert path input for the path builder — never touched on disk, so it only
# needs to be a valid absolute path on the running OS.
FAKE_PROJECT_ROOT = str(Path(tempfile.gettempdir()) / "project")

# The audit trail is deliberately NOT mocked here, though every test in this
# file used to wrap itself in patch("...audit.trail.log_operation"). conftest's
# autouse mock_infrastructure points AIPASS_TEST_LOG_DIR into tmp_path for each
# test and trail.log_path() recomputes on every call, so the only write that
# left tmp_path is already redirected for real. Template v1 item 15: mock at
# the edge, and only where no real redirect exists.


class TestVersionedBaseline:
    """First run creates baseline + current."""

    def test_first_run_creates_baseline(self, tmp_path: Path):
        """New file -> baseline + current in file-folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "hello.py").write_text("print('hello')", encoding="utf-8")

        files = [(str(project / "hello.py"), "hello.py")]
        result = copy_versioned(files, str(project))

        assert result["files_copied"] == 1

        target = Path(build_versioned_file_path(str(project), "hello.py"))
        assert target.exists()

        # Check baseline exists in same folder
        baselines = [f for f in target.parent.iterdir() if "-baseline-" in f.name]
        assert len(baselines) == 1
        assert baselines[0].name.endswith(".py")

    def test_first_run_current_matches_source(self, tmp_path: Path):
        """Current copy has same content as source."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "data.txt").write_text("original content", encoding="utf-8")

        copy_versioned([(str(project / "data.txt"), "data.txt")], str(project))

        target = Path(build_versioned_file_path(str(project), "data.txt"))
        assert target.read_text(encoding="utf-8") == "original content"


class TestVersionedDiff:
    """Change creates diff + overwrites current."""

    def test_change_creates_diff(self, tmp_path: Path):
        """Modified file -> diff file appears in _diffs/ folder."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "code.py"
        src.write_text("v1", encoding="utf-8")

        # First run
        copy_versioned([(str(src), "code.py")], str(project))

        # Modify source (ensure different mtime)
        time.sleep(0.05)
        src.write_text("v2", encoding="utf-8")

        # Second run
        copy_versioned([(str(src), "code.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "code.py"))
        diff_dir = target.parent / f"{target.name}_diffs"
        assert diff_dir.exists()
        diffs = list(diff_dir.glob("*.diff"))
        assert len(diffs) == 1

    def test_change_overwrites_current(self, tmp_path: Path):
        """After change, current has new content."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "file.txt"
        src.write_text("old", encoding="utf-8")

        copy_versioned([(str(src), "file.txt")], str(project))

        time.sleep(0.05)
        src.write_text("new", encoding="utf-8")
        copy_versioned([(str(src), "file.txt")], str(project))

        target = Path(build_versioned_file_path(str(project), "file.txt"))
        assert target.read_text(encoding="utf-8") == "new"

    def test_baseline_untouched_after_change(self, tmp_path: Path):
        """Baseline is never overwritten after first creation."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "config.py"
        src.write_text("original", encoding="utf-8")

        copy_versioned([(str(src), "config.py")], str(project))

        time.sleep(0.05)
        src.write_text("modified", encoding="utf-8")
        copy_versioned([(str(src), "config.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "config.py"))
        baselines = [f for f in target.parent.iterdir() if "-baseline-" in f.name]
        assert len(baselines) == 1
        assert baselines[0].read_text(encoding="utf-8") == "original"


class TestVersionedSkip:
    """Unchanged files are skipped."""

    def test_unchanged_skipped(self, tmp_path: Path):
        """File with same mtime -> files_unchanged incremented."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "stable.txt"
        src.write_text("no change", encoding="utf-8")

        copy_versioned([(str(src), "stable.txt")], str(project))

        # Run again without modifying
        result = copy_versioned([(str(src), "stable.txt")], str(project))
        assert result["files_unchanged"] == 1
        assert result["files_copied"] == 0


class TestVersionedNeverDelete:
    """Versioned NEVER deletes — append-only."""

    def test_deleted_source_preserved_in_store(self, tmp_path: Path):
        """Source file deleted -> versioned store still has it."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "temp.py"
        src.write_text("temp data", encoding="utf-8")

        copy_versioned([(str(src), "temp.py")], str(project))

        # Delete source
        src.unlink()

        # Run versioned again WITHOUT the deleted file
        copy_versioned([], str(project))

        # Store still has the file
        target = Path(build_versioned_file_path(str(project), "temp.py"))
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "temp data"


class TestDiffGenerator:
    """Diff generator — binary detection, unified diff."""

    def test_text_diff(self, tmp_path: Path):
        """Text files produce unified diff."""
        old = tmp_path / "old.py"
        new = tmp_path / "new.py"
        old.write_text("line1\nline2\n", encoding="utf-8")
        new.write_text("line1\nline3\n", encoding="utf-8")

        diff = generate_diff_content(old, new)

        # Three clauses joined by 'or', all three about the result: the
        # last one ("line" in diff) is true of literally any output that
        # echoes either file, so the assertion could not fail. Measured
        # 2026-09-08 -- all three headers are present, and so are the two
        # changed lines with their unified-diff signs.
        assert "--- a/old.py" in diff
        assert "+++ b/new.py" in diff
        assert "@@ -1,2 +1,2 @@" in diff
        assert "-line2" in diff
        assert "+line3" in diff

    def test_binary_marker(self, tmp_path: Path):
        """Binary files get marker instead of diff."""
        binary = tmp_path / "image.bin"
        binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00" + b"\x00" * 100)
        assert is_binary_file(binary) is True

    def test_should_create_diff_patterns(self):
        """Include patterns override ignore patterns."""
        assert should_create_diff(Path("app.py")) is True
        assert should_create_diff(Path("image.png")) is False
        assert should_create_diff(Path("data.json")) is True


class TestRestore:
    """Restore handler — reconstruct from store."""

    def test_restore_current(self, tmp_path: Path):
        """Restore current version from store."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "app.py"
        src.write_text("print('app')", encoding="utf-8")

        copy_versioned([(str(src), "app.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "app.py"))
        output = tmp_path / "restored" / "app.py"
        assert restore_file(target.parent, output) is True
        assert output.read_text(encoding="utf-8") == "print('app')"

    def test_list_versions(self, tmp_path: Path):
        """list_versions finds baseline + current + diffs."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "mod.py"
        src.write_text("v1", encoding="utf-8")

        copy_versioned([(str(src), "mod.py")], str(project))

        time.sleep(0.05)
        src.write_text("v2", encoding="utf-8")
        copy_versioned([(str(src), "mod.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "mod.py"))
        versions = list_versions(target.parent)
        types = {v["type"] for v in versions}
        assert "baseline" in types
        assert "current" in types
        assert "diff" in types


class TestVersionedFilePath:
    """Path builder — file-folder packaging."""

    def test_root_level_file(self):
        """Root-level file -> root/<name>/<name>."""
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "README.md"))
        assert "root" in str(result)
        assert result.name == "README.md"

    def test_nested_file(self):
        """Nested file -> <parent>/<name>/<name>."""
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "src/main.py"))
        assert "src" in str(result)
        assert result.name == "main.py"
        assert result.parent.name == "main.py"

    def test_long_filename_hashed(self):
        """Filename >50 chars -> shortened with hash."""
        long_name = "a" * 60 + ".py"
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, long_name))
        assert result.name == long_name
        assert len(result.parent.name) < 50


class TestRestoreModule:
    """The `restore` command — version discovery and file restore, the way a user reaches them."""

    # Three of these used to import aipass.backup.apps.modules.restore._find_file_folder
    # and assert on the Path it returned. Both of its callers — run_list_versions
    # and run_restore_file — are public and reachable from the command, so the
    # lookup is exercised here through
    # `restore <project> list <file>` and `restore <project> file <file> <out>`,
    # which is what a user types. Nothing was weakened: every claim the old
    # tests made about the folder is now made about the bytes or the line the
    # user gets.

    def test_restore_list_names_the_stored_versions_of_a_file(self, tmp_path: Path, capsys):
        project = tmp_path / "project"
        project.mkdir()
        src = project / "config.py"
        src.write_text("cfg = True", encoding="utf-8")
        copy_versioned([(str(src), "config.py")], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", "config.py"]) is True

        # Read on the filenames, not on the "[baseline]"/"[current]" type
        # labels the module formats: console.print parses Rich markup, so
        # those square brackets are consumed as unknown style tags and never
        # reach the user at all. Shipped defect, reported 2026-09-22.
        out = capsys.readouterr().out
        assert "Versions of config.py:" in out
        assert "config-baseline-" in out
        assert "config.py" in out

    def test_a_listed_diff_row_names_its_type_instead_of_losing_it_to_rich_markup(self, tmp_path: Path, capsys):
        """console.print parses markup, so "[diff]" was read as a style tag and dropped: a bare timestamp."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "mod.py"
        src.write_text("v1", encoding="utf-8")
        copy_versioned([(str(src), "mod.py")], str(project))

        time.sleep(0.05)
        src.write_text("v2", encoding="utf-8")
        copy_versioned([(str(src), "mod.py")], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", "mod.py"]) is True

        # The diff row is the one that cannot survive the loss: baseline and
        # current repeat their type in the timestamp column, a diff row does not.
        out = capsys.readouterr().out
        diff_rows = [line for line in out.splitlines() if ".diff" in line]
        assert len(diff_rows) == 1
        assert "[diff]" in diff_rows[0]
        assert "[baseline]" in out
        assert "[current]" in out

        # The heading two lines above still renders as markup, not as literal tags.
        assert "Versions of mod.py:" in out
        assert "[bold]" not in out

    def test_a_relative_path_restores_the_right_one_of_two_same_named_files(self, tmp_path: Path, capsys):
        """The documented form is `restore <project> file src/main.py out`; a basename cannot tell two main.py apart."""
        # The lookup used to join the WHOLE argument onto the matched folder,
        # so it looked for <store>/src/main.py/src/main.py and never found
        # anything — only a bare basename worked, and a basename is ambiguous
        # the moment two directories hold the same name.
        project = tmp_path / "project"
        for sub in ("src", "tools"):
            (project / sub).mkdir(parents=True)
            (project / sub / "main.py").write_text(f"where = {sub!r}", encoding="utf-8")
        pairs = [(str(project / sub / "main.py"), f"{sub}/main.py") for sub in ("src", "tools")]
        copy_versioned(pairs, str(project))

        out_path = tmp_path / "restored" / "main.py"
        assert restore_module.handle_command("restore", [str(project), "file", "tools/main.py", str(out_path)]) is True

        assert out_path.read_text(encoding="utf-8") == "where = 'tools'"
        assert f"Restored tools/main.py to {out_path}" in capsys.readouterr().out

    def test_a_file_that_was_never_stored_is_named_back_and_nothing_is_written(self, tmp_path: Path, capsys):
        out_path = tmp_path / "restored" / "nonexistent.py"

        assert restore_module.run_restore_file(str(tmp_path), "nonexistent.py", str(out_path)) is False

        # Same claim as before — the user is told which file was not found —
        # restated on the channel that now carries it. The line moved from
        # console.print (stdout) to error() (stderr) so a pipe can tell a
        # failure from a restored file; nothing about the text changed.
        assert "No versioned file found for: nonexistent.py" in capsys.readouterr().err
        assert not out_path.exists()

    def test_a_missing_versioned_file_is_named_on_stderr_and_never_on_stdout(self, tmp_path: Path, capsys):
        """Both lookup failures used console.print, so a pipe could not separate them from success output."""
        missing = "ghost.py"

        assert restore_module.handle_command("restore", [str(tmp_path), "list", missing]) is True
        out, err = capsys.readouterr()
        assert f"No versioned file found for: {missing}" in err
        assert "No versioned file found" not in out
        assert command_failed() is True

        out_path = tmp_path / "restored" / missing
        assert restore_module.handle_command("restore", [str(tmp_path), "file", missing, str(out_path)]) is True
        out, err = capsys.readouterr()
        assert f"No versioned file found for: {missing}" in err
        assert "No versioned file found" not in out
        assert not out_path.exists()

    def test_a_restore_that_fails_says_so_on_stderr_beside_no_success_line(self, tmp_path: Path, capsys, monkeypatch):
        """ "Restore failed for X" used to print on stdout, the same channel as "Restored X to Y"."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "data.txt"
        src.write_text("payload", encoding="utf-8")
        copy_versioned([(str(src), "data.txt")], str(project))

        # The handler is the edge: once the module has found a stored file the
        # copy succeeds, so the only route to the failure line is to make the
        # handler refuse (template v1 item 15 — mock at the edge, and only there).
        monkeypatch.setattr(restore_module, "restore_file", lambda folder, out: False)

        out_path = tmp_path / "restored" / "data.txt"
        assert restore_module.handle_command("restore", [str(project), "file", "data.txt", str(out_path)]) is True

        out, err = capsys.readouterr()
        assert "Restore failed for data.txt" in err
        assert "Restore failed" not in out
        assert "Restored data.txt" not in out
        assert command_failed() is True

    def test_a_filename_over_50_chars_is_stored_under_a_hashed_folder_and_the_command_still_restores_it(
        self, tmp_path: Path, capsys
    ):
        """Was a shipped defect: >50 chars store under name[:30]_md5, and the lookup globbed the full name."""
        project = tmp_path / "project"
        project.mkdir()
        long_name = "a" * 60 + ".py"
        src = project / long_name
        src.write_text("long name payload", encoding="utf-8")
        copy_versioned([(str(src), long_name)], str(project))

        stored = Path(build_versioned_file_path(str(project), long_name))
        assert stored.read_text(encoding="utf-8") == "long name payload"
        assert stored.parent.name != long_name

        assert restore_module.handle_command("restore", [str(project), "list", long_name]) is True

        # The bytes are on disk under a folder named nothing like the file, and
        # the command reaches them anyway — both the lookup and the handler.
        out, err = capsys.readouterr()
        assert f"Versions of {long_name}:" in out
        assert "[current]" in out
        assert f"No versioned file found for: {long_name}" not in err

        out_path = tmp_path / "restored" / long_name
        assert restore_module.handle_command("restore", [str(project), "file", long_name, str(out_path)]) is True
        assert out_path.read_text(encoding="utf-8") == "long name payload"
        assert build_versioned_store(str(project)).exists()

    def test_a_hashed_long_name_folder_lists_its_diffs_and_not_only_baseline_and_current(self, tmp_path: Path, capsys):
        """The diffs live in <full name>_diffs, so a handler reading the folder name found no diff at all."""
        project = tmp_path / "project"
        project.mkdir()
        long_name = "b" * 60 + ".py"
        src = project / long_name
        src.write_text("v1", encoding="utf-8")
        copy_versioned([(str(src), long_name)], str(project))

        time.sleep(0.05)
        src.write_text("v2", encoding="utf-8")
        copy_versioned([(str(src), long_name)], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", long_name]) is True

        out = capsys.readouterr().out
        assert len([line for line in out.splitlines() if "[diff]" in line]) == 1
        assert "[baseline]" in out
        assert "[current]" in out

    def test_run_restore_file_roundtrip(self, tmp_path: Path, capsys):
        """run_restore_file restores a file to an output path."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "data.txt"
        src.write_text("important data", encoding="utf-8")
        copy_versioned([(str(src), "data.txt")], str(project))

        out = str(tmp_path / "restored" / "data.txt")
        result = restore_module.run_restore_file(str(project), "data.txt", out)

        assert result is True
        assert Path(out).read_text(encoding="utf-8") == "important data"
        assert f"Restored data.txt to {out}" in capsys.readouterr().out

    def test_list_without_a_filename_is_refused_as_a_usage_error_not_answered_with_the_help_page(
        self, tmp_path: Path, capsys
    ):
        """A malformed `restore <project> list` used to print help and report success — same answer as `--help`."""
        # True: the command is ours and was handled; the failure travels as
        # command_failed() (exit 2), never as "Unknown command: restore".
        assert restore_module.handle_command("restore", [str(tmp_path), "list"]) is True

        out, err = capsys.readouterr()
        assert "restore <project> list <file>" in err
        assert "Unknown command" not in err
        assert "Usage:" not in out
        assert "restore Module" not in out
        assert command_failed() is True

    def test_no_arguments_at_all_still_answers_with_the_module_introspection(self, capsys):
        """The usage refusal must not swallow the bare `restore` path, which is not malformed."""
        assert restore_module.handle_command("restore", []) is True

        out, err = capsys.readouterr()
        assert "restore Module" in out
        assert err == ""
        assert command_failed() is False

    def test_a_help_flag_prints_the_module_and_both_usage_lines(self, capsys):
        assert restore_module.handle_command("restore", ["--help"]) is True

        out = capsys.readouterr().out
        assert "restore Module" in out
        assert "restore <project> list <file>" in out
        assert "restore <project> file <file> <out>" in out


# =============================================
