# =================== META ====================
# Name: test_error_resilience.py
# Description: Tests for error resilience in snapshot.py, versioned.py, the document handlers and audit trail
# Version: 1.1.2
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for error resilience in apps/modules/snapshot.py, versioned.py, the document handlers and audit trail."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that all handler files parse
# seedgo: no-test-needed(documentation) — handler docstrings
# seedgo: no-test-needed(constant) — the message each InvalidDocument carries; the tests pin the type only
# seedgo: no-test-needed(stdlib) — json module parsing and dumps

import json
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.drive.tracker import load_tracker
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.project import config, registry, setup
from aipass.backup.apps.handlers.project.config import DEFAULTS, load_project_config
from aipass.backup.apps.handlers.state import timestamps
from aipass.backup.apps.handlers.state.changelog import append_changelog
from aipass.backup.apps.handlers.state.timestamps import load_timestamps
from aipass.backup.apps.modules import snapshot
from aipass.backup.apps.modules.snapshot import run_snapshot
from aipass.backup.apps.modules.versioned import run_versioned
from aipass.cli.apps.modules import command_failed


# The live-tree race is reached through run_snapshot, at the two windows the
# product actually has: the quick-check reads mtimes straight after the scan,
# and the timestamp map is saved after the copy returns. Both seams below wrap
# a sibling handler, run the real one, and then change the tree under the run.


def _vanish_after_copy(monkeypatch: pytest.MonkeyPatch, victims: list[Path] | None = None) -> None:
    """Delete files from the live tree once the copy has taken them.

    run_snapshot saves the timestamp map AFTER copy_snapshot returns, so a file
    the scan listed can already be gone by the time its mtime is read. With no
    victims named, every file the copy was handed vanishes.
    """
    real_copy = snapshot.copy_snapshot

    def _copy_then_vanish(files: list[tuple[str, str]], *args, **kwargs) -> dict:
        outcome = real_copy(files, *args, **kwargs)
        doomed = victims if victims is not None else [Path(abs_p) for abs_p, _rel in files]
        for path in doomed:
            path.unlink()
        return outcome

    monkeypatch.setattr(snapshot, "copy_snapshot", _copy_then_vanish)


def _vanish_after_scan(monkeypatch: pytest.MonkeyPatch, victim: Path) -> None:
    """Delete a file the moment the scan has listed it, before the quick-check.

    This is the earlier window: the quick-check builds its mtime map from the
    filtered list, so a file that dies here is one the comparison cannot read.
    """
    real_filter = snapshot.filter_paths

    def _filter_then_vanish(*args, **kwargs) -> list[tuple[str, str]]:
        filtered = real_filter(*args, **kwargs)
        victim.unlink()
        return filtered

    monkeypatch.setattr(snapshot, "filter_paths", _filter_then_vanish)


class TestVanishedFileRace:
    """Files deleted between scan and timestamp save (live-tree TOCTOU)."""

    def test_a_file_that_vanishes_before_the_save_is_skipped_not_raised_on(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A file gone since the scan is skipped, not raised on."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "here.txt").write_text("x", encoding="utf-8")
        (project / "vanished.txt").write_text("x", encoding="utf-8")
        _vanish_after_copy(monkeypatch, [project / "vanished.txt"])

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors, "the vanished file escaped as an error"
        saved = load_timestamps(str(project))
        assert "here.txt" in saved
        assert "vanished.txt" not in saved

    def test_every_file_vanishing_persists_an_empty_map_and_still_never_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Every file gone -- an empty map is persisted, the run still completes."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "gone.txt").write_text("x", encoding="utf-8")
        _vanish_after_copy(monkeypatch)

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors
        assert load_timestamps(str(project)) == {}

    def test_an_unreadable_mtime_forbids_the_quick_check_skip(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A quick-check that could not read every mtime must not skip the run."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "kept.txt").write_text("x", encoding="utf-8")
        run_snapshot(str(project), show_panels=False)

        # racy.txt is absent from the stored map, so a partial mtime map built
        # from the survivors would compare EQUAL to it and wrongly skip.
        racy = project / "racy.txt"
        racy.write_text("x", encoding="utf-8")
        _vanish_after_scan(monkeypatch, racy)

        second = run_snapshot(str(project), show_panels=False)

        assert second.backup_path, "quick-check skipped a run whose mtimes it could not read"

    def test_an_unchanged_tree_does_take_the_quick_check_skip(self, tmp_path: Path) -> None:
        """The control for the pin above: with nothing vanished the skip is real."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "kept.txt").write_text("x", encoding="utf-8")
        run_snapshot(str(project), show_panels=False)

        second = run_snapshot(str(project), show_panels=False)

        assert not second.backup_path
        assert second.files_skipped == second.files_checked


class TestMissingProjectRoot:
    """A project path that does not exist must be refused, never scaffolded."""

    def test_snapshot_on_a_missing_root_errors_and_scaffolds_nothing(self, tmp_path: Path) -> None:
        """run_snapshot on a missing path errors and writes nothing."""
        missing = tmp_path / "no_such_project"

        result = run_snapshot(str(missing), show_panels=False)

        assert result.errors, "expected an honest error, got a clean result"
        assert result.files_copied == 0
        assert not missing.exists(), "refused path must not be scaffolded"

    def test_versioned_on_a_missing_root_errors_and_scaffolds_nothing(self, tmp_path: Path) -> None:
        """run_versioned on a missing path errors and writes nothing."""

        missing = tmp_path / "no_such_project"

        result = run_versioned(str(missing), show_panels=False)

        assert result.errors
        assert result.files_copied == 0
        assert not missing.exists()

    def test_snapshot_on_a_file_as_root_errors_and_copies_nothing(self, tmp_path: Path) -> None:
        """A file (not a directory) passed as the project root is refused."""

        a_file = tmp_path / "notadir.txt"
        a_file.write_text("x", encoding="utf-8")

        result = run_snapshot(str(a_file), show_panels=False)

        assert result.errors
        assert result.files_copied == 0

    def test_an_existing_project_root_is_not_refused_and_is_copied(self, tmp_path: Path) -> None:
        """Guard does not block a real project -- normal snapshot still works."""

        project = tmp_path / "real_project"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors
        assert result.files_copied >= 1


class TestUnreadableDocumentsAreLoud:
    """A present-but-unreadable document is an error, never an empty one."""

    def _corrupt(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")

    def test_missing_config_still_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """A project with no config yet is not an error -- absence is absence."""

        loaded = load_project_config(str(tmp_path))

        assert loaded["backup_mode"] == DEFAULTS["backup_mode"]

    def test_a_corrupt_config_raises_never_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """A corrupt config must not silently become DEFAULTS mid-backup."""

        self._corrupt(tmp_path / ".backup" / "config.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_project_config(str(tmp_path))

    def test_corrupt_registry_raises_and_survives_on_disk(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A corrupt registry raises and is left as it was, never rewritten as one project."""

        corrupt = tmp_path / "project_registry.json"
        self._corrupt(corrupt)
        monkeypatch.setattr(registry, "REGISTRY_PATH", corrupt)

        with pytest.raises(json_handler.InvalidDocument):
            registry.register_project("newproject", str(tmp_path))

        assert corrupt.read_text(encoding="utf-8") == "{not valid json"

    def test_a_corrupt_changelog_raises_never_starts_a_fresh_one(self, tmp_path: Path) -> None:
        """A corrupt changelog must not be overwritten with a one-entry one."""

        self._corrupt(tmp_path / ".backup" / "changelog.json")

        with pytest.raises(json_handler.InvalidDocument):
            append_changelog(str(tmp_path), {"mode": "snapshot"})

    def test_a_corrupt_timestamp_map_raises_never_reads_as_empty(self, tmp_path: Path) -> None:
        """A corrupt timestamp map is an error, not 'every file changed'."""

        self._corrupt(tmp_path / ".backup" / "timestamps.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))

    def test_a_corrupt_drive_tracker_raises_never_reads_as_nothing_uploaded(self, tmp_path: Path) -> None:
        """A corrupt drive tracker is an error, not 'nothing uploaded yet'."""

        self._corrupt(tmp_path / ".backup" / "drive_tracker.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_tracker(str(tmp_path))

    def test_empty_file_is_unreadable_not_empty(self, tmp_path: Path) -> None:
        """Zero bytes, the state a truncated write leaves, is not a valid document."""

        empty = tmp_path / ".backup" / "config.json"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("", encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_project_config(str(tmp_path))

    def test_valid_json_that_is_not_an_object_raises_invalid_document(self, tmp_path: Path) -> None:
        """Valid JSON of the wrong shape is an InvalidDocument, never an AttributeError."""

        ts = tmp_path / ".backup" / "timestamps.json"
        ts.parent.mkdir(parents=True, exist_ok=True)
        ts.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))


class TestWriteResultsAreChecked:
    """``write_json`` answers a bool; every backup caller reads it."""

    def test_save_project_config_reports_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """False from the primitive is False from the handler, not True."""

        attempted: list[tuple[Path, object]] = []

        # The stand-in answers per document instead of always False: only the
        # project's own config.json is refused, so a handler that wrote to any
        # other path would be told True and the False below could not come from
        # anywhere but the document this handler is named for.
        def _refuse_only_the_config(file_path: Path, data: object, *a: object, **k: object) -> bool:
            attempted.append((Path(file_path), data))
            return Path(file_path).name != "config.json"

        monkeypatch.setattr(config.json_handler, "write_json", _refuse_only_the_config)

        assert config.save_project_config(str(tmp_path), {"backup_mode": "snapshot"}) is False
        assert attempted == [(tmp_path / ".backup" / "config.json", {"backup_mode": "snapshot"})]

    def test_save_timestamps_raises_on_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """False from the primitive is WriteFailed from save_timestamps, never a quiet return."""

        attempted: list[tuple[Path, object]] = []

        def _refuse_only_the_map(file_path: Path, data: object, *a: object, **k: object) -> bool:
            attempted.append((Path(file_path), data))
            return Path(file_path).name != "timestamps.json"

        monkeypatch.setattr(timestamps.json_handler, "write_json", _refuse_only_the_map)

        with pytest.raises(json_handler.WriteFailed):
            timestamps.save_timestamps(str(tmp_path), {"a.txt": 1.0})

        assert attempted == [(tmp_path / ".backup" / "timestamps.json", {"a.txt": 1.0})]

    def test_setup_reports_a_config_it_could_not_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """create_backup_dir used to answer a path after a failed config write."""

        attempted: list[Path] = []

        def _refuse_only_the_config(file_path: Path, *a: object, **k: object) -> bool:
            attempted.append(Path(file_path))
            return Path(file_path).name != "config.json"

        monkeypatch.setattr(setup.json_handler, "write_json", _refuse_only_the_config)

        assert setup.create_backup_dir(str(tmp_path)) is None
        assert attempted == [tmp_path / ".backup" / "config.json"]


class TestACompletedCopyIsAlwaysRecorded:
    """A completed copy is recorded in the changelog and audit trail even when the timestamp map is lost.

    The record is written first and the map's failure is reported after it.
    """

    def test_a_failed_timestamp_write_still_records_the_copy_and_reports_the_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Copy done, map refused: changelog, trail, stderr and the result all say so."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        refused: list[Path] = []
        real_write = timestamps.json_handler.write_json

        # Refuses the timestamp map and DELEGATES every other document to the
        # real primitive, so the changelog asserted below is one the product
        # actually wrote. A blanket False, or a blanket True that writes
        # nothing, would prove nothing about the ordering this pins.
        def _refuse_only_the_map(file_path: Path, data: object, indent: int = 2) -> bool:
            if Path(file_path).name != "timestamps.json":
                return real_write(file_path, data, indent)
            refused.append(Path(file_path))
            return False

        monkeypatch.setattr(timestamps.json_handler, "write_json", _refuse_only_the_map)

        result = run_snapshot(str(project), show_panels=False)
        out, err = capsys.readouterr()

        assert refused == [project / ".backup" / "timestamps.json"]
        assert (Path(result.backup_path) / "code.py").read_text(encoding="utf-8") == "print('hi')"
        # code.py plus the .backupignore create_backup_dir writes for a new project.
        assert "Processing completed: 2/2 files checked" in out

        entries = json.loads((project / ".backup" / "changelog.json").read_text(encoding="utf-8"))["entries"]
        assert [entry["mode"] for entry in entries] == ["snapshot"], "the changelog forgot a completed copy"
        assert entries[-1]["files_copied"] == 2

        recorded = [
            json.loads(line)["operation"]
            for line in trail.log_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert "snapshot_complete" in recorded, "the audit trail forgot a completed copy"
        assert "snapshot_timestamps_failed" in recorded, "the lost map was never recorded"

        assert "timestamp map" in err, "the lost map was never reported to the user"
        assert [e for e in result.errors if "timestamp map" in e] == result.errors
        assert result.errors, "a run that lost its timestamp map answered a clean result"
        assert result.success is False
        assert command_failed() is True, "the lost map did not fail the command"

    def test_a_clean_run_records_the_copy_without_the_failure_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The control: with the map written, no failure is reported anywhere."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        result = run_snapshot(str(project), show_panels=False)
        _out, err = capsys.readouterr()

        saved = load_timestamps(str(project))
        assert sorted(saved) == [".backupignore", "code.py"]
        assert saved["code.py"] == (project / "code.py").stat().st_mtime
        assert not result.errors
        assert "timestamp map" not in err
        assert command_failed() is False

        recorded = [
            json.loads(line)["operation"]
            for line in trail.log_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert "snapshot_complete" in recorded
        assert "snapshot_timestamps_failed" not in recorded


class TestAuditLog:
    """backup's own audit trail -- JSONL, not the fleet's per-module json log."""

    def test_record_shape_flattens_the_payload(self, tmp_path: Path) -> None:
        """timestamp + operation + the operation's own fields, one line."""
        stream = trail.log_path()
        assert stream.is_relative_to(tmp_path.parent), f"conftest's seam did not hold: {stream}"
        project_root = str(tmp_path / "proj")
        trail.log_operation("probe_op", {"project_root": project_root})

        entry = json.loads(stream.read_text(encoding="utf-8").strip())
        assert entry["operation"] == "probe_op"
        assert entry["project_root"] == project_root
        assert entry["timestamp"]

    def test_the_path_is_recomputed_per_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The seam is read on every call, never captured at import."""

        first, second = tmp_path / "first", tmp_path / "second"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(first))
        assert trail.log_path() == first / trail.BRANCH_NAME / "logs" / trail.LOG_FILENAME
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(second))

        assert trail.log_path() == second / trail.BRANCH_NAME / "logs" / trail.LOG_FILENAME

    def test_an_empty_seam_is_absence_not_a_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty env value must not redirect the stream to the cwd."""

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")

        assert trail.log_path().name == "operations.jsonl"
        assert trail.log_path().parent.parent.name == "backup"

    def test_an_empty_seam_answers_the_branch_absolute_path_never_a_relative_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Absence falls back to the branch's OWN stream, spelled absolutely."""

        # Kills ``if test_dir is not None:``, under which an empty seam answers
        # the RELATIVE backup/logs/operations.jsonl, written into whatever the cwd is.
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")
        absent = trail.log_path()

        assert absent.is_absolute(), f"an empty seam answered a relative path: {absent}"
        assert absent == trail.branch_root(trail.__file__, 3) / "logs" / trail.LOG_FILENAME

        redirected = tmp_path / "seam"
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(redirected))

        assert trail.log_path() == redirected / trail.BRANCH_NAME / "logs" / trail.LOG_FILENAME

    def test_a_failed_append_never_takes_the_backup_down(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With every audit append refused, a real run still copies and answers clean; each refusal warns."""

        attempted: list[Path] = []
        warned: list[str] = []

        def _refuse(path: Path, *args: object, **kwargs: object) -> None:
            attempted.append(Path(path))
            raise OSError("audit stream unwritable")

        class _WarningRecorder:
            """Stands in for the module's logger to catch what it records."""

            def warning(self, message: object, *args: object, **kwargs: object) -> None:
                warned.append(str(message))

        project = tmp_path / "proj"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        monkeypatch.setattr(trail, "append_jsonl", _refuse)
        monkeypatch.setattr(trail, "logger", _WarningRecorder())

        assert trail.log_operation("probe_op", {}) is None
        probe_attempts = len(attempted)

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors
        assert (Path(result.backup_path) / "code.py").read_text(encoding="utf-8") == "print('hi')"
        assert len(attempted) > probe_attempts, "the run never reached the audit stream"
        assert warned.count("Failed to write operation log: audit stream unwritable") == len(attempted)
