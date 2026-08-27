# =================== AIPass ====================
# Name: push.py
# Description: The trinity push lane — dry-run reporting and gated execution
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Trinity Push Module

CLI routing for ``drone @memory push`` — the one lane that brings a branch's
``.trinity/`` files to the trinity standard.  All domain logic lives in
``handlers/templates/trinity_push.py``; this module parses flags, renders the
report, and enforces the two gates.

The gates
---------
**A fleet write needs ``--confirm``.**  Patrick's ruling is that the fleet run
is gated on a dry-run he has read.  Encoding that as a flag rather than as an
operator's memory is the difference between a rule and a hope — and this
branch has already demonstrated the alternative, when a command run to check
*whether a verb existed* performed a fleet-wide reset on 18 branches with no
prompt and exit 0.

**``--dry-run`` writes nothing anywhere** — not the memory files, not the
vector store, not the receipts.  Its report is the artifact Patrick reads, so
it is written to a file as well as to the terminal and the path is printed.

Note that ``push`` no longer aliases ``rollover push``.  That alias fired the
fleet-wide per-branch CONFIG reset from a bare, unprompted word; the config
reset keeps its own explicit verb and this name now belongs to the lane that
earns it.
"""

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.templates import push_report
from aipass.memory.apps.handlers.templates import trinity_push

_SUBCOMMANDS = {
    "--branch NAME": "Push a single branch (required for single-branch mode)",
    "--dry-run": "Report what would change; writes nothing anywhere",
    "--confirm": "Required for a FLEET write — the dry-run gate",
}


# =============================================================================
# COMMAND ROUTING
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """Route ``push`` and its flags.

    Args:
        command: Command name.
        args: Remaining CLI arguments.

    Returns:
        True when this module handled the command.
    """
    if command != "push":
        return False

    if not args:
        print_introspection()
        return True

    # A help flag anywhere outranks everything — asking about the push must
    # never perform one. `push` takes no free text, so a bare `help` counts.
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    branch, dry_run, confirm, bad_flag = _parse_args(args)
    if bad_flag:
        error(bad_flag, suggestion="Run 'drone @memory push --help' for the flags")
        return True

    if not dry_run and branch is None and not confirm:
        error(
            "A fleet push needs --confirm.",
            suggestion=(
                "Run 'drone @memory push --dry-run' first — that report is the gate; then re-run with --confirm"
            ),
        )
        return True

    _run_push(branch, dry_run)
    return True


def _parse_args(args: List[str]) -> tuple:
    """Parse flags. Returns (branch, dry_run, confirm, bad_flag_message)."""
    branch = None
    dry_run = False
    confirm = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--branch":
            if index + 1 >= len(args):
                return None, False, False, "--branch needs a branch name"
            branch = args[index + 1]
            index += 2
            continue
        if token == "--dry-run":
            dry_run = True
        elif token == "--confirm":
            confirm = True
        else:
            return None, False, False, f"Unknown argument: '{token}'"
        index += 1
    return branch, dry_run, confirm, None


def _run_push(branch, dry_run: bool) -> None:
    """Execute the push and render its report."""
    label = f"@{branch.lstrip('@')}" if branch else "FLEET"
    mode = "DRY RUN" if dry_run else "PUSH"
    console.print()
    console.print(
        Panel.fit(f"[bold cyan]Memory - Trinity {mode} · {label}[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()

    try:
        result = trinity_push.push(branch=branch, dry_run=dry_run)
    except Exception as exc:
        logger.error(f"[push] Trinity push crashed: {exc}", exc_info=True)
        error(f"Trinity push crashed: {exc}")
        return

    lines = push_report.render(result, label)
    for line in lines:
        console.print(line, markup=False, highlight=False)

    path = push_report.save(lines, label, dry_run)
    if path:
        console.print()
        console.print(f"[cyan]Report written to:[/cyan] {path}")
    console.print()

    json_handler.log_operation(
        "trinity_push_cli",
        {"scope": label, "dry_run": dry_run, "branches": result.get("scope", 0), "report": path},
        module_name="push",
    )


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Level 2 introspection — what this module is wired to."""
    console.print()
    console.print(
        Panel.fit("[bold cyan]Push Module - The Trinity Push[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()
    console.print("[bold]PURPOSE:[/bold]")
    console.print("  Bring a branch's .trinity/ files to the trinity standard: re-render the")
    console.print("  machine frame, archive-then-prune every non-canonical entry, leave one note.")
    console.print()
    console.print("[bold]HANDLERS:[/bold]")
    console.print("  handlers/templates/trinity_push.py   plan, archive-verify-prune, apply")
    console.print("  handlers/templates/push_store.py     vector store + read-back verification")
    console.print("  handlers/templates/receipt.py        .template_version.json stamping")
    console.print("  handlers/tracking/tab_renderer.py    meta lines and _usage from the templates")
    console.print()
    console.print("[bold]FLAGS:[/bold]")
    for flag, description in _SUBCOMMANDS.items():
        console.print(f"  [cyan]{flag:<16}[/cyan] {description}")
    console.print()
    console.print("[bold]SAFETY:[/bold] a pruned entry is vectorized and read back BEFORE it is removed.")
    console.print("  If the read-back does not match, NOTHING is pruned from that branch.")
    console.print()


def print_help() -> None:
    """Full usage."""
    console.print()
    console.print(Panel.fit("[bold cyan]drone @memory push[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory push --dry-run                  Fleet dry-run (the gate report)")
    console.print("  drone @memory push --branch @canary --dry-run One branch, no writes")
    console.print("  drone @memory push --branch @canary           Push one branch for real")
    console.print("  drone @memory push --confirm                  FLEET push (needs the flag)")
    console.print()
    console.print("[bold]WHAT A PUSH DOES, per branch:[/bold]")
    console.print("  1. Re-renders the machine frame — document_metadata as a CLOSED set,")
    console.print("     managed_by in exact branch-directory casing, _usage and guidelines")
    console.print("     verbatim from the templates, all four meta lines from config.")
    console.print("  2. Vectorizes every non-canonical entry VERBATIM, VERIFIES the ingestion")
    console.print("     by reading it back, and only then prunes it from the live file.")
    console.print("  3. Writes one canonical session note saying where those entries went.")
    console.print()
    console.print("[bold]SCOPE:[/bold] 18 active citizens + the resident projects baud, earmark,")
    console.print("  finch and aipass_site. Named explicitly — never a glob over projects/.")
    console.print()
    console.print("[bold]NOT IN SCOPE:[/bold] stray files in .trinity/ are reported, never deleted.")
    console.print()
