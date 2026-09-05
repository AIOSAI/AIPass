# =================== AIPass ====================
# Name: test_share.py
# Description: Tests for share module + handler (mocked Drive API)
# Version: 1.0.0
# Created: 2026-07-01
# Modified: 2026-07-01
# =============================================

"""Tests for share — module routing, handler logic, permission paths."""

import importlib
import sys
import types
from unittest.mock import MagicMock, patch


def _build_mocks():
    """Build the standard mock dict for importing share modules."""
    mocks: dict[str, object] = {}

    prax = types.ModuleType("aipass.prax")
    setattr(prax, "logger", MagicMock())
    mocks["aipass.prax"] = prax

    cli = types.ModuleType("aipass.cli")
    cli_apps = types.ModuleType("aipass.cli.apps")
    cli_modules = types.ModuleType("aipass.cli.apps.modules")
    setattr(cli_modules, "console", MagicMock())
    setattr(cli_modules, "header", MagicMock())
    setattr(cli_modules, "success", MagicMock())
    setattr(cli_modules, "warning", MagicMock())
    setattr(cli_modules, "error", MagicMock())
    mocks["aipass.cli"] = cli
    mocks["aipass.cli.apps"] = cli_apps
    mocks["aipass.cli.apps.modules"] = cli_modules

    audit_pkg = types.ModuleType("aipass.backup.apps.handlers.audit")
    trail_mod = types.ModuleType("aipass.backup.apps.handlers.audit.trail")
    setattr(trail_mod, "log_operation", MagicMock())
    mocks["aipass.backup.apps.handlers.audit"] = audit_pkg
    mocks["aipass.backup.apps.handlers.audit.trail"] = trail_mod

    json_pkg = types.ModuleType("aipass.backup.apps.handlers.json")
    json_handler = types.ModuleType(
        "aipass.backup.apps.handlers.json.json_handler",
    )
    setattr(json_handler, "read_json", MagicMock(return_value={}))
    setattr(json_handler, "write_json", MagicMock(return_value=True))
    setattr(json_handler, "InvalidDocument", ValueError)
    setattr(json_handler, "WriteFailed", OSError)
    mocks["aipass.backup.apps.handlers.json"] = json_pkg
    mocks["aipass.backup.apps.handlers.json.json_handler"] = json_handler

    google_client = types.ModuleType("aipass.api.apps.modules.google_client")
    setattr(google_client, "get_drive_service", MagicMock())
    setattr(google_client, "api_call_with_retry", MagicMock())
    mocks["aipass.api.apps.modules.google_client"] = google_client
    mocks["aipass.api"] = types.ModuleType("aipass.api")
    mocks["aipass.api.apps"] = types.ModuleType("aipass.api.apps")
    mocks["aipass.api.apps.modules"] = types.ModuleType("aipass.api.apps.modules")

    ghttp = types.ModuleType("googleapiclient.http")
    setattr(ghttp, "MediaFileUpload", MagicMock())
    mocks["googleapiclient"] = types.ModuleType("googleapiclient")
    mocks["googleapiclient.http"] = ghttp

    return mocks


def _fresh_import(module_path: str, mocks: dict):
    """Import a module with mocked dependencies, clearing stale entries."""
    stale = [k for k in sys.modules if k.startswith(module_path.rsplit(".", 1)[0])]
    with patch.dict(sys.modules, mocks):
        for k in stale:
            sys.modules.pop(k, None)
        return importlib.import_module(module_path)


# ── Module routing tests ─────────────────────────────────────────────


class TestShareModuleRouting:
    """Verify handle_command routing for the share module."""

    def test_handle_command_returns_true_for_primary(self) -> None:
        """handle_command returns True for the primary command."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.handle_command(mod.PRIMARY_COMMAND, []) is True

    def test_handle_command_returns_false_for_unknown(self) -> None:
        """handle_command returns False for unknown commands."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.handle_command("nonexistent", []) is False

    def test_handle_command_help(self) -> None:
        """--help flag returns True early."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.handle_command(mod.PRIMARY_COMMAND, ["--help"]) is True

    def test_handle_command_help_short(self) -> None:
        """-h flag returns True early."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.handle_command(mod.PRIMARY_COMMAND, ["-h"]) is True

    def test_handle_command_help_word(self) -> None:
        """help word returns True early."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.handle_command(mod.PRIMARY_COMMAND, ["help"]) is True

    def test_module_constants(self) -> None:
        """MODULE_NAME and PRIMARY_COMMAND are correct."""
        mocks = _build_mocks()
        mod = _fresh_import("aipass.backup.apps.modules.share", mocks)
        assert mod.MODULE_NAME == "share"
        assert mod.PRIMARY_COMMAND == "share"


# ── Handler tests ────────────────────────────────────────────────────


def _make_mock_client():
    """Build a mock DriveClient with chainable Drive API methods."""
    client = MagicMock()
    client.last_error = None
    client.file_tracker = {}
    client.backup_folder_id = None
    client.project_folder_cache = {}

    client.get_or_create_project_folder.return_value = "folder-shared-123"
    client._find_existing_file.return_value = None

    service = MagicMock()
    client.drive_service = service

    service.permissions.return_value.create.return_value = MagicMock()
    service.files.return_value.get.return_value = MagicMock()
    service.files.return_value.create.return_value = MagicMock()
    service.files.return_value.update.return_value = MagicMock()
    service.files.return_value.list.return_value = MagicMock()
    service.about.return_value.get.return_value = MagicMock()

    return client


class TestShareHandler:
    """Test the share handler functions with mocked Drive API."""

    def test_share_file_success_public(self, tmp_path) -> None:
        """Public share uploads, sets permission, returns webViewLink."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"PDF content")

        client._api_call.side_effect = [
            {"id": "file-abc-123"},
            {"id": "perm-xyz-789"},
            {"webViewLink": "https://drive.google.com/file/d/file-abc-123/view"},
        ]

        result = handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert result["link"] == "https://drive.google.com/file/d/file-abc-123/view"
        assert result["file_id"] is not None
        assert result["error"] is None

    def test_share_file_success_restricted(self, tmp_path) -> None:
        """Restricted share uses authenticated email for permission."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        test_file = tmp_path / "data.csv"
        test_file.write_text("a,b,c")

        client._api_call.side_effect = [
            {"id": "file-def-456"},
            {"user": {"emailAddress": "test@gmail.com"}},
            {"id": "perm-abc-123"},
            {"webViewLink": "https://drive.google.com/file/d/file-def-456/view"},
        ]

        result = handler.share_file(client, str(test_file), public=False)

        assert result["success"] is True
        assert result["link"] is not None
        assert result["error"] is None

    def test_share_file_not_a_file(self, tmp_path) -> None:
        """Nonexistent path returns error."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        result = handler.share_file(client, str(tmp_path / "nonexistent.txt"))

        assert result["success"] is False
        assert "Not a file" in result["error"]

    def test_share_file_directory_rejected(self, tmp_path) -> None:
        """Directory path returns error."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        result = handler.share_file(client, str(tmp_path))

        assert result["success"] is False
        assert "Not a file" in result["error"]

    def test_share_file_upload_failure(self, tmp_path) -> None:
        """Upload failure surfaces error."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client.get_or_create_project_folder.return_value = None
        client.last_error = "Folder creation failed"

        test_file = tmp_path / "fail.txt"
        test_file.write_text("content")

        result = handler.share_file(client, str(test_file))

        assert result["success"] is False
        assert "Upload failed" in result["error"]

    def test_share_file_permission_failure(self, tmp_path) -> None:
        """Permission failure after upload surfaces error."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._find_existing_file.return_value = {"id": "existing-file-id"}

        client._api_call.side_effect = [
            {"user": {"emailAddress": "test@gmail.com"}},
            None,
        ]
        client.last_error = "Permission denied"

        test_file = tmp_path / "secret.txt"
        test_file.write_text("restricted")

        result = handler.share_file(client, str(test_file))

        assert result["success"] is False
        assert "Permission failed" in result["error"]

    def test_share_file_link_retrieval_failure(self, tmp_path) -> None:
        """Link retrieval failure after permission surfaces error."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._find_existing_file.return_value = {"id": "file-id"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            None,
        ]
        client.last_error = "API error"

        test_file = tmp_path / "doc.txt"
        test_file.write_text("document")

        result = handler.share_file(client, str(test_file), public=True)

        assert result["success"] is False
        assert "Link retrieval failed" in result["error"]

    def test_idempotent_reuses_existing(self, tmp_path) -> None:
        """Existing file on Drive is reused, not re-uploaded."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._find_existing_file.return_value = {"id": "already-on-drive"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            {"webViewLink": "https://drive.google.com/file/d/already-on-drive/view"},
        ]

        test_file = tmp_path / "existing.txt"
        test_file.write_text("already uploaded")

        result = handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert result["file_id"] == "already-on-drive"
        client.get_or_create_project_folder.assert_called_once_with("Shared")

    def test_webcontentlink_fallback(self, tmp_path) -> None:
        """Falls back to webContentLink when webViewLink is absent."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._find_existing_file.return_value = {"id": "file-id"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            {"webContentLink": "https://drive.google.com/uc?id=file-id"},
        ]

        test_file = tmp_path / "download.bin"
        test_file.write_bytes(b"\x00\x01")

        result = handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert "uc?id=file-id" in result["link"]


class TestSetSharePermission:
    """Test permission-setting specifically."""

    def test_public_permission_body(self, tmp_path) -> None:
        """Public permission uses type=anyone, role=reader."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.return_value = {"id": "perm-id"}

        handler.set_share_permission(client, "file-123", public=True)

        call_args = client.drive_service.permissions().create.call_args
        assert call_args.kwargs["body"]["type"] == "anyone"
        assert call_args.kwargs["body"]["role"] == "reader"

    def test_restricted_permission_body(self, tmp_path) -> None:
        """Restricted permission uses type=user with authenticated email."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.side_effect = [
            {"user": {"emailAddress": "user@example.com"}},
            {"id": "perm-id"},
        ]

        handler.set_share_permission(client, "file-123", public=False)

        call_args = client.drive_service.permissions().create.call_args
        assert call_args.kwargs["body"]["type"] == "user"
        assert call_args.kwargs["body"]["emailAddress"] == "user@example.com"

    def test_restricted_fails_without_email(self) -> None:
        """Restricted permission fails when email lookup returns None."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.return_value = None

        result = handler.set_share_permission(client, "file-123", public=False)

        assert result is None
        assert "email" in client.last_error.lower()


class TestGetShareLink:
    """Test link retrieval."""

    def test_prefers_webviewlink(self) -> None:
        """webViewLink is preferred over webContentLink."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.return_value = {
            "webViewLink": "https://view-link",
            "webContentLink": "https://content-link",
        }

        link = handler.get_share_link(client, "file-id")
        assert link == "https://view-link"

    def test_falls_back_to_webcontentlink(self) -> None:
        """Falls back to webContentLink when webViewLink is None."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.return_value = {
            "webViewLink": None,
            "webContentLink": "https://content-link",
        }

        link = handler.get_share_link(client, "file-id")
        assert link == "https://content-link"

    def test_returns_none_on_api_failure(self) -> None:
        """Returns None when API call fails."""
        mocks = _build_mocks()
        handler = _fresh_import("aipass.backup.apps.handlers.drive.share", mocks)

        client = _make_mock_client()
        client._api_call.return_value = None

        link = handler.get_share_link(client, "file-id")
        assert link is None


# =============================================
