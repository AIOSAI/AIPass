# =================== AIPass ====================
# Name: test_drive_pipeline.py
# Description: Tests for Drive sync pipeline -- fully mocked, zero real Google calls
# Version: 2.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Tests for Drive sync pipeline -- fully mocked Google API.

All Google API calls are mocked.  No real network traffic.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module import helpers
# ---------------------------------------------------------------------------


def _mock_dependencies() -> dict[str, types.ModuleType]:
    """Build a dict of mocked dependency modules for drive handler imports."""
    mocks: dict[str, object] = {}

    # aipass.prax
    prax = types.ModuleType("aipass.prax")
    prax.logger = MagicMock()  # type: ignore[attr-defined]
    mocks["aipass.prax"] = prax

    # aipass.cli
    cli = types.ModuleType("aipass.cli")
    cli_apps = types.ModuleType("aipass.cli.apps")
    cli_modules = types.ModuleType("aipass.cli.apps.modules")
    cli_modules.console = MagicMock()  # type: ignore[attr-defined]
    cli_modules.header = MagicMock()  # type: ignore[attr-defined]
    cli_modules.success = MagicMock()  # type: ignore[attr-defined]
    cli_modules.warning = MagicMock()  # type: ignore[attr-defined]
    cli_modules.error = MagicMock()  # type: ignore[attr-defined]
    mocks["aipass.cli"] = cli
    mocks["aipass.cli.apps"] = cli_apps
    mocks["aipass.cli.apps.modules"] = cli_modules

    # json handler
    json_pkg = types.ModuleType("aipass.backup.apps.handlers.json")
    json_handler = types.ModuleType("aipass.backup.apps.handlers.json.json_handler")
    json_handler.log_operation = MagicMock()  # type: ignore[attr-defined]
    json_handler.load_json = MagicMock(return_value={})  # type: ignore[attr-defined]
    json_handler.save_json = MagicMock()  # type: ignore[attr-defined]
    mocks["aipass.backup.apps.handlers.json"] = json_pkg
    mocks["aipass.backup.apps.handlers.json.json_handler"] = json_handler

    # google api client
    api_mod = types.ModuleType("aipass.api")
    api_apps = types.ModuleType("aipass.api.apps")
    api_modules = types.ModuleType("aipass.api.apps.modules")
    google_client = types.ModuleType("aipass.api.apps.modules.google_client")
    google_client.get_drive_service = MagicMock()  # type: ignore[attr-defined]
    google_client.api_call_with_retry = MagicMock()  # type: ignore[attr-defined]
    mocks["aipass.api"] = api_mod
    mocks["aipass.api.apps"] = api_apps
    mocks["aipass.api.apps.modules"] = api_modules
    mocks["aipass.api.apps.modules.google_client"] = google_client

    # googleapiclient.http
    gapi_http = types.ModuleType("googleapiclient.http")
    gapi_http.MediaFileUpload = MagicMock()  # type: ignore[attr-defined]
    gapi = types.ModuleType("googleapiclient")
    mocks["googleapiclient"] = gapi
    mocks["googleapiclient.http"] = gapi_http

    return mocks  # type: ignore[return-value]


def _fresh_import(module_path: str, extra_mocks: dict | None = None):
    """Import a module with all dependencies mocked."""
    mocks = _mock_dependencies()
    if extra_mocks:
        mocks.update(extra_mocks)

    # Clear stale drive entries BEFORE patch.dict so they won't be restored
    for key in list(sys.modules.keys()):
        if key.startswith("aipass.backup.apps.handlers.drive"):
            del sys.modules[key]
    if module_path in sys.modules:
        del sys.modules[module_path]

    with patch.dict(sys.modules, mocks):
        mod = importlib.import_module(module_path)
        return mod


# ---------------------------------------------------------------------------
# TestDriveClient
# ---------------------------------------------------------------------------


class TestDriveClient:
    """Tests for DriveClient -- auth, folders, file lookup."""

    def test_authenticate_success(self) -> None:
        """Mock get_drive_service returns service, authenticate() returns True."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()

        mock_service = MagicMock()
        mod.get_drive_service = MagicMock(return_value=mock_service)  # type: ignore[attr-defined]

        result = client.authenticate()
        assert result is True
        assert client._drive_service is mock_service

    def test_authenticate_no_api(self) -> None:
        """GOOGLE_API_AVAILABLE=False, authenticate() returns False and logs ERROR."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        mod.GOOGLE_API_AVAILABLE = False  # type: ignore[attr-defined]
        client = mod.DriveClient()

        result = client.authenticate()
        assert result is False
        assert client.last_error == "Google API libraries not installed"
        mod.logger.error.assert_called_once()
        assert "pip install" in mod.logger.error.call_args[0][0]
        mod.logger.warning.assert_not_called()

    def test_authenticate_service_returns_none(self) -> None:
        """get_drive_service returns None, authenticate() returns False."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mod.get_drive_service = MagicMock(return_value=None)  # type: ignore[attr-defined]

        result = client.authenticate()
        assert result is False
        assert "returned None" in (client.last_error or "")

    def test_authenticate_exception(self) -> None:
        """get_drive_service raises, authenticate() returns False."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mod.get_drive_service = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[attr-defined]

        result = client.authenticate()
        assert result is False
        assert "boom" in (client.last_error or "")
        mod.logger.warning.assert_called_once()
        mod.logger.error.assert_not_called()

    def test_authenticate_missing_libs_exception_escalates_to_error(self) -> None:
        """get_drive_service raising the real 'libraries not installed' RuntimeError

        (the exact shape @api's google_client.get_google_service raises when
        google-auth/google-auth-oauthlib/google-api-python-client aren't
        installed) must escalate to logger.error carrying the install hint,
        so log_watcher/medic can see it -- WARNING is a documented no-op path.
        """
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mod.get_drive_service = MagicMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError(
                "Google auth libraries not installed. Install: pip install "
                "google-auth google-auth-oauthlib google-api-python-client"
            )
        )

        result = client.authenticate()
        assert result is False
        mod.logger.error.assert_called_once()
        assert "not installed" in mod.logger.error.call_args[0][0]
        mod.logger.warning.assert_not_called()

    def test_authenticate_transient_failure_stays_warning(self) -> None:
        """A non-install auth failure (bad creds, network) stays at WARNING --

        only the actionable 'libraries not installed' case escalates to ERROR.
        """
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mod.get_drive_service = MagicMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError("Unable to find the server at oauth2.googleapis.com")
        )

        result = client.authenticate()
        assert result is False
        mod.logger.warning.assert_called_once()
        mod.logger.error.assert_not_called()

    def test_drive_service_property_main(self) -> None:
        """drive_service returns main service when no thread-local."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_svc = MagicMock()
        client._drive_service = mock_svc

        assert client.drive_service is mock_svc

    def test_drive_service_property_thread_local(self) -> None:
        """drive_service returns thread-local service when set."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_main = MagicMock()
        mock_thread = MagicMock()
        client._drive_service = mock_main
        client._thread_local.service = mock_thread

        assert client.drive_service is mock_thread

    def test_get_or_create_backup_folder_existing(self) -> None:
        """Mock files().list returns existing folder -- uses it."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"files": [{"id": "folder_123", "name": "AIPass Backups"}]})  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "folder_123"
        assert client.backup_folder_id == "folder_123"

    def test_get_or_create_backup_folder_new(self) -> None:
        """Mock files().list returns empty, files().create called."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        call_count = {"n": 0}

        def _side_effect(request, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"files": []}
            if call_count["n"] == 2:
                return {"id": "new_folder_456"}
            return {"id": "new_folder_456", "trashed": False}

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "new_folder_456"
        assert client.backup_folder_id == "new_folder_456"

    def test_get_or_create_backup_folder_no_service(self) -> None:
        """No drive service -- returns None."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()

        result = client.get_or_create_backup_folder()
        assert result is None

    def test_get_or_create_project_folder(self) -> None:
        """Mock chain works for project subfolder."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service
        client.backup_folder_id = "root_folder"

        mod.api_call_with_retry = MagicMock(return_value={"files": [{"id": "proj_folder_789", "name": "myproject"}]})  # type: ignore[attr-defined]

        result = client.get_or_create_project_folder("myproject")
        assert result == "proj_folder_789"
        assert client.project_folder_cache["myproject"] == "proj_folder_789"

    def test_get_or_create_project_folder_cached(self) -> None:
        """Cached project folder returned without API call."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()
        client.project_folder_cache["cached_proj"] = "cached_id"

        mod.api_call_with_retry = MagicMock(return_value={"id": "cached_id", "trashed": False})  # type: ignore[attr-defined]

        result = client.get_or_create_project_folder("cached_proj")
        assert result == "cached_id"

    def test_get_or_create_nested_folder(self) -> None:
        """Nested folder created segment by segment."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        call_count = {"n": 0}

        def _side_effect(request, **kwargs):
            call_count["n"] += 1
            if call_count["n"] % 2 == 1:
                return {"files": []}  # Not found
            return {"id": f"folder_{call_count['n']}"}  # Created

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]

        result = client.get_or_create_nested_folder("parent_id", "a/b")
        assert result is not None

    def test_find_existing_file_found(self) -> None:
        """File found in folder."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"files": [{"id": "file_abc", "name": "test.txt"}]})  # type: ignore[attr-defined]

        result = client._find_existing_file("test.txt", "parent_folder")
        assert result is not None
        assert result["id"] == "file_abc"

    def test_find_existing_file_not_found(self) -> None:
        """File not in folder -- returns None."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"files": []})  # type: ignore[attr-defined]

        result = client._find_existing_file("missing.txt", "parent_folder")
        assert result is None

    def test_verify_folder_id_exists(self) -> None:
        """Folder exists and not trashed."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"id": "folder_ok", "trashed": False})  # type: ignore[attr-defined]

        result = client._verify_folder_id("folder_ok")
        assert result is True

    def test_verify_folder_id_trashed(self) -> None:
        """Folder is trashed -- returns False."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"id": "folder_trash", "trashed": True})  # type: ignore[attr-defined]

        result = client._verify_folder_id("folder_trash")
        assert result is False

    def test_api_call_success(self) -> None:
        """_api_call delegates to api_call_with_retry."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service

        mod.api_call_with_retry = MagicMock(return_value={"ok": True})  # type: ignore[attr-defined]
        mock_request = MagicMock()

        result = client._api_call(mock_request)
        assert result == {"ok": True}

    def test_api_call_retry_on_failure(self) -> None:
        """_api_call rebuilds thread service on first failure."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()

        call_count = {"n": 0}

        def _side_effect(request, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient error")
            return {"retried": True}

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]
        mod.get_drive_service = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

        result = client._api_call(MagicMock())
        assert result == {"retried": True}


# ---------------------------------------------------------------------------
# TestDriveTracker
# ---------------------------------------------------------------------------


class TestDriveTracker:
    """Tests for drive tracker -- mtime+size dedup."""

    def test_check_needs_upload_new_file(self, tmp_path: Path) -> None:
        """File not in tracker -- needs upload."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        tracker: dict = {}
        test_file = tmp_path / "new_file.txt"
        test_file.write_text("hello", encoding="utf-8")

        result = mod.check_needs_upload(tracker, test_file, tmp_path)
        assert result is True

    def test_check_needs_upload_unchanged(self, tmp_path: Path) -> None:
        """Same mtime+size -- does not need upload."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
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

        result = mod.check_needs_upload(tracker, test_file, tmp_path)
        assert result is False

    def test_check_needs_upload_changed_size(self, tmp_path: Path) -> None:
        """Different size -- needs upload."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        test_file = tmp_path / "changed.txt"
        test_file.write_text("changed content", encoding="utf-8")

        tracker = {
            "changed.txt": {
                "local_size": 1,  # wrong size
                "local_mtime": test_file.stat().st_mtime,
                "drive_id": "abc",
                "last_sync": "2026-01-01",
            }
        }

        result = mod.check_needs_upload(tracker, test_file, tmp_path)
        assert result is True

    def test_check_needs_upload_changed_mtime(self, tmp_path: Path) -> None:
        """Different mtime -- needs upload."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        test_file = tmp_path / "mtime.txt"
        test_file.write_text("data", encoding="utf-8")

        tracker = {
            "mtime.txt": {
                "local_size": test_file.stat().st_size,
                "local_mtime": 0.0,  # wrong mtime
                "drive_id": "abc",
                "last_sync": "2026-01-01",
            }
        }

        result = mod.check_needs_upload(tracker, test_file, tmp_path)
        assert result is True

    def test_update_entry(self, tmp_path: Path) -> None:
        """Updates tracker with correct values."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        tracker: dict = {}
        test_file = tmp_path / "uploaded.txt"
        test_file.write_text("uploaded content", encoding="utf-8")

        mod.update_entry(tracker, test_file, tmp_path, "drive_id_xyz")

        assert "uploaded.txt" in tracker
        entry = tracker["uploaded.txt"]
        assert entry["drive_id"] == "drive_id_xyz"
        assert entry["local_size"] == test_file.stat().st_size
        assert entry["local_mtime"] == test_file.stat().st_mtime
        assert "last_sync" in entry

    def test_clean_tracker(self) -> None:
        """Removes stale entries."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        tracker = {
            "exists.txt": {"drive_id": "a"},
            "gone.txt": {"drive_id": "b"},
            "also_gone.txt": {"drive_id": "c"},
        }

        removed = mod.clean_tracker(tracker, {"exists.txt"})
        assert "gone.txt" in removed
        assert "also_gone.txt" in removed
        assert "exists.txt" not in removed
        assert len(tracker) == 1

    def test_get_stats(self) -> None:
        """Returns correct statistics."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        tracker = {
            "a.txt": {"drive_id": "1"},
            "b.txt": {"drive_id": "2"},
            "c.txt": {"drive_id": "3"},
        }

        stats = mod.get_stats(tracker)
        assert stats["total"] == 3
        assert len(stats["sample"]) <= 5

    def test_get_stats_empty(self) -> None:
        """Empty tracker stats."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        stats = mod.get_stats({})
        assert stats["total"] == 0
        assert stats["sample"] == {}

    def test_clear_all(self, tmp_path: Path) -> None:
        """Clears tracker file."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        project = tmp_path / "project"
        project.mkdir()
        backup_dir = project / ".backup"
        backup_dir.mkdir()

        result = mod.clear_all(str(project))
        assert result is True

    def test_load_tracker(self, tmp_path: Path) -> None:
        """Load tracker returns dict from json_handler."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        result = mod.load_tracker(str(tmp_path))
        assert isinstance(result, dict)

    def test_save_tracker(self, tmp_path: Path) -> None:
        """Save tracker calls json_handler.save_json."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")
        tracker = {"file.txt": {"drive_id": "abc"}}
        mod.save_tracker(str(tmp_path), tracker)
        # Verify save_json was called (mocked)
        mod.json_handler.save_json.assert_called_once()


# ---------------------------------------------------------------------------
# TestDriveUpload
# ---------------------------------------------------------------------------


class TestDriveUpload:
    """Tests for drive upload engine."""

    def test_upload_single_file_new(self, tmp_path: Path) -> None:
        """Mock create called for new file."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")

        # Create test file
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        # Mock api_call_with_retry to return file id
        client_mod.api_call_with_retry = MagicMock(return_value={"id": "new_file_id"})  # type: ignore[attr-defined]

        result = mod.upload_single_file(client, test_file, "testproj", tmp_path)
        assert result is True

    def test_upload_single_file_update(self, tmp_path: Path) -> None:
        """Mock update called for existing file (tracked drive_id)."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")

        # Pre-populate tracker with existing drive_id
        client.file_tracker = {"existing.py": {"drive_id": "existing_drive_id"}}

        test_file = tmp_path / "existing.py"
        test_file.write_text("updated content", encoding="utf-8")

        client_mod.api_call_with_retry = MagicMock(return_value={"id": "existing_drive_id"})  # type: ignore[attr-defined]

        result = mod.upload_single_file(client, test_file, "testproj", tmp_path)
        assert result is True

    def test_upload_single_file_missing(self, tmp_path: Path) -> None:
        """Non-existent file returns False."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        missing = tmp_path / "ghost.txt"

        result = mod.upload_single_file(client, missing, "testproj", tmp_path)
        assert result is False

    def test_upload_batch_empty(self, tmp_path: Path) -> None:
        """Empty file list returns success immediately."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        result = mod.upload_batch(client, [], "proj", tmp_path, {})
        assert result["success"] is True
        assert result["uploaded"] == 0
        assert result["failed"] == 0

    def test_upload_batch_progress(self, tmp_path: Path) -> None:
        """Progress callback called during batch upload."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")

        # Create test files
        files = []
        for i in range(3):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(f)

        client_mod.api_call_with_retry = MagicMock(return_value={"id": "file_id"})  # type: ignore[attr-defined]
        client_mod.get_drive_service = MagicMock(return_value=mock_service)  # type: ignore[attr-defined]

        progress_calls = []

        def track_progress():
            """Record a progress callback invocation."""
            progress_calls.append(1)

        result = mod.upload_batch(
            client,
            files,
            "proj",
            tmp_path,
            {},
            progress_fn=track_progress,
            max_workers=1,
        )
        assert len(progress_calls) == 3
        assert result["uploaded"] + result["failed"] == 3

    def test_upload_single_file_no_media(self, tmp_path: Path) -> None:
        """MediaFileUpload not available returns False."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.upload")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        mod.MEDIA_UPLOAD_AVAILABLE = False  # type: ignore[attr-defined]

        client = client_mod.DriveClient()
        client._drive_service = MagicMock()
        client.get_or_create_project_folder = MagicMock(return_value="proj_folder")

        test_file = tmp_path / "test.txt"
        test_file.write_text("data", encoding="utf-8")

        result = mod.upload_single_file(client, test_file, "proj", tmp_path)
        assert result is False


# ---------------------------------------------------------------------------
# TestDriveTest
# ---------------------------------------------------------------------------


class TestDriveTest:
    """Tests for drive connectivity test handler."""

    def test_connectivity_success(self) -> None:
        """Auth + folder access -- success."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.test")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()

        # Patch authenticate and get_or_create_backup_folder
        client.authenticate = MagicMock(return_value=True)
        client.get_or_create_backup_folder = MagicMock(return_value="folder_ok")

        result = mod.test_connectivity(client)
        assert result["success"] is True
        assert result["folder_id"] == "folder_ok"
        assert result["error"] is None

    def test_connectivity_auth_fail(self) -> None:
        """Auth fails -- error returned."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.test")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        client.authenticate = MagicMock(return_value=False)
        client.last_error = "No credentials"

        result = mod.test_connectivity(client)
        assert result["success"] is False
        assert "No credentials" in result["error"]

    def test_connectivity_folder_fail(self) -> None:
        """Auth ok but folder access fails."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.test")
        client_mod = _fresh_import("aipass.backup.apps.handlers.drive.client")

        client = client_mod.DriveClient()
        client.authenticate = MagicMock(return_value=True)
        client.get_or_create_backup_folder = MagicMock(return_value=None)
        client.last_error = "Folder creation failed"

        result = mod.test_connectivity(client)
        assert result["success"] is False
        assert "Folder creation failed" in result["error"]


# ---------------------------------------------------------------------------
# TestDriveSync
# ---------------------------------------------------------------------------


class TestDriveSync:
    """Tests for drive sync orchestrator module."""

    def _make_mock_client_class(self, authenticate_rv=True, last_error=None):
        """Build a mock DriveClient class for late-import injection."""
        mock_client_instance = MagicMock()
        mock_client_instance.authenticate.return_value = authenticate_rv
        mock_client_instance.last_error = last_error
        mock_client_instance.file_tracker = {}

        mock_class = MagicMock(return_value=mock_client_instance)
        return mock_class, mock_client_instance

    def test_run_drive_sync_no_files(self, tmp_path: Path) -> None:
        """Empty versioned store -- skip upload."""
        project = tmp_path / "project"
        project.mkdir()
        bs = project / ".backup" / "versioned"
        bs.mkdir(parents=True)

        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        mock_class, mock_inst = self._make_mock_client_class(authenticate_rv=True)
        mock_tracker_mod = MagicMock()
        mock_tracker_mod.load_tracker.return_value = {}
        mock_tracker_mod.check_needs_upload.return_value = True
        mock_tracker_mod.save_tracker = MagicMock()

        # Inject mocked client module into late import
        mock_client_module = MagicMock()
        mock_client_module.DriveClient = mock_class

        with (
            patch.dict(
                sys.modules,
                {"aipass.backup.apps.handlers.drive.client": mock_client_module},
            ),
            patch.dict(
                sys.modules,
                {"aipass.backup.apps.handlers.drive.tracker": mock_tracker_mod},
            ),
            patch.object(mod, "build_versioned_store", return_value=bs),
        ):
            result = mod.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is True
        assert result["uploaded"] == 0

    def test_run_drive_sync_auth_failure(self, tmp_path: Path) -> None:
        """Auth failure returns error."""
        project = tmp_path / "project"
        project.mkdir()

        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        mock_class, mock_inst = self._make_mock_client_class(
            authenticate_rv=False,
            last_error="No creds",
        )
        mock_client_module = MagicMock()
        mock_client_module.DriveClient = mock_class

        with patch.dict(
            sys.modules,
            {"aipass.backup.apps.handlers.drive.client": mock_client_module},
        ):
            result = mod.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False
        assert result["error"] is not None

    def test_run_drive_sync_no_store(self, tmp_path: Path) -> None:
        """Versioned store not found."""
        project = tmp_path / "project"
        project.mkdir()

        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        mock_class, mock_inst = self._make_mock_client_class(authenticate_rv=True)
        mock_client_module = MagicMock()
        mock_client_module.DriveClient = mock_class

        with (
            patch.dict(
                sys.modules,
                {"aipass.backup.apps.handlers.drive.client": mock_client_module},
            ),
            patch.object(
                mod,
                "build_versioned_store",
                return_value=tmp_path / "nonexistent",
            ),
        ):
            result = mod.run_drive_sync(str(project), show_panels=False)

        assert result["success"] is False
        assert "not found" in (result["error"] or "")

    def test_run_drive_sync_with_files(self, tmp_path: Path) -> None:
        """Files present -- upload called."""
        project = tmp_path / "project"
        project.mkdir()
        bs = project / ".backup" / "versioned"
        bs.mkdir(parents=True)

        for i in range(3):
            f = bs / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")

        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        mock_class, mock_inst = self._make_mock_client_class(authenticate_rv=True)

        mock_client_module = MagicMock()
        mock_client_module.DriveClient = mock_class

        mock_tracker_mod = MagicMock()
        mock_tracker_mod.load_tracker.return_value = {}
        mock_tracker_mod.check_needs_upload.return_value = True
        mock_tracker_mod.save_tracker = MagicMock()

        mock_upload_mod = MagicMock()
        mock_upload_mod.upload_batch.return_value = {
            "success": True,
            "uploaded": 3,
            "failed": 0,
        }

        with (
            patch.dict(
                sys.modules,
                {
                    "aipass.backup.apps.handlers.drive.client": mock_client_module,
                    "aipass.backup.apps.handlers.drive.tracker": mock_tracker_mod,
                    "aipass.backup.apps.handlers.drive.upload": mock_upload_mod,
                },
            ),
            patch.object(mod, "build_versioned_store", return_value=bs),
        ):
            result = mod.run_drive_sync(str(project), show_panels=False)

        assert result["uploaded"] == 3
        mock_upload_mod.upload_batch.assert_called_once()

    def test_run_drive_sync_filters_ignored_files(self, tmp_path: Path) -> None:
        """Files matching .backupignore are excluded from upload list."""
        project = tmp_path / "project"
        project.mkdir()
        bs = project / ".backup" / "versioned"

        (bs / "src" / "app.py" / "app.py").parent.mkdir(parents=True)
        (bs / "src" / "app.py" / "app.py").write_text("code", encoding="utf-8")
        (bs / "node_modules" / "pkg" / "index.js" / "index.js").parent.mkdir(parents=True)
        (bs / "node_modules" / "pkg" / "index.js" / "index.js").write_text("junk", encoding="utf-8")
        (bs / "node_modules" / "other" / "lib.js" / "lib.js").parent.mkdir(parents=True)
        (bs / "node_modules" / "other" / "lib.js" / "lib.js").write_text("junk2", encoding="utf-8")

        ignore_file = project / ".backupignore"
        ignore_file.write_text("node_modules/\n", encoding="utf-8")

        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        mock_class, mock_inst = self._make_mock_client_class(authenticate_rv=True)
        mock_client_module = MagicMock()
        mock_client_module.DriveClient = mock_class

        mock_tracker_mod = MagicMock()
        mock_tracker_mod.load_tracker.return_value = {}
        mock_tracker_mod.check_needs_upload.return_value = True
        mock_tracker_mod.save_tracker = MagicMock()

        mock_upload_mod = MagicMock()
        mock_upload_mod.upload_batch.return_value = {
            "success": True,
            "uploaded": 1,
            "failed": 0,
        }

        with (
            patch.dict(
                sys.modules,
                {
                    "aipass.backup.apps.handlers.drive.client": mock_client_module,
                    "aipass.backup.apps.handlers.drive.tracker": mock_tracker_mod,
                    "aipass.backup.apps.handlers.drive.upload": mock_upload_mod,
                },
            ),
            patch.object(mod, "build_versioned_store", return_value=bs),
        ):
            result = mod.run_drive_sync(str(project), show_panels=False)

        assert result["total"] == 1
        uploaded_files = mock_upload_mod.upload_batch.call_args[0][1]
        names = [f.name for f in uploaded_files]
        assert "app.py" in names
        assert "index.js" not in names
        assert "lib.js" not in names

    def test_handle_command_help(self) -> None:
        """--help returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        assert mod.handle_command("drive_sync", ["--help"]) is True

    def test_handle_command_no_args(self) -> None:
        """No args prints introspection."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        assert mod.handle_command("drive_sync", []) is True

    def test_handle_command_wrong_command(self) -> None:
        """Wrong command returns False."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        assert mod.handle_command("wrong", []) is False


# ---------------------------------------------------------------------------
# TestDriveModules (module-level tests)
# ---------------------------------------------------------------------------


class TestDriveCheckModule:
    """Tests for drive_check module."""

    def test_handle_command_primary(self) -> None:
        """Primary command returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_check")
        assert mod.handle_command("drive_check", []) is True

    def test_handle_command_help(self) -> None:
        """--help returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_check")
        assert mod.handle_command("drive_check", ["--help"]) is True

    def test_handle_command_wrong(self) -> None:
        """Wrong command returns False."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_check")
        assert mod.handle_command("wrong", []) is False

    def test_run_drive_check_success(self) -> None:
        """Run drive check with mocked success."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_check")

        mock_client_module = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_module.DriveClient.return_value = mock_client_instance

        mock_test_module = MagicMock()
        mock_test_module.test_connectivity.return_value = {
            "success": True,
            "folder_id": "folder_ok",
            "error": None,
        }

        with patch.dict(
            sys.modules,
            {
                "aipass.backup.apps.handlers.drive.client": mock_client_module,
                "aipass.backup.apps.handlers.drive.test": mock_test_module,
            },
        ):
            result = mod.run_drive_check()
        assert result is True


class TestDriveStatsModule:
    """Tests for drive_stats module."""

    def test_handle_command_primary(self) -> None:
        """Primary command returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_stats")
        assert mod.handle_command("drive_stats", []) is True

    def test_handle_command_help(self) -> None:
        """--help returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_stats")
        assert mod.handle_command("drive_stats", ["--help"]) is True

    def test_handle_command_wrong(self) -> None:
        """Wrong command returns False."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_stats")
        assert mod.handle_command("wrong", []) is False

    def test_run_drive_stats(self, tmp_path: Path) -> None:
        """Display stats from mocked tracker."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_stats")

        mock_tracker_mod = MagicMock()
        mock_tracker_mod.load_tracker.return_value = {"a.txt": {"drive_id": "x"}}
        mock_tracker_mod.get_stats.return_value = {
            "total": 1,
            "sample": {"a.txt": {"drive_id": "x"}},
        }

        with patch.dict(
            sys.modules,
            {"aipass.backup.apps.handlers.drive.tracker": mock_tracker_mod},
        ):
            result = mod.run_drive_stats(str(tmp_path))
        assert result is True


class TestDriveClearModule:
    """Tests for drive_clear module."""

    def test_handle_command_primary(self) -> None:
        """Primary command returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")
        assert mod.handle_command("drive_clear", []) is True

    def test_handle_command_help(self) -> None:
        """--help returns True."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")
        assert mod.handle_command("drive_clear", ["--help"]) is True

    def test_handle_command_wrong(self) -> None:
        """Wrong command returns False."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")
        assert mod.handle_command("wrong", []) is False

    def test_run_drive_clear_no_force(self, tmp_path: Path) -> None:
        """Without --force, returns False."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")
        result = mod.run_drive_clear(str(tmp_path / "project"), force=False)
        assert result is False

    def test_run_drive_clear_with_force(self, tmp_path: Path) -> None:
        """With force=True, clears tracker."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")

        mock_tracker_mod = MagicMock()
        mock_tracker_mod.clear_all.return_value = True

        with patch.dict(
            sys.modules,
            {"aipass.backup.apps.handlers.drive.tracker": mock_tracker_mod},
        ):
            result = mod.run_drive_clear(str(tmp_path), force=True)
        assert result is True


# ---------------------------------------------------------------------------
# TestThreadSafety — concurrent folder operations
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Verify folder get-or-create is thread-safe (GOLD lock pattern)."""

    def test_concurrent_project_folder_single_create(self) -> None:
        """N threads calling get_or_create_project_folder -> exactly 1 create."""
        import threading

        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        mock_service = MagicMock()
        client._drive_service = mock_service
        client.backup_folder_id = "root_folder"

        create_calls = {"n": 0}
        lock = threading.Lock()

        def _side_effect(request, **kwargs):
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

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]

        results = []

        def _worker():
            r = client.get_or_create_project_folder("myproj")
            results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == "proj_folder_unique" for r in results), f"Got different IDs: {results}"

    def test_backup_folder_short_circuits(self) -> None:
        """Once backup_folder_id is set+valid, returns without re-searching."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()
        client.backup_folder_id = "already_set"

        mod.api_call_with_retry = MagicMock(return_value={"id": "already_set", "trashed": False})  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "already_set"
        assert mod.api_call_with_retry.call_count == 1

    def test_tracker_preserved_on_existing_folder(self) -> None:
        """Tracker NOT cleared when backup folder already exists in Drive."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()
        client.file_tracker = {"existing.txt": {"drive_id": "abc"}}

        mod.api_call_with_retry = MagicMock(return_value={"files": [{"id": "found_folder", "name": "AIPass Backups"}]})  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "found_folder"
        assert client.file_tracker == {"existing.txt": {"drive_id": "abc"}}

    def test_tracker_reset_on_new_folder_with_old_entries(self) -> None:
        """Tracker cleared ONLY when creating a NEW root folder AND old_count>0."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()
        client.file_tracker = {"old.txt": {"drive_id": "dead_id"}}

        call_count = {"n": 0}

        def _side_effect(request, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"files": []}
            if call_count["n"] == 2:
                return {"id": "brand_new_folder"}
            return {"id": "brand_new_folder", "trashed": False}

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "brand_new_folder"
        assert client.file_tracker == {}

    def test_tracker_not_reset_on_new_folder_empty_tracker(self) -> None:
        """Tracker NOT cleared when creating new folder with empty tracker."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.client")
        client = mod.DriveClient()
        client._drive_service = MagicMock()
        client.file_tracker = {}

        call_count = {"n": 0}

        def _side_effect(request, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"files": []}
            if call_count["n"] == 2:
                return {"id": "new_folder"}
            return {"id": "new_folder", "trashed": False}

        mod.api_call_with_retry = MagicMock(side_effect=_side_effect)  # type: ignore[attr-defined]

        result = client.get_or_create_backup_folder()
        assert result == "new_folder"
        assert client.file_tracker == {}


class TestDedup:
    """Verify tracker-based dedup skips unchanged files."""

    def test_rerun_unchanged_zero_uploads(self, tmp_path: Path) -> None:
        """All files tracked with matching mtime+size -> 0 uploads."""
        mod = _fresh_import("aipass.backup.apps.handlers.drive.tracker")

        files = []
        tracker = {}
        for i in range(5):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            files.append(f)
            stat = f.stat()
            tracker[f"file_{i}.txt"] = {
                "local_size": stat.st_size,
                "local_mtime": stat.st_mtime,
                "drive_id": f"drive_{i}",
                "last_sync": "2026-06-12T00:00:00",
            }

        needs_upload = [f for f in files if mod.check_needs_upload(tracker, f, tmp_path)]
        assert len(needs_upload) == 0


# ---------------------------------------------------------------------------
# TestCommandRouting — all 4 drive commands route by underscore name
# ---------------------------------------------------------------------------


class TestCommandRouting:
    """Verify drive commands route by underscore names."""

    def test_drive_sync_routes_underscore(self) -> None:
        """drive_sync accepts underscore, rejects hyphen."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_sync")
        assert mod.PRIMARY_COMMAND == "drive_sync"
        assert mod.handle_command("drive_sync", []) is True
        assert mod.handle_command("drive-sync", []) is False

    def test_drive_check_routes_underscore(self) -> None:
        """drive_check accepts underscore, rejects hyphen."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_check")
        assert mod.PRIMARY_COMMAND == "drive_check"
        assert mod.handle_command("drive_check", []) is True
        assert mod.handle_command("drive-check", []) is False

    def test_drive_stats_routes_underscore(self) -> None:
        """drive_stats accepts underscore, rejects hyphen."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_stats")
        assert mod.PRIMARY_COMMAND == "drive_stats"
        assert mod.handle_command("drive_stats", []) is True
        assert mod.handle_command("drive-stats", []) is False

    def test_drive_clear_routes_underscore(self) -> None:
        """drive_clear accepts underscore, rejects hyphen."""
        mod = _fresh_import("aipass.backup.apps.modules.drive_clear")
        assert mod.PRIMARY_COMMAND == "drive_clear"
        assert mod.handle_command("drive_clear", []) is True
        assert mod.handle_command("drive-clear-tracker", []) is False


# =============================================
