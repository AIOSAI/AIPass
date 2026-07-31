# =================== AIPass ====================
# Name: install.py
# Description: aipass install — one-command PyPI bootstrap (clone + setup + handoff)
# Version: 1.0.0
# Created: 2026-07-05
# Modified: 2026-07-05
# =============================================

"""
aipass install — one-command bootstrap of the whole framework

The missing half of `pip install aipass`. pip lands the *code* in site-packages;
this command materializes a working, writable AIPass home and wires it up:

    1. Resolve where AIPass should live (default ~/AIPass; --here / --path to steer).
    2. Fetch the framework there (git clone of the public repo) if not already present.
    3. Run the canonical setup.sh (venv, editable install, provider-hook wiring, binaries).
    4. Verify drone/aipass are on PATH, then hand off into `aipass init run` to
       scaffold a first project (interactive default; --no-init to skip, --with-init
       to force even headless). Init targets a sibling dir, never the engine tree.

Each step prints a Step k/N progress header. Streaming subprocesses (git, setup.sh)
show a header + their own output + a result line — no spinner (the two renderers
fight, per ui/progress.activity_spinner).

Usage:
    aipass install                       # interactive, then launches init
    aipass install --non-interactive     # CI/headless (~/AIPass), stops before init
    aipass install --with-init           # headless AND chain into init --non-interactive
    aipass install --no-init             # install the engine only, skip the handoff
    aipass install --path ~/tools/aipass # explicit home
    aipass install --project ~/proj      # where the first project scaffolds
    aipass install --here                # install into the current directory
    aipass install --dry-run             # walk all steps, no clone/setup/launch
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from aipass.cli.apps.modules import console, success, warning
from aipass.prax import logger

from aipass.aipass.apps.handlers.init.bootstrap import is_throwaway_path
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import render_step_header

COMMAND = "install"
TOTAL_STEPS = 4
REPO_URL = "https://github.com/AIOSAI/AIPass.git"
DEFAULT_HOME = Path.home() / "AIPass"
# `aipass init` refuses to run inside the engine tree (its pre-flight blocks on a
# parent registry), so the auto-handoff scaffolds the first project in a sibling.
DEFAULT_PROJECT = Path.home() / "aipass-project"

# Clone can be slow on a cold network; setup.sh compiles a venv + installs deps.
_CLONE_TIMEOUT = 600
_SETUP_TIMEOUT = 1800


def _prompt(msg: str, default: str = "") -> str:
    """Simple input prompt with optional default (raises on Ctrl-C/EOF)."""
    display = f"{msg} [{default}]: " if default else f"{msg}: "
    try:
        val = input(display).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        raise KeyboardInterrupt


def _looks_like_aipass_tree(home: Path) -> bool:
    """True if `home` already holds an AIPass source tree (idempotent re-install)."""
    if not home.is_dir():
        return False
    if (home / "setup.sh").is_file():
        return True
    return bool(list(home.glob("*_REGISTRY.json")))


def _resolve_home(path: str | None, here: bool, non_interactive: bool) -> Path:
    """Decide where AIPass lives — --here / --path / $AIPASS_HOME / prompt / default."""
    if here:
        return Path.cwd().resolve()
    if path:
        return Path(path).expanduser().resolve()
    env_home = os.environ.get("AIPASS_HOME", "").strip()
    if env_home and _looks_like_aipass_tree(Path(env_home).expanduser()):
        return Path(env_home).expanduser().resolve()
    if non_interactive:
        return DEFAULT_HOME.resolve()
    raw = _prompt("Where should AIPass live?", str(DEFAULT_HOME))
    return Path(raw).expanduser().resolve()


def _clone_repo(home: Path, dry_run: bool) -> bool:
    """git clone the public AIPass repo into `home`. Returns True on success."""
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: git clone --depth 1 {REPO_URL} {home}")
        return True
    if home.exists() and any(home.iterdir()):
        warning(f"{home} exists and is not empty — pass an empty --path, or remove it first.")
        return False
    if shutil.which("git") is None:
        warning("git not found — the installer needs git to fetch AIPass. Install git and retry.")
        return False
    home.parent.mkdir(parents=True, exist_ok=True)
    console.print("[cyan]Downloading AIPass[/cyan] [dim](git clone — this can take a minute)…[/dim]")
    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(home)], timeout=_CLONE_TIMEOUT)
        if proc.returncode == 0:
            return True
        logger.warning("[install] git clone exited %s", proc.returncode)
    except subprocess.TimeoutExpired as exc:
        logger.warning("[install] git clone timed out: %s", exc)
        warning("git clone timed out.")
    return False


def _run_setup(home: Path, dry_run: bool, no_symlink: bool = False, force_symlink: bool = False) -> bool:
    """Run the repo's setup.sh (venv + editable install + hook wiring + binaries)."""
    setup = home / "setup.sh"
    # --no-init: install owns the init handoff (_handoff_to_init) — without it,
    # setup.sh's own init chain (DPLAN-0234) would scaffold the project twice.
    # --no-symlink / --force-symlink (#660) pass through to setup.sh's CLI-symlink guard.
    setup_args = ["bash", str(setup), "--no-init"]
    if no_symlink:
        setup_args.append("--no-symlink")
    if force_symlink:
        setup_args.append("--force-symlink")
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: {' '.join(setup_args)}")
        return True
    if not setup.is_file():
        warning(f"setup.sh not found at {setup} — cannot build the environment.")
        return False
    console.print("[cyan]Building environment[/cyan] [dim](venv, dependencies, hook wiring)…[/dim]")
    try:
        proc = subprocess.run(setup_args, cwd=str(home), timeout=_SETUP_TIMEOUT)
        if proc.returncode == 0:
            return True
        logger.warning("[install] setup.sh exited %s", proc.returncode)
        warning("setup.sh reported errors — see output above.")
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("[install] setup.sh failed: %s", exc)
        warning(f"setup failed: {exc}")
    return False


def _resolve_aipass_bin(home: Path) -> str | None:
    """Locate the aipass binary post-setup — PATH, then home/.venv/bin, then ~/.local/bin."""
    found = shutil.which("aipass")
    if found:
        return found
    for candidate in (home / ".venv" / "bin" / "aipass", Path.home() / ".local" / "bin" / "aipass"):
        if candidate.is_file():
            return str(candidate)
    return None


def _verify_binaries(home: Path) -> Dict[str, str | None]:
    """Report drone/aipass resolution after setup (PATH may lag in the live shell)."""
    drone = shutil.which("drone") or (
        str(home / ".venv" / "bin" / "drone") if (home / ".venv" / "bin" / "drone").is_file() else None
    )
    aipass = _resolve_aipass_bin(home)
    if drone:
        success(f"drone: {drone}")
    else:
        warning("drone not found after setup — check the setup output above.")
    if aipass:
        success(f"aipass: {aipass}")
    else:
        warning("aipass not found after setup — check the setup output above.")
    return {"drone": drone, "aipass": aipass}


def _build_install_prompt(home: Path, bins: dict) -> str:
    """Compose the authored first prompt for the post-install @aipass chat."""
    parts = [f"Fresh AIPass install completed at {home}."]
    for name, path in bins.items():
        if path:
            parts.append(f"{name}: {path}.")
    parts.append(
        "This is my first time here — what can I do with AIPass? Show me a few things to try, with the exact commands."
    )
    return " ".join(parts)


def _should_run_init(no_init: bool) -> bool:
    """Decide whether to auto-launch init. --no-init skips; default = always chain."""
    return not no_init


def _handoff_to_init(
    home: Path,
    aipass_bin: str | None,
    non_interactive: bool,
    dry_run: bool,
    project: str | None,
    run_it: bool,
) -> None:
    """Print the installed banner, then (optionally) launch init for a first project.

    `aipass init` scaffolds a *new* project and refuses to run inside the engine
    tree (pre-flight blocks on a parent registry), so init targets a sibling
    directory (``--project`` or DEFAULT_PROJECT), never ``home``. When install ran
    headless, init is launched headless too so the whole chain stays non-blocking.
    """
    console.print()
    success(f"AIPass is installed at {home}")
    console.print()
    console.print("  [cyan]drone systems[/cyan]     [dim]# list every agent[/dim]")
    console.print("  [cyan]aipass doctor[/cyan]     [dim]# check system health[/dim]")
    console.print("  [cyan]aipass init run[/cyan]   [dim]# scaffold your first project on AIPass[/dim]")
    console.print()

    if not run_it:
        console.print("[dim]Run 'aipass init run' in a fresh directory to start your first project.[/dim]")
        return

    project_dir = _resolve_project_dir(project, non_interactive)
    if project_dir is None:
        return

    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would launch: aipass init run in {project_dir}")
        return
    if not aipass_bin:
        warning("Can't find the aipass binary yet — open a new terminal and run 'aipass init run'.")
        return

    project_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[cyan]Launching guided setup[/cyan] [dim]in {project_dir}…[/dim]")
    cmd = [aipass_bin, "init", "run"]
    if non_interactive:
        cmd.append("--non-interactive")
    try:
        subprocess.run(cmd, cwd=str(project_dir))
    except (FileNotFoundError, OSError) as exc:
        logger.warning("[install] could not launch init: %s", exc)
        warning(f"Could not launch init: {exc}. Run 'aipass init run' in {project_dir} yourself.")


def _check_and_fix_owner(home: Path) -> None:
    """Run sync-registry --check; if issues found, auto-heal with --fix."""
    try:
        check_proc = subprocess.run(
            ["drone", "@spawn", "sync-registry", "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(home),
        )
        if check_proc.returncode != 0:
            warning("Owner/identity issues detected — auto-repairing…")
            fix_proc = subprocess.run(
                ["drone", "@spawn", "sync-registry", "--fix"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(home),
            )
            if fix_proc.returncode == 0:
                success("Registry owner/identity reconciled.")
            else:
                logger.warning("[install] sync-registry --fix exit %s", fix_proc.returncode)
        else:
            success("Owner/identity OK.")
    except FileNotFoundError:
        logger.info("[install] drone not on PATH — skipping owner check")
    except subprocess.TimeoutExpired:
        logger.warning("[install] sync-registry timed out during install")
    except Exception as exc:
        logger.warning("[install] owner check skipped: %s", exc)


def _anchor_project_dir(raw: str) -> Path:
    """Resolve typed project-dir input — bare/relative names anchor to home, never CWD.

    CWD during install is the cloned engine repo, not the user's home — a bare
    name like ``dockertest`` must become ``~/dockertest``, not ``<engine>/dockertest``
    (which trips init's own-tree preflight guard).
    """
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (DEFAULT_PROJECT.parent / candidate).resolve()


def _resolve_project_dir(project: str | None, non_interactive: bool) -> Path | None:
    """Resolve the first-project directory — --project / prompt / DEFAULT_PROJECT."""
    if project:
        return Path(project).expanduser().resolve()
    if non_interactive:
        return DEFAULT_PROJECT.resolve()
    console.print(
        f"  [dim]Enter = use the path shown below, or type a name to create it under {DEFAULT_PROJECT.parent}[/dim]"
    )
    try:
        raw = _prompt("Project directory for your first project", str(DEFAULT_PROJECT))
    except KeyboardInterrupt:
        logger.info("[install] init handoff cancelled by user")
        console.print()
        return None
    return _anchor_project_dir(raw)


def run_install(
    non_interactive: bool = False,
    path: str | None = None,
    here: bool = False,
    dry_run: bool = False,
    with_init: bool = False,
    no_init: bool = False,
    project: str | None = None,
    no_symlink: bool = False,
    force_symlink: bool = False,
) -> int:
    """Run the 4-step one-command install. Returns 0 on success, 1 on failure."""
    console.print()
    console.print("[bold cyan]AIPass — one-command install[/bold cyan]")
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] No clone, no setup, no launch — walking the steps only.")

    # Step 1 — resolve + fetch the framework home
    console.print()
    console.print(render_step_header(1, TOTAL_STEPS, "Preparing AIPass home"))
    try:
        home = _resolve_home(path, here, non_interactive)
    except KeyboardInterrupt:
        logger.info("[install] cancelled at home resolution by user")
        console.print()
        warning("Cancelled.")
        return 1
    console.print(f"  Home: [cyan]{home}[/cyan]")

    if is_throwaway_path(home):
        warning(
            f"REFUSED: '{home}' is a temporary/scratchpad path. "
            "Installing here would hijack the machine-wide AIPASS_HOME. "
            "Use a permanent directory, or pass --force-global-home to override."
        )
        if "--force-global-home" not in sys.argv:
            return 1
        logger.warning("[install] --force-global-home override: proceeding with throwaway home %s", home)

    if _looks_like_aipass_tree(home):
        success(f"AIPass already present at {home} — skipping download")
    elif not _clone_repo(home, dry_run):
        warning("Could not fetch AIPass — aborting install.")
        return 1
    else:
        success(f"AIPass downloaded to {home}")

    # Step 2 — build the environment via setup.sh
    console.print()
    console.print(render_step_header(2, TOTAL_STEPS, "Building environment"))
    if not _run_setup(home, dry_run, no_symlink=no_symlink, force_symlink=force_symlink):
        warning("Environment build failed — aborting install.")
        return 1
    success("Environment ready")

    # Step 3 — verify the binaries landed
    console.print()
    console.print(render_step_header(3, TOTAL_STEPS, "Verifying install"))
    bins = _verify_binaries(home) if not dry_run else {"drone": "dry-run", "aipass": "dry-run"}

    # Owner/identity retro-trigger — check and self-heal via spawn
    if not dry_run:
        _check_and_fix_owner(home)

    # Step 4 — hand off into init (or print next steps)
    console.print()
    console.print(render_step_header(4, TOTAL_STEPS, "First project"))
    run_it = _should_run_init(no_init)
    _handoff_to_init(home, bins.get("aipass"), non_interactive, dry_run, project, run_it)

    # Log BEFORE exec — launch_inline replaces the process and never returns
    json_handler.log_operation(
        "aipass_install",
        {"home": str(home), "non_interactive": non_interactive, "dry_run": dry_run, "init": run_it},
    )

    # Install-to-chat handoff — launch @aipass concierge in same terminal
    if run_it and not dry_run and sys.stdin.isatty():
        prompt = _build_install_prompt(home, bins)
        aipass_branch = str(Path(__file__).resolve().parents[2])
        console.print()
        console.print("[dim]Launching the AIPass concierge — Ctrl-C to stay in the shell[/dim]")
        console.print()
        from aipass.aipass.apps.handlers.handoff_platform import launch_inline

        launch_inline("claude", prompt, aipass_branch)

    return 0


def print_help() -> None:
    """Print usage help for the install command."""
    console.print()
    console.print("[bold cyan]aipass install[/bold cyan] — one-command bootstrap of AIPass")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass install[/green]                      [dim]# interactive, then launches init[/dim]")
    console.print("  [green]aipass install --non-interactive[/green]    [dim]# CI/headless (~/AIPass), no init[/dim]")
    console.print("  [green]aipass install --path DIR[/green]           [dim]# explicit home[/dim]")
    console.print("  [green]aipass install --here[/green]               [dim]# install into current dir[/dim]")
    console.print("  [green]aipass install --no-init[/green]            [dim]# install only, skip init[/dim]")
    console.print("  [green]aipass install --with-init[/green]          [dim]# force init even when headless[/dim]")
    console.print("  [green]aipass install --no-symlink[/green]         [dim]# skip global CLI symlinks[/dim]")
    console.print("  [green]aipass install --force-symlink[/green]      [dim]# repoint from another install[/dim]")
    console.print("  [green]aipass install --project DIR[/green]        [dim]# where the first project scaffolds[/dim]")
    console.print("  [green]aipass install --force-global-home[/green]  [dim]# allow install into /tmp (unsafe)[/dim]")
    console.print("  [green]aipass install --dry-run[/green]            [dim]# walk steps, no side effects[/dim]")
    console.print()
    console.print("[yellow]STEPS:[/yellow] resolve home -> fetch -> setup.sh -> verify -> launch init")
    console.print()


def print_introspection() -> None:
    """Show module info for install."""
    console.print()
    console.print("[bold cyan]install Module[/bold cyan]")
    console.print("One-command bootstrap: clone + setup.sh + verify + handoff")
    console.print()
    console.print(f"[dim]Default home: {DEFAULT_HOME}[/dim]")
    console.print(f"[dim]Source: {REPO_URL}[/dim]")
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Route install subcommands. Returns True if handled, False otherwise."""
    if command != COMMAND:
        return False

    if args and args[0] in ("--help", "-h", "help"):
        print_help()
        return True
    if args and args[0] in ("--info", "info"):
        print_introspection()
        return True

    # `aipass install` runs directly; `run` is accepted as an optional verb.
    run_args = args[1:] if args and args[0] == "run" else args

    def _flag_value(flag: str) -> str | None:
        """Extract the value after a named flag, or None if absent."""
        if flag not in run_args:
            return None
        idx = run_args.index(flag)
        return run_args[idx + 1] if idx + 1 < len(run_args) else None

    non_interactive = "--non-interactive" in run_args
    dry_run = "--dry-run" in run_args
    here = "--here" in run_args
    with_init = "--with-init" in run_args
    no_init = "--no-init" in run_args
    no_symlink = "--no-symlink" in run_args
    force_symlink = "--force-symlink" in run_args
    path = _flag_value("--path")
    project = _flag_value("--project")

    result = run_install(
        non_interactive=non_interactive,
        path=path,
        here=here,
        dry_run=dry_run,
        with_init=with_init,
        no_init=no_init,
        project=project,
        no_symlink=no_symlink,
        force_symlink=force_symlink,
    )
    json_handler.log_operation(
        "install_run",
        {"non_interactive": non_interactive, "dry_run": dry_run, "with_init": with_init, "exit": result},
    )
    sys.exit(result)
