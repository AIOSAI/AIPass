# =================== AIPass ====================
# Name: inbox_audit.py
# Description: Inbox ID validator — scans all inbox.json files for non-8-hex ids
# Version: 1.1.0
# Created: 2026-04-21
# Modified: 2026-08-13
# =============================================

"""Inbox ID validator for the drone @seedgo audit inbox-ids command.

Walks all .ai_mail.local/inbox.json files in the AIPass repo and flags any
message ids that are not 8-character lowercase hex strings.  Alerts devpulse
when violations are found.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.cli import console, header
from aipass.cli.apps.modules import error, success
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help

_HEX8_RE = re.compile(r"^[0-9a-f]{8}$")

# Trees whose inboxes are snapshots, not live mail: deleted-branch archives
# and @backup's versioned store. A bad id in either is nobody's to fix.
_DEAD_TREE_DIRS = frozenset({".backup", ".archive"})


def _is_live_inbox(inbox_path: Path) -> bool:
    """Return True if *inbox_path* is a live inbox a branch can actually act on.

    Two un-actionable shapes are excluded. Anything under `.backup/` or
    `.archive/` is a snapshot of mail that has already been delivered or of a
    branch that no longer exists. And a *directory* named `inbox.json` is how
    @backup's versioned store holds a file — the current copy, a dated baseline
    and an `inbox.json_diffs/` sibling all sit inside a directory carrying the
    original name. `read_text()` on one raises IsADirectoryError; that is not an
    unreadable inbox, it is not an inbox.
    """
    if _DEAD_TREE_DIRS.intersection(inbox_path.parts):
        return False
    return inbox_path.is_file()


def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return current


def _scan_inbox(inbox_path: Path) -> List[dict]:
    """Return a list of violation dicts for messages with bad ids in *inbox_path*."""
    violations: List[dict] = []
    try:
        data = json.loads(inbox_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[inbox_audit] could not read %s: %s", inbox_path, exc)
        return violations

    for msg in data.get("messages", []):
        msg_id = msg.get("id", "")
        if not _HEX8_RE.match(str(msg_id)):
            violations.append(
                {
                    "inbox": str(inbox_path),
                    "id": msg_id,
                    "subject": msg.get("subject", ""),
                    "from": msg.get("from", ""),
                }
            )
    return violations


def _run_inbox_id_scan() -> int:
    """Scan all inbox.json files; return number of violations found."""
    json_handler.log_operation("inbox_audit_scan", {})
    repo_root = _find_repo_root()
    matched = list(repo_root.rglob(".ai_mail.local/inbox.json"))
    inbox_files = [p for p in matched if _is_live_inbox(p)]
    skipped = len(matched) - len(inbox_files)

    console.print()
    header("SEEDGO — Inbox ID Validator")
    console.print(f"[dim]Scanning {len(inbox_files)} live inbox file(s) for non-8-hex message ids...[/dim]")
    if skipped:
        console.print(f"[dim]Skipped {skipped} archived/backed-up copy(ies) — not live mail.[/dim]")
    console.print()

    all_violations: List[dict] = []
    for inbox_path in sorted(inbox_files):
        violations = _scan_inbox(inbox_path)
        all_violations.extend(violations)

    if not all_violations:
        success("All message ids are valid 8-char hex strings.")
        console.print()
        return 0

    error(f"Found {len(all_violations)} id violation(s):")
    console.print()
    for v in all_violations:
        rel = Path(v["inbox"]).relative_to(repo_root) if Path(v["inbox"]).is_absolute() else v["inbox"]
        console.print(
            f"  • [bold]{rel}[/bold]  id=[yellow]{v['id']!r}[/yellow]  from={v['from']}  subject={v['subject']!r}"
        )

    console.print()
    console.print("[yellow]Action:[/yellow] Alert devpulse — run:")
    console.print(
        f'  [green]drone @ai_mail email @devpulse "inbox-id violations" '
        f'"Found {len(all_violations)} bad message id(s) — run drone @seedgo audit inbox-ids for details"[/green]'
    )
    console.print()
    return len(all_violations)


def print_introspection() -> None:
    """Show inbox_audit module structure."""
    console.print("[bold cyan]inbox_audit[/bold cyan] — Inbox ID validator")
    console.print("  Connected Handlers: none (uses stdlib + pathlib only)")
    console.print("  Command: drone @seedgo audit inbox-ids")


def handle_command(command: str, args: List[str]) -> bool:
    """Handle `audit inbox-ids` — return True only for that exact subcommand."""
    if command == "inbox_audit":
        if not args:
            print_introspection()
            return True
        if wants_help(None, args):
            print_introspection()
            return True
    if command not in ("audit", "standards_audit"):
        return False
    if not args or args[0] != "inbox-ids":
        return False
    # Ownership is settled, so the help gate comes here: `audit inbox-ids
    # --help` had args[0] == "inbox-ids", so the gate above never saw the flag
    # and the scan rglob'd every inbox under the repo root to answer a question.
    if wants_help(None, args):
        print_introspection()
        return True
    _run_inbox_id_scan()
    return True
