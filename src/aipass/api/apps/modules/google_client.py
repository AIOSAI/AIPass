# =================== AIPass ====================
# Name: google_client.py
# Description: Google API Client Module — public API for Google services
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Google API Client Module

Public API for Google service access across AIPass.
Consumers import from here — never directly from handlers.

Provides:
- get_drive_service()      → Authenticated Google Drive v3 client
- get_google_service()     → Any Google API service (Calendar, Sheets, etc.)
- authenticate_google()    → Run OAuth2 flow and return credentials
- validate_google()        → Check if valid credentials exist
- reauth_google()          → Force re-authentication

Consumer pattern:
    from aipass.api.apps.modules.google_client import get_drive_service
    service = get_drive_service()
    service.files().list(...).execute()

Thread-safe pattern (for concurrent workers):
    service = get_drive_service(thread_safe=True)
"""

import sys
from typing import List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: F811
from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
import aipass.api.apps.handlers.google.auth as google_auth
import aipass.api.apps.handlers.google.service_factory as google_factory
import aipass.api.apps.handlers.google.retry as google_retry


# =============================================
# MODULE INTROSPECTION
# =============================================


def print_introspection() -> None:
    """Show module introspection — connected handlers and capabilities."""
    console.print()
    header("Google Client Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] Google API authentication and service factory")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  - api.apps.handlers.google.auth")
    console.print("  - api.apps.handlers.google.service_factory")
    console.print("  - api.apps.handlers.google.retry")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  - get_drive_service()     - Get authenticated Drive client")
    console.print("  - get_google_service()    - Get any Google API service")
    console.print("  - authenticate_google()   - Run OAuth2 authentication")
    console.print("  - validate_google()       - Check credential status")
    console.print("  - reauth_google()         - Force re-authentication")
    console.print()

    available = google_auth.is_available()
    status = "[green]installed[/green]" if available else "[red]missing[/red]"
    console.print(f"[cyan]Google Libraries:[/cyan] {status}")

    has_creds = google_auth.CREDS_PATH.exists()
    cred_status = "[green]found[/green]" if has_creds else "[yellow]not configured[/yellow]"
    console.print(f"[cyan]Credentials:[/cyan] {cred_status}")

    has_secret = google_auth.CLIENT_SECRET_PATH.exists()
    secret_status = "[green]found[/green]" if has_secret else "[yellow]not configured[/yellow]"
    console.print(f"[cyan]Client Secret:[/cyan] {secret_status}")
    console.print()


def print_help() -> None:
    """Print module help."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="drone @api",
        description="Google Client - Google API authentication and service access",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS (via drone @api):
  validate google   - Check Google OAuth2 credentials
  reauth google     - Re-run OAuth2 flow for Google

CROSS-BRANCH API:
  from aipass.api.apps.modules.google_client import get_drive_service
  service = get_drive_service()

CREDENTIAL SETUP:
  1. Get OAuth client secret from Google Cloud Console
  2. Save as: ~/.secrets/aipass/google_client_secret.json
  3. Run: drone @api reauth google
  4. Complete OAuth consent in browser
  5. Credentials saved to: ~/.secrets/aipass/google_creds.json
        """
    )
    console.print(parser.format_help())


# =============================================
# COMMAND HANDLING (drone @api validate google, etc.)
# =============================================


def handle_command(command: str, args: List[str]) -> bool:
    """Handle Google client commands routed via drone.

    Args:
        command: Command name (e.g. "validate", "reauth")
        args: Command arguments — first arg should be "google"

    Returns:
        True if command was handled, False to pass through.
    """
    # Help gate
    if args and args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    # NO-ARGS GATE (seedgo standard)
    if not args:
        if command == "google":
            print_introspection()
            return True
        return False

    # Only handle commands with "google" as the provider argument
    if args[0] != "google":
        return False

    if command == "validate":
        _cmd_validate()
        return True
    elif command == "reauth":
        _cmd_reauth()
        return True

    return False


# =============================================
# CLI COMMAND IMPLEMENTATIONS
# =============================================


def _cmd_validate() -> None:
    """Validate Google OAuth2 credentials."""
    header("Validate Google Credentials")
    console.print()

    if not google_auth.is_available():
        error(
            "Google auth libraries not installed",
            suggestion="pip install google-auth google-auth-oauthlib google-api-python-client",
        )
        return

    if not google_auth.CLIENT_SECRET_PATH.exists():
        error(
            "Client secret not found",
            suggestion=f"Save OAuth client secret to: {google_auth.CLIENT_SECRET_PATH}",
        )
        return

    if google_auth.validate_credentials():
        success("Google credentials are valid")
        json_handler.log_operation("google_validate", {"status": "valid"})
    else:
        warning("No valid Google credentials found")
        console.print()
        console.print("[dim]Run 'drone @api reauth google' to authenticate[/dim]")
        json_handler.log_operation("google_validate", {"status": "invalid"})


def _cmd_reauth() -> None:
    """Force Google re-authentication via OAuth flow."""
    header("Google Re-Authentication")
    console.print()

    if not google_auth.is_available():
        error(
            "Google auth libraries not installed",
            suggestion="pip install google-auth google-auth-oauthlib google-api-python-client",
        )
        return

    if not google_auth.CLIENT_SECRET_PATH.exists():
        error(
            "Client secret not found",
            suggestion=f"Save OAuth client secret to: {google_auth.CLIENT_SECRET_PATH}",
        )
        return

    warning("Starting OAuth2 flow...")
    console.print("[dim]A browser window may open for Google consent.[/dim]")
    console.print()

    creds = google_auth.reauth()

    if creds:
        success("Google re-authentication successful")
        console.print(f"[dim]Credentials saved to: {google_auth.CREDS_PATH}[/dim]")
        json_handler.log_operation("google_reauth", {"status": "success"})
    else:
        error("Google re-authentication failed")
        json_handler.log_operation("google_reauth", {"status": "failed"})


# =============================================
# PUBLIC API — Cross-branch imports
# =============================================


def get_drive_service(thread_safe: bool = False) -> object:
    """Get an authenticated Google Drive v3 service object.

    Args:
        thread_safe: If True, builds an isolated service instance
            with fresh credentials from disk (for concurrent workers).

    Returns:
        Authenticated Drive v3 service object.

    Raises:
        RuntimeError: If authentication fails or libraries unavailable.
    """
    return get_google_service("drive", "v3", thread_safe=thread_safe)


def get_google_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
    thread_safe: bool = False,
) -> object:
    """Get an authenticated Google API service object.

    Supports any Google API: Drive, Calendar, Sheets, Gmail, etc.

    Args:
        service_name: Google API service (e.g. "drive", "calendar").
        version: API version (e.g. "v3").
        scopes: OAuth2 scopes. Uses service-specific defaults if not provided.
        thread_safe: If True, builds an isolated instance for concurrent use.

    Returns:
        Authenticated service object.

    Raises:
        RuntimeError: If authentication fails or libraries unavailable.
    """
    if not google_auth.is_available():
        raise RuntimeError(
            "Google auth libraries not installed. "
            "Install: pip install google-auth google-auth-oauthlib google-api-python-client"
        )

    if thread_safe:
        service = google_factory.build_thread_safe_service(
            service_name, version, scopes
        )
    else:
        service = google_factory.build_service(service_name, version, scopes)

    if not service:
        raise RuntimeError(
            f"Failed to authenticate with Google {service_name} API. "
            "Run 'drone @api reauth google' to set up credentials."
        )

    return service


def authenticate_google(scopes: Optional[list] = None) -> bool:
    """Run Google OAuth2 authentication.

    Args:
        scopes: OAuth2 scopes to request.

    Returns:
        True if authentication succeeded.
    """
    creds = google_auth.authenticate(scopes=scopes)
    return creds is not None


def validate_google(scopes: Optional[list] = None) -> bool:
    """Check if valid Google credentials exist.

    Args:
        scopes: OAuth2 scopes to validate against.

    Returns:
        True if valid credentials exist.
    """
    return google_auth.validate_credentials(scopes=scopes)


def reauth_google(scopes: Optional[list] = None) -> bool:
    """Force Google re-authentication.

    Args:
        scopes: OAuth2 scopes to request.

    Returns:
        True if re-authentication succeeded.
    """
    creds = google_auth.reauth(scopes=scopes)
    return creds is not None


# Re-export retry utility for consumers that make raw API calls
api_call_with_retry = google_retry.api_call_with_retry
is_ssl_error = google_retry.is_ssl_error


# =============================================
# STANDALONE EXECUTION
# =============================================

if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        console.print()
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print()
        console.print(
            "Run [dim]python3 google_client.py --help[/dim] for available commands"
        )
        console.print()
        sys.exit(1)
