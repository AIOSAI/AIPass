# =================== AIPass ====================
# Name: service_factory.py
# Description: Google API service object factory
# Version: 1.1.1
# Created: 2026-03-14
# Modified: 2026-10-24
# =============================================
# pyright: reportMissingImports=false, reportOptionalCall=false

"""Google API Service Factory"""

from typing import Optional

from aipass.prax import logger
from aipass.api.apps.handlers.google import auth as auth
from aipass.api.apps.handlers.json import json_handler

try:
    from googleapiclient.discovery import build

    GOOGLE_BUILD_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Google API client library not available: {e}")
    GOOGLE_BUILD_AVAILABLE = False
    build = None  # type: ignore[assignment]


def build_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
) -> Optional[object]:
    """Build an authenticated Google API service object from the saved credentials, refreshed if expired.

    None when the libraries are missing. No usable saved credentials, a failed refresh or a failed build
    raises GoogleAuthUnavailable, whose reason @backup's DriveClient reads. Never starts the consent flow:
    an unattended caller would block on its browser callback; `drone @api reauth google` runs it.
    """
    if not GOOGLE_BUILD_AVAILABLE or not auth.is_available():
        return None

    creds = auth.load_credentials(scopes=scopes)
    if creds and creds.expired and creds.refresh_token:
        auth.refresh_credentials(creds)
    if not creds or not creds.valid:
        raise auth.GoogleAuthUnavailable(
            "No usable saved Google credentials. Run 'drone @api reauth google' to set up credentials."
        )

    try:
        service = build(service_name, version, credentials=creds)
        json_handler.log_operation("build_service", {"service": service_name, "version": version})
        return service
    except Exception as e:
        raise auth.GoogleAuthUnavailable(f"Google {service_name} service could not be built: {e}") from e


def build_thread_safe_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
) -> Optional[object]:
    """Build an isolated service instance for use in a worker thread.

    Fresh credentials from disk per call: shared credential state races on token refresh.
    """
    if not GOOGLE_BUILD_AVAILABLE or not auth.is_available():
        return None

    creds = auth.load_credentials(scopes=scopes)
    if not creds:
        return None

    if creds.expired and creds.refresh_token:
        if not auth.refresh_credentials(creds):
            return None

    if not creds.valid:
        return None

    try:
        return build(service_name, version, credentials=creds)
    except Exception as e:
        raise auth.GoogleAuthUnavailable(f"Thread-safe Google {service_name} service could not be built: {e}") from e
