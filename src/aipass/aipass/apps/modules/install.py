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
    4. End in a conversation: the @aipass concierge opens in this terminal with the
       install report in hand (interactive default; --no-chat to skip). Project
       creation is NOT part of install — the concierge points users at
       `aipass init run` for that, whenever they're ready.

Each step prints a Step k/N progress header. Streaming subprocesses (git, setup.sh)
show a header + their own output + a result line — no spinner (the two renderers
fight, per ui/progress.activity_spinner).

Usage:
    aipass install                       # interactive, ends in a welcome chat
    aipass install --non-interactive     # CI/headless (~/AIPass), no chat
    aipass install --no-chat             # install the engine only, skip the chat
    aipass install --path ~/tools/aipass # explicit home
    aipass install --here                # install into the current directory
    aipass install --chat-only           # skip the build, just the welcome chat
                                          # (used by setup.sh's own tail)
    aipass install --dry-run             # walk all steps, no clone/setup/launch
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from aipass.cli.apps.modules import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.init.bootstrap import is_throwaway_path
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import render_step_header

COMMAND = "install"
TOTAL_STEPS = 4
REPO_URL = "https://github.com/AIOSAI/AIPass.git"
DEFAULT_HOME = Path.home() / "AIPass"

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
    # --no-chat: install owns the welcome-chat ending (_end_in_chat) — without it,
    # setup.sh's own chat ending would launch (and exit-replace this process) twice.
    # --no-symlink / --force-symlink (#660) pass through to setup.sh's CLI-symlink guard.
    setup_args = ["bash", str(setup), "--no-chat"]
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


def _registry_user_name(home: Path) -> str:
    """Best-effort read of the user's name setup.sh stored in AIPASS_REGISTRY.json."""
    data = json_handler.load_path(home / "AIPASS_REGISTRY.json")
    if not data:
        return ""
    return str(data.get("metadata", {}).get("user", "") or "").strip()


def _build_install_prompt(home: Path, bins: dict, doctor_action_items: list[str] | None = None) -> str:
    """Compose the authored first prompt for the post-install @aipass chat.

    Enriched with whatever setup.sh learned about the machine (round-2 install
    UX, a0f2351e/43ff5873): the user's name (persisted in the registry, so it
    survives independent of this one run) and any ACTION NEEDED items / a
    skipped git identity, passed through env vars by setup.sh's own
    ``--chat-only`` handoff. Also enriched with the doctor preflight verdict
    (round-2 addendum 2, Patrick's ruling: doctor runs before hello, and a
    still-broken hook wiring is P1 — passed in as ``doctor_action_items`` so
    it leads the machine-still-needs list). Composition stays here, in this
    one function.
    """
    parts = [f"Fresh AIPass install completed at {home}."]
    for name, path in bins.items():
        if path:
            parts.append(f"{name}: {path}.")

    user_name = _registry_user_name(home)
    if user_name:
        parts.append(f"The user's name is {user_name} — greet them by name.")

    if os.environ.get("AIPASS_IDENTITY_SKIPPED") == "1":
        parts.append("Git identity was skipped during setup — commits will fail until it's configured.")

    action_needed = list(doctor_action_items or [])
    action_needed += [line for line in os.environ.get("AIPASS_ACTION_NEEDED", "").splitlines() if line.strip()]
    if action_needed:
        parts.append("The machine still needs: " + "; ".join(action_needed) + ".")

    parts.append(
        "This is my first time here — what can I do with AIPass? Show me a few things to try, with the exact commands."
    )
    return " ".join(parts)


def _print_next_steps(home: Path) -> None:
    """Print the installed banner + a few commands to try next."""
    console.print()
    success(f"AIPass is installed at {home}")
    console.print()
    console.print("  [cyan]drone systems[/cyan]     [dim]# list every agent[/dim]")
    console.print("  [cyan]aipass doctor[/cyan]     [dim]# check system health[/dim]")
    console.print("  [cyan]aipass init run[/cyan]   [dim]# scaffold your first project on AIPass[/dim]")
    console.print()


def _ask_permission_mode() -> str:
    """Ask how the concierge session should run. Returns a launch flag_variant.

    The repo ships ``defaultMode: acceptEdits`` in ``.claude/settings.json``, so
    a plain launch asks before system-changing commands. The stranger deserves
    the choice up front instead of inheriting it silently; any non-answer
    (Enter, Ctrl-C, EOF) keeps the safe default.
    """
    console.print("How should the concierge session run?")
    console.print("  [cyan]1.[/cyan] Accept edits [dim](default — asks before system-changing commands)[/dim]")
    console.print("  [cyan]2.[/cyan] Bypass permissions [dim](full autonomy — no permission prompts)[/dim]")
    try:
        choice = _prompt("Choice", "1")
    except KeyboardInterrupt:
        logger.info("[install] permission-mode selector cancelled — keeping accept-edits default")
        console.print()
        return "default"
    return "skip-permissions" if choice.strip() == "2" else "default"


def _run_doctor_preflight() -> list[str]:
    """Run 'aipass doctor --fix' before the concierge says hello (Patrick's ruling,
    round-2 addendum 2): heals what it can, then reports what's still broken.

    Hook wiring is P1 — a still-broken result is printed as a loud, highlighted
    top line, and returned so ``_build_install_prompt`` leads with it too.
    """
    from aipass.aipass.apps.modules.doctor import run_doctor_preflight

    try:
        _error_count, hook_action_items = run_doctor_preflight(fix=True)
    except Exception as exc:
        logger.warning("[install] doctor preflight crashed: %s", exc)
        warning("Health check could not run — run 'aipass doctor --fix' manually.")
        return ["doctor preflight crashed — run 'aipass doctor --fix' manually and check hook wiring"]

    if hook_action_items:
        error("ACTION NEEDED — hooks are not fully wired:")
        for item in hook_action_items:
            console.print(f"  • {item}")
        console.print()

    return hook_action_items


def _end_in_chat(home: Path, bins: dict, dry_run: bool, no_chat: bool) -> None:
    """End the install in a conversation with the @aipass concierge (TTY only).

    Project creation is NOT part of install — ``aipass init run`` stays a
    separate, later step; the concierge points users there when they're ready.
    ``launch_inline`` replaces this process and never returns when it fires.
    """
    _print_next_steps(home)

    if no_chat:
        console.print("[dim]Skipped the welcome chat (--no-chat). Run 'claude' in this directory anytime.[/dim]")
        return
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] would launch the AIPass concierge welcome chat.")
        return
    if not sys.stdin.isatty():
        console.print(f"[dim]Run 'claude' in {home} when you're ready to meet the AIPass concierge.[/dim]")
        return

    hook_action_items = _run_doctor_preflight()

    console.print()
    flag_variant = _ask_permission_mode()
    prompt = _build_install_prompt(home, bins, doctor_action_items=hook_action_items)
    aipass_branch = str(Path(__file__).resolve().parents[2])
    console.print()
    console.print("[dim]Launching the AIPass concierge — Ctrl-C to stay in the shell[/dim]")
    console.print()
    from aipass.aipass.apps.handlers.handoff_platform import launch_inline

    launch_inline("claude", prompt, aipass_branch, flag_variant)


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


def run_chat_only(
    non_interactive: bool = False,
    path: str | None = None,
    here: bool = False,
    dry_run: bool = False,
    no_chat: bool = False,
) -> int:
    """End-in-chat only — no clone/setup/verify. Used by setup.sh's own tail.

    setup.sh already built the environment in bash; this just resolves the
    home it built and reuses ``_build_install_prompt``/``launch_inline`` so
    the welcome chat is composed in exactly one place.
    """
    try:
        home = _resolve_home(path, here, non_interactive)
    except KeyboardInterrupt:
        logger.info("[install] chat-only handoff cancelled by user")
        console.print()
        warning("Cancelled.")
        return 1
    bins = _verify_binaries(home) if not dry_run else {"drone": "dry-run", "aipass": "dry-run"}
    _end_in_chat(home, bins, dry_run, no_chat)
    return 0


def run_install(
    non_interactive: bool = False,
    path: str | None = None,
    here: bool = False,
    dry_run: bool = False,
    no_chat: bool = False,
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

    # Step 4 — end in a welcome chat (no project creation — see module docstring)
    console.print()
    console.print(render_step_header(4, TOTAL_STEPS, "Welcome"))

    # Log BEFORE exec — launch_inline (inside _end_in_chat) replaces the process
    # and never returns when it fires.
    json_handler.log_operation(
        "aipass_install",
        {"home": str(home), "non_interactive": non_interactive, "dry_run": dry_run, "chat": not no_chat},
    )

    _end_in_chat(home, bins, dry_run, no_chat)
    return 0


def print_help() -> None:
    """Print usage help for the install command."""
    console.print()
    console.print("[bold cyan]aipass install[/bold cyan] — one-command bootstrap of AIPass")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass install[/green]                      [dim]# interactive, ends in a chat[/dim]")
    console.print("  [green]aipass install --non-interactive[/green]    [dim]# CI/headless (~/AIPass), no chat[/dim]")
    console.print("  [green]aipass install --path DIR[/green]           [dim]# explicit home[/dim]")
    console.print("  [green]aipass install --here[/green]               [dim]# install into current dir[/dim]")
    console.print("  [green]aipass install --no-chat[/green]            [dim]# install only, skip the chat[/dim]")
    console.print("  [green]aipass install --no-symlink[/green]         [dim]# skip global CLI symlinks[/dim]")
    console.print("  [green]aipass install --force-symlink[/green]      [dim]# repoint from another install[/dim]")
    console.print("  [green]aipass install --chat-only[/green]          [dim]# skip the build, just the chat[/dim]")
    console.print("  [green]aipass install --force-global-home[/green]  [dim]# allow install into /tmp (unsafe)[/dim]")
    console.print("  [green]aipass install --dry-run[/green]            [dim]# walk steps, no side effects[/dim]")
    console.print()
    console.print("[yellow]STEPS:[/yellow] resolve home -> fetch -> setup.sh -> verify -> welcome chat")
    console.print()
    console.print("[dim]Project creation isn't part of install — run 'aipass init run' for that, whenever ready.[/dim]")
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

    if wants_help(args):
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
    no_chat = "--no-chat" in run_args
    chat_only = "--chat-only" in run_args
    no_symlink = "--no-symlink" in run_args
    force_symlink = "--force-symlink" in run_args
    path = _flag_value("--path")

    if chat_only:
        result = run_chat_only(
            non_interactive=non_interactive,
            path=path,
            here=here,
            dry_run=dry_run,
            no_chat=no_chat,
        )
    else:
        result = run_install(
            non_interactive=non_interactive,
            path=path,
            here=here,
            dry_run=dry_run,
            no_chat=no_chat,
            no_symlink=no_symlink,
            force_symlink=force_symlink,
        )
    json_handler.log_operation(
        "install_run",
        {"non_interactive": non_interactive, "dry_run": dry_run, "chat_only": chat_only, "exit": result},
    )
    sys.exit(result)
