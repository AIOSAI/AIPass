# =================== AIPass ====================
# Name: client.py
# Description: Google Drive client — auth, folders, file lookup via @api gateway
# Version: 2.1.0
# Created: 2026-04-16
# Modified: 2026-10-21
# =============================================

"""Google Drive client.

All auth flows through ``aipass.api.apps.modules.google_client``; never console-OAuth.
"""

from __future__ import annotations

import threading
from typing import Any

from aipass.prax import logger

from ..audit import trail

try:
    from aipass.api.apps.modules.google_client import (
        api_call_with_retry,
        get_drive_service,
    )

    GOOGLE_API_AVAILABLE = True
except ImportError:
    logger.info("Google API client libraries not available")
    GOOGLE_API_AVAILABLE = False
    get_drive_service = None  # type: ignore[assignment]
    api_call_with_retry = None  # type: ignore[assignment]


BACKUP_FOLDER_NAME = "AIPass Backups"
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveClient:
    """Google Drive v3 client backed by the @api gateway."""

    def __init__(self) -> None:
        self._drive_service: Any = None
        self._thread_local = threading.local()
        self._folder_cache_lock = threading.Lock()
        self.backup_folder_id: str | None = None
        self.project_folder_cache: dict[str, str] = {}
        self.file_tracker: dict[str, dict] = {}
        # (parent_id, name) -> id of every live file, from drive_sync's listing at run start; a create adopts a hit.
        self.live_files: dict[tuple[str, str], str] = {}
        self.last_error: str | None = None

    @property
    def drive_service(self) -> Any:
        """Return thread-local service if set, otherwise main service."""
        return getattr(self._thread_local, "service", None) or self._drive_service

    def authenticate(self) -> bool:
        """Authenticate through the @api gateway."""
        if not GOOGLE_API_AVAILABLE:
            self.last_error = "Google API libraries not installed"
            logger.error(
                "[backup] Drive sync unavailable: aipass.api Google client gateway "
                "failed to import. Install: pip install google-auth "
                "google-auth-oauthlib google-api-python-client"
            )
            trail.log_operation(
                "drive_authenticate",
                {"success": False, "reason": self.last_error},
            )
            return False

        try:
            self._drive_service = get_drive_service(thread_safe=False)  # type: ignore[misc]
            if self._drive_service is None:
                self.last_error = "get_drive_service returned None"
                trail.log_operation(
                    "drive_authenticate",
                    {"success": False, "reason": self.last_error},
                )
                return False
            trail.log_operation("drive_authenticate", {"success": True})
            return True
        except Exception as exc:
            self.last_error = str(exc)
            # Only "not installed" (a human must pip install) is ERROR for medic; auth/network is transient.
            if "libraries not installed" in self.last_error:
                logger.error(f"[backup] Drive sync unavailable: {exc}")
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
                self.last_error = str(exc)
                logger.info(f"API call retry also failed: {exc}")
                return None

    def _build_thread_service(self) -> Any:
        """Build an isolated Drive service for the current thread."""
        return get_drive_service(thread_safe=True)  # type: ignore[misc]

    def _verify_folder_id(self, folder_id: str) -> bool | None:
        """Check that a folder exists and is not trashed; None when Drive could not be asked.

        Callers read None like False and search again; the searches refuse to create on no answer.
        """
        if not self.drive_service:
            return None
        try:
            request = self.drive_service.files().get(fileId=folder_id, fields="id,trashed")
            result = self._api_call(request)
            if result is None:
                return None
            return not result.get("trashed", True)
        except Exception as exc:
            logger.info(f"Failed to verify folder {folder_id}: {exc}")
            return None

    def get_or_create_backup_folder(self) -> str | None:
        """Get or create the root 'AIPass Backups' folder.

        Takes no lock: callers hold _folder_cache_lock (or run single-threaded); locking here deadlocks.
        """
        if self.backup_folder_id:
            if self._verify_folder_id(self.backup_folder_id):
                return self.backup_folder_id
            self.backup_folder_id = None

        if not self.drive_service:
            return None

        query = f"name='{BACKUP_FOLDER_NAME}' and mimeType='{FOLDER_MIME}' and trashed=false"
        try:
            request = self.drive_service.files().list(
                q=query,
                spaces="drive",
                fields="files(id,name)",
            )
            result = self._api_call(request)
            if result is None:
                # No answer is not an empty search: a create here makes a second root.
                self.last_error = "Backup folder search got no answer - not creating a second root"
                logger.warning(self.last_error)
                return None
            if result.get("files"):
                self.backup_folder_id = result["files"][0]["id"]
                trail.log_operation(
                    "get_backup_folder",
                    {"action": "found_existing", "folder_id": self.backup_folder_id},
                )
                return self.backup_folder_id
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning(f"Failed to search for backup folder: {exc}")
            return None

        try:
            metadata = {"name": BACKUP_FOLDER_NAME, "mimeType": FOLDER_MIME}
            request = self.drive_service.files().create(body=metadata, fields="id")
            result = self._api_call(request)
            if not result:
                return None

            new_id: str = result["id"]
            self.backup_folder_id = new_id

            if not self._verify_folder_id(new_id):
                self.last_error = f"Backup folder {new_id} created but not accessible"
                self.backup_folder_id = None
                return None

            trail.log_operation(
                "get_backup_folder",
                {"action": "created_new", "folder_id": new_id},
            )
            return self.backup_folder_id
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning(f"Failed to create backup folder: {exc}")

        return None

    def get_or_create_project_folder(self, project_name: str) -> str | None:
        """Get or create a project subfolder; the lock spans check, search and create so threads make no duplicates."""
        with self._folder_cache_lock:
            if project_name in self.project_folder_cache:
                folder_id = self.project_folder_cache[project_name]
                if self._verify_folder_id(folder_id):
                    return folder_id
                del self.project_folder_cache[project_name]

            backup_folder_id = self.get_or_create_backup_folder()
            if not backup_folder_id:
                return None

            query = (
                f"name='{project_name}' "
                f"and mimeType='{FOLDER_MIME}' "
                f"and '{backup_folder_id}' in parents "
                f"and trashed=false"
            )
            try:
                request = self.drive_service.files().list(
                    q=query,
                    spaces="drive",
                    fields="files(id,name)",
                )
                result = self._api_call(request)
                if result is None:
                    # No answer is not an empty search: a create here makes a duplicate project folder.
                    self.last_error = (
                        f"Project folder search for '{project_name}' got no answer - not creating a duplicate"
                    )
                    logger.warning(self.last_error)
                    return None
                if result.get("files"):
                    folder_id = result["files"][0]["id"]
                    self.project_folder_cache[project_name] = folder_id
                    return folder_id
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning(f"Failed to search for project folder '{project_name}': {exc}")
                return None

            try:
                metadata = {
                    "name": project_name,
                    "mimeType": FOLDER_MIME,
                    "parents": [backup_folder_id],
                }
                request = self.drive_service.files().create(body=metadata, fields="id")
                result = self._api_call(request)
                if result:
                    folder_id = result["id"]
                    self.project_folder_cache[project_name] = folder_id
                    return folder_id
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning(f"Failed to create project folder '{project_name}': {exc}")

            return None

    def _find_or_create_segment(self, parent_id: str, name: str) -> str | None:
        """Search for or create a single folder segment under parent_id."""
        query = f"name='{name}' and mimeType='{FOLDER_MIME}' and '{parent_id}' in parents and trashed=false"
        request = self.drive_service.files().list(
            q=query,
            spaces="drive",
            fields="files(id,name)",
        )
        result = self._api_call(request)
        if result is None:
            # No answer is not an empty search: a create here makes a duplicate folder.
            self.last_error = f"Folder search for '{name}' got no answer - not creating a duplicate"
            logger.warning(self.last_error)
            return None
        if result.get("files"):
            return result["files"][0]["id"]

        metadata = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        request = self.drive_service.files().create(body=metadata, fields="id")
        result = self._api_call(request)
        return result["id"] if result else None

    def get_or_create_nested_folder(
        self,
        parent_id: str,
        folder_path: str,
    ) -> str | None:
        """Create a nested folder hierarchy segment by segment, the whole walk under the lock."""
        if not folder_path or folder_path == ".":
            return parent_id

        with self._folder_cache_lock:
            cache_key = f"{parent_id}:{folder_path}"
            if cache_key in self.project_folder_cache:
                folder_id = self.project_folder_cache[cache_key]
                if self._verify_folder_id(folder_id):
                    return folder_id
                del self.project_folder_cache[cache_key]

            current_parent = parent_id
            segments = [s for s in folder_path.split("/") if s]

            for segment in segments:
                segment_key = f"{current_parent}:{segment}"

                if segment_key in self.project_folder_cache:
                    cached_id = self.project_folder_cache[segment_key]
                    if self._verify_folder_id(cached_id):
                        current_parent = cached_id
                        continue
                    del self.project_folder_cache[segment_key]

                try:
                    folder_id = self._find_or_create_segment(current_parent, segment)
                except Exception as exc:
                    self.last_error = str(exc)
                    logger.info(f"Failed to handle nested folder '{segment}': {exc}")
                    return None
                if not folder_id:
                    return None
                current_parent = folder_id
                self.project_folder_cache[segment_key] = current_parent

            self.project_folder_cache[cache_key] = current_parent
            return current_parent

    def _find_existing_file(
        self,
        filename: str,
        parent_folder_id: str,
    ) -> dict | None:
        """Find a file by name in a folder (excludes trashed)."""
        query = f"name='{filename}' and '{parent_folder_id}' in parents and trashed=false"
        try:
            request = self.drive_service.files().list(
                q=query,
                spaces="drive",
                fields="files(id,name)",
            )
            result = self._api_call(request)
            if result and result.get("files"):
                return result["files"][0]
        except Exception as exc:
            logger.info(f"Failed to find file {filename}: {exc}")
        return None
