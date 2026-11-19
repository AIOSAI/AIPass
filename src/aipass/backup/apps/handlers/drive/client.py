# =================== AIPass ====================
# Name: client.py
# Description: Google Drive client — auth, folders, file lookup via @api gateway
# Version: 2.3.0
# Created: 2026-04-16
# Modified: 2026-11-18
# =============================================

"""Google Drive client.

All auth flows through ``aipass.api.apps.modules.google_client``; never console-OAuth.
"""

from __future__ import annotations

import re
import socket
import threading
from typing import Any

from aipass.prax import logger

from ..audit import trail

try:
    from aipass.api import api_call_with_retry, get_drive_service

    GOOGLE_API_AVAILABLE = True
except ImportError:
    logger.info("Google API client libraries not available")
    GOOGLE_API_AVAILABLE = False
    get_drive_service = None  # type: ignore[assignment]
    api_call_with_retry = None  # type: ignore[assignment]


BACKUP_FOLDER_NAME = "AIPass Backups"
FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_PACKAGES = "google-auth google-auth-oauthlib google-api-python-client"


class DriveError(Exception):
    """Drive gave no answer, or no usable one: a failure, never an empty result."""


#: Network-layer failures known by name across httplib2, urllib3 and requests, none of them a Google answer.
_NETWORK_ERROR_NAMES = {"ServerNotFoundError", "NameResolutionError", "NewConnectionError", "ConnectionError"}
_UNRESOLVED_HOST = re.compile(r"Failed to resolve '([^']+)'|Unable to find the server at ([\w.-]+)")


def network_down(exc: BaseException) -> str:
    """The plain line when exc, or anything in its cause chain, is the network failing; "" for a Google answer."""
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        seen.add(id(link))
        if isinstance(link, (socket.gaierror, ConnectionError, TimeoutError)) or (
            type(link).__name__ in _NETWORK_ERROR_NAMES
        ):
            host = _UNRESOLVED_HOST.search(str(exc))
            if host:
                return f"network is down (cannot resolve {host.group(1) or host.group(2)})"
            return f"network is down ({type(link).__name__}: {link})"
        link = link.__cause__ or link.__context__
    return ""


def quoted(value: str) -> str:
    """A string literal for a Drive search query: ' and \\ escaped, so "Bob's notes" stays one name."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class DriveClient:
    """Google Drive v3 client backed by the @api gateway."""

    def __init__(self) -> None:
        self._drive_service: Any = None
        self._thread_local = threading.local()
        self._folder_cache_lock = threading.Lock()
        self.backup_folder_id: str | None = None
        self.project_folder_cache: dict[str, str] = {}
        self.file_tracker: dict[str, dict] = {}
        # Workers write file_tracker while the batch saves it; the save copies it under this lock.
        self.tracker_lock = threading.Lock()
        # (parent_id, name) -> id of every live file, from drive_sync's listing at run start; a create adopts a hit.
        self.live_files: dict[tuple[str, str], str] = {}
        self.last_error: str | None = None
        # Set by the first call that failed for want of a network; drive_sync stops on it.
        self.network_down = ""

    @property
    def drive_service(self) -> Any:
        """Return thread-local service if set, otherwise main service."""
        return getattr(self._thread_local, "service", None) or self._drive_service

    def authenticate(self) -> bool:
        """Authenticate through the @api gateway: True, or False only on a failure that last_error names."""
        try:
            if not GOOGLE_API_AVAILABLE:
                raise DriveError("Google API libraries not installed")
            self._drive_service = get_drive_service(thread_safe=False)  # type: ignore[misc]
            if self._drive_service is None:
                raise DriveError("get_drive_service returned None")
            trail.log_operation("drive_authenticate", {"success": True})
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self.network_down = network_down(exc)
            # Only "not installed" (a human must pip install) is ERROR for medic; auth/network is transient.
            if "libraries not installed" in self.last_error:
                hint = "" if "pip install" in self.last_error else f". Install: pip install {GOOGLE_PACKAGES}"
                logger.error(f"[backup] Drive sync unavailable: {exc}{hint}")
            else:
                logger.warning(f"Drive authentication failed: {exc}")
            trail.log_operation(
                "drive_authenticate",
                {"success": False, "error": self.last_error},
            )
            return False

    def _api_call(self, request: Any, max_retries: int = 3) -> Any:
        """Execute a Google API request with retry."""
        try:
            return api_call_with_retry(request, max_retries=max_retries)  # type: ignore[misc]
        except Exception as first_exc:
            logger.info(f"API call failed, rebuilding thread service: {first_exc}")
            try:
                self._thread_local.service = self._build_thread_service()
                return api_call_with_retry(request, max_retries=1)  # type: ignore[misc]
            except Exception as exc:
                self.last_error = self._thread_local.failure = str(exc)
                self.network_down = self.network_down or network_down(exc)
                logger.info(f"API call retry also failed: {exc}")
                return None

    def _create(self, metadata: dict, what: str) -> str:
        """The new item's id; DriveError naming the cause _api_call recorded, else ``what``, on no answer."""
        # Per thread: last_error is shared by the upload workers and may hold another call's error.
        self._thread_local.failure = None
        result = self._api_call(self.drive_service.files().create(body=metadata, fields="id"))
        if not result:
            raise DriveError(self._thread_local.failure or what)
        return result["id"]

    def _build_thread_service(self) -> Any:
        """Build an isolated Drive service for the current thread."""
        return get_drive_service(thread_safe=True)  # type: ignore[misc]

    def _verify_folder_id(self, folder_id: str) -> bool | None:
        """True for a live folder, False for a trashed one; None only when Drive could not be asked.

        Callers read None like False and search again; the searches refuse to create on no answer.
        """
        try:
            if not self.drive_service:
                raise DriveError("No Drive service")
            request = self.drive_service.files().get(fileId=folder_id, fields="id,trashed")
            result = self._api_call(request)
            if result is None:
                raise DriveError("no answer")
            return not result.get("trashed", True)
        except Exception as exc:
            logger.info(f"Failed to verify folder {folder_id}: {exc}")
            return None

    def get_or_create_backup_folder(self) -> str | None:
        """The root 'AIPass Backups' folder id; None only on a failure that last_error names.

        Takes no lock: callers hold _folder_cache_lock (or run single-threaded); locking here deadlocks.
        """
        if self.backup_folder_id:
            if self._verify_folder_id(self.backup_folder_id):
                return self.backup_folder_id
            self.backup_folder_id = None

        query = f"name={quoted(BACKUP_FOLDER_NAME)} and mimeType='{FOLDER_MIME}' and trashed=false"
        try:
            if not self.drive_service:
                raise DriveError("No Drive service - authenticate first")
            request = self.drive_service.files().list(q=query, spaces="drive", fields="files(id,name)")
            result = self._api_call(request)
            if result is None:
                # No answer is not an empty search: a create here makes a second root.
                raise DriveError("Backup folder search got no answer - not creating a second root")
            if result.get("files"):
                self.backup_folder_id = result["files"][0]["id"]
                trail.log_operation(
                    "get_backup_folder",
                    {"action": "found_existing", "folder_id": self.backup_folder_id},
                )
                return self.backup_folder_id

            metadata = {"name": BACKUP_FOLDER_NAME, "mimeType": FOLDER_MIME}
            new_id = self._create(metadata, "Backup folder create got no answer")
            if not self._verify_folder_id(new_id):
                raise DriveError(f"Backup folder {new_id} created but not accessible")

            self.backup_folder_id = new_id
            trail.log_operation("get_backup_folder", {"action": "created_new", "folder_id": new_id})
            return new_id
        except DriveError as exc:
            self.last_error = str(exc)
            logger.warning(self.last_error)
            return None
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning(f"Failed to find or create the backup folder: {exc}")
            return None

    def get_or_create_project_folder(self, project_name: str) -> str | None:
        """A project subfolder's id; None only on a failure that last_error names.

        The lock spans check, search and create so threads make no duplicates.
        """
        with self._folder_cache_lock:
            # The cache lives one run, and the run listed Drive at its start: a hit costs no call.
            if project_name in self.project_folder_cache:
                return self.project_folder_cache[project_name]

            try:
                backup_folder_id = self.get_or_create_backup_folder()
                if not backup_folder_id:
                    # get_or_create_backup_folder named the cause; it reaches the operator unchanged.
                    raise DriveError(self.last_error or f"No backup folder for project '{project_name}'")
                query = (
                    f"name={quoted(project_name)} "
                    f"and mimeType='{FOLDER_MIME}' "
                    f"and '{backup_folder_id}' in parents "
                    f"and trashed=false"
                )
                request = self.drive_service.files().list(q=query, spaces="drive", fields="files(id,name)")
                result = self._api_call(request)
                if result is None:
                    # No answer is not an empty search: a create here makes a duplicate project folder.
                    raise DriveError(
                        f"Project folder search for '{project_name}' got no answer - not creating a duplicate"
                    )
                if result.get("files"):
                    folder_id: str = result["files"][0]["id"]
                else:
                    metadata = {"name": project_name, "mimeType": FOLDER_MIME, "parents": [backup_folder_id]}
                    folder_id = self._create(metadata, f"Project folder create for '{project_name}' got no answer")
                self.project_folder_cache[project_name] = folder_id
                return folder_id
            except DriveError as exc:
                self.last_error = str(exc)
                logger.warning(self.last_error)
                return None
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning(f"Failed to find or create project folder '{project_name}': {exc}")
                return None

    def _find_or_create_segment(self, parent_id: str, name: str) -> str:
        """The id of one folder segment under parent_id, found or created; DriveError when Drive gave no answer."""
        query = f"name={quoted(name)} and mimeType='{FOLDER_MIME}' and '{parent_id}' in parents and trashed=false"
        result = self._api_call(self.drive_service.files().list(q=query, spaces="drive", fields="files(id,name)"))
        if result is None:
            # No answer is not an empty search: a create here makes a duplicate folder.
            raise DriveError(f"Folder search for '{name}' got no answer - not creating a duplicate")
        if result.get("files"):
            return result["files"][0]["id"]

        metadata = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        return self._create(metadata, f"Folder create for '{name}' got no answer")

    def get_or_create_nested_folder(
        self,
        parent_id: str,
        folder_path: str,
    ) -> str | None:
        """A nested folder's id, made segment by segment under the lock; None only on a failure last_error names."""
        if not folder_path or folder_path == ".":
            return parent_id

        with self._folder_cache_lock:
            cache_key = f"{parent_id}:{folder_path}"
            if cache_key in self.project_folder_cache:
                return self.project_folder_cache[cache_key]

            current_parent = parent_id
            segments = [s for s in folder_path.split("/") if s]

            for segment in segments:
                segment_key = f"{current_parent}:{segment}"

                if segment_key in self.project_folder_cache:
                    current_parent = self.project_folder_cache[segment_key]
                    continue

                try:
                    current_parent = self._find_or_create_segment(current_parent, segment)
                except DriveError as exc:
                    self.last_error = str(exc)
                    logger.warning(self.last_error)
                    return None
                except Exception as exc:
                    self.last_error = str(exc)
                    logger.warning(f"Failed to find or create nested folder '{segment}': {exc}")
                    return None
                self.project_folder_cache[segment_key] = current_parent

            self.project_folder_cache[cache_key] = current_parent
            return current_parent

    def _find_existing_file(
        self,
        filename: str,
        parent_folder_id: str,
    ) -> dict | None:
        """The untrashed file of that name in the folder, or None when there is none; DriveError on no answer."""
        query = f"name={quoted(filename)} and '{parent_folder_id}' in parents and trashed=false"
        result = self._api_call(self.drive_service.files().list(q=query, spaces="drive", fields="files(id,name)"))
        if result is None:
            # No answer is not "not there": the caller would upload a twin.
            raise DriveError(f"File search for '{filename}' got no answer - not uploading a twin")
        files = result.get("files")
        return files[0] if files else None
