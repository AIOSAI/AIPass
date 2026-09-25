# =================== META ====================
# Name: test_versioned_engine.py
# Description: Tests for versioned engine — baseline, diff, skip, never-delete, restore
# Version: 2.0.3
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/copy/versioned.py and the restore route in apps/modules/restore.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under apps/handlers/copy, diff and path parses and imports
# seedgo: no-test-needed(documentation) — that the public handler and module functions carry docstrings
# seedgo: no-test-needed(constant) — BACKUP_DIR's ".backup" text and the store's "versioned" directory name
# seedgo: no-test-needed(generated) — the dates _make_baseline_name and _copy_changed_file stamp into file names

import os
import tempfile
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

# The audit trail is deliberately NOT mocked here. conftest's autouse
# mock_infrastructure points AIPASS_TEST_LOG_DIR at a per-test directory beside
# tmp_path and trail.log_path() recomputes on every call, so the audit write is
# already redirected for real. Template v1 item 15: mock at the edge, and only
# where no real redirect exists.


class TestVersionedBaseline:
    """`copy_versioned` on a file the store has never seen — the baseline and the current copy it lays down."""

    def test_a_first_run_stores_one_baseline_beside_the_current_copy(self, tmp_path: Path):
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
        assert baselines[0].name.startswith("hello-baseline-")
        assert baselines[0].read_text(encoding="utf-8") == "print('hello')"

    def test_a_first_run_stores_the_current_copy_with_the_source_text(self, tmp_path: Path):
        """Current copy has same content as source."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "data.txt").write_text("original content", encoding="utf-8")

        copy_versioned([(str(project / "data.txt"), "data.txt")], str(project))

        target = Path(build_versioned_file_path(str(project), "data.txt"))
        assert target.read_text(encoding="utf-8") == "original content"


class TestVersionedDiff:
    """`copy_versioned` on a source newer than its stored copy — the diff it adds, the copy it overwrites."""

    def test_a_changed_source_adds_exactly_one_diff_to_the_files_diffs_folder(self, tmp_path: Path):
        """Modified file -> diff file appears in _diffs/ folder."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "code.py"
        src.write_text("v1", encoding="utf-8")

        # First run
        copy_versioned([(str(src), "code.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "code.py"))

        # Modify the source and stamp it ten seconds past the copy the store
        # already holds. copy_versioned decides on src_mtime != tgt_mtime, so
        # the relationship the diff depends on is stated here instead of hoped
        # for: a sleep moves nothing at all where mtimes have one-second
        # granularity, and costs the suite real time where they do not.
        src.write_text("v2", encoding="utf-8")
        newer = target.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        # Second run
        copy_versioned([(str(src), "code.py")], str(project))

        diff_dir = target.parent / f"{target.name}_diffs"
        assert diff_dir.exists()
        diffs = list(diff_dir.glob("*.diff"))
        assert len(diffs) == 1

    def test_a_changed_source_overwrites_the_current_copy_with_the_new_text(self, tmp_path: Path):
        """After change, current has new content."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "file.txt"
        src.write_text("old", encoding="utf-8")

        copy_versioned([(str(src), "file.txt")], str(project))

        target = Path(build_versioned_file_path(str(project), "file.txt"))

        # Ten seconds past the store's copy, stated rather than slept for.
        src.write_text("new", encoding="utf-8")
        newer = target.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        copy_versioned([(str(src), "file.txt")], str(project))

        assert target.read_text(encoding="utf-8") == "new"

    def test_a_changed_source_leaves_one_baseline_still_holding_the_first_text(self, tmp_path: Path):
        """Baseline is never overwritten after first creation."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "config.py"
        src.write_text("original", encoding="utf-8")

        copy_versioned([(str(src), "config.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "config.py"))

        # Ten seconds past the store's copy, stated rather than slept for.
        src.write_text("modified", encoding="utf-8")
        newer = target.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        copy_versioned([(str(src), "config.py")], str(project))

        baselines = [f for f in target.parent.iterdir() if "-baseline-" in f.name]
        assert len(baselines) == 1
        assert baselines[0].read_text(encoding="utf-8") == "original"


class TestVersionedSkip:
    """`copy_versioned` on a source whose mtime matches its stored copy — counted, not copied."""

    def test_an_unchanged_source_is_counted_unchanged_and_not_copied_again(self, tmp_path: Path):
        """File with same mtime -> files_unchanged incremented."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "stable.txt"
        src.write_text("no change", encoding="utf-8")

        copy_versioned([(str(src), "stable.txt")], str(project))

        # Green only because shutil.copy2 gave the stored copy the source's mtime
        # (versioned.py:52) and the engine skips on src_mtime == tgt_mtime (129-131).
        # Run again without modifying
        result = copy_versioned([(str(src), "stable.txt")], str(project))
        assert result["files_unchanged"] == 1
        assert result["files_copied"] == 0


class TestVersionedNeverDelete:
    """`copy_versioned` on a run that no longer lists a stored file — the stored copy stays."""

    def test_a_deleted_source_left_out_of_the_next_run_keeps_its_stored_copy_and_text(self, tmp_path: Path):
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
    """The diff generator — a unified diff for text, a marker for binary, and which file types get a diff at all."""

    def test_a_text_change_yields_a_unified_diff_with_both_headers_the_hunk_and_both_changed_lines(
        self, tmp_path: Path
    ):
        """Text files produce unified diff."""
        old = tmp_path / "old.py"
        new = tmp_path / "new.py"
        old.write_text("line1\nline2\n", encoding="utf-8")
        new.write_text("line1\nline3\n", encoding="utf-8")

        diff = generate_diff_content(old, new)

        assert "--- a/old.py" in diff
        assert "+++ b/new.py" in diff
        assert "@@ -1,2 +1,2 @@" in diff
        assert "-line2" in diff
        assert "+line3" in diff

    def test_a_binary_file_gets_the_changed_marker_instead_of_a_unified_diff(self, tmp_path: Path):
        """Binary files get marker instead of diff."""
        binary = tmp_path / "image.bin"
        binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00" + b"\x00" * 100)
        text = tmp_path / "notes.txt"
        text.write_text("line1\n", encoding="utf-8")
        assert is_binary_file(binary) is True
        assert generate_diff_content(binary, text) == "Binary file image.bin changed\n"

    def test_code_and_data_types_get_diffs_and_an_image_type_does_not(self):
        """A .py and a .json file get diffs; a .png file does not."""
        assert should_create_diff(Path("app.py")) is True
        assert should_create_diff(Path("image.png")) is False
        assert should_create_diff(Path("data.json")) is True


class TestRestore:
    """The restore handlers — writing a file-folder's current copy out, and listing what the folder holds."""

    def test_restore_file_writes_the_stored_current_copy_to_the_output_path(self, tmp_path: Path):
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

    def test_list_versions_reports_baseline_current_and_diff_after_one_change(self, tmp_path: Path):
        """list_versions finds baseline + current + diffs."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "mod.py"
        src.write_text("v1", encoding="utf-8")

        copy_versioned([(str(src), "mod.py")], str(project))

        target = Path(build_versioned_file_path(str(project), "mod.py"))

        # Ten seconds past the store's copy, stated rather than slept for. The
        # diff's own name is built from the OLD copy's mtime (versioned.py:68),
        # which this leaves untouched, so the stored timestamp stays real.
        src.write_text("v2", encoding="utf-8")
        newer = target.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        copy_versioned([(str(src), "mod.py")], str(project))

        versions = list_versions(target.parent)
        types = {v["type"] for v in versions}
        assert "baseline" in types
        assert "current" in types
        assert "diff" in types


class TestVersionedFilePath:
    """`build_versioned_file_path` — where in the store a file's folder sits, and what the folder is called."""

    def test_a_root_level_file_is_stored_under_root_in_a_folder_of_its_own_name(self):
        """Root-level file -> root/<name>/<name>."""
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "README.md"))
        # Segments below the store, not a substring of the whole path: the prefix
        # comes from tempfile.gettempdir(), which may itself contain "root".
        store = build_versioned_store(FAKE_PROJECT_ROOT)
        assert result.relative_to(store).parts == ("root", "README.md", "README.md")

    def test_a_nested_file_is_stored_under_its_parent_in_a_folder_of_its_own_name(self):
        """Nested file -> <parent>/<name>/<name>."""
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "src/main.py"))
        store = build_versioned_store(FAKE_PROJECT_ROOT)
        assert result.relative_to(store).parts == ("src", "main.py", "main.py")

    def test_a_name_over_50_chars_is_stored_in_a_folder_named_its_first_30_chars_and_md5(self):
        """Filename >50 chars -> shortened with hash."""
        long_name = "a" * 60 + ".py"
        result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, long_name))
        assert result.name == long_name
        # name[:30] + "_" + md5(name)[:8], the digest read off the product once.
        assert result.parent.name == "a" * 30 + "_96e1cede"


class TestRestoreModule:
    """The `restore` command — version discovery and file restore, the way a user reaches them."""

    # The private lookup `_find_file_folder` is reached only through what a user
    # types: `restore <project> list <file>` and `restore <project> file <file> <out>`.

    def test_restore_list_names_the_stored_versions_of_a_file(self, tmp_path: Path, capsys):
        project = tmp_path / "project"
        project.mkdir()
        src = project / "config.py"
        src.write_text("cfg = True", encoding="utf-8")
        copy_versioned([(str(src), "config.py")], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", "config.py"]) is True

        # Read on the stored filenames; the "[type]" labels are pinned by the diff-row test below.
        out, err = capsys.readouterr()
        assert "Versions of config.py:" in out
        assert "config-baseline-" in out
        # A row whose last column is the current copy's name — the heading ends "config.py:".
        assert any(row.split()[-1] == "config.py" for row in out.splitlines() if row.strip())
        assert err == ""

    def test_a_listed_diff_row_names_its_type_instead_of_losing_it_to_rich_markup(self, tmp_path: Path, capsys):
        """console.print parses markup, so "[diff]" was read as a style tag and dropped: a bare timestamp."""
        project = tmp_path / "project"
        project.mkdir()
        src = project / "mod.py"
        src.write_text("v1", encoding="utf-8")
        copy_versioned([(str(src), "mod.py")], str(project))

        # Ten seconds past the store's copy, stated rather than slept for: one
        # diff row is what this test reads, and it only exists if the engine
        # sees the second write as a change.
        stored = Path(build_versioned_file_path(str(project), "mod.py"))
        src.write_text("v2", encoding="utf-8")
        newer = stored.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        copy_versioned([(str(src), "mod.py")], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", "mod.py"]) is True

        # The diff row is the one that cannot survive the loss: baseline and
        # current repeat their type in the timestamp column, a diff row does not.
        out, err = capsys.readouterr()
        assert err == ""
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
        out, err = capsys.readouterr()
        assert f"Restored tools/main.py to {out_path}" in out
        assert err == ""

    def test_a_file_that_was_never_stored_is_named_back_and_nothing_is_written(self, tmp_path: Path, capsys):
        out_path = tmp_path / "restored" / "nonexistent.py"

        assert restore_module.run_restore_file(str(tmp_path), "nonexistent.py", str(out_path)) is False

        # Same claim as before — the user is told which file was not found —
        # restated on the channel that now carries it. The line moved from
        # console.print (stdout) to error() (stderr) so a pipe can tell a
        # failure from a restored file; nothing about the text changed.
        out, err = capsys.readouterr()
        assert "No versioned file found for: nonexistent.py" in err
        assert out == ""
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
        # The stand-in answers FROM its argument — it refuses this file's folder
        # and would succeed for any other — and records what it was handed, so a
        # module that stopped consulting restore_file, or consulted it with the
        # wrong folder or the wrong output path, cannot reach the line below.
        # A `lambda folder, out: False` could not tell those apart.
        asked: list[tuple[Path, Path]] = []

        def refuse_only_this_files_folder(file_folder: Path, output_path: Path) -> bool:
            asked.append((file_folder, output_path))
            return file_folder.name != "data.txt"

        monkeypatch.setattr(restore_module, "restore_file", refuse_only_this_files_folder)

        out_path = tmp_path / "restored" / "data.txt"
        assert restore_module.handle_command("restore", [str(project), "file", "data.txt", str(out_path)]) is True

        stored_folder = Path(build_versioned_file_path(str(project), "data.txt")).parent
        assert asked == [(stored_folder, out_path)]

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

        # Ten seconds past the store's copy, stated rather than slept for: the
        # [diff] row this test demands exists only if the engine reads the
        # second write as a change.
        stored = Path(build_versioned_file_path(str(project), long_name))
        src.write_text("v2", encoding="utf-8")
        newer = stored.stat().st_mtime + 10
        os.utime(src, (newer, newer))

        copy_versioned([(str(src), long_name)], str(project))

        assert restore_module.handle_command("restore", [str(project), "list", long_name]) is True

        out, err = capsys.readouterr()
        assert err == ""
        assert len([line for line in out.splitlines() if "[diff]" in line]) == 1
        assert "[baseline]" in out
        assert "[current]" in out

    def test_run_restore_file_writes_the_stored_text_and_names_where_it_went(self, tmp_path: Path, capsys):
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
        stdout, stderr = capsys.readouterr()
        assert f"Restored data.txt to {out}" in stdout
        assert stderr == ""

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

    def test_a_stored_folder_with_no_readable_version_is_refused_on_stderr_not_noted_on_stdout(
        self, tmp_path: Path, capsys
    ):
        """The "No versions found" line printed on stdout and left the run at exit 0, reporting success."""
        # Reaching the line is the work. `_find_file_folder` only answers with a
        # folder that HOLDS the file, and for a short name the folder is named
        # after the file, so `_stored_file` always recognises a current version
        # and the list is never empty. The one route left open is a hashed
        # folder (>50 chars: the folder is name[:30]_md5, the file keeps its
        # full name), where the current version is identified by being the only
        # non-baseline file in there. A store pruned down to its current file
        # plus one leftover has two of those, so no version is readable at all
        # while the file the user named is sitting right there -- which is why
        # the earlier `No versioned file found` guard does NOT cover this and
        # the message is the only thing the user gets.
        project = tmp_path / "project"
        project.mkdir()
        long_name = "c" * 60 + ".py"
        src = project / long_name
        src.write_text("payload", encoding="utf-8")
        copy_versioned([(str(src), long_name)], str(project))

        folder = Path(build_versioned_file_path(str(project), long_name)).parent
        for stored in folder.iterdir():
            if "-baseline-" in stored.name:
                stored.unlink()
        (folder / "leftover.tmp").write_text("half a write", encoding="utf-8")

        assert restore_module.handle_command("restore", [str(project), "list", long_name]) is True

        out, err = capsys.readouterr()
        assert f"No versions found for: {long_name}" in err
        assert "No versions found" not in out
        # The file the user asked about was found -- this is the OTHER failure,
        # and answering it with the lookup's line would send them hunting for a
        # backup that exists.
        assert "No versioned file found" not in err
        # error() marks the process failed, which resolve_exit turns into 2. On
        # console.print the same run reported success for a listing it refused.
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

        out, err = capsys.readouterr()
        assert "restore Module" in out
        assert "restore <project> list <file>" in out
        assert "restore <project> file <file> <out>" in out
        assert err == ""


# =============================================
