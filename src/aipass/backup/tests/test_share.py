# =================== META ====================
# Name: test_share.py
# Description: Tests for the share module and the drive/share handler it drives
# Version: 2.0.0
# Created: 2026-07-01
# Modified: 2026-09-22
# =============================================

"""Tests for apps/modules/share.py and apps/handlers/drive/share.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under apps/handlers/drive/ parses and imports
# seedgo: no-test-needed(documentation) — that the public share functions carry docstrings
# seedgo: no-test-needed(constant) — the Rich colour tags print_introspection and print_help emit
# seedgo: no-test-needed(stdlib) — pathlib's resolve()/is_file() and mimetypes' type guessing
# seedgo: no-test-needed(generated) — the Drive file, folder and permission IDs; the API mints them

from unittest.mock import MagicMock

import pytest

from aipass.backup.apps.handlers.drive import share as share_handler
from aipass.backup.apps.handlers.drive import upload as upload_mod
from aipass.backup.apps.modules import share as share_module

# MEASURED, and the reason this file never widens past the two shapes below.
# `share` publishes to a REAL Google account: run_share() builds a DriveClient and
# calls authenticate() before anything validates the path it was handed — the
# is_file() check lives further down, inside share_file. So one
# handle_command("share", ["anything"]) is live OAuth, and with a real path behind
# it a live upload and a live share link. Two rules follow, and neither is style:
#   * a routing test either stops inside print_introspection / print_help, or it
#     records run_share through monkeypatch and asserts it was NOT reached;
#   * a handler test is handed the MagicMock DriveClient below, and
#     googleapiclient's MediaFileUpload is replaced at the edge, so the only bytes
#     that ever move are tmp_path's.
# The consoles are NOT mocked, and do not need to be: aipass.cli.apps.modules.console
# IS display.CONSOLE, a real Rich console printing to sys.stdout, and error()/warning()
# write to display.err_console on sys.stderr — capsys reads both, and conftest.py
# already pins both widths to 200 for the session.


@pytest.fixture(autouse=True)
def no_live_media_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    """The upload edge: googleapiclient's own uploader, never handed a real service."""
    monkeypatch.setattr(upload_mod, "MediaFileUpload", MagicMock())


@pytest.fixture
def client() -> MagicMock:
    """A stand-in DriveClient — the network edge, and the only thing this file mocks."""
    drive_client = MagicMock()
    drive_client.last_error = None
    drive_client.file_tracker = {}
    drive_client.backup_folder_id = None
    drive_client.project_folder_cache = {}

    drive_client.get_or_create_project_folder.return_value = "folder-shared-123"
    drive_client._find_existing_file.return_value = None

    service = MagicMock()
    drive_client.drive_service = service

    service.permissions.return_value.create.return_value = MagicMock()
    service.files.return_value.get.return_value = MagicMock()
    service.files.return_value.create.return_value = MagicMock()
    service.files.return_value.update.return_value = MagicMock()
    service.files.return_value.list.return_value = MagicMock()
    service.about.return_value.get.return_value = MagicMock()

    return drive_client


# ---------------------------------------------------------------------------
# handle_command — the routing a user actually types
# ---------------------------------------------------------------------------


class TestShareModuleRouting:
    """`drone @backup share ...` — what each spelling of the command does."""

    def test_no_args_names_the_module_and_the_handlers_it_drives(self, capsys) -> None:
        assert share_module.handle_command(share_module.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "share Module" in out
        assert "Handlers: drive/client, drive/upload, drive/share" in out
        assert err == ""

    def test_a_command_that_is_not_ours_is_declined_and_prints_nothing(self, capsys) -> None:
        assert share_module.handle_command("nonexistent", []) is False

        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    def test_a_help_flag_explains_the_upload_instead_of_performing_it(self, capsys, monkeypatch) -> None:
        """run_share authenticates before it validates, so help must never reach it."""
        ran: list = []
        monkeypatch.setattr(share_module, "run_share", lambda path, **kwargs: ran.append((path, kwargs)))

        assert share_module.handle_command(share_module.PRIMARY_COMMAND, ["--help"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "USAGE:" in printed
        assert "drone @backup share <file_path> [--public]" in printed

    def test_a_short_help_flag_behind_a_filename_still_preempts_the_upload(self, capsys, monkeypatch) -> None:
        """The module screens the WHOLE sequence: `share report.pdf -h` is help, not an upload."""
        ran: list = []
        monkeypatch.setattr(share_module, "run_share", lambda path, **kwargs: ran.append((path, kwargs)))

        assert share_module.handle_command(share_module.PRIMARY_COMMAND, ["report.pdf", "-h"]) is True

        assert ran == []
        assert "USAGE:" in capsys.readouterr().out

    def test_the_bare_help_word_preempts_only_in_first_position(self, capsys, monkeypatch) -> None:
        """`share help` is help; `share notes.txt help` is a file that happens to be named help."""
        ran: list = []
        monkeypatch.setattr(share_module, "run_share", lambda path, **kwargs: ran.append((path, kwargs)))

        assert share_module.handle_command(share_module.PRIMARY_COMMAND, ["help"]) is True
        assert ran == []
        assert "USAGE:" in capsys.readouterr().out

        assert share_module.handle_command(share_module.PRIMARY_COMMAND, ["notes.txt", "help"]) is True
        assert ran == [("notes.txt", {"public": False})]

    def test_the_primary_command_is_the_verb_the_router_answers_to(self, capsys) -> None:
        assert share_module.MODULE_NAME == "share"
        assert share_module.PRIMARY_COMMAND == "share"

        assert share_module.handle_command(share_module.PRIMARY_COMMAND, []) is True
        assert "Primary command: share" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# share_file — upload, permission, link, in one pipeline
# ---------------------------------------------------------------------------


class TestShareFile:
    """The whole pipeline, against a Drive client that never leaves the process."""

    def test_a_public_share_uploads_once_and_returns_the_view_link(self, tmp_path, client) -> None:
        test_file = tmp_path / "report.pdf"
        test_file.write_bytes(b"PDF content")

        client._api_call.side_effect = [
            {"id": "file-abc-123"},
            {"id": "perm-xyz-789"},
            {"webViewLink": "https://drive.google.com/file/d/file-abc-123/view"},
        ]

        result = share_handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert result["link"] == "https://drive.google.com/file/d/file-abc-123/view"
        assert result["file_id"] == "file-abc-123"
        assert result["error"] is None
        assert client.get_or_create_project_folder.call_args_list[0].args == ("Shared",)
        assert client.drive_service.permissions().create.call_args.kwargs["body"]["type"] == "anyone"

    def test_a_restricted_share_names_the_authenticated_user_and_not_anyone(self, tmp_path, client) -> None:
        test_file = tmp_path / "data.csv"
        test_file.write_text("a,b,c", encoding="utf-8")

        client._api_call.side_effect = [
            {"id": "file-def-456"},
            {"user": {"emailAddress": "test@gmail.com"}},
            {"id": "perm-abc-123"},
            {"webViewLink": "https://drive.google.com/file/d/file-def-456/view"},
        ]

        result = share_handler.share_file(client, str(test_file), public=False)

        assert result["success"] is True
        assert result["link"] is not None
        assert result["error"] is None
        body = client.drive_service.permissions().create.call_args.kwargs["body"]
        assert body["type"] == "user"
        assert body["emailAddress"] == "test@gmail.com"

    def test_a_path_that_is_not_there_is_refused_before_anything_is_uploaded(self, tmp_path, client) -> None:
        result = share_handler.share_file(client, str(tmp_path / "nonexistent.txt"))

        assert result["success"] is False
        assert "Not a file" in result["error"]
        assert client.get_or_create_project_folder.called is False

    def test_a_directory_is_refused_before_anything_is_uploaded(self, tmp_path, client) -> None:
        result = share_handler.share_file(client, str(tmp_path))

        assert result["success"] is False
        assert "Not a file" in result["error"]
        assert client.get_or_create_project_folder.called is False

    def test_a_failed_upload_names_the_clients_error_and_claims_no_file_id(self, tmp_path, client) -> None:
        client.get_or_create_project_folder.return_value = None
        client.last_error = "Folder creation failed"

        test_file = tmp_path / "fail.txt"
        test_file.write_text("content", encoding="utf-8")

        result = share_handler.share_file(client, str(test_file))

        assert result["success"] is False
        assert "Upload failed" in result["error"]
        assert "Folder creation failed" in result["error"]
        assert result["file_id"] is None
        assert result["link"] is None

    def test_a_failed_permission_still_names_the_uploaded_file_and_hands_back_no_link(self, tmp_path, client) -> None:
        """The file reached Drive; a run that could not share it must say which file it left there."""
        client._find_existing_file.return_value = {"id": "existing-file-id"}

        client._api_call.side_effect = [
            {"user": {"emailAddress": "test@gmail.com"}},
            None,
        ]
        client.last_error = "Permission denied"

        test_file = tmp_path / "secret.txt"
        test_file.write_text("restricted", encoding="utf-8")

        result = share_handler.share_file(client, str(test_file))

        assert result["success"] is False
        assert "Permission failed" in result["error"]
        assert result["file_id"] == "existing-file-id"
        assert result["link"] is None

    def test_a_failed_link_lookup_is_a_failure_even_though_the_permission_was_set(self, tmp_path, client) -> None:
        client._find_existing_file.return_value = {"id": "file-id"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            None,
        ]
        client.last_error = "API error"

        test_file = tmp_path / "doc.txt"
        test_file.write_text("document", encoding="utf-8")

        result = share_handler.share_file(client, str(test_file), public=True)

        assert result["success"] is False
        assert "Link retrieval failed" in result["error"]
        assert result["file_id"] == "file-id"
        assert result["link"] is None

    def test_a_file_already_on_drive_is_reused_rather_than_uploaded_twice(self, tmp_path, client) -> None:
        client._find_existing_file.return_value = {"id": "already-on-drive"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            {"webViewLink": "https://drive.google.com/file/d/already-on-drive/view"},
        ]

        test_file = tmp_path / "existing.txt"
        test_file.write_text("already uploaded", encoding="utf-8")

        result = share_handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert result["file_id"] == "already-on-drive"
        client.get_or_create_project_folder.assert_called_once_with("Shared")
        assert client.drive_service.files().create.called is False

    def test_a_file_with_no_view_link_is_shared_by_its_download_link(self, tmp_path, client) -> None:
        client._find_existing_file.return_value = {"id": "file-id"}

        client._api_call.side_effect = [
            {"id": "perm-id"},
            {"webContentLink": "https://drive.google.com/uc?id=file-id"},
        ]

        test_file = tmp_path / "download.bin"
        test_file.write_bytes(b"\x00\x01")

        result = share_handler.share_file(client, str(test_file), public=True)

        assert result["success"] is True
        assert "uc?id=file-id" in result["link"]


# ---------------------------------------------------------------------------
# set_share_permission — who the link is for
# ---------------------------------------------------------------------------


class TestSetSharePermission:
    """The permission body is the difference between a private file and a public one."""

    def test_a_public_permission_is_anyone_with_the_link_as_a_reader(self, client) -> None:
        client._api_call.return_value = {"id": "perm-id"}

        permission_id = share_handler.set_share_permission(client, "file-123", public=True)

        body = client.drive_service.permissions().create.call_args.kwargs["body"]
        assert permission_id == "perm-id"
        assert body["type"] == "anyone"
        assert body["role"] == "reader"
        assert "emailAddress" not in body

    def test_a_restricted_permission_is_the_authenticated_user_and_nobody_else(self, client) -> None:
        client._api_call.side_effect = [
            {"user": {"emailAddress": "user@example.com"}},
            {"id": "perm-id"},
        ]

        permission_id = share_handler.set_share_permission(client, "file-123", public=False)

        body = client.drive_service.permissions().create.call_args.kwargs["body"]
        assert permission_id == "perm-id"
        assert body["type"] == "user"
        assert body["role"] == "reader"
        assert body["emailAddress"] == "user@example.com"

    def test_an_unknown_account_refuses_the_permission_rather_than_opening_it_to_anyone(self, client) -> None:
        """No email must never fall through to type=anyone — that is a private file published."""
        client._api_call.return_value = None

        result = share_handler.set_share_permission(client, "file-123", public=False)

        assert result is None
        assert "email" in client.last_error.lower()
        assert client.drive_service.permissions().create.called is False


# ---------------------------------------------------------------------------
# get_share_link — which of the two links a user is handed
# ---------------------------------------------------------------------------


class TestGetShareLink:
    """Drive answers with two links; the product has to pick one."""

    def test_the_view_link_is_preferred_over_the_download_link(self, client) -> None:
        client._api_call.return_value = {
            "webViewLink": "https://view-link",
            "webContentLink": "https://content-link",
        }

        link = share_handler.get_share_link(client, "file-id")

        assert link == "https://view-link"
        assert client.drive_service.files().get.call_args.kwargs["fileId"] == "file-id"

    def test_the_download_link_is_used_when_drive_reports_no_view_link(self, client) -> None:
        client._api_call.return_value = {
            "webViewLink": None,
            "webContentLink": "https://content-link",
        }

        link = share_handler.get_share_link(client, "file-id")

        assert link == "https://content-link"

    def test_a_failed_lookup_yields_no_link_rather_than_an_empty_one(self, client) -> None:
        client._api_call.return_value = None

        link = share_handler.get_share_link(client, "file-id")

        assert link is None


# =============================================
