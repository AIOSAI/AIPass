# =================== AIPass ====================
# Name: service_factory.py
# Description: Google API service object factory
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================
# pyright: reportMissingImports=false, reportOptionalCall=false

"""
Google API Service Factory

Builds authenticated Google API service objects (Drive, Calendar, etc.).
Supports both single-threaded and thread-safe modes.

Thread-safe mode loads fresh credentials from disk per call,
avoiding token refresh races in concurrent operations.
This pattern was extracted from backup's drive_sync_client.py.

Usage:
    from aipass.api.apps.handlers.google.service_factory import (
        build_service, build_thread_safe_service
    )

    # Single-threaded
    service = build_service("drive", "v3")

    # Thread-safe (for concurrent workers)
    service = build_thread_safe_service("drive", "v3")
"""

from typing import Optional

from aipass.prax import logger
from aipass.api.apps.handlers.google import auth as auth
from aipass.api.apps.handlers.json import json_handler

# =============================================
# GOOGLE API AVAILABILITY
# =============================================

try:
    from googleapiclient.discovery import build

    GOOGLE_BUILD_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Google API client library not available: {e}")
    GOOGLE_BUILD_AVAILABLE = False
    build = None  # type: ignore[assignment]


# =============================================
# SERVICE FACTORIES
# =============================================


def build_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
) -> Optional[object]:
    """Build an authenticated Google API service object.

    Uses the full auth lifecycle (load → refresh → OAuth flow).

    Args:
        service_name: Google API service (e.g. "drive", "calendar", "sheets").
        version: API version (e.g. "v3", "v3").
        scopes: OAuth2 scopes. Defaults to service-specific defaults from auth module.

    Returns:
        Authenticated service object, or None if auth/build fails.
    """
    if not GOOGLE_BUILD_AVAILABLE or not auth.is_available():
        return None

    creds = auth.authenticate(scopes=scopes)
    if not creds:
        return None

    try:
        service = build(service_name, version, credentials=creds)
        json_handler.log_operation("build_service", {"service": service_name, "version": version})
        return service
    except Exception as e:
        logger.error(f"Failed to build Google {service_name} service: {e}")
        return None


def build_thread_safe_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
) -> Optional[object]:
    """Build an isolated service instance for use in a worker thread.

    Loads fresh credentials from disk to avoid sharing credential state
    (token refresh races) and creates a fully isolated HTTP/SSL connection.

    Args:
        service_name: Google API service name.
        version: API version.
        scopes: OAuth2 scopes.

    Returns:
        Isolated authenticated service object, or None on failure.
    """
    if not GOOGLE_BUILD_AVAILABLE or not auth.is_available():
        return None

    # Load fresh credentials from disk — no shared state
    creds = auth.load_credentials(scopes=scopes)
    if not creds:
        return None

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        if not auth.refresh_credentials(creds):
            return None

    if not creds.valid:
        return None

    try:
        return build(service_name, version, credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build thread-safe Google {service_name} service: {e}")
        return None
