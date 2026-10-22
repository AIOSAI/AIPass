# =================== AIPass ====================
# Name: secrets.py
# Description: Secrets Module — cross-branch in-process door
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-10-22
# =============================================

"""
Secrets Module

Cross-branch in-process API for the secrets provider store.
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")
from typing import Any, List, Optional, Union

from aipass.prax import logger  # noqa: F401 — seedgo imports standard
from aipass.cli.apps.modules import console, header, error, success, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as _handler


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("Secrets Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] Cross-branch secrets access (in-process)")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.auth.secrets")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  • get_secret() - Read secret by provider/slug")
    console.print("  • set_secret() - Write secret to the keyring entry <provider>/<slug>")
    console.print("  • list_secrets() - List slugs for a provider")
    console.print("  • secrets migrate - Import the store's files into the keyring and shred them")
    console.print()


def print_help():
    """Print help output for secrets module"""
    console.print()
    console.print("[bold cyan]SECRETS — values rest in the login keyring, service 'aipass'[/bold cyan]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [cyan]drone @api secrets migrate \\[--dry-run][/cyan]")
    console.print()
    console.print("  [dim]Imports <provider>/<slug>.json, <provider>/<slug>, the .env's <PROVIDER>_API_KEY[/dim]")
    console.print("  [dim]lines, google_client_secret.json and google_creds.json into the keyring, then zeroes[/dim]")
    console.print("  [dim]and unlinks each file. Anything else is left and named. --dry-run changes nothing.[/dim]")
    console.print("  [dim]The owner's run: a seat never runs it unasked.[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle `secrets` (migrate); get-secret routes through api_key.py."""
    if command != "secrets":
        return False

    if not args or args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] != "migrate":
        error(f"Unknown secrets verb: {args[0]}", suggestion="drone @api secrets --help")
        return True

    migrate("--dry-run" in args[1:])
    return True


def migrate(dry_run: bool) -> None:
    """Orchestrate `secrets migrate`: the backend, what moved, what failed and what was left."""
    header("Secrets Migrate" + (" (dry run)" if dry_run else ""))
    console.print()

    try:
        report = _handler.migrate_store(dry_run=dry_run)
    except _handler.SecretsUnavailable as e:
        error(str(e))
        return

    console.print(f"  Backend: {report['backend']}")
    verb = "Would move" if dry_run else "Moved"
    for name in report["moved"]:
        console.print(f"  {verb}: {name}")
    for name in report["left"]:
        console.print(f"  [dim]Left: {name}[/dim]")
    for name, reason in report["failed"]:
        error(f"Not moved, file kept: {name} ({reason})")
    json_handler.log_operation(
        "secrets_migrate", {"dry_run": dry_run, "moved": len(report["moved"]), "failed": len(report["failed"])}
    )

    console.print()
    if report["failed"]:
        return
    if not report["moved"]:
        success("Nothing left to move")
    elif dry_run:
        warning("Dry run: nothing written, nothing shredded")
    else:
        success(f"{len(report['moved'])} entries in the keyring; their files are shredded")


def get_secret(provider: str, slug: str, as_json: bool = False) -> Optional[Any]:
    """Read a secret from the provider store."""
    result = _handler.get_secret(provider, slug, as_json=as_json)
    json_handler.log_operation("secrets_get", {"provider": provider, "slug": slug, "found": result is not None})
    return result


def set_secret(provider: str, slug: str, value: Union[str, dict], *, as_json: bool = False) -> str:
    """Write a secret to the keyring entry <provider>/<slug>; returns the entry's name."""
    result = _handler.set_secret(provider, slug, value, as_json=as_json)
    json_handler.log_operation("secrets_set", {"provider": provider, "slug": slug, "wrote": True})
    return result


def list_secrets(provider: str) -> List[str]:
    """List available secret slugs for a provider."""
    return _handler.list_secrets(provider)


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    error(f"Unknown command: {args[0]}")
    sys.exit(1)
