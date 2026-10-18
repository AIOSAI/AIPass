# =================== AIPass ====================
# Name: auth.py
# Description: Google OAuth2 authentication and credential management
# Version: 1.1.0
# Created: 2026-03-14
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalMemberAccess=false, reportOptionalCall=false

"""Google OAuth2 Authentication Handler"""

import os
from pathlib import Path
from typing import Optional

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler

DEFAULT_SCOPES = {
    "drive": ["https://www.googleapis.com/auth/drive.file"],
    "calendar": ["https://www.googleapis.com/auth/calendar.readonly"],
}

SECRETS_DIR = Path.home() / ".secrets" / "aipass"
CREDS_PATH = SECRETS_DIR / "google_creds.json"
CLIENT_SECRET_PATH = SECRETS_DIR / "google_client_secret.json"


try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import TransportError
    from google_auth_oauthlib.flow import InstalledAppFlow

    GOOGLE_AUTH_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Google auth libraries not available: {e}")
    GOOGLE_AUTH_AVAILABLE = False
    Credentials = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    # Used in an `except` clause: None there is a TypeError at catch time; an empty tuple catches nothing.
    TransportError = ()  # type: ignore[assignment, misc]
    InstalledAppFlow = None  # type: ignore[assignment, misc]


class GoogleAuthUnavailable(RuntimeError):
    """Saved credentials, a refresh, the consent flow or a service build failed.

    A RuntimeError: get_google_service documents RuntimeError, and @backup's DriveClient keeps str(exc) as last_error.
    """


def is_available() -> bool:
    """Check if Google auth libraries are installed."""
    return GOOGLE_AUTH_AVAILABLE


def load_credentials(scopes: Optional[list] = None) -> Optional["Credentials"]:
    """Load saved OAuth2 credentials from disk."""
    if not GOOGLE_AUTH_AVAILABLE:
        return None

    if not CREDS_PATH.exists():
        return None

    effective_scopes = scopes or DEFAULT_SCOPES["drive"]

    try:
        creds = Credentials.from_authorized_user_file(str(CREDS_PATH), effective_scopes)
        json_handler.log_operation("credentials_loaded", {"source": str(CREDS_PATH)})
        return creds
    except Exception as e:
        raise GoogleAuthUnavailable(f"Saved Google credentials could not be loaded: {e}") from e


def refresh_credentials(creds: "Credentials") -> bool:
    """Attempt to refresh expired credentials."""
    if not GOOGLE_AUTH_AVAILABLE:
        return False

    if not creds or not creds.expired or not creds.refresh_token:
        return False

    try:
        creds.refresh(Request())
        _save_credentials(creds)
        return True
    except TransportError as e:  # type: ignore[misc]
        raise GoogleAuthUnavailable(f"Google credential refresh failed, transient network error: {e}") from e
    except Exception as e:
        raise GoogleAuthUnavailable(f"Google credential refresh failed: {e}") from e


def run_oauth_flow(
    scopes: Optional[list] = None,
    port: int = 0,
    open_browser: bool = True,
) -> Optional["Credentials"]:
    """Run the full OAuth2 consent flow."""
    if not GOOGLE_AUTH_AVAILABLE:
        return None

    if not CLIENT_SECRET_PATH.exists():
        return None

    effective_scopes = scopes or DEFAULT_SCOPES["drive"]

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), effective_scopes)
        creds = flow.run_local_server(port=port, open_browser=open_browser)
        _save_credentials(creds)
        return creds
    except Exception as e:
        raise GoogleAuthUnavailable(f"Google OAuth flow failed: {e}") from e


def authenticate(scopes: Optional[list] = None) -> Optional["Credentials"]:
    """Full authentication lifecycle: load → refresh → OAuth flow.

    GoogleAuthUnavailable propagates so a headless caller (@backup) learns why instead of a consent flow starting.
    """
    if not GOOGLE_AUTH_AVAILABLE:
        return None

    creds = load_credentials(scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        if refresh_credentials(creds):
            return creds

    return run_oauth_flow(scopes=scopes)


def reauth(
    scopes: Optional[list] = None,
    port: int = 8085,
    open_browser: bool = False,
) -> Optional["Credentials"]:
    """Force re-authentication via OAuth flow (console mode).

    Unusable saved credentials are the case reauth repairs: logged, not raised.
    """
    try:
        creds = load_credentials(scopes)
        if creds and creds.expired and creds.refresh_token:
            if refresh_credentials(creds):
                return creds
    except GoogleAuthUnavailable as e:
        logger.warning(f"Saved credentials unusable, running the consent flow: {e}")

    return run_oauth_flow(scopes=scopes, port=port, open_browser=open_browser)


def validate_credentials(scopes: Optional[list] = None) -> bool:
    """Check if valid Google credentials exist.

    Raises GoogleAuthUnavailable rather than reporting unreadable or offline as invalid.
    """
    creds = load_credentials(scopes)
    if not creds:
        return False

    if creds.valid:
        return True

    if creds.expired and creds.refresh_token:
        return refresh_credentials(creds)

    return False


def _save_credentials(creds: "Credentials") -> None:
    """Save credentials to the standard secrets path with restricted permissions."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.chmod(CREDS_PATH, 0o600)
