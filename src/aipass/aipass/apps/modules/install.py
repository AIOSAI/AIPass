# =================== AIPass ====================
# Name: install.py
# Description: aipass install — one-command PyPI bootstrap (clone + setup + doctor + report)
# Version: 1.9.0
# Created: 2026-07-05
# Modified: 2026-11-25
# =============================================

"""
aipass install — one-command bootstrap of the whole framework
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict
from urllib.parse import unquote, urlsplit, urlunsplit

from aipass.cli import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.aipass.apps.handlers import provider_choice
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
_DOCTOR_TIMEOUT = 600
# Exported to setup.sh under --non-interactive, for it to read before its own [ -t 0 ].
NON_INTERACTIVE_ENV = "AIPASS_NON_INTERACTIVE"
# Exported under --yes: consent to setup.sh's machine changes, given up front.
YES_ENV = "AIPASS_YES"
WAKE_PROMPT = (
    "Read dropbox/install_report.json: a fresh AIPass install. "
    "Greet me by name, then walk me through each attention item."
)
_PHONE_FAILED = {
    "group": "Phone",
    "label": "phone face",
    "severity": "error",
    "detail": "asked for (no --no-baud) and not installed; the Phone face step above says why",
    "remediation": "aipass baud install",
}
_CLOSING_NOTE = (
    "devpulse is the seat you talk to: the admin agent, with higher privileges to change files in any directory,",
    "under your supervision. aipass is the machine concierge for host problems (Wi-Fi drops, a USB port not",
    "working, CPU running hot, battery, screen flicker), so devpulse stays on your projects.",
)


def _prompt(msg: str, default: str = "") -> str:
    """Simple input prompt with optional default (raises on Ctrl-C/EOF)."""
    display = f"{msg} [Enter for {default}]: " if default else f"{msg}: "
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


#: A home lands in shell rc lines, hook commands and three providers' configs; only a plain path survives them all.
_UNSAFE_HOME = re.compile(r"[\s\"'`$&;|<>()\\*?!{}\[\]#]")


def _checked_home(raw: str) -> Path:
    """*raw* as a home path, or ValueError naming why: absolute or ~/..., no whitespace, quote or shell character."""
    if not (raw.startswith("/") or raw.startswith("~/")):
        raise ValueError(f"{raw!r} is not an absolute path or ~/...")
    if _UNSAFE_HOME.search(raw[1:] if raw.startswith("~/") else raw):
        raise ValueError(f"{raw!r} holds whitespace, a quote or a shell character")
    return Path(raw).expanduser().resolve()


def _resolve_home(path: str | None, here: bool, non_interactive: bool) -> Path:
    """Decide where AIPass lives — --here / --path / $AIPASS_HOME / cwd / prompt / default."""
    if here:
        return Path.cwd().resolve()
    if path:
        return _checked_home(path)
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
    while True:
        try:
            return _checked_home(_prompt("Where should AIPass live?", str(DEFAULT_HOME)))
        except ValueError as exc:
            warning(f"Home refused: {exc}. Give an absolute path or ~/name.")


def install_lock_path(home: Path) -> Path:
    """The lock guarding one install of `home`.

    Lives in the parent: on a fresh machine `home` does not exist until the clone lands.
    """
    return home.parent / f".{home.name}.install.lock"


def _fire_lock_removed(path: Path, reason: str) -> None:
    """Fire file_deleted for a removed install lock on the home's own event bus.

    A bootstrap runs from a wheel outside any home, where the bus's handlers need a home
    at import (RepoRootNotFound): it fires through the home's own drone instead.
    """
    home = path.parent / path.name.removeprefix(".").removesuffix(".install.lock")
    if Path(__file__).resolve().is_relative_to(home.resolve()):
        try:
            from aipass.trigger import trigger

            trigger.fire("file_deleted", path=str(path), reason=reason)
        except ImportError as exc:
            logger.warning("[install] trigger unavailable for file_deleted event: %s", exc)
        return
    drone = home / ".venv" / "bin" / "drone"
    if not drone.is_file():
        logger.warning("[install] no drone at %s yet: file_deleted for %s not fired", drone, path)
        return
    cmd = [str(drone), "@trigger", "fire", "file_deleted", f"path={path}", f"reason={reason}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(home))
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[install] file_deleted for %s not fired through %s: %s", path, drone, exc)
        return
    if proc.returncode != 0:
        logger.warning("[install] file_deleted for %s: drone exit %s: %s", path, proc.returncode, proc.stderr.strip())


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
        # Only a holder PROVEN dead (False) is taken over; no readable pid (None) is left alone.
        alive = _pid_alive(int(holder_pid)) if holder_pid else None
        if _retry and alive is False:
            if not _clear_stale_lock(lock, holder_pid):
                return None
            # One takeover only, so two racing installs cannot ping-pong clearing each other.
            return acquire_install_lock(home, _retry=False)
        holder = f", held by pid {holder_pid}" if holder_pid else ""
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


def _pid_alive(pid: int) -> bool:
    """True when `pid` names a live process, False when it is gone."""
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
    marker = path / ".git"
    if not (marker.is_file() or (marker.is_dir() and any(marker.iterdir()))):
        raise SourceRefused(f"{path} is not a repository (no .git, or an empty one)")
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
            if source.startswith("file://"):
                _point_origin_upstream(home, Path(unquote(urlsplit(source).path)))
            return True
        # The user's line first: an unwritable log home must not swallow the last word.
        warning(f"git clone failed (exit {proc.returncode}) — git's own message is above. Check the network and retry.")
        logger.warning("[install] git clone exited %s", proc.returncode)
    except subprocess.TimeoutExpired as exc:
        warning("git clone timed out.")
        logger.warning("[install] git clone timed out after %ss", exc.timeout)
    return False


def _point_origin_upstream(home: Path, checkout: Path) -> None:
    """A home cloned from a local checkout takes that checkout's origin, every branch fetched.

    Left as cloned, origin is the checkout's directory and fetches one branch: the home
    cannot sync or open a PR. A checkout with no origin keeps the clone as it is.
    """
    upstream = subprocess.run(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=30
    )
    url = upstream.stdout.strip()
    if upstream.returncode != 0 or not url:
        logger.info("[install] %s has no origin; the home's origin stays %s", checkout, checkout.as_uri())
        return
    for args in (
        ["remote", "set-url", "origin", url],
        ["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
    ):
        subprocess.run(["git", "-C", str(home), *args], check=True, capture_output=True, text=True, timeout=30)
    console.print(f"origin -> {_redact_url(url)} (the checkout's own), every branch fetched", markup=False)


def _run_setup(
    home: Path,
    dry_run: bool,
    no_symlink: bool = False,
    force_symlink: bool = False,
    non_interactive: bool = False,
    yes: bool = False,
) -> bool:
    """Run the repo's setup.sh (venv + editable install + hook wiring + binaries).

    ``non_interactive`` closes stdin and exports AIPASS_NON_INTERACTIVE=1: install.sh
    hands this process the user's tty, so setup.sh's ``[ -t 0 ]`` alone would still prompt.
    ``yes`` exports AIPASS_YES=1, consent to setup.sh's machine changes.
    """
    setup = home / "setup.sh"
    # --no-finish: install's own step 5 runs the doctor and the report, once, in this process.
    setup_args = ["bash", str(setup), "--no-finish"]
    if no_symlink:
        setup_args.append("--no-symlink")
    if force_symlink:
        setup_args.append("--force-symlink")
    exported = {**({NON_INTERACTIVE_ENV: "1"} if non_interactive else {}), **({YES_ENV: "1"} if yes else {})}
    said = (["stdin closed"] if non_interactive else []) + [f"{k}=1" for k in exported]
    closed = f" ({', '.join(said)})" if said else ""
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: {' '.join(setup_args)}{closed}")
        return True
    if not setup.is_file():
        warning(f"setup.sh not found at {setup} — cannot build the environment.")
        return False
    console.print("[cyan]Building environment[/cyan] [dim](venv, dependencies, hook wiring)…[/dim]")
    stdin = subprocess.DEVNULL if non_interactive else None
    env = {**os.environ, **exported} if exported else None
    try:
        proc = subprocess.run(setup_args, cwd=str(home), timeout=_SETUP_TIMEOUT, env=env, stdin=stdin)
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


def _setup_attention(home: Path) -> list[dict]:
    """setup.sh's action items, one per line of ``<home>/.aipass/setup_attention.txt``, as attention rows."""
    path = home / ".aipass" / "setup_attention.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("[install] no %s: setup.sh predates it or never ran", path)
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("[install] setup.sh's action items unreadable at %s: %s", path, exc)
        detail = f"setup.sh's action items unreadable at {path}: {exc}"
        return [{"group": "Setup", "label": "setup.sh", "severity": "error", "detail": detail, "remediation": ""}]
    return [
        {"group": "Setup", "label": "setup.sh", "severity": "warning", "detail": line.strip(), "remediation": ""}
        for line in text.splitlines()
        if line.strip()
    ]


def _health_check(home: Path, dry_run: bool, non_interactive: bool, yes: bool = False) -> tuple[list[dict], dict]:
    """Run the home's own 'aipass doctor --fix' in the home. Returns (attention rows, doctor counts).

    In-process, a bootstrap from a wheel would judge its own cwd, environment and code, not the home.
    """
    flags = ["--yes"] if yes else []
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would run: aipass doctor --fix {' '.join(flags)}".rstrip())
        return [], {"pass": 0, "warn": 0, "error": 0}
    aipass_bin = home / ".venv" / "bin" / "aipass"
    rows_file = home / ".aipass" / "install_doctor_rows.json"
    cmd = [str(aipass_bin), "doctor", "--fix", "--rows-json", str(rows_file), *flags]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(home),
            env={**os.environ, "AIPASS_HOME": str(home)},
            stdin=subprocess.DEVNULL if non_interactive else None,
            timeout=_DOCTOR_TIMEOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"exit {proc.returncode}")
        data = json.loads(rows_file.read_text(encoding="utf-8"))
        return data["rows"], data["counts"]
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError, TypeError) as exc:
        logger.error("[install] the home's doctor did not report (%s): %s", aipass_bin, exc)
        error(f"Health check did not run: {aipass_bin} doctor: {exc}. Run 'aipass doctor --fix' in {home}.")
        crash = {"group": "Doctor", "label": "doctor", "severity": "error", "detail": f"did not run: {exc}"}
        return [{**crash, "remediation": f"cd {shlex.quote(str(home))} && aipass doctor --fix"}], {
            "pass": 0,
            "warn": 0,
            "error": 1,
        }


def install_report_path(home: Path) -> Path:
    """devpulse's dropbox copy of the install outcome, overwritten each install."""
    return home / "src" / "aipass" / "devpulse" / "dropbox" / "install_report.json"


def _aipass_version() -> str:
    try:
        return importlib.metadata.version("aipass")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _final_screen(
    home: Path, attention: list[dict], counts: dict, dry_run: bool, failed: list[str] | None = None
) -> int:
    """Installed line, what needs attention, the report, the wake command. Returns the exit code.

    *failed* names the requested steps that did not land; they and any doctor error make the exit 1,
    once the report is written.
    """
    report_path = install_report_path(home)
    if dry_run:
        console.print(f"[yellow]\\[dry-run][/yellow] would write the install report: {report_path}")
        return 0
    console.print()
    faults = [f"a requested step failed: {', '.join(failed)}"] if failed else []
    if counts.get("error", 0):
        faults.append(f"the health check found {counts['error']} error(s)")
    if faults:
        error(f"AIPass installed at {home}, but {'; '.join(faults)}")
    else:
        success(f"AIPass installed at {home}")
    console.print()
    if attention:
        console.print("[bold]Needs attention:[/bold]")
        for item in attention:
            fix = f" -> {item['remediation']}" if item["remediation"] else ""
            line = f"  {item['severity']}: {item['label']}: {item['detail']}{fix}"
            console.print(line, markup=False, highlight=False)
    else:
        console.print("Nothing needs attention.")
    console.print()
    report = {
        "kind": "aipass_install_report",
        "version": 1,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "home": str(home),
        "aipass_version": _aipass_version(),
        "user_name": _registry_user_name(home),
        "outcome": "step_failed" if failed else "doctor_errors" if counts.get("error", 0) else "installed",
        "failed_steps": failed or [],
        "doctor": counts,
        "attention": attention,
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.error("[install] install report not written to %s: %s", report_path, exc)
        error(f"Could not write the install report at {report_path}: {exc}")
        return 1
    json_handler.log_operation("install_report", {"path": str(report_path), "attention": len(attention)})
    console.print(f"Report: {report_path}", markup=False, highlight=False)
    console.print()
    for line in _CLOSING_NOTE:
        console.print(f"[dim]{line}[/dim]")
    return 1 if faults else 0


def _finish(
    home: Path,
    dry_run: bool,
    non_interactive: bool,
    last_print: Callable[[], None] | None = None,
    yes: bool = False,
    failed: list[dict] | None = None,
) -> int:
    """Step 5 and the final screen: the doctor with its fix, the phone print, then the report.

    *failed* holds attention rows for requested steps that did not land; each fails the exit.
    """
    console.print()
    console.print(render_step_header(5, TOTAL_STEPS, "Health check"))
    attention, counts = _health_check(home, dry_run, non_interactive, yes)
    if last_print is not None:
        last_print()
    failed = failed or []
    rows = [*failed, *attention, *_setup_attention(home)]
    return _final_screen(home, rows, counts, dry_run, failed=[row["label"] for row in failed])


def _install_phone_face(dry_run: bool, no_baud: bool, baud_tag: str = LATEST) -> bool:
    """The Phone face step. False when skipped or failed; run_install fails the exit on a requested miss."""
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
    """Run sync-registry --check in `home`; if issues found, auto-heal with --fix. A check that cannot run is shown."""
    fix_cmd = f"cd {home} && drone @spawn sync-registry --fix"
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
                warning(f"Owner/identity repair failed (exit {fix_proc.returncode}): run {fix_cmd}")
        else:
            success("Owner/identity OK.")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("[install] owner check could not run: %s", exc)
        warning(f"Owner/identity NOT checked ({exc}): run {fix_cmd}")


def run_finish(
    non_interactive: bool = False,
    path: str | None = None,
    here: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> int:
    """Step 5 and the final screen only, no clone/setup. setup.sh's tail calls it."""
    try:
        home = _resolve_home(path, here, non_interactive)
    except KeyboardInterrupt:
        logger.info("[install] --finish cancelled by user")
        console.print()
        warning("Cancelled.")
        return 1
    except ValueError as exc:
        error(f"Home refused: {exc}. Give an absolute path or ~/name.")
        return 2
    if not dry_run:
        _verify_binaries(home)
    return _finish(home, dry_run, non_interactive, yes=yes)


def run_install(
    non_interactive: bool = False,
    path: str | None = None,
    here: bool = False,
    dry_run: bool = False,
    no_symlink: bool = False,
    force_symlink: bool = False,
    no_baud: bool = False,
    baud_tag: str = LATEST,
    source: str | None = None,
    yes: bool = False,
    provider: str | None = None,
) -> int:
    """Run the 5-step one-command install, then the provider question. Returns 0 on success, 1 on failure.

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
    except ValueError as exc:
        error(f"Home refused: {exc}. Give an absolute path or ~/name.")
        return 2
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

    # Released before the phone step, which can wait on Enter. A dry run writes nothing and takes no lock.
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
            home,
            dry_run,
            no_symlink=no_symlink,
            force_symlink=force_symlink,
            non_interactive=non_interactive,
            yes=yes,
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
    failed = [] if face_installed or no_baud else [_PHONE_FAILED]

    json_handler.log_operation(
        "aipass_install",
        {
            "home": str(home),
            "non_interactive": non_interactive,
            "dry_run": dry_run,
            "phone_face": face_installed,
            "yes": yes,
            "baud_tag": baud_tag,
        },
    )

    result = _finish(home, dry_run, non_interactive, last_print=phone_print, yes=yes, failed=failed)
    ending = provider_choice.run_ending(
        provider,
        home,
        WAKE_PROMPT,
        non_interactive=non_interactive,
        dry_run=dry_run,
        prompt=input,
        say=lambda line: console.print(line, markup=False, highlight=False),
    )
    return result or ending


def print_help() -> None:
    """Print usage help for the install command."""
    console.print()
    console.print("[bold cyan]aipass install[/bold cyan] — one-command bootstrap of AIPass")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass install[/green]                      [dim]# interactive, ends at the report[/dim]")
    console.print(
        "  [green]aipass install --non-interactive[/green]    "
        "[dim]# CI/headless (~/AIPass), no questions, no pairing QR[/dim]"
    )
    console.print(
        "  [green]aipass install --yes[/green]               [dim]# consent to the machine changes up front;"
        " without it --non-interactive skips them, each a warning[/dim]"
    )
    console.print("  [green]aipass install --path DIR[/green]           [dim]# explicit home[/dim]")
    console.print("  [green]aipass install --here[/green]               [dim]# install into current dir[/dim]")
    console.print("  [green]aipass install --no-baud[/green]            [dim]# skip phone face + baud-cli[/dim]")
    console.print("  [green]aipass install --baud-tag TAG[/green]       [dim]# baud release, default latest[/dim]")
    console.print(
        "  [green]aipass install --source PATH|URL[/green]   [dim]# clone AIPass from this path or URL instead of the"
        " public repo (a local path clones its committed HEAD; for the install sandbox)[/dim]"
    )
    console.print(
        "  [green]aipass install --provider NAME[/green]    [dim]# claude|codex|opencode: answer the last question"
        " headless (install it if missing, wire it, open devpulse in it)[/dim]"
    )
    console.print("  [green]aipass install --no-symlink[/green]         [dim]# skip global CLI symlinks[/dim]")
    console.print("  [green]aipass install --force-symlink[/green]      [dim]# repoint from another install[/dim]")
    console.print("  [green]aipass install --finish[/green]             [dim]# just the doctor + report[/dim]")
    console.print("  [green]aipass install --force-global-home[/green]  [dim]# allow install into /tmp (unsafe)[/dim]")
    console.print("  [green]aipass install --dry-run[/green]            [dim]# walk steps, no side effects[/dim]")
    console.print()
    console.print(
        "[yellow]STEPS:[/yellow] resolve home -> fetch -> setup.sh -> verify -> phone face + baud-cli"
        " -> doctor + report"
    )
    console.print()
    console.print(
        "[dim]Project creation isn't part of install — run 'aipass init <dir>' for that, whenever ready.[/dim]"
    )
    console.print("[dim]With a phone face installed, the install starts the server when no boot unit runs it,[/dim]")
    console.print("[dim]then waits for Enter and shows the pairing QR. No QR (--non-interactive, or no server[/dim]")
    console.print("[dim]on a tailnet bind): drone @api host-api pair phone --scope operate[/dim]")
    console.print("[dim]A dry run takes no install lock, so it can preview beside a live install.[/dim]")
    console.print()


def print_introspection() -> None:
    """Show module info for install."""
    console.print()
    console.print("[bold cyan]install Module[/bold cyan]")
    console.print("One-command bootstrap: clone + setup.sh + verify + doctor --fix + install report")
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


_SWITCHES = (
    "--non-interactive", "--yes", "--dry-run", "--here", "--finish",
    "--no-symlink", "--force-symlink", "--no-baud", "--force-global-home",
)  # fmt: skip
_VALUE_FLAGS = ("--path", "--baud-tag", "--source", "--provider")


def _unknown_args(args: list[str]) -> list[str]:
    """The args install does not know; a value flag's next arg is its value, whatever it looks like."""
    unknown: list[str] = []
    it = iter(args)
    for arg in it:
        if arg in _VALUE_FLAGS:
            next(it, None)
        elif arg not in _SWITCHES and arg.split("=", 1)[0] not in _VALUE_FLAGS:
            unknown.append(arg)
    return unknown


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

    unknown = _unknown_args(args)
    if unknown:
        logger.warning("[install] refused unknown args: %s", unknown)
        error(f"aipass install: unknown argument(s): {' '.join(unknown)}")
        print_help()
        sys.exit(2)

    non_interactive = "--non-interactive" in args
    yes = "--yes" in args
    dry_run = "--dry-run" in args
    here = "--here" in args
    finish = "--finish" in args
    no_symlink = "--no-symlink" in args
    force_symlink = "--force-symlink" in args
    no_baud = "--no-baud" in args
    path = _flag_value(args, "--path") or None
    # A valueless --baud-tag or --source reaches its validator as "" and is refused there.
    baud_tag = _flag_value(args, "--baud-tag")
    baud_tag = LATEST if baud_tag is None else baud_tag
    source = _flag_value(args, "--source")
    provider = _flag_value(args, "--provider")
    if provider is not None and provider not in provider_choice.PROVIDERS:
        error(f"--provider takes one of: {', '.join(provider_choice.ORDER)}")
        sys.exit(2)

    if finish:
        result = run_finish(non_interactive=non_interactive, path=path, here=here, dry_run=dry_run, yes=yes)
    else:
        result = run_install(
            non_interactive=non_interactive,
            path=path,
            here=here,
            dry_run=dry_run,
            no_symlink=no_symlink,
            force_symlink=force_symlink,
            no_baud=no_baud,
            baud_tag=baud_tag,
            source=source,
            yes=yes,
            provider=provider,
        )
    json_handler.log_operation(
        "install_run",
        {
            "non_interactive": non_interactive,
            "dry_run": dry_run,
            "yes": yes,
            "finish": finish,
            "source": _redact_url(source) if source else "default",
            "exit": result,
        },
    )
    sys.exit(result)
