# =================== AIPass ====================
# Name: home_paths.py
# Description: The home-paths verb — the developer_home standard over the whole tracked tree, for CI
# Version: 1.0.0
# Created: 2026-10-04
# Modified: 2026-10-17
# =============================================

"""The `home-paths` verb. Scans every tracked text file of the repository for a
developer's home directory (the `developer_home` standard); it is the CI gate.

A bare call describes the verb; `scan` runs it. A red exits 1; a tree git cannot list
exits 2, because "could not measure" is not "clean"; an unknown flag exits 7.
"""

from pathlib import Path
from typing import List, Optional

from aipass.cli import console
from aipass.cli.apps.modules import error, success
from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import developer_home_check
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.modules import CommandRefused

COMMANDS: tuple = ("home-paths", "home_paths")

FLAGS: tuple = ("--help", "-h")

SCAN_TOKEN = "scan"


def handle_command(command: str, args: List[str]) -> bool:
    """Claim `home-paths` and run it. A red or an unusable argument raises CommandRefused."""
    if command not in COMMANDS:
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(None, args):
        print_help()
        return True

    root = _parse(args)
    _scan(root)
    return True


def _parse(args: List[str]) -> Path:
    """The root to scan, from `scan [<root>]`; anything else is refused by name."""
    if args[0] != SCAN_TOKEN:
        _refuse(args[0], f"home-paths does not know '{args[0]}' - the word that runs it is '{SCAN_TOKEN}'")
    rest = args[1:]
    for token in rest:
        if token.startswith("-"):
            _refuse(token, f"home-paths does not know the option '{token}' - it accepts {', '.join(FLAGS)}")
    if len(rest) > 1:
        _refuse(rest[1], "home-paths scan takes at most one root")
    if not rest:
        found = _repo_root()
        if found is None:
            _refuse(SCAN_TOKEN, "no git repository holds this branch - name the root: home-paths scan <root>")
        return found  # type: ignore[return-value]
    root = Path(rest[0]).resolve()
    if not root.is_dir():
        _refuse(rest[0], f"not a directory: {rest[0]}")
    return root


def _refuse(token: str, message: str) -> None:
    error(message, suggestion="drone @seedgo home-paths --help")
    raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, token)


def _repo_root() -> Optional[Path]:
    """The repository containing this branch: the nearest parent holding `.git`."""
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _scan(root: Path) -> None:
    """Scan, print one line per hit and one total, and refuse on red."""
    result = developer_home_check.scan_tracked(root)
    for rel, line, matched in result["hits"]:
        console.print(f"{rel}:{line}: {matched}", markup=False, highlight=False, soft_wrap=True)
    for reason in result["errors"]:
        error(f"cannot measure: {reason}")
    json_handler.log_operation(
        "home_paths_scanned", {"root": root.name, "hits": len(result["hits"]), "errors": len(result["errors"])}
    )
    total = (
        f"{len(result['hits'])} developer home path(s) in {result['files_read']} tracked text file(s) "
        f"({result['binary_skipped']} binary skipped)"
    )
    if result["errors"]:
        logger.warning("[home_paths] could not measure %s: %s", root, result["errors"])
        console.print(total, markup=False, highlight=False)
        raise CommandRefused(refusal.EXIT_UNPROVEN, "home-paths")
    if result["hits"]:
        error(total)
        raise CommandRefused(refusal.EXIT_SCORED_FAILED, "home-paths")
    success(total)


def print_help() -> None:
    """Usage, exit codes, and where the bypass lives."""
    console.print()
    console.print("[bold cyan]seedgo home-paths[/bold cyan] - no developer's home directory in a tracked text file")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drone @seedgo home-paths                 what the verb is")
    console.print("  drone @seedgo home-paths scan            scan the repo holding this branch")
    console.print("  drone @seedgo home-paths scan <root>     scan the repo at <root>")
    console.print()
    console.print("[yellow]Exit codes[/yellow]")
    console.print("  0 clean   1 a hit   2 could not measure (git, an unreadable file)   7 an unknown argument")
    console.print()
    console.print("[yellow]Bypass[/yellow]")
    console.print("  a line rule for developer_home in the owning branch's .seedgo/bypass.json")
    console.print("  Standard: drone @seedgo standard developer_home")
    console.print()


def print_introspection() -> None:
    """What this verb is, shown when it is called with no arguments."""
    console.print()
    console.print("[bold cyan]home-paths[/bold cyan] - the developer_home standard over the whole tracked tree")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim]- aipass_standards/developer_home_check.py (scan_tracked, scan_text)[/dim]")
    console.print("  [dim]- context_standards/name_ratchet.py (tracked_files: git ls-files)[/dim]")
    console.print()
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo home-paths scan[/green]      [dim]# Scan the tracked tree[/dim]")
    console.print("  [green]drone @seedgo home-paths --help[/green]    [dim]# Full usage guide[/dim]")
    console.print()
