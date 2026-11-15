# =================== AIPass ====================
# Name: init_flow.py
# Description: aipass init — project scaffold, scaffold update, first agent
# Version: 2.1.0
# Created: 2026-04-16
# Modified: 2026-11-14
# =============================================

"""
aipass init — non-interactive project commands

Scaffold a project, update an existing one, create an agent. No guided setup: the owner
retired it 2026-11-14 (FPLAN-0924).
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

from aipass.cli.apps.modules import console, error as cli_error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

COMMAND = "init"


def _resolve_package_dir() -> str | None:
    """Find the src/<package>/ path in CWD project."""
    src_dir = Path.cwd() / "src"
    if not src_dir.is_dir():
        return None
    for child in src_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            return f"src/{child.name}"
    return None


def print_introspection() -> None:
    """Show what the init module offers."""
    console.print()
    console.print("[bold cyan]init_flow Module[/bold cyan]")
    console.print("Project scaffold, scaffold update and first agent; no guided setup")
    console.print()
    console.print("[dim]Run 'aipass init --help' for usage.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the init command."""
    console.print()
    console.print("[bold cyan]aipass init[/bold cyan] — project scaffold and update")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print(
        "  [green]aipass init \\[target] \\[name][/green]        "
        "[dim]# instant project scaffold in target (default: cwd)[/dim]"
    )
    console.print("  [green]aipass init agent <name>[/green]             [dim]# create an agent via drone @spawn[/dim]")
    console.print(
        "  [green]aipass init update \\[target][/green]          [dim]# apply the scaffold plan + git auth[/dim]"
    )
    console.print(
        "  [green]aipass init update --dry-run[/green]         [dim]# print the plan, write nothing (exit 2)[/dim]"
    )
    console.print("  [green]aipass init update --json[/green]            [dim]# the same plan, machine-readable[/dim]")
    console.print()


def _handle_init_scaffold(args: list[str]) -> int:
    """Handle `aipass init [target] [name]` — instant project scaffold."""
    from aipass.aipass.apps.handlers.init.bootstrap import init_project

    target = Path(args[0]) if args else Path.cwd()
    project_name = args[1] if len(args) > 1 else None
    try:
        # Positional only: a flag here was read as the project name and scaffolded `--DRY-RUN_REGISTRY.json`.
        flags = [arg for arg in args if arg.startswith("-")]
        if flags:
            raise ValueError(
                f"aipass init [target] [name] takes no flags (got {' '.join(flags)}) and writes the scaffold. "
                "Preview an existing project with: aipass init update --dry-run"
            )
        result = init_project(target, project_name)
        success(f"Project initialized at {target}")
        for note in result.get("notes", []):
            warning(note)
        console.print()

        package_dir = None
        for child in (target / "src").iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                package_dir = child
                break

        console.print("[bold]Project structure:[/bold]")
        console.print(f"  {target}/")
        if package_dir:
            rel_pkg = package_dir.relative_to(target)
            console.print(f"  └── {rel_pkg}/    [dim]← agents live here[/dim]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        if str(target) != str(Path.cwd()):
            console.print(f"  [cyan]cd {target}[/cyan]")
        console.print("  [cyan]aipass init agent <name>[/cyan]    [dim]# create your first agent[/dim]")
        console.print()

        json_handler.log_operation("aipass_init", {"target": str(target), "result": result})
        return 0
    except Exception as exc:
        logger.warning("[init_flow] scaffold failed: %s", exc)
        cli_error(f"Init failed: {exc}")
        return 1


def _run_git_auth_provisioning(target: Path, dry_run: bool = False) -> int:
    """Provision the project for manager-class git; print every repair."""
    from aipass.aipass.apps.handlers.init.git_auth import GitAuthRefusal, provision_git_auth

    console.print()
    console.print("[bold]Git authorization (owner-tier)[/bold]")
    try:
        result = provision_git_auth(target, dry_run=dry_run)
    except GitAuthRefusal as exc:
        cli_error(f"Cannot provision git authorization: {exc}")
        logger.warning("[init_flow] git-auth provisioning refused: %s", exc)
        json_handler.log_operation("aipass_git_auth", {"target": str(target), "refusal": str(exc)})
        return 1

    repairs = result["repairs"]
    verb = "would repair" if dry_run else "repaired"
    if repairs:
        success(f"Owner '{result['owner']}' — {verb} {len(repairs)} item(s):")
        for item in repairs:
            console.print(f"  + {item}")
    else:
        success(f"Owner '{result['owner']}' already holds owner-tier — nothing to repair.")
    for item in result["already_ok"]:
        console.print(f"  [dim]· {item}[/dim]")

    if dry_run:
        console.print("[dim]Preview only — no files written.[/dim]")
    elif result["verified"]:
        success("Verified against all four owner-tier checks.")
    else:
        cli_error("Repairs written, but verification still fails:")
        for item in result["verify_failures"]:
            console.print(f"  - {item}")

    # No log_operation here: the handler already recorded what it wrote.
    return 0 if dry_run or result["verified"] else 1


_PLAN_GLYPHS: dict = {
    "create": ("+", "green"),
    "update": ("~", "yellow"),
    "current": ("=", "dim"),
    "kept-local": ("!", "cyan"),
    "retire": ("-", "magenta"),
    "skipped": ("·", "blue"),
}


def _print_scaffold_plan(result: dict, *, dry_run: bool) -> None:
    """Print the scaffold plan — the same block whether previewing or applying.

    What a manager pasted for a go and what actually ran must read as the same thing.
    """
    files = result.get("files") or []
    handlers = result.get("handlers") or []
    if not files and not handlers:
        updated = result.get("updated_files", [])
        if updated:
            success(f"Updated {len(updated)} file(s):")
            for f in updated:
                console.print(f"  + {f}")
        else:
            success("All files already current.")
        current = result.get("already_current", [])
        if current:
            console.print(f"  ({len(current)} already up to date)")
        return

    verb = "would change" if dry_run else "changed"
    console.print(
        f"\n[bold]Scaffold plan[/bold] — {result.get('project_name', '?')}  [dim]{result.get('target', '')}[/dim]"
    )
    stamped = result.get("stamped_version") or "unstamped"
    console.print(f"[dim]AIPass {result.get('aipass_version', '?')} · project stamped {stamped}[/dim]\n")

    from rich.markup import escape

    width = max((len(entry["path"]) for entry in files), default=0)
    for entry in files:
        glyph, colour = _PLAN_GLYPHS.get(entry["action"], ("?", "white"))
        label = entry["action"].ljust(11)
        console.print(
            f"  [{colour}]{glyph} {label}[/{colour}] {entry['path'].ljust(width)}  [dim]{entry['reason']}[/dim]"
        )
        for line in entry.get("lines", []):
            console.print(f"      [dim]+ {escape(line)}[/dim]")

    if handlers:
        added = [h["name"] for h in handlers if h["action"] == "add"]
        retired = [h["name"] for h in handlers if h["action"] == "retire"]
        console.print("")
        if added:
            console.print(f"  [green]hooks[/green]   add     {', '.join(sorted(added))}")
        if retired:
            console.print(f"  [magenta]hooks[/magenta]   retire  {', '.join(sorted(retired))}")

    console.print("")
    if result.get("stamp_pending"):
        state = "pending" if dry_run else "written"
        console.print(f"  [yellow]stamp[/yellow]   {stamped} → {result.get('aipass_version', '?')} {state}")
    if result.get("trust_reenrol"):
        console.print(
            "  [green]trust[/green]   re-enrolled" if not dry_run else "  [green]trust[/green]   re-enrol on apply"
        )
    if result.get("backup_dir"):
        console.print(f"  [dim]backup  {result['backup_dir']}[/dim]")

    protected = [e for e in files if e["action"] == "skipped"]
    if protected:
        console.print(f"  [blue]owner[/blue]   {len(protected)} file(s) protected by .updateignore")

    # Count writes, not non-current labels: a kept file whose sidecar exists changes nothing.
    changed = [e for e in files if e.get("writes")]
    console.print(
        f"\n  {len(changed)} of {len(files)} file(s) {verb}, {len(files) - len(changed) - len(protected)} unchanged."
    )

    kept = [e for e in files if e["action"] == "kept-local"]
    if kept:
        console.print(
            f"  [dim]{len(kept)} file(s) kept: your copy stands. Diff it against the .aipass-new"
            " beside it; delete yours to take the template.[/dim]"
        )


def _handle_init_update(args: list[str]) -> int:
    """Handle `aipass init update [target] [--dry-run] [--json]`.

    Exit-code contract: ``--dry-run`` exits 0 when current and 2 when anything is pending.
    """
    from aipass.aipass.apps.handlers.init.bootstrap import update_project

    dry_run = "--dry-run" in args
    as_json = "--json" in args
    positional = [a for a in args if not a.startswith("--")]
    target = Path(positional[0]) if positional else Path.cwd()

    try:
        result = update_project(target, apply=not dry_run)
    except Exception as exc:
        logger.warning("[init_flow] update failed: %s", exc)
        cli_error(f"Update failed: {exc}")
        return 1

    if as_json:
        # print_json, not print(): no markup or wrapping, so a pipe gets parseable JSON.
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_scaffold_plan(result, dry_run=dry_run)

    if dry_run:
        if not as_json:
            if result.get("stamp_only"):
                console.print(
                    "[dim]Preview only — nothing written. Stamp only: no file would change, "
                    f"so no go is needed. Run: aipass init update {target}[/dim]"
                )
            else:
                console.print("[dim]Preview only — nothing written. Apply needs the owner's or devpulse's go.[/dim]")
        if as_json:
            # Under --json stdout is exactly one JSON document; the git-auth plan goes to
            # stderr, since a refusal there is the only place its fix is named.
            with contextlib.redirect_stdout(sys.stderr):
                auth_rc = _run_git_auth_provisioning(target, dry_run=True)
        else:
            auth_rc = _run_git_auth_provisioning(target, dry_run=True)
        if auth_rc != 0:
            return auth_rc
        return 2 if result.get("pending") else 0

    for note in result.get("notes", []):
        warning(note)
    try:
        if result.get("trust_enrolled"):
            success("Enrolled in trust registry — hooks active.")
        elif "trust_enrolled" in result and result["trust_enrolled"] is None:
            # None is project_home's 'registry unavailable', distinct from a refusal.
            warning(f"Trust registry unavailable — not enrolled. Run 'aipass trust {target}' once AIPass is installed.")
        from aipass.aipass.apps.modules.install import _check_and_fix_owner

        _check_and_fix_owner(target)

        json_handler.log_operation("aipass_init_update", {"target": str(target), "result": result})
    except Exception as exc:
        logger.warning("[init_flow] update failed: %s", exc)
        cli_error(f"Update failed: {exc}")
        return 1

    # Last, so it wins over sync-registry's class migration; outside the try so a
    # git-auth fault never reads as a scaffold-update failure.
    return _run_git_auth_provisioning(target)


def _handle_init_agent(args: list[str]) -> int:
    """Handle `aipass init agent <name>` — create a new agent via spawn."""
    if not args:
        cli_error("Usage: aipass init agent <name>")
        return 1
    agent_name = args[0]
    import subprocess as _sp

    package_dir = _resolve_package_dir()
    if package_dir:
        agent_path = f"{package_dir}/{agent_name}"
    else:
        agent_path = f"src/{agent_name}"

    cmd = ["drone", "@spawn", "create", agent_path]
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    result = _sp.run(cmd, capture_output=False)
    return result.returncode


def handle_command(command: str, args: list[str]) -> bool:
    """Route init subcommands. Returns True if handled, False otherwise."""
    if command != COMMAND:
        return False

    if not args:
        print_help()
        return True

    if wants_help(args):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    if args[0] == "agent":
        sys.exit(_handle_init_agent(args[1:]))
        return True

    if args[0] == "update":
        sys.exit(_handle_init_update(args[1:]))
        return True

    # Retired, not a project name: scaffolding ./run would answer an old doc's command silently.
    if args[0] == "run":
        cli_error("'aipass init run' was retired 2026-11-14: no guided setup. Use: aipass init [target] [name]")
        sys.exit(1)

    sys.exit(_handle_init_scaffold(args))
    return True


if __name__ == "__main__":
    handle_command("init", sys.argv[1:])
