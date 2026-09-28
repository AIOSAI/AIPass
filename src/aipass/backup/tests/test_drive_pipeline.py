# =================== META ====================
# Name: test_drive_pipeline.py
# Description: Tests for the Drive sync pipeline -- every Google edge sealed, zero live calls
# Version: 3.0.3
# Created: 2026-06-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/drive_sync.py and the apps/handlers/drive/ pipeline it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under handlers/drive/ parses and imports
# seedgo: no-test-needed(constant) — BACKUP_FOLDER_NAME, FOLDER_MIME and TRACKER_FILENAME's strings
# seedgo: no-test-needed(stdlib) — ThreadPoolExecutor's scheduling and mimetypes' extension table

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import test as drive_test
from aipass.backup.apps.handlers.drive import tracker as drive_tracker
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.path import builder as path_builder
from aipass.backup.apps.modules import display, drive_check, drive_clear, drive_stats, drive_sync

# The product is imported for real, not stubbed into sys.modules. The upload path
# publishes to a REAL Google account; conftest's autouse ``sealed_google_edge``
# seals both doors to it and the media reader before every test, and a call that
# gets through raises rather than dials.
#
# Everything else in the pipeline is exercised for real. The tracker writes to
# ``<project>/.backup/drive_tracker.json``, which is under ``tmp_path``, and the
# audit trail and logger are redirected by conftest's ``mock_infrastructure``.


@pytest.fixture
def drive_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The Drive request edge, recorded: every request the client would send lands here."""
    edge = MagicMock(name="api_call_with_retry", return_value=None)
    monkeypatch.setattr(drive_client, "api_call_with_retry", edge)
    return edge


@pytest.fixture
def recorded_logger(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """@prax's logger, recorded. The severity it is called at is the contract medic reads."""
    recorder = MagicMock(name="logger")
    monkeypatch.setattr(drive_client, "logger", recorder)
    return recorder


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[list[Path]]:
    """Record the batches drive_sync hands to the upload engine, and send none of them."""
    batches: list[list[Path]] = []

    def _record(client, files, project_name, backup_root, tracker, **kwargs) -> dict:
        """Stand in for upload_batch: count the files, report them all uploaded."""
        batches.append(list(files))
        return {"success": True, "uploaded": len(files), "failed": 0, "bytes_uploaded": 0}

    monkeypatch.setattr(drive_upload, "upload_batch", _record)
    return batches


def _install_offline_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    authenticated: bool = True,
    last_error: str | None = None,
) -> MagicMock:
    """Put a DriveClient that talks to nobody where the late import looks for one."""
    instance = MagicMock(name="DriveClient")
    instance.authenticate.return_value = authenticated
    instance.last_error = last_error
    instance.file_tracker = {}
    monkeypatch.setattr(drive_client, "DriveClient", MagicMock(return_value=instance))
    return instance


# ---------------------------------------------------------------------------
# DriveClient — auth, folders, file lookup
# ---------------------------------------------------------------------------


class TestDriveClient:
    """Tests for DriveClient -- auth, folders, file lookup."""

    def test_authenticate_keeps_the_gateway_service_and_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A service from the gateway is kept, and authenticate() says so."""
        service = MagicMock(name="drive_service")
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(return_value=service))
        client = drive_client.DriveClient()

        assert client.authenticate() is True
        assert client._drive_service is service
        assert client.last_error is None

    def test_authenticate_without_google_libraries_refuses_at_error_with_the_install_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded_logger: MagicMock,
    ) -> None:
        """GOOGLE_API_AVAILABLE=False: refused at ERROR, carrying the install hint."""
        monkeypatch.setattr(drive_client, "GOOGLE_API_AVAILABLE", False)
        client = drive_client.DriveClient()

        assert client.authenticate() is False
        assert client.last_error == "Google API libraries not installed"
        recorded_logger.error.assert_called_once()
        assert "pip install" in recorded_logger.error.call_args[0][0]
        recorded_logger.warning.assert_not_called()

    def test_authenticate_fails_when_the_gateway_returns_no_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A gateway that hands back None is a failure, not a client with no service."""
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(return_value=None))
        client = drive_client.DriveClient()

        assert client.authenticate() is False
        assert client.last_error == "get_drive_service returned None"
        assert client.drive_service is None

    def test_authenticate_reports_a_raising_gateway_as_a_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded_logger: MagicMock,
    ) -> None:
        """A raising gateway is reported, kept in last_error, and stays a WARNING."""
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(side_effect=RuntimeError("boom")))
        client = drive_client.DriveClient()

        assert client.authenticate() is False
        assert client.last_error == "boom"
        recorded_logger.warning.assert_called_once()
        recorded_logger.error.assert_not_called()

    def test_authenticate_missing_libs_exception_escalates_to_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded_logger: MagicMock,
    ) -> None:
        """The real 'libraries not installed' RuntimeError escalates to ERROR, not WARNING."""
        # The message is @api's own, the exact shape google_client.get_google_service
        # raises when google-auth/-oauthlib/api-python-client are absent. ERROR is
        # what log_watcher and medic can see; WARNING is a documented no-op path.
        monkeypatch.setattr(
            drive_client,
            "get_drive_service",
            MagicMock(
                side_effect=RuntimeError(
                    "Google auth libraries not installed. Install: pip install "
                    "google-auth google-auth-oauthlib google-api-python-client"
                )
            ),
        )
        client = drive_client.DriveClient()

        assert client.authenticate() is False
        recorded_logger.error.assert_called_once()
        assert "not installed" in recorded_logger.error.call_args[0][0]
        recorded_logger.warning.assert_not_called()

    def test_authenticate_transient_failure_stays_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        recorded_logger: MagicMock,
    ) -> None:
        """A bad-creds or network failure stays at WARNING -- only the install case escalates."""
        monkeypatch.setattr(
            drive_client,
            "get_drive_service",
            MagicMock(side_effect=RuntimeError("Unable to find the server at oauth2.googleapis.com")),
        )
        client = drive_client.DriveClient()

        assert client.authenticate() is False
        recorded_logger.warning.assert_called_once()
        recorded_logger.error.assert_not_called()

    def test_drive_service_is_the_main_service_when_no_thread_local_is_set(self) -> None:
        """drive_service returns the main service when no thread-local is set."""
        client = drive_client.DriveClient()
        service = MagicMock(name="main_service")
        client._drive_service = service

        assert client.drive_service is service

    def test_drive_service_prefers_the_thread_local_service_over_the_main_one(self) -> None:
        """A thread-local service wins over the main one -- that is what keeps threads apart."""
        client = drive_client.DriveClient()
        main = MagicMock(name="main_service")
        thread = MagicMock(name="thread_service")
        client._drive_service = main
        client._thread_local.service = thread

        assert client.drive_service is thread

    def test_backup_folder_found_by_search_is_used_without_a_create(self, drive_api: MagicMock) -> None:
        """A search that finds the root folder uses it and never asks for a create."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"files": [{"id": "folder_123", "name": "AIPass Backups"}]}

        assert client.get_or_create_backup_folder() == "folder_123"
        assert client.backup_folder_id == "folder_123"
        client._drive_service.files.return_value.create.assert_not_called()

    def test_backup_folder_not_found_is_created_then_verified(self, drive_api: MagicMock) -> None:
        """An empty search creates the root folder, then verifies it is reachable."""
        service = MagicMock(name="drive_service")
        client = drive_client.DriveClient()
        client._drive_service = service
        drive_api.side_effect = [
            {"files": []},
            {"id": "new_folder_456"},
            {"id": "new_folder_456", "trashed": False},
        ]

        assert client.get_or_create_backup_folder() == "new_folder_456"
        assert client.backup_folder_id == "new_folder_456"
        service.files.return_value.create.assert_called_once()
        # The third answer is the verify at client.py:213-216. Counting the calls
        # is what makes it required: an unconsumed side_effect entry is not an
        # error, so without this the guard could be deleted and stay green.
        assert drive_api.call_count == 3
        service.files.return_value.get.assert_called_once_with(fileId="new_folder_456", fields="id,trashed")

    def test_backup_folder_created_but_unverified_is_refused_with_last_error(self, drive_api: MagicMock) -> None:
        """A created folder that does not verify is refused: no id, and last_error names it."""
        service = MagicMock(name="drive_service")
        client = drive_client.DriveClient()
        client._drive_service = service
        drive_api.side_effect = [
            {"files": []},
            {"id": "unreachable_789"},
            {"id": "unreachable_789", "trashed": True},
        ]

        assert client.get_or_create_backup_folder() is None
        assert client.backup_folder_id is None
        assert client.last_error == "Backup folder unreachable_789 created but not accessible"
        assert drive_api.call_count == 3

    def test_backup_folder_without_a_service_is_none_and_sends_no_request(self, drive_api: MagicMock) -> None:
        """With no service there is no folder and no request -- not a crash."""
        client = drive_client.DriveClient()

        assert client.get_or_create_backup_folder() is None
        assert client.backup_folder_id is None
        drive_api.assert_not_called()

    def test_an_outage_never_creates_a_second_root_or_resets_the_tracker(self, drive_api: MagicMock) -> None:
        """Mutant: the search's no-answer falls through to the create, as an empty search does."""
        service = MagicMock(name="drive_service")
        client = drive_client.DriveClient()
        client._drive_service = service
        client.backup_folder_id = "cached_root"
        client.file_tracker = {"kept.txt": {"drive_id": "abc"}}
        # Verify and search both get no answer; the last two are what a fall-through would consume.
        drive_api.side_effect = [None, None, {"id": "second_root"}, {"id": "second_root", "trashed": False}]

        assert client.get_or_create_backup_folder() is None
        service.files.return_value.create.assert_not_called()
        assert client.file_tracker == {"kept.txt": {"drive_id": "abc"}}
        assert client.last_error == "Backup folder search got no answer - not creating a second root"
        assert drive_api.call_count == 2

    def test_project_folder_found_is_returned_and_cached_by_project_name(self, drive_api: MagicMock) -> None:
        """A found project folder is returned and cached under its project name."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.backup_folder_id = "root_folder"
        drive_api.return_value = {"files": [{"id": "proj_folder_789", "name": "myproject"}]}

        assert client.get_or_create_project_folder("myproject") == "proj_folder_789"
        assert client.project_folder_cache["myproject"] == "proj_folder_789"

    def test_project_folder_cached_costs_one_verify_and_no_search(self, drive_api: MagicMock) -> None:
        """A cached project folder costs one verify and no search."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.project_folder_cache["cached_proj"] = "cached_id"
        drive_api.return_value = {"id": "cached_id", "trashed": False}

        assert client.get_or_create_project_folder("cached_proj") == "cached_id"
        assert drive_api.call_count == 1

    def test_nested_folder_is_created_and_cached_segment_by_segment(self, drive_api: MagicMock) -> None:
        """A nested path is created segment by segment, and every segment is cached."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")

        calls = {"n": 0}

        def _side_effect(request, **kwargs):
            """Answer 'not found' then 'created' for each segment in turn."""
            calls["n"] += 1
            if calls["n"] % 2 == 1:
                return {"files": []}
            return {"id": f"folder_{calls['n']}"}

        drive_api.side_effect = _side_effect

        result = client.get_or_create_nested_folder("parent_id", "a/b")

        assert result == "folder_4"
        assert client.project_folder_cache["parent_id:a"] == "folder_2"
        assert client.project_folder_cache["parent_id:a/b"] == "folder_4"

    def test_find_existing_file_returns_the_drive_entry_when_present(self, drive_api: MagicMock) -> None:
        """A file that is in the folder comes back with its Drive id."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"files": [{"id": "file_abc", "name": "test.txt"}]}

        assert client._find_existing_file("test.txt", "parent_folder") == {"id": "file_abc", "name": "test.txt"}

    def test_find_existing_file_returns_none_on_an_empty_search(self, drive_api: MagicMock) -> None:
        """An empty result is None, never an invented entry."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"files": []}

        assert client._find_existing_file("missing.txt", "parent_folder") is None

    def test_verify_folder_id_accepts_a_live_untrashed_folder(self, drive_api: MagicMock) -> None:
        """A folder that exists and is not trashed verifies."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"id": "folder_ok", "trashed": False}

        assert client._verify_folder_id("folder_ok") is True

    def test_verify_folder_id_rejects_a_trashed_folder(self, drive_api: MagicMock) -> None:
        """A trashed folder does NOT verify -- uploading into it loses the files."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"id": "folder_trash", "trashed": True}

        assert client._verify_folder_id("folder_trash") is False

    def test_api_call_hands_the_request_to_the_gateway_with_a_budget_of_three(self, drive_api: MagicMock) -> None:
        """_api_call hands the request straight to the gateway, with the retry budget."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        drive_api.return_value = {"ok": True}
        request = MagicMock(name="request")

        assert client._api_call(request) == {"ok": True}
        drive_api.assert_called_once_with(request, max_retries=3)

    def test_api_call_failure_retries_once_on_a_rebuilt_thread_service_with_a_budget_of_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        drive_api: MagicMock,
    ) -> None:
        """A first failure rebuilds the THREAD's service and retries once."""
        thread_service = MagicMock(name="thread_service")
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(return_value=thread_service))
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="main_service")
        drive_api.side_effect = [RuntimeError("transient error"), {"retried": True}]
        request = MagicMock(name="request")

        assert client._api_call(request) == {"retried": True}
        assert client._thread_local.service is thread_service
        # Both answers are claimed, and the budgets with them: the retry runs on
        # the SHRUNKEN budget (client.py:124), which the returned value alone
        # leaves free to be widened back to 3.
        assert drive_api.call_count == 2
        drive_api.assert_has_calls([call(request, max_retries=3), call(request, max_retries=1)])


# ---------------------------------------------------------------------------
# tracker — mtime+size dedup, and the file it keeps
# ---------------------------------------------------------------------------


class TestDriveTracker:
    """Tests for drive tracker -- mtime+size dedup."""

    def test_check_needs_upload_is_true_for_an_untracked_file(self, tmp_path: Path) -> None:
        """A file the tracker has never seen needs upload."""
        test_file = tmp_path / "new_file.txt"
        test_file.write_text("hello", encoding="utf-8")

        assert drive_tracker.check_needs_upload({}, test_file, tmp_path) is True

    def test_check_needs_upload_is_false_when_mtime_and_size_match(self, tmp_path: Path) -> None:
        """Matching mtime AND size is the whole dedup rule: no upload."""
        test_file = tmp_path / "unchanged.txt"
        test_file.write_text("same", encoding="utf-8")
        stat = test_file.stat()
        tracker = {
            "unchanged.txt": {
                "local_size": stat.st_size,
                "local_mtime": stat.st_mtime,
                "drive_id": "abc",
                "last_sync": "2026-01-01T00:00:00",
            }
        }

        assert drive_tracker.check_needs_upload(tracker, test_file, tmp_path) is False

    def test_check_needs_upload_is_true_when_the_size_changed(self, tmp_path: Path) -> None:
        """A size that no longer matches needs upload."""
        test_file = tmp_path / "changed.txt"
        test_file.write_text("changed content", encoding="utf-8")
        tracker = {
            "changed.txt": {
                "local_size": 1,
                "local_mtime": test_file.stat().st_mtime,
                "drive_id": "abc",
                "last_sync": "2026-01-01",
            }
        }

        assert drive_tracker.check_needs_upload(tracker, test_file, tmp_path) is True

    def test_check_needs_upload_is_true_when_the_mtime_changed(self, tmp_path: Path) -> None:
        """An mtime that no longer matches needs upload."""
        test_file = tmp_path / "mtime.txt"
        test_file.write_text("data", encoding="utf-8")
        tracker = {
            "mtime.txt": {
                "local_size": test_file.stat().st_size,
                "local_mtime": 0.0,
                "drive_id": "abc",
                "last_sync": "2026-01-01",
            }
        }

        assert drive_tracker.check_needs_upload(tracker, test_file, tmp_path) is True

    def test_update_entry_records_the_drive_id_and_stat_under_the_relative_path(self, tmp_path: Path) -> None:
        """An uploaded file is recorded under its relative path with the stat that dedups it."""
        tracker: dict = {}
        test_file = tmp_path / "uploaded.txt"
        test_file.write_text("uploaded content", encoding="utf-8")

        before = datetime.now(timezone.utc)
        drive_tracker.update_entry(tracker, test_file, tmp_path, "drive_id_xyz")
        after = datetime.now(timezone.utc)

        entry = tracker["uploaded.txt"]
        assert entry["drive_id"] == "drive_id_xyz"
        assert entry["local_size"] == test_file.stat().st_size
        assert entry["local_mtime"] == test_file.stat().st_mtime
        assert before <= datetime.fromisoformat(entry["last_sync"]) <= after

    def test_clean_tracker_removes_and_names_the_entries_whose_file_is_gone(self) -> None:
        """Entries whose file is gone are removed and named back to the caller."""
        tracker = {
            "exists.txt": {"drive_id": "a"},
            "gone.txt": {"drive_id": "b"},
            "also_gone.txt": {"drive_id": "c"},
        }

        removed = drive_tracker.clean_tracker(tracker, {"exists.txt"})

        assert sorted(removed) == ["also_gone.txt", "gone.txt"]
        assert tracker == {"exists.txt": {"drive_id": "a"}}

    def test_get_stats_counts_every_entry_and_samples_at_most_five(self) -> None:
        """Stats count every entry and sample at most five of them."""
        tracker = {name: {"drive_id": name} for name in ("a", "b", "c", "d", "e", "f", "g")}

        stats = drive_tracker.get_stats(tracker)

        assert stats["total"] == 7
        assert len(stats["sample"]) == 5

    def test_get_stats_on_an_empty_tracker_is_zero_and_an_empty_sample(self) -> None:
        """An empty tracker reports zero and an empty sample, not None."""
        assert drive_tracker.get_stats({}) == {"total": 0, "sample": {}}

    def test_clear_all_leaves_an_empty_tracker_document_instead_of_deleting_it(self, tmp_path: Path) -> None:
        """clear_all leaves an EMPTY tracker document, not a deleted file."""
        drive_tracker.save_tracker(str(tmp_path), {"file.txt": {"drive_id": "abc"}})

        assert drive_tracker.clear_all(str(tmp_path)) is True
        written = tmp_path / ".backup" / drive_tracker.TRACKER_FILENAME
        assert json.loads(written.read_text(encoding="utf-8")) == {}

    def test_load_tracker_reads_the_seeded_file_and_is_empty_when_unseeded(self, tmp_path: Path) -> None:
        """An unseeded project loads the EMPTY tracker, from .backup/drive_tracker.json."""
        # isinstance(result, dict) alone was satisfied by a tracker that had
        # invented entries, which for this handler is the dangerous direction: a
        # phantom entry tells drive_sync a file is already uploaded and it skips
        # it. So the value is pinned, and the file the reader went to beside it.
        seeded = {"seen.txt": {"drive_id": "abc"}}
        (tmp_path / ".backup").mkdir()
        (tmp_path / ".backup" / drive_tracker.TRACKER_FILENAME).write_text(json.dumps(seeded), encoding="utf-8")

        assert drive_tracker.load_tracker(str(tmp_path)) == seeded
        assert drive_tracker.load_tracker(str(tmp_path / "unseeded")) == {}

    def test_save_tracker_writes_json_under_the_projects_backup_dir(self, tmp_path: Path) -> None:
        """The tracker lands on disk as JSON, under the project's .backup/."""
        drive_tracker.save_tracker(str(tmp_path), {"file.txt": {"drive_id": "abc"}})

        written = tmp_path / ".backup" / drive_tracker.TRACKER_FILENAME
        assert json.loads(written.read_text(encoding="utf-8")) == {"file.txt": {"drive_id": "abc"}}


# ---------------------------------------------------------------------------
# upload — single file and threaded batch
# ---------------------------------------------------------------------------


class TestDriveUpload:
    """Tests for drive upload engine."""

    def test_upload_single_file_creates_an_untracked_file_and_records_its_id(
        self,
        tmp_path: Path,
        drive_api: MagicMock,
    ) -> None:
        """A file with no tracked id is CREATED, and the new id lands in the tracker."""
        client = drive_client.DriveClient()
        service = MagicMock(name="drive_service")
        client._drive_service = service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')", encoding="utf-8")
        drive_api.return_value = {"id": "new_file_id"}

        assert drive_upload.upload_single_file(client, test_file, "testproj", tmp_path) is True
        service.files.return_value.create.assert_called_once()
        service.files.return_value.update.assert_not_called()
        assert client.file_tracker["hello.py"]["drive_id"] == "new_file_id"

    def test_upload_single_file_updates_a_tracked_file_in_place_instead_of_creating(
        self,
        tmp_path: Path,
        drive_api: MagicMock,
    ) -> None:
        """A file with a tracked id is UPDATED in place, never created a second time."""
        client = drive_client.DriveClient()
        service = MagicMock(name="drive_service")
        client._drive_service = service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")
        client.file_tracker = {"existing.py": {"drive_id": "existing_drive_id"}}
        test_file = tmp_path / "existing.py"
        test_file.write_text("updated content", encoding="utf-8")
        drive_api.return_value = {"id": "existing_drive_id"}

        assert drive_upload.upload_single_file(client, test_file, "testproj", tmp_path) is True
        service.files.return_value.update.assert_called_once()
        service.files.return_value.create.assert_not_called()
        assert service.files.return_value.update.call_args.kwargs["fileId"] == "existing_drive_id"

    def test_upload_single_file_refuses_a_missing_file_before_any_request(
        self,
        tmp_path: Path,
        drive_api: MagicMock,
    ) -> None:
        """A file that is not there is refused before any folder is touched."""
        client = drive_client.DriveClient()

        assert drive_upload.upload_single_file(client, tmp_path / "ghost.txt", "testproj", tmp_path) is False
        drive_api.assert_not_called()

    def test_upload_batch_of_nothing_succeeds_without_a_request(self, tmp_path: Path, drive_api: MagicMock) -> None:
        """An empty list is a success that costs nothing and asks Drive for nothing."""
        client = drive_client.DriveClient()

        result = drive_upload.upload_batch(client, [], "proj", tmp_path, {})

        assert result == {"success": True, "uploaded": 0, "failed": 0}
        drive_api.assert_not_called()

    def test_upload_batch_advances_progress_once_per_file_and_tracks_each(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        drive_api: MagicMock,
    ) -> None:
        """Every file in a batch advances progress once and lands in the shared tracker."""
        service = MagicMock(name="drive_service")
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(return_value=service))
        client = drive_client.DriveClient()
        client._drive_service = service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")

        files = []
        for index in range(3):
            path = tmp_path / f"file_{index}.txt"
            path.write_text(f"content {index}", encoding="utf-8")
            files.append(path)

        drive_api.return_value = {"id": "file_id"}
        progress_calls: list[int] = []
        tracker: dict = {}

        def track_progress() -> None:
            """Record a progress callback invocation."""
            progress_calls.append(1)

        result = drive_upload.upload_batch(
            client,
            files,
            "proj",
            tmp_path,
            tracker,
            progress_fn=track_progress,
            max_workers=1,
        )

        assert len(progress_calls) == 3
        assert result["uploaded"] == 3 and result["failed"] == 0
        assert sorted(tracker) == ["file_0.txt", "file_1.txt", "file_2.txt"]

    def test_upload_single_file_without_media_upload_fails_and_tracks_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without MediaFileUpload there is no upload, and no half-written tracker entry."""
        monkeypatch.setattr(drive_upload, "MEDIA_UPLOAD_AVAILABLE", False)
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")
        test_file = tmp_path / "test.txt"
        test_file.write_text("data", encoding="utf-8")

        assert drive_upload.upload_single_file(client, test_file, "proj", tmp_path) is False
        assert client.file_tracker == {}


# ---------------------------------------------------------------------------
# build_drive_path — the destination the upload lane builds out of folder ids
# ---------------------------------------------------------------------------


class TestDriveDestinationPath:
    """build_drive_path: <BACKUP_FOLDER_NAME>/<project dir name>/<store-relative path>, pure computation."""

    def test_drive_path_opens_with_the_root_and_project_folders_the_lane_creates(self, tmp_path: Path) -> None:
        """A store-root file lands under <root folder>/<project dir name>/, not at the Drive root."""
        project = tmp_path / "myproject"

        result = path_builder.build_drive_path(str(project), "notes.txt")

        assert result == Path(drive_client.BACKUP_FOLDER_NAME) / "myproject" / "notes.txt"

    def test_drive_path_keeps_the_relative_files_parent_folders_instead_of_flattening(self, tmp_path: Path) -> None:
        """A nested store-relative file keeps every parent segment -- upload creates one folder each."""
        # The shape is the versioned store's own: <parent>/<name-folder>/<name>
        # (builder.build_versioned_file_path), which is what drive_sync hands the
        # engine as backup_root-relative. Flattening to the bare leaf is exactly
        # upload.py:75-76's not-relative fallback, and it is NOT this path.
        project = tmp_path / "myproject"

        result = path_builder.build_drive_path(str(project), "src/app.py/app.py")

        assert result == Path(drive_client.BACKUP_FOLDER_NAME) / "myproject" / "src" / "app.py" / "app.py"

    def test_drive_path_does_not_re_hash_a_long_name_the_store_already_hashed(self, tmp_path: Path) -> None:
        """A >50-char name passes through untouched: the Drive lane has no hashing step."""
        # build_versioned_file_path applies name[:30]_md5[:8] on the way INTO the
        # store, so the store-relative path already carries the shortened folder.
        # Nothing in handlers/drive/ hashes anything; borrowing the local twin's
        # recipe here would rename the file a second time, and the upload would
        # then publish under a name no tracker key or restore lookup matches.
        project = tmp_path / "myproject"
        long_name = "a" * 51 + ".txt"

        result = path_builder.build_drive_path(str(project), f"docs/{long_name}")

        assert result.name == long_name
        assert result == Path(drive_client.BACKUP_FOLDER_NAME) / "myproject" / "docs" / long_name


# ---------------------------------------------------------------------------
# test_connectivity — the connectivity probe
# ---------------------------------------------------------------------------


class TestDriveTest:
    """Tests for drive connectivity test handler."""

    def test_connectivity_passes_and_names_the_folder_it_reached(
        self,
        monkeypatch: pytest.MonkeyPatch,
        drive_api: MagicMock,
    ) -> None:
        """Auth plus folder access is a pass, and it names the folder it reached."""
        service = MagicMock(name="drive_service")
        monkeypatch.setattr(drive_client, "get_drive_service", MagicMock(return_value=service))
        drive_api.return_value = {"files": [{"id": "folder_ok", "name": "AIPass Backups"}]}

        result = drive_test.test_connectivity(drive_client.DriveClient())

        assert result == {"success": True, "folder_id": "folder_ok", "error": None}

    def test_connectivity_stops_at_auth_and_reports_the_clients_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed auth stops at step one and reports the client's own error."""
        monkeypatch.setattr(
            drive_client,
            "get_drive_service",
            MagicMock(side_effect=RuntimeError("No credentials")),
        )

        result = drive_test.test_connectivity(drive_client.DriveClient())

        assert result["success"] is False
        assert result["error"] == "No credentials"
        assert result["folder_id"] is None

    def test_connectivity_fails_with_the_fallback_reason_when_folder_access_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        drive_api: MagicMock,
    ) -> None:
        """Auth can pass and folder access still fail -- that is a FAIL with the fallback reason."""
        monkeypatch.setattr(
            drive_client,
            "get_drive_service",
            MagicMock(return_value=MagicMock(name="drive_service")),
        )
        # The search answers empty and the create gets no answer: nothing sets last_error, so the fallback speaks.
        drive_api.side_effect = [{"files": []}, None]

        result = drive_test.test_connectivity(drive_client.DriveClient())

        assert result["success"] is False
        assert result["error"] == "Failed to access backup folder"
        assert drive_api.call_count == 2
        assert result["folder_id"] is None


# ---------------------------------------------------------------------------
# drive_sync — the orchestrator, through the command
# ---------------------------------------------------------------------------


class TestDriveSync:
    """Tests for drive sync orchestrator module."""

    @staticmethod
    def _store(tmp_path: Path) -> tuple[Path, Path]:
        """A project with an empty versioned store where the real builder looks for it."""
        project = tmp_path / "project"
        store = project / ".backup" / "versioned"
        store.mkdir(parents=True)
        return project, store

    def test_run_drive_sync_on_an_empty_store_uploads_nothing_and_saves_no_tracker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """An empty store is a success that uploads nothing and saves no tracker."""
        project, _store = self._store(tmp_path)
        _install_offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is True
        assert result["uploaded"] == 0 and result["total"] == 0
        assert uploads == []
        assert not (project / ".backup" / drive_tracker.TRACKER_FILENAME).exists()

    def test_run_drive_sync_stops_on_a_failed_auth_before_any_upload(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """A failed auth stops the run before the store is even looked at."""
        project = tmp_path / "project"
        project.mkdir()
        _install_offline_client(monkeypatch, authenticated=False, last_error="No creds")

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False
        assert result["error"] == "No creds"
        assert uploads == []

    def test_run_drive_sync_names_a_missing_versioned_store_and_uploads_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """A missing versioned store is named back, and nothing is uploaded."""
        project = tmp_path / "project"
        project.mkdir()
        missing = project / ".backup" / "versioned"
        _install_offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False
        assert result["error"] == f"Versioned store not found: {missing}"
        assert uploads == []

    def test_run_drive_sync_hands_every_untracked_file_to_one_upload_batch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """Every untracked file in the store is handed to the upload engine, once."""
        project, store = self._store(tmp_path)
        for index in range(3):
            (store / f"file_{index}.txt").write_text(f"content {index}", encoding="utf-8")
        _install_offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["uploaded"] == 3 and result["total"] == 3
        assert len(uploads) == 1
        assert sorted(f.name for f in uploads[0]) == ["file_0.txt", "file_1.txt", "file_2.txt"]
        assert (project / ".backup" / drive_tracker.TRACKER_FILENAME).exists()

    def test_run_drive_sync_filters_ignored_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """Files matching .backupignore are excluded from the upload list."""
        project, store = self._store(tmp_path)
        for rel in (
            "src/app.py/app.py",
            "node_modules/pkg/index.js/index.js",
            "node_modules/other/lib.js/lib.js",
        ):
            (store / rel).parent.mkdir(parents=True, exist_ok=True)
            (store / rel).write_text("code", encoding="utf-8")
        (project / ".backupignore").write_text("node_modules/\n", encoding="utf-8")
        _install_offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["total"] == 1
        assert [f.name for f in uploads[0]] == ["app.py"]

    def test_run_drive_sync_skips_legacy_tmp_copies(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        uploads: list,
    ) -> None:
        """Temps a pre-rule versioned run stored never go to Drive (DPLAN-0338)."""
        # The store is re-filtered through load_spec, so the built-in *.tmp floor
        # reaches copies made before it existed -- for a .backupignore that never
        # names *.tmp, which is every one seeded before the rule.
        project, store = self._store(tmp_path)
        for rel in (
            "data_json/state.json/state.json",
            "data_json/tmpab12cd34.tmp/tmpab12cd34.tmp",
            "data_json/tmpab12cd34.tmp/tmpab12cd34-baseline-2026-08-15.tmp",
            "data_json/.4242_7.tmp/.4242_7.tmp",
        ):
            (store / rel).parent.mkdir(parents=True, exist_ok=True)
            (store / rel).write_text("x", encoding="utf-8")
        (project / ".backupignore").write_text("node_modules/\n", encoding="utf-8")
        _install_offline_client(monkeypatch)

        result = drive_sync.run_drive_sync(str(project), show_panels=False)

        assert result["total"] == 1
        assert [f.relative_to(store).as_posix() for f in uploads[0]] == ["data_json/state.json/state.json"]

    def test_drive_sync_help_flag_prints_usage_and_never_runs_the_sync(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`drive_sync --help` describes the run and never performs it."""
        ran: list = []
        monkeypatch.setattr(drive_sync, "run_drive_sync", lambda *args, **kwargs: ran.append(args))

        assert drive_sync.handle_command("drive_sync", ["--help"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "Usage: drive_sync <project_root> [options]" in printed
        assert "--force" in printed

    def test_note_and_project_reach_the_upload_instead_of_the_defaults(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--project and --note change what upload_batch is handed; without them it gets the defaults."""

        # Two projects, not one run twice: the first run writes a tracker, and a
        # second run over the same store would skip every file and never reach
        # the upload at all. build_versioned_store is NOT patched here -- the
        # real builder already answers <project>/.backup/versioned, which is
        # inside tmp_path, so the product's own path code runs.
        # The Google edge is sealed by conftest's autouse seal, the client is
        # a MagicMock, and upload_batch is the recorder below: nothing dials.
        def _seed(name: str) -> Path:
            """A project whose versioned store holds one file to upload."""
            project = tmp_path / name
            store = project / ".backup" / "versioned"
            store.mkdir(parents=True)
            (store / "file.txt").write_text("content", encoding="utf-8")
            return project

        flagged = _seed("flagged")
        plain = _seed("plain")
        _install_offline_client(monkeypatch)

        handed: list[tuple[str, str]] = []

        def _record(client, files, project_name, backup_root, tracker, **kwargs) -> dict:
            """Stand in for upload_batch: keep the project name and the note it was given."""
            handed.append((project_name, kwargs["note"]))
            return {"success": True, "uploaded": len(files), "failed": 0, "bytes_uploaded": 0}

        monkeypatch.setattr(drive_upload, "upload_batch", _record)
        # header() fires @cli's event bus; replaced where display binds it, so nothing fires.
        titles: list[str] = []
        monkeypatch.setattr(display, "header", lambda title, *args, **kwargs: titles.append(title))

        flagged_args = [str(flagged), "--project", "renamed", "--note", "nightly"]
        assert drive_sync.handle_command("drive_sync", flagged_args) is True
        assert drive_sync.handle_command("drive_sync", [str(plain)]) is True
        assert titles == ["Backup — Drive sync", "Backup — Drive sync"]

        # The flagged row carries the values the flags spelled; the plain row
        # carries the fallbacks (the directory's own name, and no note). Delete
        # either parse and the first row collapses onto the second.
        assert handed == [("renamed", "nightly"), ("plain", "")], f"the flags did not reach the upload: {handed!r}"

    def test_drive_sync_no_args_names_the_module_and_its_handlers(self, capsys: pytest.CaptureFixture) -> None:
        """No args names the module and the handlers behind it."""
        assert drive_sync.handle_command("drive_sync", []) is True

        printed = capsys.readouterr().out
        assert "drive_sync Module" in printed
        assert "Handlers: drive/client, drive/upload, drive/tracker" in printed
        assert "Usage: drive_sync" not in printed

    def test_drive_sync_declines_a_foreign_command_in_silence(self, capsys: pytest.CaptureFixture) -> None:
        """A command that is not ours is declined in silence."""
        assert drive_sync.handle_command("wrong", []) is False
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# drive_check / drive_stats / drive_clear — one class per module
# ---------------------------------------------------------------------------


class TestDriveCheckModule:
    """Tests for drive_check module."""

    def test_drive_check_no_args_introspects_without_running_the_check(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No args introspects; it must not authenticate against the real account."""
        ran: list = []
        monkeypatch.setattr(drive_check, "run_drive_check", lambda: ran.append(1))

        assert drive_check.handle_command("drive_check", []) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "drive_check Module" in printed
        assert "Handlers: drive/client, drive/test" in printed
        assert "drive_check run — test Drive auth and folder access" not in printed

    def test_drive_check_help_flag_anywhere_prints_usage_and_never_runs_the_check(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A help flag anywhere in the sequence explains instead of making a live call."""
        # 'run --help' opens with a real verb: only the whole-sequence screen
        # keeps it from reaching run_drive_check.
        ran: list = []
        monkeypatch.setattr(drive_check, "run_drive_check", lambda: ran.append(1))

        assert drive_check.handle_command("drive_check", ["--help"]) is True
        assert drive_check.handle_command("drive_check", ["run", "--help"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        # The usage line is print_help's own; the introspection header prints on other paths too.
        assert printed.count("drive_check run — test Drive auth and folder access") == 2

    def test_drive_check_declines_a_foreign_command_in_silence(self, capsys: pytest.CaptureFixture) -> None:
        """A command that is not ours is declined in silence."""
        assert drive_check.handle_command("wrong", []) is False
        assert capsys.readouterr().out == ""

    def test_run_drive_check_pass_prints_the_folder_it_reached(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A passing probe is reported to the user with the folder it reached."""
        _install_offline_client(monkeypatch)
        monkeypatch.setattr(
            drive_test,
            "test_connectivity",
            lambda client: {"success": True, "folder_id": "folder_ok", "error": None},
        )

        assert drive_check.run_drive_check() is True

        printed = capsys.readouterr().out
        assert "Drive connectivity test PASSED" in printed
        assert "Backup folder ID: folder_ok" in printed

    def test_run_drive_check_failure_goes_to_stderr(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed probe is an error on stderr, which is what drone's piping reads."""
        _install_offline_client(monkeypatch)
        monkeypatch.setattr(
            drive_test,
            "test_connectivity",
            lambda client: {"success": False, "folder_id": None, "error": "No credentials"},
        )

        assert drive_check.run_drive_check() is False

        out, err = capsys.readouterr()
        assert "Drive connectivity test FAILED: No credentials" in err
        assert "PASSED" not in out


class TestDriveStatsModule:
    """Tests for drive_stats module."""

    def test_drive_stats_no_args_names_the_module_and_its_handler(self, capsys: pytest.CaptureFixture) -> None:
        """No args names the module and the handler behind it."""
        assert drive_stats.handle_command("drive_stats", []) is True

        printed = capsys.readouterr().out
        assert "drive_stats Module" in printed
        assert "Handlers: drive/tracker" in printed
        assert "Usage: drive_stats" not in printed

    def test_drive_stats_help_flag_prints_usage_and_never_reads_a_tracker(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A help flag prints the usage line and never reads a tracker."""
        ran: list = []
        monkeypatch.setattr(drive_stats, "run_drive_stats", lambda project_root: ran.append(project_root))

        assert drive_stats.handle_command("drive_stats", ["--help"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "Usage: drive_stats <project_root>" in printed

    def test_drive_stats_declines_a_foreign_command_in_silence(self, capsys: pytest.CaptureFixture) -> None:
        """A command that is not ours is declined in silence."""
        assert drive_stats.handle_command("wrong", []) is False
        assert capsys.readouterr().out == ""

    def test_run_drive_stats_prints_the_tracker_on_disk(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """The stats a user sees come from the tracker file on disk."""
        drive_tracker.save_tracker(str(tmp_path), {"a.txt": {"drive_id": "x"}})

        assert drive_stats.run_drive_stats(str(tmp_path)) is True

        printed = capsys.readouterr().out
        assert "Total tracked files: 1" in printed
        assert "a.txt: x" in printed


class TestDriveClearModule:
    """Tests for drive_clear module."""

    def test_drive_clear_no_args_names_the_module_and_says_force_is_required(
        self,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """No args names the module and says the clear needs --force."""
        assert drive_clear.handle_command("drive_clear", []) is True

        printed = capsys.readouterr().out
        assert "drive_clear Module" in printed
        assert "Handlers: drive/tracker (requires --force)" in printed
        assert "Usage: drive_clear" not in printed

    def test_drive_clear_help_flag_prints_usage_and_clears_nothing(
        self,
        capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A help flag prints the usage line and clears nothing."""
        ran: list = []
        monkeypatch.setattr(drive_clear, "run_drive_clear", lambda project_root, force=False: ran.append(project_root))

        assert drive_clear.handle_command("drive_clear", ["--help"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "Usage: drive_clear <project_root> --force" in printed

    def test_drive_clear_declines_a_foreign_command_in_silence(self, capsys: pytest.CaptureFixture) -> None:
        """A command that is not ours is declined in silence."""
        assert drive_clear.handle_command("wrong", []) is False
        assert capsys.readouterr().out == ""

    def test_run_drive_clear_without_force_leaves_the_tracker_untouched(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Without --force the tracker is left exactly as it was."""
        drive_tracker.save_tracker(str(tmp_path), {"a.txt": {"drive_id": "x"}})

        assert drive_clear.run_drive_clear(str(tmp_path), force=False) is False

        assert "Use --force to confirm tracker deletion." in capsys.readouterr().out
        assert drive_tracker.load_tracker(str(tmp_path)) == {"a.txt": {"drive_id": "x"}}

    def test_run_drive_clear_with_force_empties_the_tracker_and_says_so(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """With force the tracker document is emptied on disk and the user is told."""
        drive_tracker.save_tracker(str(tmp_path), {"a.txt": {"drive_id": "x"}})

        assert drive_clear.run_drive_clear(str(tmp_path), force=True) is True

        assert "Drive tracker cleared." in capsys.readouterr().out
        assert drive_tracker.load_tracker(str(tmp_path)) == {}


# ---------------------------------------------------------------------------
# TestFolderGetOrCreate — folder get-or-create: concurrency, short-circuit, tracker reset
# ---------------------------------------------------------------------------


class TestFolderGetOrCreate:
    """Folder get-or-create: one create under concurrent callers, the verify short-circuit, the tracker reset."""

    def test_concurrent_project_folder_single_create(self, drive_api: MagicMock) -> None:
        """N threads calling get_or_create_project_folder -> exactly 1 create."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.backup_folder_id = "root_folder"

        create_calls = {"n": 0}
        lock = threading.Lock()

        def _side_effect(request, **kwargs):
            """Answer the verify, then the search, then the one create."""
            with lock:
                create_calls["n"] += 1
                n = create_calls["n"]
            if n == 1:
                return {"id": "root_folder", "trashed": False}
            if n == 2:
                return {"files": []}
            if n == 3:
                return {"id": "proj_folder_unique"}
            return {"trashed": False}

        drive_api.side_effect = _side_effect

        results: list = []

        def _worker() -> None:
            """One thread asking for the same project folder as all the others."""
            results.append(client.get_or_create_project_folder("myproj"))

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == ["proj_folder_unique"] * 5
        assert client.project_folder_cache["myproj"] == "proj_folder_unique"

    def test_backup_folder_short_circuits(self, drive_api: MagicMock) -> None:
        """Once backup_folder_id is set and valid, one verify answers -- no re-search."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.backup_folder_id = "already_set"
        drive_api.return_value = {"id": "already_set", "trashed": False}

        assert client.get_or_create_backup_folder() == "already_set"
        assert drive_api.call_count == 1

    def test_tracker_preserved_on_existing_folder(self, drive_api: MagicMock) -> None:
        """Tracker NOT cleared when the backup folder already exists in Drive."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.file_tracker = {"existing.txt": {"drive_id": "abc"}}
        drive_api.return_value = {"files": [{"id": "found_folder", "name": "AIPass Backups"}]}

        assert client.get_or_create_backup_folder() == "found_folder"
        assert client.file_tracker == {"existing.txt": {"drive_id": "abc"}}

    def test_tracker_reset_on_new_folder_with_old_entries(self, drive_api: MagicMock) -> None:
        """Tracker cleared ONLY when creating a NEW root folder AND old_count>0."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.file_tracker = {"old.txt": {"drive_id": "dead_id"}}
        client.project_folder_cache["stale"] = "dead_folder"
        drive_api.side_effect = [
            {"files": []},
            {"id": "brand_new_folder"},
            {"id": "brand_new_folder", "trashed": False},
        ]

        assert client.get_or_create_backup_folder() == "brand_new_folder"
        assert client.file_tracker == {}
        assert client.project_folder_cache == {}
        # Search, create, then the verify at client.py:213-216 -- the reset path
        # still verifies the new folder, so the third call is part of the claim.
        assert drive_api.call_count == 3

    def test_tracker_not_reset_on_new_folder_empty_tracker(self, drive_api: MagicMock) -> None:
        """An empty tracker is still empty after a new folder -- and no reset is logged."""
        client = drive_client.DriveClient()
        client._drive_service = MagicMock(name="drive_service")
        client.project_folder_cache["keep"] = "keep_folder"
        drive_api.side_effect = [
            {"files": []},
            {"id": "new_folder"},
            {"id": "new_folder", "trashed": False},
        ]

        assert client.get_or_create_backup_folder() == "new_folder"
        assert client.file_tracker == {}
        assert client.project_folder_cache == {"keep": "keep_folder"}
        # Same three: search, create, verify. The empty tracker skips the reset
        # block but NOT the verify, so the count is still 3.
        assert drive_api.call_count == 3


class TestDedup:
    """Verify tracker-based dedup skips unchanged files."""

    def test_rerun_unchanged_zero_uploads(self, tmp_path: Path) -> None:
        """All files tracked with matching mtime+size -> 0 uploads."""
        files = []
        tracker: dict = {}
        for index in range(5):
            path = tmp_path / f"file_{index}.txt"
            path.write_text(f"content {index}", encoding="utf-8")
            files.append(path)
            stat = path.stat()
            tracker[f"file_{index}.txt"] = {
                "local_size": stat.st_size,
                "local_mtime": stat.st_mtime,
                "drive_id": f"drive_{index}",
                "last_sync": "2026-06-12T00:00:00",
            }

        needs_upload = [f for f in files if drive_tracker.check_needs_upload(tracker, f, tmp_path)]

        assert needs_upload == []


# ---------------------------------------------------------------------------
# TestCommandRouting — all 4 drive commands route by underscore name
# ---------------------------------------------------------------------------


class TestCommandRouting:
    """Verify drive commands route by underscore names."""

    def test_drive_sync_routes_underscore(self, capsys: pytest.CaptureFixture) -> None:
        """drive_sync accepts the underscore spelling and declines the hyphen one."""
        assert drive_sync.PRIMARY_COMMAND == "drive_sync"
        assert drive_sync.handle_command("drive_sync", []) is True
        assert drive_sync.handle_command("drive-sync", []) is False
        assert capsys.readouterr().out.count("drive_sync Module") == 1

    def test_drive_check_routes_underscore(self, capsys: pytest.CaptureFixture) -> None:
        """drive_check accepts the underscore spelling and declines the hyphen one."""
        assert drive_check.PRIMARY_COMMAND == "drive_check"
        assert drive_check.handle_command("drive_check", []) is True
        assert drive_check.handle_command("drive-check", []) is False
        assert capsys.readouterr().out.count("drive_check Module") == 1

    def test_drive_stats_routes_underscore(self, capsys: pytest.CaptureFixture) -> None:
        """drive_stats accepts the underscore spelling and declines the hyphen one."""
        assert drive_stats.PRIMARY_COMMAND == "drive_stats"
        assert drive_stats.handle_command("drive_stats", []) is True
        assert drive_stats.handle_command("drive-stats", []) is False
        assert capsys.readouterr().out.count("drive_stats Module") == 1

    def test_drive_clear_routes_underscore(self, capsys: pytest.CaptureFixture) -> None:
        """drive_clear accepts the underscore spelling and declines the old hyphen one."""
        assert drive_clear.PRIMARY_COMMAND == "drive_clear"
        assert drive_clear.handle_command("drive_clear", []) is True
        assert drive_clear.handle_command("drive-clear-tracker", []) is False
        assert capsys.readouterr().out.count("drive_clear Module") == 1


# =============================================
