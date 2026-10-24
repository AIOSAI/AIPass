# =================== AIPass ====================
# Name: install.py
# Description: aipass install — one-command PyPI bootstrap (clone + setup + handoff)
# Version: 1.5.2
# Created: 2026-07-05
# Modified: 2026-10-24
# =============================================

"""
aipass install — one-command bootstrap of the whole framework
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import urlsplit, urlunsplit

from aipass.cli.apps.modules import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.baud import LATEST, FetchError, validate_tag
from aipass.aipass.apps.handlers.init.bootstrap import is_throwaway_path
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.ui.progress import render_step_header

COMMAND = "install"
TOTAL_STEPS = 5
REPO_URL = "https://github.com/AIOSAI/AIPass.git"
_URL_PREFIXES = ("https://", "http://", "ssh://", "git://", "file://", "git@")
DEFAULT_HOME = Path.home() / "AIPass"

# Clone can be slow on a cold network; setup.sh compiles a venv + installs deps.
_CLONE_TIMEOUT = 600
_SETUP_TIMEOUT = 1800
# Exported to setup.sh under --non-interactive, for it to read before its own [ -t 0 ].
NON_INTERACTIVE_ENV = "AIPASS_NON_INTERACTIVE"


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
    return (home / "setup.sh").is_file() and (home / "AIPASS_REGISTRY.json").is_file()


def _redact_url(url: str) -> str:
    """`url` with any user:token@ userinfo removed, safe to print and log."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def _resolve_home(path: str | None, here: bool, non_interactive: bool) -> Path:
    """Decide where AIPass lives — --here / --path / $AIPASS_HOME / cwd / prompt / default."""
    if here:
        return Path.cwd().resolve()
    if path:
        return Path(path).expanduser().resolve()
    env_home = os.environ.get("AIPASS_HOME", "").strip()
    if env_home and _looks_like_aipass_tree(Path(env_home).expanduser()):
        return Path(env_home).expanduser().resolve()
    if non_interactive:
        # The cwd counts only when it is an AIPass tree: a headless run from an
        # unrelated directory still lands on DEFAULT_HOME.
        cwd = Path.cwd().resolve()
        if _looks_like_aipass_tree(cwd):
            logger.info("[install] non-interactive: cwd is an AIPass tree, using %s", cwd)
            return cwd
        return DEFAULT_HOME.resolve()
    raw = _prompt("Where should AIPass live?", str(DEFAULT_HOME))
    return Path(raw).expanduser().resolve()


def install_lock_path(home: Path) -> Path:
    """The lock guarding one install of `home`.

    Lives in the parent: on a fresh machine `home` does not exist until the clone lands.
    """
    return home.parent / f".{home.name}.install.lock"


def _fire_lock_removed(path: Path, reason: str) -> None:
    """Fire the lock-removal trigger event, ignoring an absent trigger branch."""
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("file_deleted", path=str(path), reason=reason)
    except ImportError as exc:
        logger.warning("[install] trigger unavailable for file_deleted event: %s", exc)


def _lock_holder_pid(lock: Path) -> str:
    """The pid recorded in `lock`, or "" when it is unreadable or malformed."""
    try:
        holder = lock.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("[install] lock %s unreadable: %s", lock, exc)
        return ""
    first = holder.split()[0] if holder else ""
    return first if first.isdigit() else ""


def _clear_stale_lock(lock: Path, holder_pid: str) -> bool:
    """Remove a lock whose holder is gone. True when the lock is now free."""
    logger.warning("[install] stale lock from dead pid %s, taking over", holder_pid)
    warning(f"Clearing a stale install lock left by pid {holder_pid}: {lock}")
    try:
        lock.unlink()
    except FileNotFoundError:
        logger.info("[install] stale lock %s vanished before takeover", lock)
        return True
    except OSError as exc:
        logger.warning("[install] could not clear stale lock: %s", exc)
        error(f"REFUSED: could not clear the stale install lock at {lock}: {exc}")
        return False
    _fire_lock_removed(lock, "stale_install_lock_cleared")
    return True


def acquire_install_lock(home: Path, _retry: bool = True) -> Path | None:
    """Claim the install lock for `home`, or return None if another run holds it.

    A lock whose pid is proven gone is taken over, announced: a crashed install
    must not wedge the machine. An unknown holder is never stolen from.
    """
    lock = install_lock_path(home)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        logger.info("[install] install lock %s already held, inspecting holder", lock)
        holder_pid = _lock_holder_pid(lock)
        # Only a holder PROVEN dead (False) is taken over; unknown (None) is left alone.
        alive = _pid_alive(int(holder_pid)) if holder_pid else None
        if _retry and alive is False:
            if not _clear_stale_lock(lock, holder_pid):
                return None
            # One takeover only, so two racing installs cannot ping-pong clearing each other.
            return acquire_install_lock(home, _retry=False)
        holder = f", held by pid {holder_pid}" if holder_pid else ""
        if holder_pid and alive is None:
            holder += f" - could not tell whether pid {holder_pid} is alive"
        error(
            f"REFUSED: another install of {home} is already running "
            f"(lock: {lock}{holder}). "
            "Wait for it to finish, or delete the lock if you know it is dead."
        )
        return None
    except OSError as exc:
        logger.warning("[install] could not create lock %s: %s", lock, exc)
        error(f"REFUSED: could not create the install lock at {lock}: {exc}")
        return None

    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    return lock


def _pid_alive(
    pid: int,
    platform_name: str | None = None,
    runner: Callable[..., Any] | None = None,
) -> bool | None:
    """True when `pid` names a live process, False when it is gone, on POSIX and on Windows.

    ``platform_name`` and ``runner`` are test seams, defaulting at call time.
    None when the Windows probe fails: the caller must not steal the lock on it.
    Never os.kill(pid, 0) on Windows: it terminates the target whatever the signal.
    """
    run = subprocess.run if runner is None else runner
    if (platform_name is None and sys.platform == "win32") or platform_name == "win32":
        try:
            out = run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("[install] tasklist probe for pid %s failed: %s", pid, exc)
            return None  # unknown: the caller never steals on it
        return str(pid) in out.stdout

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def release_install_lock(lock: Path | None) -> None:
    """Drop the install lock, never raising — a failed release must not mask the install."""
    if lock is None:
        return
    try:
        lock.unlink()
    except FileNotFoundError:
        logger.info("[install] lock %s already gone at release", lock)
        return
    except OSError as exc:
        logger.warning("[install] could not release lock %s: %s", lock, exc)
        return
    _fire_lock_removed(lock, "install_lock_released")


def _announce_cloned_branch(home: Path) -> None:
    """Print which branch actually landed. Never raises — naming is a courtesy.

    The clone takes the repo's default branch, not the one the caller stands in;
    the name is read back from the clone so it cannot drift.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(home),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[install] could not read cloned branch: %s", exc)
        return
    branch = (proc.stdout or "").strip()
    if proc.returncode != 0 or not branch:
        logger.info("[install] cloned branch unreadable (exit %s)", proc.returncode)
        return
    console.print(f"  [dim]branch:[/dim] [cyan]{branch}[/cyan] [dim](the repo default)[/dim]")


class SourceRefused(ValueError):
    """--source named no checkout. The message names the path and is safe to print."""


def _resolve_source(source: str | None) -> str:
    """What to fetch: REPO_URL by default, a URL as given, a local checkout as its file:// URI.

    A local path goes through file:// so ``--depth 1`` holds: only the committed HEAD
    crosses, never the working tree. A bad value raises, never falls back to the public repo.
    """
    if source is None:
        return REPO_URL
    if not source:
        raise SourceRefused("it needs a path or a URL")
    if source.startswith(_URL_PREFIXES):
        return source
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise SourceRefused(f"{path} does not exist")
    if not path.is_dir():
        raise SourceRefused(f"{path} is not a directory")
    if not (path / ".git").exists():
        raise SourceRefused(f"{path} is not a repository (no .git)")
    return path.as_uri()


def _clone_repo(
    home: Path, dry_run: bool, which: Callable[[str], str | None] | None = None, source: str = REPO_URL
) -> bool:
    """git clone ``source`` (the public AIPass repo by default, _resolve_source) into `home`. True on success.

    *which* is a test seam: ``shutil.which`` when None, resolved at call time.
    """
    if which is None:
        which = shutil.which
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: git clone --depth 1 {_redact_url(source)} {home}")
        return True
    if home.exists() and any(home.iterdir()):
        warning(f"{home} exists and is not empty — pass an empty --path, or remove it first.")
        return False
    if which("git") is None:
        warning("git not found — the installer needs git to fetch AIPass. Install git and retry.")
        return False
    home.parent.mkdir(parents=True, exist_ok=True)
    console.print("[cyan]Downloading AIPass[/cyan] [dim](git clone — this can take a minute)…[/dim]")
    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", source, str(home)], timeout=_CLONE_TIMEOUT)
        if proc.returncode == 0:
            _announce_cloned_branch(home)
            return True
        # The user's line first: an unwritable log home must not swallow the last word.
        warning(f"git clone failed (exit {proc.returncode}) — git's own message is above. Check the network and retry.")
        logger.warning("[install] git clone exited %s", proc.returncode)
    except subprocess.TimeoutExpired as exc:
        warning("git clone timed out.")
        logger.warning("[install] git clone timed out after %ss", exc.timeout)
    return False


def _run_setup(
    home: Path, dry_run: bool, no_symlink: bool = False, force_symlink: bool = False, non_interactive: bool = False
) -> bool:
    """Run the repo's setup.sh (venv + editable install + hook wiring + binaries).

    ``non_interactive`` closes stdin and exports AIPASS_NON_INTERACTIVE=1: install.sh
    hands this process the user's tty, so setup.sh's ``[ -t 0 ]`` alone would still prompt.
    """
    setup = home / "setup.sh"
    # --no-chat: install owns the chat ending; setup.sh's own would launch a second one.
    setup_args = ["bash", str(setup), "--no-chat"]
    if no_symlink:
        setup_args.append("--no-symlink")
    if force_symlink:
        setup_args.append("--force-symlink")
    closed = " (stdin closed, AIPASS_NON_INTERACTIVE=1)" if non_interactive else ""
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: {' '.join(setup_args)}{closed}")
        return True
    if not setup.is_file():
        warning(f"setup.sh not found at {setup} — cannot build the environment.")
        return False
    console.print("[cyan]Building environment[/cyan] [dim](venv, dependencies, hook wiring)…[/dim]")
    quiet = {"stdin": subprocess.DEVNULL, "env": {**os.environ, NON_INTERACTIVE_ENV: "1"}} if non_interactive else {}
    try:
        proc = subprocess.run(setup_args, cwd=str(home), timeout=_SETUP_TIMEOUT, **quiet)
        if proc.returncode == 0:
            return True
        warning("setup.sh reported errors — see output above.")
        logger.warning("[install] setup.sh exited %s", proc.returncode)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        warning(f"setup failed: {exc}")
        logger.warning("[install] setup.sh failed: %s", exc)
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
    data = json_handler.read_json(home / "AIPASS_REGISTRY.json")
    if not data:
        return ""
    return str(data.get("metadata", {}).get("user", "") or "").strip()


def _build_install_prompt(home: Path, bins: dict, doctor_action_items: list[str] | None = None) -> str:
    """Compose the authored first prompt for the post-install @aipass chat.

    The env vars come from setup.sh's ``--chat-only`` handoff; ``doctor_action_items``
    lead the still-needs list because broken hook wiring is P1.
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

    Any non-answer (Enter, Ctrl-C, EOF) keeps the repo's acceptEdits default.
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
    """Run 'aipass doctor --fix' before the concierge says hello: heal, then report what's still broken.

    Broken hook wiring is printed loud and returned so the prompt leads with it.
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


def _end_in_chat(
    home: Path, bins: dict, dry_run: bool, no_chat: bool, last_print: Callable[[], None] | None = None
) -> None:
    """End the install in a conversation with the @aipass concierge (TTY only).

    ``launch_inline`` replaces this process and never returns; ``last_print`` (the
    phone print) is the last output on every ending, so each calls it before a launch.
    """
    _print_next_steps(home)
    finish = last_print if last_print is not None else (lambda: None)

    # Every early return skips the preflight below, so each names the command that runs it.
    if no_chat:
        console.print("[dim]Skipped the welcome chat (--no-chat). Run 'claude' in this directory anytime.[/dim]")
        warning("Health check skipped with the chat — run 'aipass doctor --fix' to check hook wiring.")
        finish()
        return
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] would launch the AIPass concierge welcome chat.")
        console.print("[yellow]\\[dry-run][/yellow] would run the 'aipass doctor --fix' health check.")
        finish()
        return
    if not sys.stdin.isatty():
        console.print(f"[dim]Run 'claude' in {home} when you're ready to meet the AIPass concierge.[/dim]")
        warning("Health check skipped (no TTY) — run 'aipass doctor --fix' to check hook wiring.")
        finish()
        return

    hook_action_items = _run_doctor_preflight()

    console.print()
    flag_variant = _ask_permission_mode()
    prompt = _build_install_prompt(home, bins, doctor_action_items=hook_action_items)
    aipass_branch = str(Path(__file__).resolve().parents[2])
    finish()
    console.print()
    console.print("[dim]Launching the AIPass concierge — Ctrl-C to stay in the shell[/dim]")
    console.print()
    from aipass.aipass.apps.handlers.handoff_platform import launch_inline

    launch_inline("claude", prompt, aipass_branch, flag_variant)


def _install_phone_face(dry_run: bool, no_baud: bool, baud_tag: str = LATEST) -> bool:
    """The Phone face step: best-effort, so its outcome never fails the install."""
    if no_baud:
        console.print("[dim]Skipped the phone face and baud-cli (--no-baud). Install later: aipass baud install[/dim]")
        return False
    from aipass.aipass.apps.modules.baud import install_best_effort

    return install_best_effort(dry_run=dry_run, tag=baud_tag)


def _phone_print(dry_run: bool, face_installed: bool, non_interactive: bool = False) -> Callable[[], None] | None:
    """The phone facts read now; the bind, the boot unit, the server and the print run last (FPLAN-0642, DPLAN-0407).

    ``non_interactive`` never mints a pairing code: install.sh owns the terminal and the pair.
    """
    if not face_installed:
        return None
    from aipass.aipass.apps.modules.baud import finish_phone, phone_readiness

    ready = phone_readiness(dry_run=dry_run)
    return lambda: finish_phone(ready, dry_run=dry_run, non_interactive=non_interactive)


def _check_and_fix_owner(home: Path, drone_bin: str = "drone") -> None:
    """Run sync-registry --check in `home`; if issues found, auto-heal with --fix."""
    try:
        check_proc = subprocess.run(
            [drone_bin, "@spawn", "sync-registry", "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(home),
        )
        if check_proc.returncode != 0:
            warning("Owner/identity issues detected — auto-repairing…")
            fix_proc = subprocess.run(
                [drone_bin, "@spawn", "sync-registry", "--fix"],
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

    Reuses ``_end_in_chat`` so the welcome chat is composed in exactly one place.
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
    no_baud: bool = False,
    baud_tag: str = LATEST,
    source: str | None = None,
) -> int:
    """Run the 5-step one-command install. Returns 0 on success, 1 on failure.

    A bad ``baud_tag`` or ``source`` is refused with 2 (bad usage) before anything is cloned.
    """
    console.print()
    console.print("[bold cyan]AIPass — one-command install[/bold cyan]")
    if dry_run:
        console.print("[yellow]\\[dry-run][/yellow] No clone, no setup, no launch — walking the steps only.")
    try:
        validate_tag(baud_tag)
    except FetchError as exc:
        logger.warning("[install] --baud-tag refused before the clone: %s", exc)
        error(f"--baud-tag refused: {exc}")
        return 2
    try:
        clone_from = _resolve_source(source)
    except SourceRefused as exc:
        logger.warning("[install] --source refused before the clone: %s", exc)
        error(f"--source refused: {exc}")
        return 2

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
    if source is not None:
        console.print(f"  Source: [cyan]{_redact_url(clone_from)}[/cyan]")

    if is_throwaway_path(home):
        warning(
            f"REFUSED: '{home}' is a temporary/scratchpad path. "
            "Installing here would hijack the machine-wide AIPASS_HOME. "
            "Use a permanent directory, or pass --force-global-home to override."
        )
        if "--force-global-home" not in sys.argv:
            return 1
        logger.warning("[install] --force-global-home override: proceeding with throwaway home %s", home)

    # Released before the chat: launch_inline replaces this process, so a later
    # release never runs and wedges the home. A dry run writes nothing and takes no lock.
    install_lock = None if dry_run else acquire_install_lock(home)
    if install_lock is None and not dry_run:
        return 1

    try:
        if _looks_like_aipass_tree(home):
            success(f"AIPass already present at {home} — skipping download")
        elif not _clone_repo(home, dry_run, source=clone_from):
            warning("Could not fetch AIPass — aborting install.")
            return 1
        else:
            success(f"AIPass downloaded to {home}")

        console.print()
        console.print(render_step_header(2, TOTAL_STEPS, "Building environment"))
        if not _run_setup(
            home, dry_run, no_symlink=no_symlink, force_symlink=force_symlink, non_interactive=non_interactive
        ):
            warning("Environment build failed — aborting install.")
            return 1
        success("Environment ready")

        console.print()
        console.print(render_step_header(3, TOTAL_STEPS, "Verifying install"))
        bins = _verify_binaries(home) if not dry_run else {"drone": "dry-run", "aipass": "dry-run"}

        if not dry_run:
            _check_and_fix_owner(home, bins["drone"] or "drone")
    finally:
        release_install_lock(install_lock)

    console.print()
    console.print(render_step_header(4, TOTAL_STEPS, "Phone face + baud-cli"))
    face_installed = _install_phone_face(dry_run, no_baud, baud_tag)
    phone_print = _phone_print(dry_run, face_installed, non_interactive)

    console.print()
    console.print(render_step_header(5, TOTAL_STEPS, "Welcome"))

    # Log before _end_in_chat: its launch_inline replaces the process and never returns.
    json_handler.log_operation(
        "aipass_install",
        {
            "home": str(home),
            "non_interactive": non_interactive,
            "dry_run": dry_run,
            "chat": not no_chat,
            "phone_face": face_installed,
            "baud_tag": baud_tag,
        },
    )

    _end_in_chat(home, bins, dry_run, no_chat, last_print=phone_print)
    return 0


def print_help() -> None:
    """Print usage help for the install command."""
    console.print()
    console.print("[bold cyan]aipass install[/bold cyan] — one-command bootstrap of AIPass")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass install[/green]                      [dim]# interactive, ends in a chat[/dim]")
    console.print(
        "  [green]aipass install --non-interactive[/green]    "
        "[dim]# CI/headless (~/AIPass), no chat, no pairing QR[/dim]"
    )
    console.print("  [green]aipass install --path DIR[/green]           [dim]# explicit home[/dim]")
    console.print("  [green]aipass install --here[/green]               [dim]# install into current dir[/dim]")
    console.print("  [green]aipass install --no-chat[/green]            [dim]# install only, skip the chat[/dim]")
    console.print("  [green]aipass install --no-baud[/green]            [dim]# skip phone face + baud-cli[/dim]")
    console.print("  [green]aipass install --baud-tag TAG[/green]       [dim]# baud release, default latest[/dim]")
    console.print(
        "  [green]aipass install --source PATH|URL[/green]   [dim]# clone AIPass from this path or URL instead of the"
        " public repo (a local path clones its committed HEAD; for the install sandbox)[/dim]"
    )
    console.print("  [green]aipass install --no-symlink[/green]         [dim]# skip global CLI symlinks[/dim]")
    console.print("  [green]aipass install --force-symlink[/green]      [dim]# repoint from another install[/dim]")
    console.print("  [green]aipass install --chat-only[/green]          [dim]# skip the build, just the chat[/dim]")
    console.print("  [green]aipass install --force-global-home[/green]  [dim]# allow install into /tmp (unsafe)[/dim]")
    console.print("  [green]aipass install --dry-run[/green]            [dim]# walk steps, no side effects[/dim]")
    console.print()
    console.print(
        "[yellow]STEPS:[/yellow] resolve home -> fetch -> setup.sh -> verify -> phone face + baud-cli -> welcome chat"
    )
    console.print()
    console.print("[dim]Project creation isn't part of install — run 'aipass init run' for that, whenever ready.[/dim]")
    console.print("[dim]With a phone face installed, the install starts the server when no boot unit runs it,[/dim]")
    console.print("[dim]then waits for Enter and shows the pairing QR. No QR (--non-interactive, or no server[/dim]")
    console.print("[dim]on a tailnet bind): drone @api host-api pair phone --scope operate[/dim]")
    console.print("[dim]A dry run takes no install lock, so it can preview beside a live install.[/dim]")
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


def _flag_value(args: list[str], flag: str) -> str | None:
    """A value flag in either spelling: ``--flag value`` or ``--flag=value`` (DPLAN-0409 C3).

    None: absent. "": present with no value, which the caller refuses rather than defaulting.
    """
    prefix = f"{flag}="
    for idx, arg in enumerate(args):
        if arg == flag:
            return args[idx + 1] if idx + 1 < len(args) else ""
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


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

    run_args = args[1:] if args and args[0] == "run" else args

    non_interactive = "--non-interactive" in run_args
    dry_run = "--dry-run" in run_args
    here = "--here" in run_args
    no_chat = "--no-chat" in run_args
    chat_only = "--chat-only" in run_args
    no_symlink = "--no-symlink" in run_args
    force_symlink = "--force-symlink" in run_args
    no_baud = "--no-baud" in run_args
    path = _flag_value(run_args, "--path") or None
    # A valueless --baud-tag or --source reaches its validator as "" and is refused there.
    baud_tag = _flag_value(run_args, "--baud-tag")
    baud_tag = LATEST if baud_tag is None else baud_tag
    source = _flag_value(run_args, "--source")

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
            no_baud=no_baud,
            baud_tag=baud_tag,
            source=source,
        )
    json_handler.log_operation(
        "install_run",
        {
            "non_interactive": non_interactive,
            "dry_run": dry_run,
            "chat_only": chat_only,
            "source": _redact_url(source) if source else "default",
            "exit": result,
        },
    )
    sys.exit(result)
