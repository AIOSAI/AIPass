# =================== AIPass ====================
# Name: google_client.py
# Description: Google API Client Module — public API for Google services
# Version: 1.1.0
# Created: 2026-03-14
# Modified: 2026-10-17
# =============================================

"""
Google API Client Module

Public API for Google service access across AIPass.
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger  # noqa: F401
import aipass.api.apps.handlers.google.auth as google_auth
import aipass.api.apps.handlers.google.service_factory as google_factory
import aipass.api.apps.handlers.google.retry as google_retry


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
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]GOOGLE_CLIENT — Google API authentication and service access[/bold cyan]")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]  [dim](via drone @api)[/dim]")
    console.print("  [cyan]validate google[/cyan]  [dim]Check Google OAuth2 credentials[/dim]")
    console.print("  [cyan]reauth google[/cyan]   [dim]Re-run OAuth2 flow for Google[/dim]")
    console.print()
    console.print("[yellow]CROSS-BRANCH API:[/yellow]")
    console.print("  [dim]from aipass.api.apps.modules.google_client import get_drive_service[/dim]")
    console.print("  [dim]service = get_drive_service()[/dim]")
    console.print()
    console.print("[yellow]CREDENTIAL SETUP:[/yellow]")
    console.print("  [dim]1.[/dim] Get OAuth client secret from Google Cloud Console")
    console.print("  [dim]2.[/dim] Save as: [cyan]~/.secrets/aipass/google_client_secret.json[/cyan]")
    console.print("  [dim]3.[/dim] Run: [cyan]drone @api reauth google[/cyan]")
    console.print("  [dim]4.[/dim] Complete OAuth consent in browser")
    console.print("  [dim]5.[/dim] Credentials saved to: [cyan]~/.secrets/aipass/google_creds.json[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle Google client commands routed via drone."""
    if not args:
        if command == "google":
            print_introspection()
            return True
        return False

    if args[0] != "google":
        return False

    remaining = args[1:] if len(args) > 1 else []
    if remaining and remaining[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "validate":
        _cmd_validate()
        return True
    elif command == "reauth":
        _cmd_reauth()
        return True

    return False


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

    try:
        valid = google_auth.validate_credentials()
    except google_auth.GoogleAuthUnavailable as e:
        error(str(e), suggestion="Run 'drone @api reauth google' to authenticate")
        json_handler.log_operation("google_validate", {"status": "unavailable"})
        return

    if valid:
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

    try:
        creds = google_auth.reauth()
    except google_auth.GoogleAuthUnavailable as e:
        error(str(e))
        json_handler.log_operation("google_reauth", {"status": "failed"})
        return

    if creds:
        success("Google re-authentication successful")
        console.print(f"[dim]Credentials saved to: {google_auth.CREDS_PATH}[/dim]")
        json_handler.log_operation("google_reauth", {"status": "success"})
    else:
        error("Google re-authentication failed")
        json_handler.log_operation("google_reauth", {"status": "failed"})


def get_drive_service(thread_safe: bool = False) -> object:
    """Get an authenticated Google Drive v3 service object."""
    return get_google_service("drive", "v3", thread_safe=thread_safe)


def get_google_service(
    service_name: str = "drive",
    version: str = "v3",
    scopes: Optional[list] = None,
    thread_safe: bool = False,
) -> object:
    """Get an authenticated Google API service object.

    Raises RuntimeError, a contract @backup's DriveClient relies on; GoogleAuthUnavailable is one.
    """
    if not google_auth.is_available():
        raise RuntimeError(
            "Google auth libraries not installed. "
            "Install: pip install google-auth google-auth-oauthlib google-api-python-client"
        )

    if thread_safe:
        service = google_factory.build_thread_safe_service(service_name, version, scopes)
    else:
        service = google_factory.build_service(service_name, version, scopes)

    if not service:
        raise RuntimeError(
            f"Failed to authenticate with Google {service_name} API. "
            "Run 'drone @api reauth google' to set up credentials."
        )

    return service


def authenticate_google(scopes: Optional[list] = None) -> bool:
    """Run Google OAuth2 authentication."""
    creds = google_auth.authenticate(scopes=scopes)
    return creds is not None


def validate_google(scopes: Optional[list] = None) -> bool:
    """Check if valid Google credentials exist."""
    return google_auth.validate_credentials(scopes=scopes)


def reauth_google(scopes: Optional[list] = None) -> bool:
    """Force Google re-authentication."""
    creds = google_auth.reauth(scopes=scopes)
    return creds is not None


def api_call_with_retry(*args, **kwargs):
    """Execute API call with retry logic for SSL and transient errors."""
    return google_retry.api_call_with_retry(*args, **kwargs)


def is_ssl_error(error):
    """Check if an error is an SSL-related error."""
    return google_retry.is_ssl_error(error)


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
        error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")
        sys.exit(1)
