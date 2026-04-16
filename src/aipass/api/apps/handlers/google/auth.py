# =================== AIPass ====================
# Name: auth.py
# Description: Google OAuth2 authentication and credential management
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalMemberAccess=false, reportOptionalCall=false

"""
Google OAuth2 Authentication Handler

Manages the OAuth2 lifecycle for Google API access:
- Load/save credentials from ~/.secrets/aipass/
- Token refresh for expired credentials
- Full OAuth2 consent flow for new authentication
- Re-authentication when tokens are revoked

This is pure auth plumbing — no business logic.
Consumers get authenticated credentials, they decide what to do with them.
"""

import os
from pathlib import Path
from typing import Optional

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

# Default scopes per service — consumers can override
DEFAULT_SCOPES = {
    "drive": ["https://www.googleapis.com/auth/drive.file"],
    "calendar": ["https://www.googleapis.com/auth/calendar.readonly"],
}

# Credential storage — AIPass standard location
SECRETS_DIR = Path.home() / ".secrets" / "aipass"
CREDS_PATH = SECRETS_DIR / "google_creds.json"
CLIENT_SECRET_PATH = SECRETS_DIR / "google_client_secret.json"


# =============================================
# GOOGLE API AVAILABILITY
# =============================================

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    GOOGLE_AUTH_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Google auth libraries not available: {e}")
    GOOGLE_AUTH_AVAILABLE = False
    Credentials = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    InstalledAppFlow = None  # type: ignore[assignment, misc]


# =============================================
# CREDENTIAL OPERATIONS
# =============================================


def is_available() -> bool:
    """Check if Google auth libraries are installed."""
    return GOOGLE_AUTH_AVAILABLE


def load_credentials(scopes: Optional[list] = None) -> Optional["Credentials"]:
    """Load saved OAuth2 credentials from disk.

    Args:
        scopes: OAuth2 scopes to validate against.
                Defaults to Drive scopes if not provided.

    Returns:
        Credentials object if found and loadable, None otherwise.
    """
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
        logger.error(f"Failed to load credentials from {CREDS_PATH}: {e}")
        return None


def refresh_credentials(creds: "Credentials") -> bool:
    """Attempt to refresh expired credentials.

    Args:
        creds: Expired Credentials object with a refresh token.

    Returns:
        True if refresh succeeded, False otherwise.
    """
    if not GOOGLE_AUTH_AVAILABLE:
        return False

    if not creds or not creds.expired or not creds.refresh_token:
        return False

    try:
        creds.refresh(Request())
        _save_credentials(creds)
        return True
    except Exception as e:
        logger.error(f"Failed to refresh credentials: {e}")
        return False


def run_oauth_flow(
    scopes: Optional[list] = None,
    port: int = 0,
    open_browser: bool = True,
) -> Optional["Credentials"]:
    """Run the full OAuth2 consent flow.

    Requires google_client_secret.json at ~/.secrets/aipass/.
    Opens a local server for the OAuth callback.

    Args:
        scopes: OAuth2 scopes to request.
        port: Local server port (0 = auto-assign).
        open_browser: Whether to auto-open the consent page.

    Returns:
        Credentials object if flow succeeded, None otherwise.
    """
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
        logger.error(f"OAuth flow failed: {e}")
        return None


def authenticate(scopes: Optional[list] = None) -> Optional["Credentials"]:
    """Full authentication lifecycle: load → refresh → OAuth flow.

    Tries in order:
    1. Load existing valid credentials
    2. Refresh expired credentials
    3. Run full OAuth2 consent flow

    Args:
        scopes: OAuth2 scopes. Defaults to Drive scopes.

    Returns:
        Valid Credentials object, or None if all methods fail.
    """
    if not GOOGLE_AUTH_AVAILABLE:
        return None

    # Step 1: Load existing
    creds = load_credentials(scopes)

    if creds and creds.valid:
        return creds

    # Step 2: Refresh expired
    if creds and creds.expired and creds.refresh_token:
        if refresh_credentials(creds):
            return creds

    # Step 3: Full OAuth flow
    return run_oauth_flow(scopes=scopes)


def reauth(
    scopes: Optional[list] = None,
    port: int = 8085,
    open_browser: bool = False,
) -> Optional["Credentials"]:
    """Force re-authentication via OAuth flow (console mode).

    Used when existing credentials are revoked or corrupted.
    Defaults to console-friendly settings (no browser, fixed port).

    Args:
        scopes: OAuth2 scopes.
        port: Local server port for callback.
        open_browser: Whether to auto-open browser.

    Returns:
        Fresh Credentials object, or None on failure.
    """
    # Try refresh first — maybe token just expired
    creds = load_credentials(scopes)
    if creds and creds.expired and creds.refresh_token:
        if refresh_credentials(creds):
            return creds

    # Force new flow
    return run_oauth_flow(scopes=scopes, port=port, open_browser=open_browser)


def validate_credentials(scopes: Optional[list] = None) -> bool:
    """Check if valid Google credentials exist.

    Args:
        scopes: OAuth2 scopes to validate against.

    Returns:
        True if valid (or refreshable) credentials exist.
    """
    creds = load_credentials(scopes)
    if not creds:
        return False

    if creds.valid:
        return True

    if creds.expired and creds.refresh_token:
        return refresh_credentials(creds)

    return False


# =============================================
# INTERNAL HELPERS
# =============================================


def _save_credentials(creds: "Credentials") -> None:
    """Save credentials to the standard secrets path with restricted permissions."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    with open(CREDS_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    os.chmod(CREDS_PATH, 0o600)
