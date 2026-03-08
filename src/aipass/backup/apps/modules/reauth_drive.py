# ===================AIPASS====================
# META DATA HEADER
# Name: reauth_drive.py - Google Drive Re-Authentication Module
# Date: 2026-02-21
# Version: 1.2.0
# Category: backup_system
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-03-06): Adapted for AIPass public repo
#     * Removed shebang, sys.path manipulation, prax/cli imports
#     * Uses standard logging and rich console
#     * Relative handler imports, Google API deps wrapped in try/except
#   - v1.1.0 (2026-02-21): Fixed handle_command() signature (command, args) → (args)
#   - v1.0.0 (2026-02-20): Initial version - standalone reauth utility
#
# CODE STANDARDS:
#   - Handlers implement logic, modules orchestrate
# =============================================

"""
reauth_drive - Google Drive Re-Authentication Module

Standalone Google Drive re-authentication module.
Uses console-based OAuth flow (no browser needed).
Delegates implementation to reauth_handler.
"""

import sys
import logging
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

# Handler imports
from aipass.backup.apps.handlers.utils.reauth_handler import reauth as _run_reauth

CLIENT_SECRETS = Path(__file__).resolve().parents[1] / 'credentials.json'
CREDS_PATH = Path.home() / '.aipass' / 'drive_creds.json'


def handle_command(args) -> bool:
    """Handle reauth commands routed from the backup_system orchestrator.

    Args:
        args: Command-line arguments from CLI parser

    Returns:
        bool: True if command handled, False otherwise
    """
    if not hasattr(args, 'command'):
        return False

    command = args.command
    if command in ['--help', '-h', 'help']:
        print_help()
        return True

    if command == 'reauth':
        return _execute_reauth()

    return False


def print_help():
    """Display help for the reauth_drive module."""
    console.print()
    console.print("[bold cyan]reauth_drive - Google Drive Re-Authentication[/bold cyan]")
    console.print()
    console.print("Re-authenticates with Google Drive using console OAuth flow.")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  python3 reauth_drive.py          # Run re-authentication")
    console.print("  python3 reauth_drive.py --help   # Show this help")
    console.print()


def _execute_reauth() -> bool:
    """Orchestrate the re-authentication flow with user feedback."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request  # noqa: F811
        from googleapiclient.discovery import build
    except ImportError as e:
        console.print(f"[red]Missing package: {e}[/red]")
        console.print(f"Install: {sys.executable} -m pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        return False

    if not CLIENT_SECRETS.exists():
        console.print(f"[red]ERROR: Client secrets not found at: {CLIENT_SECRETS}[/red]")
        logger.warning(f"OAuth client secrets not found at: {CLIENT_SECRETS}")
        return False

    console.print()
    console.print("[bold cyan]" + "="*60 + "[/bold cyan]")
    console.print("[bold cyan]GOOGLE DRIVE RE-AUTHENTICATION[/bold cyan]")
    console.print("[bold cyan]" + "="*60 + "[/bold cyan]")

    # Check for token refresh first
    if CREDS_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(CREDS_PATH), ['https://www.googleapis.com/auth/drive.file'])
            if creds and creds.expired and creds.refresh_token:
                console.print("Attempting token refresh...")
                logger.info("Attempting Drive token refresh")
        except Exception as e:
            logger.warning(f"Token refresh check failed: {e}")

    console.print()
    console.print("Starting local auth server...")
    console.print("A URL will be printed below - open it in your browser.")
    console.print("After authorizing, the browser will redirect to localhost.")
    console.print()

    success = _run_reauth(CLIENT_SECRETS)

    if success:
        console.print("[green]Re-authentication SUCCESSFUL![/green]")
        logger.info("Drive re-authentication successful")
        # Show account info
        try:
            creds = Credentials.from_authorized_user_file(str(CREDS_PATH), ['https://www.googleapis.com/auth/drive.file'])
            service = build('drive', 'v3', credentials=creds)
            about = service.about().get(fields="user,storageQuota").execute()
            email = about['user']['emailAddress']
            quota = about.get('storageQuota', {})
            usage_gb = int(quota.get('usage', 0)) / (1024**3)
            limit_gb = int(quota.get('limit', 0)) / (1024**3)
            console.print(f"Authenticated as: {email}")
            console.print(f"Storage: {usage_gb:.2f} GB / {limit_gb:.2f} GB")
        except Exception:
            pass
    else:
        console.print("[red]Re-authentication FAILED[/red]")
        logger.error("Drive re-authentication failed")

    return success


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)
    success = _execute_reauth()
    sys.exit(0 if success else 1)
