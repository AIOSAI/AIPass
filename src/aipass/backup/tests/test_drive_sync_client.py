"""Tests for drive_sync_client — GoogleDriveSync core client logic."""

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def mock_deps(monkeypatch):
    """Mock all external deps before importing drive_sync_client."""
    mock_logger = MagicMock()
    mock_prax = MagicMock()
    mock_prax.logger = mock_logger

    # Already set by conftest, but ensure it stays
    monkeypatch.setitem(sys.modules, "aipass.prax", mock_prax)

    # JSON handler mocks
    mock_jh = MagicMock()
    mock_jh.log_operation = MagicMock(return_value=True)
    mock_json_init = MagicMock()
    mock_json_init.json_handler = mock_jh
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json", mock_json_init)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json.json_handler", mock_jh)

    # drive_sync_json mock
    mock_dsj = MagicMock()
    mock_dsj.load_config = MagicMock(return_value={})
    mock_dsj.save_config = MagicMock()
    mock_dsj.load_data = MagicMock(return_value={})
    mock_dsj.save_data = MagicMock()
    mock_dsj.log_operation = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.backup.apps.handlers.json.drive_sync_json",
        mock_dsj,
    )

    # Google API mocks
    mock_get_drive_service = MagicMock()
    mock_api_call_with_retry = MagicMock()
    mock_google_client = MagicMock()
    mock_google_client.get_drive_service = mock_get_drive_service
    mock_google_client.api_call_with_retry = mock_api_call_with_retry

    monkeypatch.setitem(sys.modules, "aipass.api", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.modules", MagicMock())
    monkeypatch.setitem(
        sys.modules,
        "aipass.api.apps.modules.google_client",
        mock_google_client,
    )

    # googleapiclient mock (MediaFileUpload)
    mock_media_upload = MagicMock()
    mock_http_mod = MagicMock()
    mock_http_mod.MediaFileUpload = mock_media_upload
    mock_googleapiclient = MagicMock()
    mock_googleapiclient.http = mock_http_mod
    monkeypatch.setitem(sys.modules, "googleapiclient", mock_googleapiclient)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", mock_http_mod)

    # Remove cached drive_sync_client so re-import picks up mocks
    for key in list(sys.modules):
        if "drive_sync_client" in key:
            monkeypatch.delitem(sys.modules, key, raising=False)
    # Also remove handler parent packages so import chain is clean
    for key in list(sys.modules):
        if key.startswith("aipass.backup.apps.handlers") and "json" not in key:
            monkeypatch.delitem(sys.modules, key, raising=False)

    return {
        "mock_logger": mock_logger,
        "mock_jh": mock_jh,
        "mock_dsj": mock_dsj,
        "mock_api_call_with_retry": mock_api_call_with_retry,
        "mock_media_upload": mock_media_upload,
    }


def _make_client(mock_deps):
    """Create a GoogleDriveSync with mocked internals (no real file I/O)."""
    from aipass.backup.apps.handlers.operations.drive_sync_client import (
        GoogleDriveSync,
    )

    with patch.object(GoogleDriveSync, "__init__", lambda self: None):
        client = GoogleDriveSync()

    # Set required attributes that __init__ normally creates
    client._drive_service = None
    client._thread_local = threading.local()
    client.backup_folder_id = None
    client.project_folder_cache = {}
    client.file_tracker = {}
    client.data = {}
    client.last_error = None
    client.tracker_was_reset = False
    client._folder_cache_lock = threading.Lock()
    client.config = {}

    return client


# ===================================================================
# Tests -- drive_service property (getter / setter)
# ===================================================================


class TestDriveServiceProperty:
    """Validate the drive_service property getter and setter."""

    def test_drive_service_getter_returns_main_service(self, mock_deps):
        """Getter returns _drive_service when no thread-local service is set."""
        client = _make_client(mock_deps)
        client._drive_service = "main_svc"
        # No thread-local service set

        assert client.drive_service == "main_svc"

    def test_drive_service_getter_prefers_thread_local(self, mock_deps):
        """Getter returns thread-local service when both are set."""
        client = _make_client(mock_deps)
        client._drive_service = "main_svc"
        client._thread_local.service = "thread_svc"

        assert client.drive_service == "thread_svc"

    def test_drive_service_getter_returns_none_when_nothing_set(self, mock_deps):
        """Getter returns None when neither thread-local nor main service is set."""
        client = _make_client(mock_deps)

        assert client.drive_service is None

    def test_drive_service_setter(self, mock_deps):
        """Setter updates _drive_service attribute."""
        client = _make_client(mock_deps)
        assert client._drive_service is None

        client.drive_service = "new_svc"

        assert client._drive_service == "new_svc"


# ===================================================================
# Tests -- get_or_create_backup_folder
# ===================================================================


class TestGetOrCreateBackupFolder:
    """Validate backup folder retrieval and creation logic."""

    def test_get_or_create_backup_folder_cached(self, mock_deps):
        """Returns cached folder ID when it is still valid (not trashed)."""
        client = _make_client(mock_deps)
        client.backup_folder_id = "cached_id"
        client._drive_service = "svc"

        with patch.object(client, "_verify_folder_id", return_value=True) as mock_verify:
            result = client.get_or_create_backup_folder()

        assert result == "cached_id"
        mock_verify.assert_called_once_with("cached_id")

    def test_get_or_create_backup_folder_finds_existing(self, mock_deps):
        """Finds an existing 'AIPass Backups' folder via Drive API search."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        # _api_call_with_retry returns search results, then verify passes
        list_result = {"files": [{"id": "existing_folder_id", "name": "AIPass Backups"}]}

        with (
            patch.object(
                client, "_api_call_with_retry", return_value=list_result
            ) as mock_api,
            patch.object(client, "_verify_folder_id", return_value=True),
        ):
            result = client.get_or_create_backup_folder()

        assert result == "existing_folder_id"
        assert client.backup_folder_id == "existing_folder_id"
        mock_api.assert_called_once()

    def test_get_or_create_backup_folder_creates_new(self, mock_deps):
        """Creates new folder when no existing folder is found on Drive."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        # First call: list returns empty (no existing folder)
        # Second call: create returns new folder ID
        call_responses = [
            {"files": []},       # list result
            {"id": "new_id"},    # create result
        ]

        with (
            patch.object(
                client,
                "_api_call_with_retry",
                side_effect=call_responses,
            ),
            patch.object(client, "_verify_folder_id", return_value=True),
        ):
            result = client.get_or_create_backup_folder()

        assert result == "new_id"
        assert client.backup_folder_id == "new_id"

    def test_get_or_create_backup_folder_creates_new_resets_tracker(self, mock_deps):
        """Creating a new folder resets the file tracker when entries exist."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()
        client.file_tracker = {"old_file": {"drive_id": "old_id"}}
        client.project_folder_cache = {"proj": "old_folder"}
        client.data = {"runtime_state": {"file_tracker": {}, "cached_folders": {}}}

        call_responses = [
            {"files": []},
            {"id": "brand_new_id"},
        ]

        with (
            patch.object(
                client,
                "_api_call_with_retry",
                side_effect=call_responses,
            ),
            patch.object(client, "_verify_folder_id", return_value=True),
            patch.object(client, "_save_file_tracker"),
        ):
            result = client.get_or_create_backup_folder()

        assert result == "brand_new_id"
        assert client.tracker_was_reset is True
        assert len(client.file_tracker) == 0
        assert len(client.project_folder_cache) == 0

    def test_get_or_create_backup_folder_no_service_returns_none(self, mock_deps):
        """Returns None when drive_service is not set."""
        client = _make_client(mock_deps)
        # _drive_service stays None, no cached backup_folder_id

        result = client.get_or_create_backup_folder()

        assert result is None
        assert "not authenticated" in (client.last_error or "")

    def test_get_or_create_backup_folder_cached_but_trashed(self, mock_deps):
        """Clears cache and searches Drive when cached folder is trashed."""
        client = _make_client(mock_deps)
        client.backup_folder_id = "trashed_id"
        client._drive_service = MagicMock()

        list_result = {"files": [{"id": "fresh_id", "name": "AIPass Backups"}]}

        with (
            patch.object(
                client,
                "_verify_folder_id",
                side_effect=[False, True],  # First call: trashed; second: verify new
            ),
            patch.object(
                client, "_api_call_with_retry", return_value=list_result
            ),
        ):
            result = client.get_or_create_backup_folder()

        assert result == "fresh_id"
        assert client.backup_folder_id == "fresh_id"


# ===================================================================
# Tests -- get_or_create_nested_folder
# ===================================================================


class TestGetOrCreateNestedFolder:
    """Validate nested folder creation logic."""

    def test_get_or_create_nested_folder_empty_path(self, mock_deps):
        """Returns parent_folder_id when folder_path is '.'."""
        client = _make_client(mock_deps)

        result = client.get_or_create_nested_folder("parent_123", ".")

        assert result == "parent_123"

    def test_get_or_create_nested_folder_none_path(self, mock_deps):
        """Returns parent_folder_id when folder_path is empty string."""
        client = _make_client(mock_deps)

        result = client.get_or_create_nested_folder("parent_456", "")

        assert result == "parent_456"

    def test_get_or_create_nested_folder_creates_segments(self, mock_deps):
        """Creates each path segment that does not yet exist on Drive."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        # For path "a/b": two list calls (empty = not found), two create calls
        call_responses = [
            {"files": []},         # search for "a" -> not found
            {"id": "folder_a"},    # create "a"
            {"files": []},         # search for "b" -> not found
            {"id": "folder_b"},    # create "b"
        ]

        with (
            patch.object(
                client,
                "_api_call_with_retry",
                side_effect=call_responses,
            ),
            patch.object(client, "_verify_folder_id", return_value=False),
        ):
            result = client.get_or_create_nested_folder("root_id", "a/b")

        assert result == "folder_b"
        # Both segments should be cached
        assert "root_id:a" in client.project_folder_cache
        assert "folder_a:b" in client.project_folder_cache

    def test_get_or_create_nested_folder_finds_existing_segments(self, mock_deps):
        """Uses existing folders found on Drive instead of creating new ones."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        call_responses = [
            {"files": [{"id": "existing_a"}]},  # "a" exists
            {"files": [{"id": "existing_b"}]},  # "b" exists
        ]

        with (
            patch.object(
                client,
                "_api_call_with_retry",
                side_effect=call_responses,
            ),
            patch.object(client, "_verify_folder_id", return_value=False),
        ):
            result = client.get_or_create_nested_folder("root_id", "a/b")

        assert result == "existing_b"

    def test_get_or_create_nested_folder_uses_cache(self, mock_deps):
        """Returns cached folder ID for full path without making API calls."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()
        client.project_folder_cache["root_id:a/b"] = "cached_nested_id"

        with patch.object(client, "_verify_folder_id", return_value=True):
            result = client.get_or_create_nested_folder("root_id", "a/b")

        assert result == "cached_nested_id"

    def test_get_or_create_nested_folder_api_error_returns_parent(self, mock_deps):
        """Falls back to parent_folder_id on API error."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        with (
            patch.object(
                client,
                "_api_call_with_retry",
                side_effect=RuntimeError("API down"),
            ),
            patch.object(client, "_verify_folder_id", return_value=False),
        ):
            result = client.get_or_create_nested_folder("fallback_id", "x/y")

        assert result == "fallback_id"


# ===================================================================
# Tests -- upload_backup_file
# ===================================================================


class TestUploadBackupFile:
    """Validate backup file upload logic."""

    def test_upload_backup_file_no_service_returns_false(self, mock_deps):
        """Returns False immediately when drive_service is None."""
        client = _make_client(mock_deps)
        # _drive_service stays None

        result = client.upload_backup_file(
            local_file=Path("/fake/backup.tar.gz"),
            project_name="TestProject",
        )

        assert result is False

    def test_upload_backup_file_success_create_new(self, mock_deps, tmp_path):
        """Uploads a new file to Drive and returns True."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        # Create a real temp file so stat() works
        test_file = tmp_path / "test_backup.json"
        test_file.write_text('{"data": true}', encoding="utf-8")

        mock_project_folder = "proj_folder_id"
        mock_target_folder = "target_folder_id"
        created_file = {"id": "new_drive_file_id"}

        with (
            patch.object(
                client,
                "get_or_create_project_folder",
                return_value=mock_project_folder,
            ),
            patch.object(
                client,
                "get_or_create_nested_folder",
                return_value=mock_target_folder,
            ),
            patch.object(
                client,
                "_find_existing_file",
                return_value=None,
            ),
            patch.object(
                client,
                "_api_call_with_retry",
                return_value=created_file,
            ),
        ):
            result = client.upload_backup_file(
                local_file=test_file,
                project_name="TestProject",
                note="test upload",
            )

        assert result is True

    def test_upload_backup_file_success_update_existing(self, mock_deps, tmp_path):
        """Updates an existing file on Drive using its tracked drive_id."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        test_file = tmp_path / "existing_backup.json"
        test_file.write_text('{"version": 2}', encoding="utf-8")

        # Pre-populate file tracker with an existing drive_id
        client.file_tracker = {
            "existing_backup.json": {"drive_id": "tracked_drive_id"}
        }

        updated_file = {"id": "tracked_drive_id"}

        with (
            patch.object(
                client,
                "get_or_create_project_folder",
                return_value="proj_folder",
            ),
            patch.object(
                client,
                "get_or_create_nested_folder",
                return_value="target_folder",
            ),
            patch.object(
                client,
                "_api_call_with_retry",
                return_value=updated_file,
            ),
        ):
            result = client.upload_backup_file(
                local_file=test_file,
                project_name="TestProject",
            )

        assert result is True

    def test_upload_backup_file_no_project_folder_returns_false(
        self, mock_deps, tmp_path
    ):
        """Returns False when project folder creation fails."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        test_file = tmp_path / "backup.json"
        test_file.write_text("{}", encoding="utf-8")

        with patch.object(
            client, "get_or_create_project_folder", return_value=None
        ):
            result = client.upload_backup_file(
                local_file=test_file,
                project_name="TestProject",
            )

        assert result is False

    def test_upload_backup_file_updates_statistics(self, mock_deps, tmp_path):
        """Successful upload increments upload statistics in data dict."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()
        client.data = {}

        test_file = tmp_path / "stats_test.json"
        test_file.write_text('{"key": "val"}', encoding="utf-8")
        file_size = test_file.stat().st_size

        with (
            patch.object(
                client,
                "get_or_create_project_folder",
                return_value="pf_id",
            ),
            patch.object(
                client,
                "get_or_create_nested_folder",
                return_value="tf_id",
            ),
            patch.object(
                client,
                "_find_existing_file",
                return_value=None,
            ),
            patch.object(
                client,
                "_api_call_with_retry",
                return_value={"id": "created_id"},
            ),
        ):
            client.upload_backup_file(
                local_file=test_file,
                project_name="TestProject",
            )

        stats = client.data["statistics"]
        assert stats["total_uploads"] == 1
        assert stats["successful_uploads"] == 1
        assert stats["failed_uploads"] == 0
        assert stats["total_bytes_uploaded"] == file_size

    def test_upload_backup_file_with_nested_path(self, mock_deps, tmp_path):
        """Computes correct nested folder path from backup_root."""
        client = _make_client(mock_deps)
        client._drive_service = MagicMock()

        # Create nested file structure
        sub_dir = tmp_path / "sub" / "deep"
        sub_dir.mkdir(parents=True)
        test_file = sub_dir / "nested.json"
        test_file.write_text("{}", encoding="utf-8")

        nested_folder_calls = []

        def capture_nested(parent_id, folder_path):
            nested_folder_calls.append(folder_path)
            return "nested_target_id"

        with (
            patch.object(
                client,
                "get_or_create_project_folder",
                return_value="pf_id",
            ),
            patch.object(
                client,
                "get_or_create_nested_folder",
                side_effect=capture_nested,
            ),
            patch.object(
                client,
                "_find_existing_file",
                return_value=None,
            ),
            patch.object(
                client,
                "_api_call_with_retry",
                return_value={"id": "file_id"},
            ),
        ):
            client.upload_backup_file(
                local_file=test_file,
                project_name="TestProject",
                backup_root=tmp_path,
            )

        assert len(nested_folder_calls) == 1
        assert nested_folder_calls[0] == "sub/deep"
