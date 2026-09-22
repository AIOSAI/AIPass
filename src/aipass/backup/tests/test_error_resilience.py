# =================== META ====================
# Name: test_error_resilience.py
# Description: Tests for error resilience -- corrupt JSON, missing files
# Version: 1.1.0
# Created: 2026-06-12
# Modified: 2026-09-22
# =============================================

"""Tests for src/aipass/backup/apps/modules/snapshot.py, versioned.py, and handlers."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that all handler files parse and import
# seedgo: no-test-needed(documentation) — handler docstrings
# seedgo: no-test-needed(constant) — error codes and messages
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

    def _copy_then_vanish(files: list[tuple[str, str]], *args: object, **kwargs: object) -> dict:
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

    def _filter_then_vanish(*args: object, **kwargs: object) -> list[tuple[str, str]]:
        filtered = real_filter(*args, **kwargs)
        victim.unlink()
        return filtered

    monkeypatch.setattr(snapshot, "filter_paths", _filter_then_vanish)


class TestVanishedFileRace:
    """Files deleted between scan and timestamp save (live-tree TOCTOU)."""

    def test_a_file_that_vanishes_before_the_save_is_skipped_not_raised_on(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A file gone since the scan is skipped, not raised on.

        Regression: error 33f74c75 -- another branch's pytest fixture created
        and deleted AIPASS_REGISTRY.json.test_backup at the repo root mid-run.
        The unguarded comprehension raised FileNotFoundError, which escaped
        run_snapshot and killed the whole 'all' cycle.
        """
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
        """A quick-check that could not read every mtime must not skip the run.

        The quick-check map is the stricter of the two: None, never a partial
        dict. A partial dict is a comparison made out of whichever files
        survived, and it compares EQUAL exactly when the vanished entries are
        missing from the stored map too -- the shape built below, where the
        racy file was created after the stored map was written. A forgiving
        helper would report "no changes" for a tree it never finished reading.
        """
        project = tmp_path / "proj"
        project.mkdir()
        (project / "kept.txt").write_text("x", encoding="utf-8")
        run_snapshot(str(project), show_panels=False)

        racy = project / "racy.txt"
        racy.write_text("x", encoding="utf-8")
        _vanish_after_scan(monkeypatch, racy)

        second = run_snapshot(str(project), show_panels=False)

        assert second.backup_path, "quick-check skipped a run whose mtimes it could not read"

    def test_an_unchanged_tree_does_take_the_quick_check_skip(self, tmp_path: Path) -> None:
        """The control for the pin above: with nothing vanished the skip is real.

        Without this, a quick-check that never skips anything would make the
        test above vacuously green.
        """
        project = tmp_path / "proj"
        project.mkdir()
        (project / "kept.txt").write_text("x", encoding="utf-8")
        run_snapshot(str(project), show_panels=False)

        second = run_snapshot(str(project), show_panels=False)

        assert not second.backup_path
        assert second.files_skipped == second.files_checked


class TestMissingProjectRoot:
    """A project path that does not exist must be refused, never scaffolded.

    Regression: create_backup_dir already refused a non-directory (returns
    None), but run_snapshot/run_versioned ignored that refusal and the rest of
    the pipeline created the tree anyway -- a typo'd path produced a full
    .backup/ scaffold plus a backup of the .backupignore it had just written,
    and reported success.
    """

    def test_snapshot_refuses_missing_root(self, tmp_path: Path) -> None:
        """run_snapshot on a missing path errors and writes nothing."""
        missing = tmp_path / "no_such_project"

        result = run_snapshot(str(missing), show_panels=False)

        assert result.errors, "expected an honest error, got a clean result"
        assert result.files_copied == 0
        assert not missing.exists(), "refused path must not be scaffolded"

    def test_versioned_refuses_missing_root(self, tmp_path: Path) -> None:
        """run_versioned on a missing path errors and writes nothing."""

        missing = tmp_path / "no_such_project"

        result = run_versioned(str(missing), show_panels=False)

        assert result.errors
        assert result.files_copied == 0
        assert not missing.exists()

    def test_snapshot_refuses_file_as_root(self, tmp_path: Path) -> None:
        """A file (not a directory) passed as the project root is refused."""

        a_file = tmp_path / "notadir.txt"
        a_file.write_text("x", encoding="utf-8")

        result = run_snapshot(str(a_file), show_panels=False)

        assert result.errors
        assert result.files_copied == 0

    def test_existing_project_still_runs(self, tmp_path: Path) -> None:
        """Guard does not block a real project -- normal snapshot still works."""

        project = tmp_path / "real_project"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors
        assert result.files_copied >= 1


class TestUnreadableDocumentsAreLoud:
    """A present-but-unreadable document is an error, never an empty one.

    Under the old handler ``load_json`` answered ``{}`` for a missing file AND
    for a corrupt one, so no caller could tell them apart. The registry is the
    sharpest case: ``register_project`` writes back what it read, so the empty
    answer replaced every registration in the file with the one being added.
    The fleet's ``read_json`` answers None for both; backup separates them
    here, once per document, and refuses to write over what it could not read.
    """

    def _corrupt(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")

    def test_missing_config_still_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """A project with no config yet is not an error -- absence is absence."""

        config = load_project_config(str(tmp_path))

        assert config["backup_mode"] == DEFAULTS["backup_mode"]

    def test_corrupt_config_raises(self, tmp_path: Path) -> None:
        """A corrupt config must not silently become DEFAULTS mid-backup."""

        self._corrupt(tmp_path / ".backup" / "config.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_project_config(str(tmp_path))

    def test_corrupt_registry_raises_and_survives_on_disk(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The data-loss path: a corrupt registry must never read as empty.

        Answering {} here and carrying on would have register_project write a
        one-project registry over every other registration, with no copy left.
        """

        corrupt = tmp_path / "project_registry.json"
        self._corrupt(corrupt)
        monkeypatch.setattr(registry, "REGISTRY_PATH", corrupt)

        with pytest.raises(json_handler.InvalidDocument):
            registry.register_project("newproject", str(tmp_path))

        assert corrupt.read_text(encoding="utf-8") == "{not valid json"

    def test_corrupt_changelog_raises(self, tmp_path: Path) -> None:
        """A corrupt changelog must not be overwritten with a one-entry one."""

        self._corrupt(tmp_path / ".backup" / "changelog.json")

        with pytest.raises(json_handler.InvalidDocument):
            append_changelog(str(tmp_path), {"mode": "snapshot"})

    def test_corrupt_timestamps_raises(self, tmp_path: Path) -> None:
        """A corrupt timestamp map is an error, not 'every file changed'."""

        self._corrupt(tmp_path / ".backup" / "timestamps.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))

    def test_corrupt_tracker_raises(self, tmp_path: Path) -> None:
        """A corrupt drive tracker is an error, not 'nothing uploaded yet'."""

        self._corrupt(tmp_path / ".backup" / "drive_tracker.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_tracker(str(tmp_path))

    def test_empty_file_is_unreadable_not_empty(self, tmp_path: Path) -> None:
        """empty_file / empty_content -- zero bytes is not a valid document.

        The old handler answered {} here, indistinguishable from "no config
        yet". A truncated write leaves exactly this state, so it is the one
        corruption most likely to be real.
        """

        empty = tmp_path / ".backup" / "config.json"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("", encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_project_config(str(tmp_path))

    def test_readable_but_not_an_object_raises(self, tmp_path: Path) -> None:
        """Valid JSON of the wrong shape used to reach an AttributeError."""

        ts = tmp_path / ".backup" / "timestamps.json"
        ts.parent.mkdir(parents=True, exist_ok=True)
        ts.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))


class TestWriteResultsAreChecked:
    """``write_json`` answers a bool; every backup caller reads it."""

    def test_save_project_config_reports_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """False from the primitive is False from the handler, not True."""

        monkeypatch.setattr(config.json_handler, "write_json", lambda *a, **k: False)

        assert config.save_project_config(str(tmp_path), {"backup_mode": "snapshot"}) is False

    def test_save_timestamps_raises_on_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A versioned run whose timestamps never landed is not a success."""

        monkeypatch.setattr(timestamps.json_handler, "write_json", lambda *a, **k: False)

        with pytest.raises(json_handler.WriteFailed):
            timestamps.save_timestamps(str(tmp_path), {"a.txt": 1.0})

    def test_setup_reports_a_config_it_could_not_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """create_backup_dir used to answer a path after a failed config write."""

        monkeypatch.setattr(setup.json_handler, "write_json", lambda *a, **k: False)

        assert setup.create_backup_dir(str(tmp_path)) is None


class TestAuditLog:
    """backup's own audit trail -- JSONL, not the fleet's per-module json log."""

    def test_record_shape_flattens_the_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """timestamp + operation + the operation's own fields, one line."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        trail.log_operation("probe_op", {"project_root": "/some/project"})

        stream = tmp_path / "backup" / "logs" / "operations.jsonl"
        entry = json.loads(stream.read_text(encoding="utf-8").strip())
        assert entry["operation"] == "probe_op"
        assert entry["project_root"] == "/some/project"
        assert entry["timestamp"]

    def test_the_path_is_recomputed_per_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The seam is read on every call, never captured at import.

        This is what keeps the suite off the branch's live
        logs/operations.jsonl -- the reason 37 real writes used to land there.
        """

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "first"))
        first = trail.log_path()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "second"))

        assert trail.log_path() != first

    def test_an_empty_seam_is_absence_not_a_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty env value must not redirect the stream to the cwd."""

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")

        assert trail.log_path().name == "operations.jsonl"
        assert trail.log_path().parent.parent.name == "backup"

    def test_a_failed_append_never_takes_the_backup_down(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The audit trail is a record of work, not the work."""

        def _refuse(*args: object, **kwargs: object) -> None:
            raise OSError("audit stream unwritable")

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(trail, "append_jsonl", _refuse)

        assert trail.log_operation("probe_op", {}) is None
