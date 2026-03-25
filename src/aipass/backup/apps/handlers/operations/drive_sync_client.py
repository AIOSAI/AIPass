# =================== AIPass ====================
# Name: drive_sync_client.py
# Description: Google Drive Sync Client Handler
# Version: 1.0.0
# Created: 2026-02-20
# Modified: 2026-03-09
# =============================================

"""
Google Drive Sync Client Handler

Contains the GoogleDriveSync class - the core implementation for
uploading backup files to Google Drive with OAuth2 authentication.
Called exclusively by the google_drive_sync module orchestrator.
"""

# =============================================
# IMPORTS
# =============================================

import sys
import copy
import fcntl
import json
import os
import ssl
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from aipass.prax import logger

# Google API imports (optional — not installed in every environment)
try:
    from googleapiclient.discovery import build  # type: ignore[import-unresolved]
    from googleapiclient.http import MediaFileUpload  # type: ignore[import-unresolved]
    from google.auth.transport.requests import Request  # type: ignore[import-unresolved]
    from google.oauth2.credentials import Credentials  # type: ignore[import-unresolved]
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-unresolved]
    GOOGLE_API_AVAILABLE = True
except ImportError as e:
    logger.info(f"Google API libraries not available: {e}")
    GOOGLE_API_AVAILABLE = False
    build = None  # type: ignore[assignment]
    MediaFileUpload = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    InstalledAppFlow = None  # type: ignore[assignment]

# JSON handler for data persistence
from aipass.backup.apps.handlers.json.drive_sync_json import (
    load_config as _load_config_fn,
    save_config as _save_config_fn,
    load_data as _load_data_fn,
    save_data as _save_data_fn,
    load_log as _load_log_fn,
    save_log as _save_log_fn,
    log_operation as _log_operation_fn,
)
from aipass.backup.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

_BACKUP_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/backup/
JSON_DIR = _BACKUP_ROOT / "backup_json"

SCOPES = ['https://www.googleapis.com/auth/drive.file']
MODULE_NAME = "google_drive_sync"
CONFIG_FILE = JSON_DIR / f"{MODULE_NAME}_config.json"
DATA_FILE = JSON_DIR / f"{MODULE_NAME}_data.json"
LOG_FILE = JSON_DIR / f"{MODULE_NAME}_log.json"
_log_lock = threading.Lock()

# Convenience wrappers that use this module's JSON file paths
def _load_config():
    """Load config using module constants."""
    return _load_config_fn(CONFIG_FILE)

def _save_config(config):
    """Save config using module constants."""
    _save_config_fn(CONFIG_FILE, config)

def _load_data():
    """Load data using module constants."""
    return _load_data_fn(DATA_FILE)

def _save_data(data):
    """Save data using module constants."""
    _save_data_fn(DATA_FILE, data)

def _load_log(max_retries=3):
    """Load log using module constants."""
    return _load_log_fn(LOG_FILE, max_retries)

def _save_log(log):
    """Save log using module constants."""
    _save_log_fn(LOG_FILE, log)

def _log_operation(operation, details, success=True, correlation_id=None):
    """Log operation using module constants."""
    _log_operation_fn(LOG_FILE, operation, details, success, correlation_id)


def _atomic_json_write(file_path: Path, data: Any):
    """Write JSON atomically via temp file + rename to prevent corruption."""
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, str(file_path))
    except Exception as e:
        logger.warning(f"Atomic JSON write failed for {file_path}: {e}")
        try:
            os.unlink(tmp_path)
        except OSError as e:
            logger.info(f"Failed to clean up temp file {tmp_path}: {e}")
        raise


class GoogleDriveSync:
    """Handles Google Drive integration for backup uploads"""

    def __init__(self):
        """Initialize Google Drive sync with AIPass standards"""
        self.config = _load_config()
        self.data = _load_data()

        # Paths
        self.creds_path = Path.home() / '.aipass' / 'drive_creds.json'
        self.client_secrets_path = Path(__file__).parent.parent / 'credentials.json'

        # Runtime state
        self._drive_service = None
        self._thread_local = threading.local()
        self._folder_cache_lock = threading.Lock()
        self.backup_folder_id = None
        self.project_folder_cache = self.data.get("runtime_state", {}).get("cached_folders", {})
        self.file_tracker = self.data.get("runtime_state", {}).get("file_tracker", {})

        self.last_error = None  # Last error message for callers
        self.tracker_was_reset = False  # Set True when new folder = tracker invalidated

        # Check if Google API is available
        if not GOOGLE_API_AVAILABLE:

            self.config["config"]["enabled"] = False
            _save_config(self.config)

    @property
    def drive_service(self):
        """Return thread-local service if set, otherwise the main service"""
        return getattr(self._thread_local, 'service', None) or self._drive_service

    @drive_service.setter
    def drive_service(self, value):
        """Set the main Drive API service instance."""
        self._drive_service = value

    def authenticate(self) -> bool:
        """Authenticate with Google Drive using OAuth credentials"""
        json_handler.log_operation("drive_authenticate_started")

        if not GOOGLE_API_AVAILABLE:
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


            return False

        start_time = datetime.now()
        creds = None

        # Load existing credentials if they exist
        if self.creds_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.creds_path), SCOPES)  # type: ignore[union-attr]
            except Exception as e:
                logger.warning(f"Failed to load credentials from {self.creds_path}: {e}")
                creds = None

        # If no valid credentials, start OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())  # type: ignore[misc]

                except Exception as e:
                    logger.warning(f"Failed to refresh credentials: {e}")
                    creds = None

            if not creds:
                # Check if client secrets file exists
                if not self.client_secrets_path.exists():


                    return False

                try:


                    flow = InstalledAppFlow.from_client_secrets_file(  # type: ignore[union-attr]
                        str(self.client_secrets_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                except Exception as e:
                    logger.warning(f"OAuth flow failed: {e}")
                    _log_operation("authenticate", {"message": f"OAuth flow failed: {e}", "error_details": {"exception_type": type(e).__name__, "stack_trace": str(e)}}, success=False)
                    return False

        # Save credentials for next time
        try:
            # Create .aipass directory if it doesn't exist
            self.creds_path.parent.mkdir(parents=True, exist_ok=True)

            # Save credentials
            with open(self.creds_path, 'w', encoding='utf-8') as f:
                f.write(creds.to_json())

        except Exception as e:
            logger.warning(f"Failed to save credentials to {self.creds_path}: {e}")

        # Build Drive service
        try:
            self.creds = creds  # Store for building per-thread services
            self.drive_service = build('drive', 'v3', credentials=creds)  # type: ignore[misc]

            # Update runtime state (ensure runtime_state exists first)
            if "runtime_state" not in self.data:
                self.data["runtime_state"] = {}
            self.data["runtime_state"]["authenticated"] = True
            _save_data(self.data)

            # Log successful authentication
            execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
            _log_operation("authenticate", {"message": "Successfully authenticated with Google Drive", "execution_time_ms": execution_time}, success=True)

            return True
        except Exception as e:
            logger.warning(f"Failed to build Drive service: {e}")
            _log_operation("authenticate", {"message": f"Failed to build Drive service: {e}", "error_details": {"exception_type": type(e).__name__, "stack_trace": str(e)}}, success=False)
            return False

    def get_storage_quota(self) -> Optional[Dict[str, Any]]:
        """Get Google Drive storage quota information"""
        try:
            if not self.drive_service:
                return None

            about = self.drive_service.about().get(fields="storageQuota").execute()
            quota = about.get('storageQuota', {})

            # Convert bytes to GB for readability
            limit = int(quota.get('limit', 0))
            usage = int(quota.get('usage', 0))

            limit_gb = limit / (1024**3)
            usage_gb = usage / (1024**3)
            free_gb = (limit - usage) / (1024**3)
            percent_used = (usage / limit * 100) if limit > 0 else 0

            return {
                'limit_gb': limit_gb,
                'usage_gb': usage_gb,
                'free_gb': free_gb,
                'percent_used': percent_used
            }
        except Exception as e:
            logger.warning(f"Failed to get storage quota: {e}")
            return None

    def _verify_folder_id(self, folder_id: str) -> bool:
        """Verify a cached folder ID exists and is NOT trashed."""
        if not self.drive_service or not folder_id:
            return False
        try:
            result = self._api_call_with_retry(
                self.drive_service.files().get(fileId=folder_id, fields='id,trashed')
            )
            return not result.get('trashed', False)
        except Exception as e:
            logger.warning(f"Failed to verify folder {folder_id}: {e}")
            return False

    def get_or_create_backup_folder(self) -> Optional[str]:
        """Get or create the main 'AIPass Backups' folder in Drive.

        Returns folder ID or None on failure. Caller must handle None.
        """
        if self.backup_folder_id:
            # Verify cached ID isn't trashed
            if self._verify_folder_id(self.backup_folder_id):
                return self.backup_folder_id
            self.backup_folder_id = None

        try:
            if not self.drive_service:
                raise RuntimeError("Drive service not authenticated")

            # Search for existing folder (excludes trashed)
            results = self._api_call_with_retry(self.drive_service.files().list(
                q="name='AIPass Backups' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ))

            folders = results.get('files', [])

            if folders:
                self.backup_folder_id = folders[0]['id']
            else:
                # Creating NEW folder - old one is gone/trashed
                folder_metadata = {
                    'name': 'AIPass Backups',
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                folder = self._api_call_with_retry(self.drive_service.files().create(
                    body=folder_metadata,
                    fields='id'
                ))
                self.backup_folder_id = folder.get('id')
                if not self.backup_folder_id:
                    raise RuntimeError("Drive API returned no folder ID after create")

                # Reset tracker - all old drive_ids point to dead files
                old_count = len(self.file_tracker)
                if old_count > 0:
                    self.file_tracker.clear()
                    self.project_folder_cache.clear()
                    if "runtime_state" in self.data:
                        self.data["runtime_state"]["file_tracker"] = {}
                        self.data["runtime_state"]["cached_folders"] = {}
                    self._save_file_tracker()
                    self.tracker_was_reset = True
                    _log_operation("tracker_reset", {
                        "message": f"New backup folder created - reset {old_count} tracker entries",
                        "old_tracker_count": old_count,
                        "new_folder_id": self.backup_folder_id
                    })

            # Verify the folder is actually accessible
            if not self._verify_folder_id(self.backup_folder_id):
                raise RuntimeError(f"Backup folder {self.backup_folder_id} created but not accessible")

            return self.backup_folder_id

        except Exception as e:
            logger.warning(f"Backup folder setup failed: {e}")
            self.last_error = f"Backup folder setup failed: {e}"
            return None

    def get_or_create_project_folder(self, project_name: str) -> Optional[str]:
        """Get or create project subfolder within AIPass Backups."""
        # Lock covers cache check + search + create to prevent duplicate folders
        with self._folder_cache_lock:
            if project_name in self.project_folder_cache:
                folder_id = self.project_folder_cache[project_name]
                if self._verify_folder_id(folder_id):
                    return folder_id
                # Cached ID is trashed or gone - clear it
                del self.project_folder_cache[project_name]
                if project_name in self.data.get("runtime_state", {}).get("cached_folders", {}):
                    del self.data["runtime_state"]["cached_folders"][project_name]
                    _save_data(self.data)

            backup_folder_id = self.get_or_create_backup_folder()
            if not backup_folder_id:
                return None

            try:
                if not self.drive_service:
                    return None
                results = self._api_call_with_retry(self.drive_service.files().list(
                    q=f"name='{project_name}' and mimeType='application/vnd.google-apps.folder' and '{backup_folder_id}' in parents and trashed=false",
                    fields="files(id, name)"
                ))

                folders = results.get('files', [])

                if folders:
                    project_folder_id = folders[0]['id']
                else:
                    folder_metadata = {
                        'name': project_name,
                        'mimeType': 'application/vnd.google-apps.folder',
                        'parents': [backup_folder_id]
                    }
                    folder = self._api_call_with_retry(self.drive_service.files().create(
                        body=folder_metadata,
                        fields='id'
                    ))
                    project_folder_id = folder.get('id')

                self.project_folder_cache[project_name] = project_folder_id
                return project_folder_id

            except Exception as e:
                logger.warning(f"Failed to get or create project folder '{project_name}': {e}")
                return None

    def get_or_create_nested_folder(self, parent_folder_id: str, folder_path: str) -> Optional[str]:
        """Create nested folder structure in Google Drive"""
        if not folder_path or folder_path == '.':
            return parent_folder_id

        # Lock covers cache check + search + create to prevent duplicate folders
        cache_key = f"{parent_folder_id}:{folder_path}"
        with self._folder_cache_lock:
            if cache_key in self.project_folder_cache:
                folder_id = self.project_folder_cache[cache_key]
                if self._verify_folder_id(folder_id):
                    return folder_id
                # Cached ID is trashed or gone - clear it
                del self.project_folder_cache[cache_key]
                if cache_key in self.data.get("runtime_state", {}).get("cached_folders", {}):
                    del self.data["runtime_state"]["cached_folders"][cache_key]
                    _save_data(self.data)

            try:
                path_parts = folder_path.split('/')
                current_parent_id = parent_folder_id

                for part in path_parts:
                    if not part:
                        continue

                    # Check cache for this intermediate path segment too
                    segment_key = f"{current_parent_id}:{part}"
                    if segment_key in self.project_folder_cache:
                        cached_id = self.project_folder_cache[segment_key]
                        if self._verify_folder_id(cached_id):
                            current_parent_id = cached_id
                            continue
                        del self.project_folder_cache[segment_key]

                    if not self.drive_service:
                        return parent_folder_id
                    results = self._api_call_with_retry(self.drive_service.files().list(
                        q=f"name='{part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent_id}' in parents and trashed=false",
                        fields="files(id, name)"
                    ))

                    folders = results.get('files', [])

                    if folders:
                        current_parent_id = folders[0]['id']
                    else:
                        folder_metadata = {
                            'name': part,
                            'mimeType': 'application/vnd.google-apps.folder',
                            'parents': [current_parent_id]
                        }
                        if not self.drive_service:
                            return parent_folder_id
                        folder = self._api_call_with_retry(self.drive_service.files().create(
                            body=folder_metadata,
                            fields='id'
                        ))
                        current_parent_id = folder.get('id')

                    # Cache each intermediate segment
                    self.project_folder_cache[segment_key] = current_parent_id

                self.project_folder_cache[cache_key] = current_parent_id
                return current_parent_id

            except Exception as e:
                logger.warning(f"Failed to create nested folder '{folder_path}': {e}")
                return parent_folder_id  # Fallback to parent folder

    def upload_backup_file(self, local_file: Path, project_name: str, note: str = "", backup_root: Optional[Path] = None) -> bool:
        """Upload a backup file to the appropriate project folder with nested structure"""
        if not self.drive_service:

            return False

        project_folder_id = self.get_or_create_project_folder(project_name)
        if not project_folder_id:
            return False

        try:
            # Calculate relative path from backup root to maintain folder structure
            if backup_root and backup_root in local_file.parents:
                relative_path = local_file.relative_to(backup_root)
                folder_path = str(relative_path.parent) if relative_path.parent != Path('.') else ""
                # Convert Windows paths to forward slashes for consistency
                folder_path = folder_path.replace('\\', '/')
            else:
                folder_path = ""

            # Get or create the nested folder structure
            target_folder_id = self.get_or_create_nested_folder(project_folder_id, folder_path)
            if not target_folder_id:

                return False

            file_metadata = {
                'name': local_file.name,
                'parents': [target_folder_id],
                'description': f'AIPass backup - {note}' if note else 'AIPass backup'
            }

            media = MediaFileUpload(str(local_file), resumable=True)  # type: ignore[misc]

            # Get file tracker info to avoid API calls when possible
            if backup_root and backup_root in local_file.parents:
                relative_path = local_file.relative_to(backup_root)
                file_key = str(relative_path).replace('\\', '/')
            else:
                file_key = local_file.name

            existing_file = None
            tracked_file = self.file_tracker.get(file_key)

            # Use cached drive_id if file is tracked, otherwise find it
            if tracked_file and tracked_file.get("drive_id"):
                # File is tracked, use cached drive_id
                existing_file = {"id": tracked_file["drive_id"]}

            else:
                # File not tracked or no drive_id, search Drive
                existing_file = self._find_existing_file(local_file.name, target_folder_id)
                if existing_file is None and tracked_file:
                    # File was previously tracked but can't find it on Drive
                    # Skip rather than create duplicate - will retry next sync
                    return False

            # For files called by new sync system, we already know they need upload
            # Skip the size comparison check to avoid redundant work

            if existing_file:
                # Update existing file - don't include parents field for updates
                update_metadata = {
                    'name': local_file.name,
                    'description': f'AIPass backup - {note}' if note else 'AIPass backup'
                }
                file = self._api_call_with_retry(self.drive_service.files().update(
                    fileId=existing_file['id'],
                    body=update_metadata,
                    media_body=media
                ))
                action = "Updated"
            else:
                # Create new file
                file = self._api_call_with_retry(self.drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ))
                action = "Uploaded"

            # Update file tracker with new drive_id
            drive_file_id = file.get('id') if 'file' in locals() else (existing_file.get('id') if existing_file else None)
            if drive_file_id and backup_root:
                self._update_file_tracker(local_file, backup_root, drive_file_id)

            # Update statistics (ensure statistics exists first)
            if "statistics" not in self.data:
                self.data["statistics"] = {
                    "total_uploads": 0,
                    "successful_uploads": 0,
                    "failed_uploads": 0,
                    "total_bytes_uploaded": 0
                }
            self.data["statistics"]["total_uploads"] += 1
            self.data["statistics"]["successful_uploads"] += 1
            self.data["statistics"]["total_bytes_uploaded"] += local_file.stat().st_size
            # Stats saved to disk in batches by sync_backup_files(), not per-file

            # Log operation
            _log_operation(f"upload_file", {
                "message": f"{action} {local_file.name} to {project_name}",
                "file_size": local_file.stat().st_size,
                "project": project_name
            }, success=True)

            return True

        except Exception as e:
            logger.warning(f"Failed to upload {local_file.name}: {e}")
            # Update failure statistics (ensure statistics exists first)
            if "statistics" not in self.data:
                self.data["statistics"] = {
                    "total_uploads": 0,
                    "successful_uploads": 0,
                    "failed_uploads": 0,
                    "total_bytes_uploaded": 0
                }
            self.data["statistics"]["total_uploads"] += 1
            self.data["statistics"]["failed_uploads"] += 1
            _save_data(self.data)

            # Log failure
            _log_operation("upload_file", {
                "message": f"Failed to upload {local_file.name}",
                "error_details": {"exception_type": type(e).__name__, "stack_trace": str(e)}
            }, success=False)
            return False

    def _find_existing_file(self, filename: str, parent_folder_id: str) -> Optional[Dict[str, Any]]:
        """Find existing file in Drive folder with metadata"""
        try:
            if not self.drive_service:
                return None
            # Escape single quotes in filename for Drive API query
            safe_filename = filename.replace("\\", "\\\\").replace("'", "\\'")
            results = self._api_call_with_retry(self.drive_service.files().list(
                q=f"name='{safe_filename}' and '{parent_folder_id}' in parents and trashed=false",
                fields="files(id, name, size, modifiedTime, md5Checksum)"
            ))

            files = results.get('files', [])
            return files[0] if files else None

        except Exception as e:
            logger.warning(f"Failed to find existing file '{filename}' in folder {parent_folder_id}: {e}")
            return None

    def _load_file_tracker(self) -> Dict[str, Dict[str, Any]]:
        """Load file tracker from data JSON"""
        return self.data.get("runtime_state", {}).get("file_tracker", {})

    def _save_file_tracker(self):
        """Save file tracker to data JSON"""
        if "runtime_state" not in self.data:
            self.data["runtime_state"] = {}
        self.data["runtime_state"]["file_tracker"] = self.file_tracker
        _save_data(self.data)

    def _build_thread_service(self):
        """Build a separate Drive service instance for use in a worker thread.

        Loads fresh credentials from disk to avoid sharing credential state
        (token refresh races) and creates a fully isolated HTTP/SSL connection.
        """
        creds = Credentials.from_authorized_user_file(str(self.creds_path), SCOPES)  # type: ignore[union-attr]
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore[misc]
        return build('drive', 'v3', credentials=creds)  # type: ignore[misc]

    @staticmethod
    def _is_ssl_error(exc: Exception) -> bool:
        """Check if an exception is a transient SSL/connection error."""
        if isinstance(exc, (ssl.SSLError, BrokenPipeError, ConnectionResetError)):
            return True
        ssl_keywords = (
            'DECRYPTION_FAILED_OR_BAD_RECORD_MAC',
            'WRONG_VERSION_NUMBER',
            'EOF occurred',
            'ssl.SSLError',
            'BrokenPipeError',
            'ConnectionReset',
        )
        msg = str(exc)
        return any(kw in msg for kw in ssl_keywords)

    def _api_call_with_retry(self, request: Any, max_retries: int = 3) -> Dict[str, Any]:
        """Execute a Google API request with exponential backoff on SSL errors."""
        for attempt in range(max_retries + 1):
            try:
                return request.execute()
            except Exception as e:
                if attempt < max_retries and self._is_ssl_error(e):
                    wait = 2 ** attempt

                    time.sleep(wait)
                    # Rebuild this thread's service on SSL failure
                    self._thread_local.service = self._build_thread_service()
                    continue
                raise
        raise RuntimeError("Retries exhausted")

    def _check_file_needs_upload_local(self, local_file: Path, backup_root: Path) -> bool:
        """Check if file needs upload using local tracker (no API calls)"""
        try:
            # Calculate relative path for tracking
            if backup_root and backup_root in local_file.parents:
                relative_path = local_file.relative_to(backup_root)
                file_key = str(relative_path).replace('\\', '/')
            else:
                file_key = local_file.name

            # Get current file stats
            current_size = local_file.stat().st_size
            current_mtime = local_file.stat().st_mtime

            # Check if file is in tracker
            if file_key not in self.file_tracker:

                return True  # New file, needs upload

            tracked_file = self.file_tracker[file_key]

            # Compare local file stats with tracker
            if (current_size != tracked_file.get("local_size", 0) or
                current_mtime != tracked_file.get("local_mtime", 0)):

                return True  # File changed, needs upload

            # File unchanged according to tracker

            return False

        except Exception as e:
            logger.warning(f"Failed to check upload status for {local_file}: {e}")
            return True  # On error, assume file needs upload

    def _update_file_tracker(self, local_file: Path, backup_root: Path, drive_file_id: str):
        """Update file tracker after successful upload"""
        try:
            # Calculate relative path for tracking
            if backup_root and backup_root in local_file.parents:
                relative_path = local_file.relative_to(backup_root)
                file_key = str(relative_path).replace('\\', '/')
            else:
                file_key = local_file.name

            # Get current file stats
            current_size = local_file.stat().st_size
            current_mtime = local_file.stat().st_mtime

            # Update tracker
            self.file_tracker[file_key] = {
                "local_size": current_size,
                "local_mtime": current_mtime,
                "drive_id": drive_file_id,
                "drive_size": current_size,
                "last_sync": datetime.now().isoformat()
            }

            # Tracker updated in-memory; disk save is batched by sync_backup_files()

        except Exception as e:
            logger.warning(f"Failed to update file tracker for {local_file}: {e}")

    def _clean_file_tracker(self, existing_files: set):
        """Remove tracker entries for files that no longer exist"""
        try:
            keys_to_remove = []
            for file_key in self.file_tracker.keys():
                if file_key not in existing_files:
                    keys_to_remove.append(file_key)

            for key in keys_to_remove:
                del self.file_tracker[key]

            if keys_to_remove:
                self._save_file_tracker()

        except Exception as e:
            logger.warning(f"Failed to clean file tracker: {e}")

    def prepare_sync(self, backup_dir: Path, force_sync: bool = False, limit: int = 0):
        """Scan files and determine what needs uploading. No API calls.

        Args:
            backup_dir: Directory to scan
            force_sync: Force upload all files regardless of tracker
            limit: Only consider first N files (0 = no limit). Same N files every run.

        Returns:
            tuple: (files_to_upload, skipped_count, total_count)
        """
        if not backup_dir.exists():
            return [], 0, 0

        self.file_tracker = self._load_file_tracker()

        # Collect all files first (sorted for deterministic order)
        all_files = sorted(
            [f for f in backup_dir.rglob("*") if f.is_file() and not f.name.startswith('.')],
            key=lambda f: str(f)
        )
        # Apply limit - always the same files every run
        if limit > 0:
            all_files = all_files[:limit]

        files_to_upload = []
        skipped_count = 0
        total_count = len(all_files)
        existing_files = set()

        for backup_file in all_files:
            if backup_dir in backup_file.parents:
                relative_path = backup_file.relative_to(backup_dir)
                file_key = str(relative_path).replace('\\', '/')
                existing_files.add(file_key)
            if force_sync or self._check_file_needs_upload_local(backup_file, backup_dir):
                files_to_upload.append(backup_file)
            else:
                skipped_count += 1

        # Only clean tracker when doing full sync (not limited)
        if limit == 0:
            self._clean_file_tracker(existing_files)

        return files_to_upload, skipped_count, total_count

    def _file_needs_upload(self, local_file: Path, drive_file: Optional[Dict[str, Any]]) -> bool:
        """Check if a file needs to be uploaded based on size comparison"""
        if not drive_file:
            return True  # File doesn't exist in Drive, needs upload

        try:
            local_size = local_file.stat().st_size
            drive_size = int(drive_file.get('size', 0))

            # If sizes are different, file has changed
            if local_size != drive_size:
                return True

            # If sizes are same, assume file is unchanged
            return False

        except Exception as e:
            logger.warning(f"Failed to check if file needs upload for {local_file}: {e}")
            return True  # Upload on error to be safe

    def sync_backup_files(self, backup_dir: Path, project_name: str, note: str = "", force_sync: bool = False,
                          prepared_files=None, skipped_count=0, total_count=0, progress_fn=None) -> dict:
        """Sync backup files to Drive using local-first change detection.

        Args:
            backup_dir: Directory containing backup files
            project_name: Project name for Drive folder
            note: Optional sync note
            force_sync: Force upload all files regardless of tracker
            prepared_files: Pre-scanned file list from prepare_sync(). If None, does own scan.
            skipped_count: From prepare_sync()
            total_count: From prepare_sync()
            progress_fn: Callback fn(completed, total, success_count) called periodically

        Returns:
            dict with keys: success, uploaded, skipped, failed, total
        """
        result = {"success": False, "uploaded": 0, "skipped": skipped_count, "failed": 0, "total": total_count, "error": None}

        if not backup_dir.exists():
            result["error"] = f"Backup directory not found: {backup_dir}"
            return result

        # Pre-flight: verify Drive folder is accessible before uploading anything
        project_folder_id = self.get_or_create_project_folder(project_name)
        if not project_folder_id:
            result["error"] = self.last_error or f"Failed to create/access Drive folder for '{project_name}'"
            return result

        # Phase 1: Use pre-scanned files if provided, otherwise scan locally
        if prepared_files is not None:
            files_to_upload = prepared_files
        else:
            files_to_upload, skipped_count, total_count = self.prepare_sync(backup_dir, force_sync)
            result["skipped"] = skipped_count
            result["total"] = total_count

        upload_count = len(files_to_upload)

        # Phase 2: Upload only the files that need it (WITH API CALLS)
        success_count = 0
        completed_count = 0
        failed_count = 0

        BATCH_SAVE_INTERVAL = 50  # Save tracker to disk every N uploads
        MAX_WORKERS = 3  # Parallel upload threads (kept low to avoid SSL contention)
        tracker_lock = threading.Lock()

        if upload_count > 0:
            # Pre-create project folder before threads start (avoid duplicate creation)
            self.get_or_create_project_folder(project_name)

            def _upload_one(backup_file):
                """Upload a single file using a thread-local Drive service"""
                # Each thread gets its own Drive service with isolated SSL connections
                if not hasattr(self._thread_local, 'service'):
                    self._thread_local.service = self._build_thread_service()
                upload_result = self.upload_backup_file(backup_file, project_name, note, backup_dir)
                return (backup_file, upload_result)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(_upload_one, f): f for f in files_to_upload}
                for future in as_completed(futures):
                    _, upload_ok = future.result()
                    with tracker_lock:
                        completed_count += 1
                        if upload_ok:
                            success_count += 1
                        else:
                            failed_count += 1

                        # Batch save every BATCH_SAVE_INTERVAL files
                        if completed_count % BATCH_SAVE_INTERVAL == 0:
                            self._save_file_tracker()
                            _save_data(self.data)

                        # Progress callback on every file for smooth progress bar
                        if progress_fn:
                            progress_fn(completed_count, upload_count, success_count)

            # Final save and progress update after all uploads complete
            self._save_file_tracker()
            _save_data(self.data)
            if progress_fn:
                progress_fn(completed_count, upload_count, success_count)

        # Update last sync time
        if "runtime_state" not in self.data:
            self.data["runtime_state"] = {}
        self.data["runtime_state"]["last_sync"] = datetime.now().isoformat()
        _save_data(self.data)

        # Log sync operation
        total_success = success_count + skipped_count
        _log_operation("sync_backup", {
            "message": f"Synced {total_success}/{total_count} files for {project_name} ({success_count} uploaded, {skipped_count} skipped)",
            "uploaded_count": success_count,
            "skipped_count": skipped_count,
            "total_count": total_count,
            "project": project_name,
            "force_sync": force_sync
        }, success=(total_success == total_count))

        result["success"] = (failed_count == 0)
        result["uploaded"] = success_count
        result["failed"] = failed_count
        return result
