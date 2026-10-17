# =================== AIPass ====================
# Name: test_drive_snapshot_lane.py
# Description: Tests for the Drive lane's source store, tracker lane stamp, never-leaves floor and Drive headroom
# Version: 1.2.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/modules/drive_sync.py: the snapshot store it uploads, the tracker lane, the floor and the headroom."""

# A second file for drive_sync, split by behaviour (template item 19):
# test_drive_pipeline.py sits near the 1,500-line cap, and the three behaviours
# DPLAN-0411 added to the lane -- which store leaves the machine, which tracker
# answers for it, and what is refused on the way out -- read as one unit here.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the literal string of SET_ASIDE_FILENAME, read by name below

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import DEFAULT, MagicMock

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import tracker as drive_tracker
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.state.changelog import load_changelog
from aipass.backup.apps.modules import display, drive_sync, status
from aipass.cli.apps.modules import command_failed

# conftest's autouse sealed_google_edge seals both doors to the real account;
# the DriveClient below is a MagicMock that talks to nobody.


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[list[Path]]:
    """Record the batches drive_sync hands to the upload engine, and send none of them."""
    batches: list[list[Path]] = []

    def _record(client, files, project_name, backup_root, tracker, **kwargs) -> dict:
        """Stand in for upload_batch: keep the files, report them all uploaded."""
        batches.append(list(files))
        return {"success": True, "uploaded": len(files), "failed": 0, "bytes_uploaded": 0}

    monkeypatch.setattr(drive_upload, "upload_batch", _record)
    return batches


#: An account with room for anything these tests upload: 15 GiB free.
ROOMY = {"storageQuota": {"usage": "0", "limit": str(15 * 1024**3)}}


def _offline_client(monkeypatch: pytest.MonkeyPatch, quota: dict | None = ROOMY) -> MagicMock:
    """Put a DriveClient that talks to nobody where the late import looks for one.

    The about.get request answers with ``quota``; every other request answers
    with ``_api_call.return_value``, which a test may set.
    """
    instance = MagicMock(name="DriveClient")
    instance.authenticate.return_value = True
    instance.last_error = None
    instance.file_tracker = {}
    about_request = instance.drive_service.about.return_value.get.return_value
    instance._api_call.side_effect = lambda request, *args, **kwargs: quota if request is about_request else DEFAULT
    monkeypatch.setattr(drive_client, "DriveClient", MagicMock(return_value=instance))
    return instance


def _seed(root: Path, rels: tuple[str, ...]) -> None:
    """Write one small file at each relative path under root."""
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x", encoding="utf-8")


def _tracker_doc(project: Path, name: str = drive_tracker.TRACKER_FILENAME) -> dict:
    """The tracker document on disk, as JSON."""
    return json.loads((project / ".backup" / name).read_text(encoding="utf-8"))


class TestTheLaneUploadsTheSnapshotStore:
    """drive_sync reads .backup/snapshots/, and the versioned store never leaves the machine."""

    def test_the_snapshot_store_is_uploaded_and_the_versioned_store_is_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("src/app.py", "notes.txt"))
        _seed(project / ".backup" / "versioned", ("old.txt/old.txt",))
        _offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        snapshots = project / ".backup" / "snapshots"
        assert result["location"] == str(snapshots)
        assert sorted(f.relative_to(snapshots).as_posix() for f in uploads[0]) == ["notes.txt", "src/app.py"]

    def test_the_project_root_reaches_the_upload_engine_so_its_periodic_tracker_save_can_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        _offline_client(monkeypatch)
        handed: list = []

        def _record(client, files, project_name, backup_root, tracker, **kwargs) -> dict:
            """Stand in for upload_batch: keep the project root it was handed."""
            handed.append(kwargs.get("project_root"))
            return {"success": True, "uploaded": len(files), "failed": 0, "bytes_uploaded": 0}

        monkeypatch.setattr(drive_upload, "upload_batch", _record)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        assert handed == [str(project)]

    def test_a_project_with_only_a_versioned_store_names_the_missing_snapshot_and_uploads_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "versioned", ("old.txt/old.txt",))
        _offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False
        assert result["error"] == f"Snapshot store not found: {project / '.backup' / 'snapshots'}"
        assert uploads == []

    def test_files_land_under_the_projects_snapshot_folder_on_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The real upload engine runs; only the client's folder calls are recorded.
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("src/app.py", "notes.txt"))
        client = _offline_client(monkeypatch)
        client.get_or_create_project_folder.return_value = "proj_folder"
        client.get_or_create_nested_folder.side_effect = lambda parent, path: f"folder:{Path(path).as_posix()}"
        client._api_call.return_value = {"id": "drive_id"}

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["uploaded"] == 2 and result["failed"] == 0
        client.get_or_create_project_folder.assert_called_with("project")
        nested = sorted(Path(c.args[1]).as_posix() for c in client.get_or_create_nested_folder.call_args_list)
        assert nested == ["snapshot", "snapshot/src"]
        tracked = _tracker_doc(project)
        assert sorted(k for k in tracked if k != drive_tracker.LANE_KEY) == ["notes.txt", str(Path("src/app.py"))]


class TestTheTrackerAnswersForOneLane:
    """The tracker carries the lane it tracks; a tracker from another lane is set aside, never deleted."""

    def test_a_saved_tracker_is_stamped_with_the_snapshot_lane(self, tmp_path: Path) -> None:
        drive_tracker.save_tracker(str(tmp_path), {"a.txt": {"drive_id": "x"}})

        assert _tracker_doc(tmp_path) == {"_lane": "snapshot", "a.txt": {"drive_id": "x"}}
        assert drive_tracker.load_tracker(str(tmp_path)) == {"a.txt": {"drive_id": "x"}}

    def test_an_unstamped_versioned_era_tracker_is_set_aside_and_a_fresh_one_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        old = {"a.txt/a.txt": {"drive_id": "versioned_id", "local_size": 1, "local_mtime": 1.0}}
        (project / ".backup" / drive_tracker.TRACKER_FILENAME).write_text(json.dumps(old), encoding="utf-8")
        recorder = MagicMock(name="logger")
        monkeypatch.setattr(drive_tracker, "logger", recorder)
        _offline_client(monkeypatch)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        assert _tracker_doc(project, drive_tracker.SET_ASIDE_FILENAME) == old
        assert _tracker_doc(project) == {"_lane": "snapshot"}
        assert [f.name for f in uploads[0]] == ["a.txt"]
        set_aside_lines = [c.args[0] for c in recorder.info.call_args_list if "set aside" in c.args[0]]
        assert len(set_aside_lines) == 1, recorder.info.call_args_list

    def test_a_tracker_stamped_with_another_lane_is_set_aside_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        old = {"_lane": "versioned", "a.txt/a.txt": {"drive_id": "versioned_id"}}
        (project / ".backup" / drive_tracker.TRACKER_FILENAME).write_text(json.dumps(old), encoding="utf-8")
        _offline_client(monkeypatch)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        assert _tracker_doc(project, drive_tracker.SET_ASIDE_FILENAME) == old

    def test_a_snapshot_tracker_is_kept_and_its_unchanged_files_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        stat = (project / ".backup" / "snapshots" / "a.txt").stat()
        entry = {"drive_id": "d", "local_size": stat.st_size, "local_mtime": stat.st_mtime}
        doc = {"_lane": "snapshot", "a.txt": entry}
        (project / ".backup" / drive_tracker.TRACKER_FILENAME).write_text(json.dumps(doc), encoding="utf-8")
        _offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["skipped"] == 1 and uploads == []
        assert not (project / ".backup" / drive_tracker.SET_ASIDE_FILENAME).exists()

    def test_an_earlier_set_aside_is_never_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        earlier = {"kept.txt/kept.txt": {"drive_id": "earlier"}}
        foreign = {"b.txt/b.txt": {"drive_id": "foreign"}}
        (project / ".backup" / drive_tracker.SET_ASIDE_FILENAME).write_text(json.dumps(earlier), encoding="utf-8")
        (project / ".backup" / drive_tracker.TRACKER_FILENAME).write_text(json.dumps(foreign), encoding="utf-8")
        _offline_client(monkeypatch)

        with pytest.raises(json_handler.WriteFailed, match="already exists"):
            drive_sync.run_drive_sync(str(project), show_panels=False)

        assert _tracker_doc(project, drive_tracker.SET_ASIDE_FILENAME) == earlier
        assert _tracker_doc(project) == foreign
        assert uploads == []


class TestTheRunIsReadByStatus:
    """A run that uploads leaves one drive_sync changelog entry, which status --json reads as the lane's last run."""

    def test_a_run_that_uploads_leaves_the_drive_lane_non_null_in_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("src/app.py", "notes.txt", "kept.txt"))
        # One file is already on Drive: the entry counts what this run uploaded, not the store.
        stat = (project / ".backup" / "snapshots" / "kept.txt").stat()
        drive_tracker.save_tracker(
            str(project), {"kept.txt": {"drive_id": "d", "local_size": stat.st_size, "local_mtime": stat.st_mtime}}
        )
        _offline_client(monkeypatch)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        entries = load_changelog(str(project))
        assert [(e["mode"], e["files_copied"]) for e in entries] == [("drive_sync", 2)]
        lane = status.build_status(str(project))["lanes"]["drive_sync"]
        assert lane == {"last": entries[0]["timestamp"], "files": 2}

    def test_a_run_with_a_failed_upload_writes_no_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt", "b.txt"))
        _offline_client(monkeypatch)
        partial = {"success": False, "uploaded": 1, "failed": 1, "bytes_uploaded": 0}
        monkeypatch.setattr(drive_upload, "upload_batch", lambda *args, **kwargs: partial)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        assert load_changelog(str(project)) == []

    def test_a_run_with_everything_up_to_date_writes_no_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        # The snapshot lane's rule: a run that found nothing to copy writes no entry.
        project = tmp_path / "project"
        _seed(project / ".backup" / "snapshots", ("a.txt",))
        stat = (project / ".backup" / "snapshots" / "a.txt").stat()
        drive_tracker.save_tracker(
            str(project), {"a.txt": {"drive_id": "d", "local_size": stat.st_size, "local_mtime": stat.st_mtime}}
        )
        _offline_client(monkeypatch)

        drive_sync.run_drive_sync(str(project), show_panels=False)

        assert uploads == [] and load_changelog(str(project)) == []


class TestTheNeverLeavesFloor:
    """Secrets and the host token store are held back from Drive, whatever .backupignore says."""

    HELD = (
        ".secrets/token.txt",
        "deep/dir/.secrets/creds.json",
        "server.key",
        "certs/site.pem",
        ".env",
        "app/.env.local",
        "api_json/tokens_data.json",
        "api_json/tokens_config.json",
        "src/aipass/api/api_json/tokens_data.json",
        "src/aipass/api/api_json/tokens_config.json",
    )
    SENT = ("keep.txt", "env.py", "secrets.md", "api_json/other.json")

    def test_floored_files_are_counted_and_never_uploaded_and_stay_in_the_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        snapshots = project / ".backup" / "snapshots"
        _seed(snapshots, self.HELD + self.SENT)
        recorder = MagicMock(name="logger")
        monkeypatch.setattr(drive_sync, "logger", recorder)
        _offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert sorted(f.relative_to(snapshots).as_posix() for f in uploads[0]) == sorted(self.SENT)
        assert result["held_back"] == len(self.HELD) and result["total"] == len(self.SENT)
        floor_lines = [c.args[0] for c in recorder.info.call_args_list if "never-leaves" in c.args[0]]
        assert floor_lines == [f"[backup] Drive sync: held back {len(self.HELD)} files the never-leaves floor matches"]
        assert all((snapshots / rel).is_file() for rel in self.HELD)

    def test_a_backupignore_negation_cannot_reopen_the_floor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        snapshots = project / ".backup" / "snapshots"
        _seed(snapshots, ("server.key", "keep.txt"))
        (project / ".backupignore").write_text("*.key\n!server.key\n", encoding="utf-8")
        _offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert [f.name for f in uploads[0]] == ["keep.txt"]
        assert result["held_back"] == 1


#: Three files of 1000, 1000 and 970 bytes: 2,970 bytes, "2.9 KB" through the branch's one humaniser.
SIZES = {"a.txt": 1000, "b.txt": 1000, "c.txt": 970}


def _sized_store(project: Path) -> None:
    """A snapshot store holding SIZES' files at their exact sizes."""
    store = project / ".backup" / "snapshots"
    store.mkdir(parents=True)
    for name, size in SIZES.items():
        (store / name).write_text("x" * size, encoding="utf-8")


def _quota(usage: int, limit: int | None) -> dict:
    """about.get's answer, numbers as strings the way Drive sends them; no limit key when limit is None."""
    quota = {"usage": str(usage)}
    if limit is not None:
        quota["limit"] = str(limit)
    return {"storageQuota": quota}


def _main(argv: list[str]) -> int:
    """Run the real entry point with argv."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["backup", *argv])
        return entry.main()


@pytest.fixture
def quiet_headers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the panel titles instead of drawing them."""
    # header() fires @cli's event bus; replaced where display binds it, so nothing fires.
    titles: list[str] = []
    monkeypatch.setattr(display, "header", lambda title, *args, **kwargs: titles.append(title))
    return titles


class TestTheRunMustFitTheDrive:
    """drive_sync weighs what it is about to upload against the account's free space before the first upload."""

    REFUSAL = "Drive has 1.4 KB free; this run needs 2.9 KB. Nothing uploaded."

    def test_a_run_that_does_not_fit_uploads_nothing_ends_on_the_one_sentence_and_exits_non_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=8566, limit=10000))

        assert _main(["drive_sync", str(project)]) == 2

        out = capsys.readouterr().out
        assert out.splitlines()[-1] == self.REFUSAL
        assert uploads == []
        assert load_changelog(str(project)) == []
        assert not (project / ".backup" / drive_tracker.TRACKER_FILENAME).exists()

    def test_a_quiet_run_that_does_not_fit_still_says_the_sentence_and_is_not_a_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=8566, limit=10000))

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False and result["uploaded"] == 0
        assert result["error"] == self.REFUSAL
        assert capsys.readouterr().out.splitlines() == [self.REFUSAL]
        assert command_failed() is True

    def test_a_run_that_fits_says_the_headroom_on_its_first_line_and_uploads(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
        quiet_headers: list,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=20000 - 13926, limit=20000))

        assert _main(["drive_sync", str(project)]) == 0

        assert capsys.readouterr().out.splitlines()[0] == "Drive: 2.9 KB to upload, 13.6 KB free"
        assert sorted(f.name for f in uploads[0]) == sorted(SIZES)

    def test_a_run_that_needs_exactly_the_free_space_fits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=10000 - 2970, limit=10000))

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is True and len(uploads[0]) == 3

    def test_a_run_one_byte_over_the_free_space_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=10000 - 2969, limit=10000))

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False and uploads == []
        assert result["error"] == "Drive has 2.9 KB free; this run needs 2.9 KB. Nothing uploaded."

    def test_an_account_with_no_limit_passes_and_says_none_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, _quota(usage=10**12, limit=None))

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is True and len(uploads[0]) == 3
        assert capsys.readouterr().out.splitlines()[0] == "Drive: 2.9 KB to upload, no storage limit reported"

    def test_a_quota_call_with_no_answer_is_an_error_that_uploads_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        client = _offline_client(monkeypatch, quota=None)
        client.last_error = "quota request timed out"

        assert _main(["drive_sync", str(project)]) == 2

        expected = "Drive quota unavailable: quota request timed out. Nothing uploaded."
        assert capsys.readouterr().out.splitlines()[-1] == expected
        assert uploads == []

    def test_an_answer_without_a_storage_quota_is_an_error_that_uploads_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: list, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        _sized_store(project)
        _offline_client(monkeypatch, quota={"user": {}})

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        expected = "Drive quota unavailable: about.get returned no storageQuota usage. Nothing uploaded."
        assert result["success"] is False and result["error"] == expected
        assert capsys.readouterr().out.splitlines() == [expected]
        assert uploads == []
