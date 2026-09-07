# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Tests for error resilience -- corrupt JSON, missing files
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Test error resilience -- file not found, corrupt JSON, empty files, bad paths."""

from pathlib import Path

import pytest

from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.modules.snapshot import _build_current_timestamps, _build_saved_timestamps


class TestVanishedFileRace:
    """Files deleted between scan and timestamp save (live-tree TOCTOU)."""

    def test_saved_timestamps_skip_vanished_file(self, tmp_path: Path) -> None:
        """A file gone since the scan is skipped, not raised on.

        Regression: error 33f74c75 -- another branch's pytest fixture created
        and deleted AIPASS_REGISTRY.json.test_backup at the repo root mid-run.
        The unguarded comprehension raised FileNotFoundError, which escaped
        run_snapshot and killed the whole 'all' cycle.
        """
        real = tmp_path / "here.txt"
        real.write_text("x", encoding="utf-8")
        filtered = [
            (str(real), "here.txt"),
            (str(tmp_path / "vanished.txt"), "vanished.txt"),
        ]

        timestamps = _build_saved_timestamps(filtered)

        assert "here.txt" in timestamps
        assert "vanished.txt" not in timestamps

    def test_saved_timestamps_all_vanished(self, tmp_path: Path) -> None:
        """Every file gone -- returns empty dict, still never raises."""
        filtered = [(str(tmp_path / "gone.txt"), "gone.txt")]

        assert _build_saved_timestamps(filtered) == {}

    def test_quick_check_still_invalidates_on_missing(self, tmp_path: Path) -> None:
        """The quick-check helper keeps its stricter contract: None, not a partial dict.

        A partial dict would compare unequal to the stored one and silently
        force a full re-copy; None is the explicit 'cannot compare' signal.
        """
        filtered = [(str(tmp_path / "gone.txt"), "gone.txt")]

        assert _build_current_timestamps(filtered) is None


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
        from aipass.backup.apps.modules.snapshot import run_snapshot

        missing = tmp_path / "no_such_project"

        result = run_snapshot(str(missing), show_panels=False)

        assert result.errors, "expected an honest error, got a clean result"
        assert result.files_copied == 0
        assert not missing.exists(), "refused path must not be scaffolded"

    def test_versioned_refuses_missing_root(self, tmp_path: Path) -> None:
        """run_versioned on a missing path errors and writes nothing."""
        from aipass.backup.apps.modules.versioned import run_versioned

        missing = tmp_path / "no_such_project"

        result = run_versioned(str(missing), show_panels=False)

        assert result.errors
        assert result.files_copied == 0
        assert not missing.exists()

    def test_snapshot_refuses_file_as_root(self, tmp_path: Path) -> None:
        """A file (not a directory) passed as the project root is refused."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

        a_file = tmp_path / "notadir.txt"
        a_file.write_text("x", encoding="utf-8")

        result = run_snapshot(str(a_file), show_panels=False)

        assert result.errors
        assert result.files_copied == 0

    def test_existing_project_still_runs(self, tmp_path: Path) -> None:
        """Guard does not block a real project -- normal snapshot still works."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

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
        from aipass.backup.apps.handlers.project.config import DEFAULTS, load_project_config

        config = load_project_config(str(tmp_path))

        assert config["backup_mode"] == DEFAULTS["backup_mode"]

    def test_corrupt_config_raises(self, tmp_path: Path) -> None:
        """A corrupt config must not silently become DEFAULTS mid-backup."""
        from aipass.backup.apps.handlers.project.config import load_project_config

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
        from aipass.backup.apps.handlers.project import registry

        corrupt = tmp_path / "project_registry.json"
        self._corrupt(corrupt)
        monkeypatch.setattr(registry, "REGISTRY_PATH", corrupt)

        with pytest.raises(json_handler.InvalidDocument):
            registry.register_project("newproject", str(tmp_path))

        assert corrupt.read_text(encoding="utf-8") == "{not valid json"

    def test_corrupt_changelog_raises(self, tmp_path: Path) -> None:
        """A corrupt changelog must not be overwritten with a one-entry one."""
        from aipass.backup.apps.handlers.state.changelog import append_changelog

        self._corrupt(tmp_path / ".backup" / "changelog.json")

        with pytest.raises(json_handler.InvalidDocument):
            append_changelog(str(tmp_path), {"mode": "snapshot"})

    def test_corrupt_timestamps_raises(self, tmp_path: Path) -> None:
        """A corrupt timestamp map is an error, not 'every file changed'."""
        from aipass.backup.apps.handlers.state.timestamps import load_timestamps

        self._corrupt(tmp_path / ".backup" / "timestamps.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))

    def test_corrupt_tracker_raises(self, tmp_path: Path) -> None:
        """A corrupt drive tracker is an error, not 'nothing uploaded yet'."""
        from aipass.backup.apps.handlers.drive.tracker import load_tracker

        self._corrupt(tmp_path / ".backup" / "drive_tracker.json")

        with pytest.raises(json_handler.InvalidDocument):
            load_tracker(str(tmp_path))

    def test_empty_file_is_unreadable_not_empty(self, tmp_path: Path) -> None:
        """empty_file / empty_content -- zero bytes is not a valid document.

        The old handler answered {} here, indistinguishable from "no config
        yet". A truncated write leaves exactly this state, so it is the one
        corruption most likely to be real.
        """
        from aipass.backup.apps.handlers.project.config import load_project_config

        empty = tmp_path / ".backup" / "config.json"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("", encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_project_config(str(tmp_path))

    def test_readable_but_not_an_object_raises(self, tmp_path: Path) -> None:
        """Valid JSON of the wrong shape used to reach an AttributeError."""
        from aipass.backup.apps.handlers.state.timestamps import load_timestamps

        ts = tmp_path / ".backup" / "timestamps.json"
        ts.parent.mkdir(parents=True, exist_ok=True)
        ts.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(json_handler.InvalidDocument):
            load_timestamps(str(tmp_path))


class TestWriteResultsAreChecked:
    """``write_json`` answers a bool; every backup caller reads it."""

    def test_save_project_config_reports_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """False from the primitive is False from the handler, not True."""
        from aipass.backup.apps.handlers.project import config

        monkeypatch.setattr(config.json_handler, "write_json", lambda *a, **k: False)

        assert config.save_project_config(str(tmp_path), {"backup_mode": "snapshot"}) is False

    def test_save_timestamps_raises_on_a_failed_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A versioned run whose timestamps never landed is not a success."""
        from aipass.backup.apps.handlers.state import timestamps

        monkeypatch.setattr(timestamps.json_handler, "write_json", lambda *a, **k: False)

        with pytest.raises(json_handler.WriteFailed):
            timestamps.save_timestamps(str(tmp_path), {"a.txt": 1.0})

    def test_setup_reports_a_config_it_could_not_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """create_backup_dir used to answer a path after a failed config write."""
        from aipass.backup.apps.handlers.project import setup

        monkeypatch.setattr(setup.json_handler, "write_json", lambda *a, **k: False)

        assert setup.create_backup_dir(str(tmp_path)) is None


class TestAuditLog:
    """backup's own audit trail -- JSONL, not the fleet's per-module json log."""

    def test_record_shape_flattens_the_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """timestamp + operation + the operation's own fields, one line."""
        import json

        from aipass.backup.apps.handlers.audit import trail

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
        from aipass.backup.apps.handlers.audit import trail

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "first"))
        first = trail.log_path()
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "second"))

        assert trail.log_path() != first

    def test_an_empty_seam_is_absence_not_a_redirect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty env value must not redirect the stream to the cwd."""
        from aipass.backup.apps.handlers.audit import trail

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", "")

        assert trail.log_path().name == "operations.jsonl"
        assert trail.log_path().parent.parent.name == "backup"

    def test_a_failed_append_never_takes_the_backup_down(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The audit trail is a record of work, not the work."""
        from aipass.backup.apps.handlers.audit import trail

        def _refuse(*args: object, **kwargs: object) -> None:
            raise OSError("audit stream unwritable")

        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        monkeypatch.setattr(trail, "append_jsonl", _refuse)

        assert trail.log_operation("probe_op", {}) is None
