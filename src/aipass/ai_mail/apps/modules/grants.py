# =================== AIPass ====================
# Name: grants.py
# Description: Grants Module: the open scoped write grants dispatches carry, listed
# Version: 1.0.0
# Created: 2026-11-03
# Modified: 2026-11-03
# =============================================

"""
Grants Module

Lists the scoped write grants open on the dispatch register. Granting happens on the
dispatch verb (--grant-root, --grant); a gate decides a write through door_dispatch_grant.
"""

import os
import sys
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.handlers.dispatch.grant import open_grants
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_LIVENESS = {True: "monitor alive", False: "monitor GONE", None: "monitor unknown"}


def print_help() -> None:
    """Print help for the grants command."""
    console.print(
        """
Grants - scoped write grants carried by open dispatches

  drone @ai_mail grants      List each open grant: dispatch, sender -> target, root and paths, monitor

GRANTING (admin seat only), on the dispatch verb:
  drone @ai_mail dispatch @hooks "S" "B" --grant-root <project dir> --grant src/loop.ts,src/hooks
  Files grant themselves; a directory grants everything under it, new files included. Refused
  before the send for a non-admin sender, a manager target, an absolute path, .., a path that
  escapes the root, the root itself, .git, a missing path, or an overlap with an open grant.
  The body gains a GRANT block. The grant lives on the dispatch's register row and ends when the
  row closes (monitor exit, reply, stop, close); only the session carrying that dispatch's
  AIPASS_DISPATCH_ID holds it.
""",
        markup=False,
    )


def handle_command(command: str, args: List[str]) -> bool:
    """Handle the grants command; False for any other command."""
    if command != "grants":
        return False
    if wants_help(args):
        print_help()
        return True
    json_handler.log_operation("grants_list", {})
    try:
        rows = open_grants()
    except OSError as exc:
        logger.warning("[grants] register unreadable: %s", exc)
        error(f"Cannot read the dispatch register: {exc}")
        return True
    if not rows:
        console.print("No open grants")
        return True
    console.print(f"\nOpen grants ({len(rows)})\n")
    for row in rows:
        grant = row["grant"]
        paths = ", ".join(list(grant.get("files", [])) + [f"{d}/" for d in grant.get("dirs", [])])
        late = " · OVERDUE" if row.get("overdue") else ""
        console.print(f"  {row.get('dispatch_id')}  {row.get('sender')} -> {row.get('target')}", soft_wrap=True)
        console.print(f"    {grant.get('root')}: {paths}", soft_wrap=True, markup=False)
        console.print(f"    {_LIVENESS.get(row.get('monitor_alive'))}{late}", markup=False)
    return True


def print_introspection() -> None:
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]grants Module[/bold cyan]")
    console.print("[dim]Lists the open scoped write grants on the dispatch register.[/dim]")
    console.print("  [cyan]handlers/dispatch/grant.py[/cyan] [dim](open_grants)[/dim]")
    console.print()


if __name__ == "__main__":
    print_introspection()
