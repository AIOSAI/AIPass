# =================== AIPass ====================
# Name: permissions.py
# Description: Shared trust list for hook layer and drone authorization
# Version: 1.0.0
# Created: 2026-04-21
# Modified: 2026-04-21
# =============================================

"""Shared permission definitions for cross-branch write authorization.

Single source of truth for which branches may write outside their own
directory. Consumed by pre_edit_gate.py (hook layer) and
drone/apps/plugins/devpulse_ops/auth.py (drone layer).
"""

from __future__ import annotations

import json
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

TRUSTED_CROSS_WRITERS: tuple[str, ...] = ("devpulse", "seedgo", "spawn")


def is_trusted_caller(name: str) -> bool:
    """Return True if *name* is in TRUSTED_CROSS_WRITERS."""
    json_handler.log_operation("is_trusted_caller", {"name": name})
    return name.lower() in TRUSTED_CROSS_WRITERS


def identify_caller(cwd: str | None = None) -> str:
    """Walk up from *cwd* (default: CWD) to find passport.json, return branch_name.

    Returns the branch name string, or empty string if no passport is found
    or the file cannot be parsed.
    """
    start = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    current = start
    for _ in range(10):
        passport = current / ".trinity" / "passport.json"
        if passport.exists():
            try:
                data = json.loads(passport.read_text(encoding="utf-8"))
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                return name or ""
            except Exception as exc:
                logger.warning("[permissions] identify_caller: failed to parse passport at %s: %s", passport, exc)
                return ""
        parent = current.parent
        if parent == current:
            break
        current = parent
    return ""


def print_introspection() -> None:
    """Display permissions module info."""
    from aipass.cli import console

    console.print("[bold cyan]permissions[/bold cyan] — shared trust list for hook + drone layers")
    console.print(f"  TRUSTED_CROSS_WRITERS: {TRUSTED_CROSS_WRITERS}")
    console.print("  Functions: is_trusted_caller(name), identify_caller(cwd)")


def handle_command(command: str, args: list) -> bool:
    """Claim the ``permissions`` command and render the trust list; ignore the rest.

    route_command() offers every command to every module in discovery order, so a
    module that prints while returning False writes above whichever module
    actually answers. The old gate keyed on the ARGUMENTS (no args, or --help)
    rather than the command name, so the trust list leaked over every bare
    subcommand — while `drone @seedgo permissions` itself was answered with
    "Unknown command" and then printed the block anyway.
    """
    if command != "permissions":
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(None, args):
        print_introspection()
        return True
    return False
