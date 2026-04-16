# =================== AIPass ====================
# Name: passport.py
# Description: Passport command — thin CLI layer for granting birthright citizenship
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-14
# =============================================

"""Passport command orchestrator for branch lifecycle management.

Thin CLI module that parses arguments and delegates to the passport handler.
All implementation logic lives in apps/handlers/passport_ops.py.
"""

import argparse

from pathlib import Path

from aipass.cli.apps.modules import console, error, warning
from aipass.prax import logger

from aipass.spawn.apps.handlers.passport_ops import grant_passport
from aipass.spawn.apps.handlers.registry import find_registry
from aipass.spawn.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("passport Module")
    console.print("Grant birthright citizenship — minimal identity (.trinity/, .aipass/, README.md)")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - passport_ops.py (grant_passport — create minimal citizen identity and register)")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Args:
        command: The command string (e.g. "passport")
        args: List of arguments for the command

    Returns:
        True if command was handled, False otherwise.
    """
    if command != "passport":
        return False

    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    return handle_passport(args) == 0


def _search_src_subdirs(src_dir: Path, dirname: str) -> Path | None:
    """Search src/*/dirname for an existing directory."""
    if not src_dir.is_dir():
        return None
    for sub in src_dir.iterdir():
        if not sub.is_dir():
            continue
        candidate = sub / dirname
        if candidate.exists():
            return candidate
    return None


def _resolve_target(dirname: str) -> Path:
    """Resolve a @dirname to a filesystem path.

    Searches CWD, project root (via registry), and src/ subdirectories.
    For new directories, defaults to CWD-relative.
    """
    # Absolute or home-relative path — use directly
    if dirname.startswith("/") or dirname.startswith("~"):
        return Path(dirname).expanduser()

    # 1. CWD-relative
    cwd_path = Path.cwd() / dirname
    if cwd_path.exists():
        return cwd_path

    # 2. Project-relative via registry
    try:
        reg_path = find_registry()
        project_root = reg_path.parent
        for candidate in [
            project_root / dirname,
            project_root / "src" / dirname,
        ]:
            if candidate.exists():
                return candidate
        # Search src/*/dirname (e.g., src/aipass/target)
        found = _search_src_subdirs(project_root / "src", dirname)
        if found:
            return found
    except Exception as exc:
        logger.warning("[passport] Registry lookup failed during target resolution: %s", exc)

    # 3. Default: CWD-relative (passport will create it if needed)
    return cwd_path


def handle_passport(args: list[str]) -> int:
    """Parse args and execute passport grant.

    Args patterns:
        ["@dirname"]                    -> grant birthright to dirname
        ["@dirname", "--role", "X"]     -> with role
        ["@dirname", "--purpose", "X"]  -> with purpose

    Returns exit code (0=success, 1=failure).
    """
    if not args:
        warning("Usage: drone @spawn passport <@dirname> [--role ...] [--purpose ...]")
        console.print()
        console.print("  [dim]Grant birthright citizenship to a directory[/dim]")
        console.print()
        console.print("  [green]@dirname[/green]     Directory to grant citizenship (created if needed)")
        warning("--role", details="Role description for the passport")
        warning("--purpose", details="Purpose description")
        return 1

    # Intercept --help before argparse (argparse has add_help=False)
    if "--help" in args or "-h" in args:
        print_introspection()
        return 0

    parser = argparse.ArgumentParser(prog="spawn passport", add_help=False)
    parser.add_argument("target")
    parser.add_argument("--role", default="")
    parser.add_argument("--purpose", default="")

    parsed = parser.parse_args(args)

    # Strip @ prefix if present
    target = parsed.target.lstrip("@")

    # Resolve target path — CWD-aware for external project support
    target_path = _resolve_target(target)

    result = grant_passport(
        target_path=str(target_path),
        role=parsed.role,
        purpose=parsed.purpose,
    )

    if result["success"]:
        json_handler.log_operation("passport_granted", data={"branch": result["branch_name"]})
        console.print()
        console.print(f"[green]Passport granted: {result['branch_name']}[/green]")
        console.print("  Class: birthright")
        console.print(f"  Path: {result['path']}")
        console.print(f"  Files: {result['files_copied']}")
        console.print(f"  Registry: {'updated' if result['registry_updated'] else 'not updated'}")
        if result["validation_issues"]:
            warning(f"{len(result['validation_issues'])} unreplaced placeholders")
        console.print()
        return 0
    else:
        error(result["error"])
        return 1
