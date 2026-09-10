# =================== AIPass ====================
# Name: release_notice.py
# Version: 1.0.0
# Description: Manager-only "AIPass release available" notice builder (DPLAN-0335 leg 2)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Builds the manager-only notice that a project's scaffold is behind AIPass.

A release mail can be read and closed; this is the half that stays until the
scaffold is actually current. It reads two files and writes none: the cwd
passport (to answer "is this seat a manager?") and the project's
``.aipass/scaffold_manifest.json`` (to answer "which AIPass wrote this
scaffold?"). It never runs ``aipass init update`` — applying is Patrick's or
devpulse's call, never the notice's (DPLAN-0335, Patrick 2026-09-09 23:51).

Shared by apps/handlers/lifecycle/release_notice.py (SessionStart) and
apps/handlers/lifecycle/post_compact_regrounding.py (the post-compact regroup
path), so both doors emit one identical block from one code path.
"""

import json
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

#: The only citizen_class this notice speaks to. A specialist cannot run
#: ``aipass init update`` against its host project, so telling one is noise.
MANAGER_CLASS = "manager"

#: A project root is the directory holding a *_REGISTRY.json — the same marker
#: edit_gate and @ai_mail's find_project_root use. Kept identical on purpose:
#: the manifest belongs to whatever the rest of the system calls the project.
_PROJECT_MARKER = "*_REGISTRY.json"

#: Written by @aipass's init run / adopt / init update (DPLAN-0335 leg 3).
#: Schema fixed in the plan: aipass_version (str), stamped_at (ISO 8601),
#: files (rel path -> sha256). Only the first two are read here.
MANIFEST_REL = Path(".aipass") / "scaffold_manifest.json"


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]release_notice[/bold cyan] — Manager-only AIPass release notice builder (DPLAN-0335)")


def _find_project_root(start: Path) -> Path | None:
    """Return the nearest ancestor of *start* holding a *_REGISTRY.json, or None."""
    try:
        current = start.resolve()
    except OSError as exc:
        logger.info("[HOOKS] release_notice: project root unresolvable for %s: %s", start, exc)
        return None
    for candidate in [current, *current.parents]:
        try:
            if any(candidate.glob(_PROJECT_MARKER)):
                return candidate
        except OSError as exc:
            logger.info("[HOOKS] release_notice: project marker scan failed at %s: %s", candidate, exc)
            break
    return None


def _find_passport(start: Path) -> Path | None:
    """Walk up from *start* to the nearest .trinity/passport.json, stopping at $HOME."""
    try:
        search = start.resolve()
    except OSError:
        return None
    home = Path.home()
    while search != home and search.parent != search:
        passport = search / ".trinity" / "passport.json"
        if passport.exists():
            return passport
        search = search.parent
    return None


def _is_manager(passport: Path) -> bool:
    """True when the passport declares citizen_class manager.

    Passport 2.0 moved the class inside ``identity`` (DPLAN-0319); the top level
    is read as a fallback so a 1.0 passport is not silently treated as a
    non-manager. Unreadable passport means "not a manager" — a notice that
    cannot prove who it is talking to says nothing.
    """
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] release_notice: passport unreadable at %s: %s", passport, exc)
        return False
    if not isinstance(data, dict):
        return False
    identity = data.get("identity")
    nested = identity.get("citizen_class") if isinstance(identity, dict) else None
    return (nested or data.get("citizen_class")) == MANAGER_CLASS


def _is_aipass_source_repo(root: Path) -> bool:
    """True for the AIPass source checkout itself.

    ``aipass init update`` refuses its own repo, so a notice there could never
    be cleared — it would nag every session forever. devpulse's own passport
    says manager, so without this the loudest seat on the machine is the one
    that gets the useless nag.
    """
    return (root / "src" / "aipass").is_dir() and (root / "pyproject.toml").exists()


def _version_tuple(text: object) -> tuple[int, ...] | None:
    """Parse a dotted numeric version into a comparable tuple, or None.

    A plain tuple compare rather than packaging.version: ``packaging`` is not in
    this project's declared dependencies (pyproject ``dependencies`` is rich,
    watchdog, requests, psutil, questionary, pathspec), so importing it here
    would make a hook depend on whatever pip happened to leave in the venv.
    AIPass versions are plain MAJOR.MINOR.PATCH, which a tuple orders correctly.

    Leading digits of each dotted chunk are taken, so a hypothetical "2.9.0rc1"
    reads as (2, 9, 0) — one release too low rather than unparseable.
    """
    parts: list[int] = []
    for chunk in str(text).strip().split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or None


def _is_behind(stamped: tuple[int, ...], installed: tuple[int, ...]) -> bool:
    """Compare two version tuples, zero-padded to equal length.

    Padding matters: without it a scaffold stamped "2.8" would read as behind
    installed "2.8.0" forever, because (2, 8) < (2, 8, 0).
    """
    width = max(len(stamped), len(installed))
    pad = (0,) * width
    return (stamped + pad)[:width] < (installed + pad)[:width]


def _installed_version() -> str:
    """The running aipass version. Imported at call time, never at module import."""
    import importlib

    return str(getattr(importlib.import_module("aipass"), "__version__", ""))


def _read_manifest(root: Path) -> dict | None:
    """Read the project's scaffold manifest, or None when absent/unreadable."""
    path = root / MANIFEST_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] release_notice: manifest unreadable at %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _stamp_date(stamped_at: str) -> str:
    """The date half of an ISO 8601 stamp — "2026-09-09T07:55:36.794203+00:00" is
    a lot of characters to spend, every wake, on a block whose only job is "you
    are behind". Anything that is not ISO-shaped is passed through untouched
    rather than guessed at."""
    head = stamped_at.split("T", 1)[0]
    return head if len(head) == 10 and head.count("-") == 2 else stamped_at


def _format_block(root: Path, installed: str, stamped: str, stamped_at: str) -> str:
    """Render the notice. *stamped* empty means the scaffold was never stamped."""
    if stamped:
        stamped_line = f"  stamped:   {stamped}" + (f" ({_stamp_date(stamped_at)})" if stamped_at else "")
    else:
        stamped_line = "  stamped:   never stamped (no .aipass/scaffold_manifest.json)"
    return "\n".join(
        [
            "[AIPASS RELEASE NOTICE — managers only, DPLAN-0335]",
            "This project's scaffold is behind the installed AIPass.",
            f"  installed: {installed}",
            stamped_line,
            f"  project:   {root}",
            "Preview what an update would change — writes nothing:",
            f"  aipass init update {root} --dry-run",
            "Apply ONLY with Patrick's or devpulse's go. This notice never runs the update.",
        ]
    )


def build_notice(hook_data: dict) -> str:
    """Return the notice block, or "" when this seat should hear nothing.

    Silent for: a non-manager seat, a seat with no passport, a cwd outside any
    project, the AIPass source repo, and a scaffold already at the installed
    version. Absent or unparseable manifest counts as behind — a project that
    cannot say which AIPass wrote it has not been stamped by leg 3 yet.

    Args:
        hook_data: The hook payload; only ``cwd`` is read, falling back to the
            process cwd when the event does not carry one.

    Returns:
        The rendered block, or an empty string.
    """
    start = Path(hook_data.get("cwd", "") or Path.cwd())

    passport = _find_passport(start)
    if not passport or not _is_manager(passport):
        return ""

    root = _find_project_root(start)
    if root is None or _is_aipass_source_repo(root):
        return ""

    installed_raw = _installed_version()
    installed = _version_tuple(installed_raw)
    if installed is None:
        # An unreadable installed version is an AIPass defect, not a project's.
        # Staying quiet keeps the bug out of every manager's prompt.
        logger.info("[HOOKS] release_notice: installed version unparseable: %r", installed_raw)
        return ""

    manifest = _read_manifest(root) or {}
    stamped_raw = str(manifest.get("aipass_version", "") or "")
    stamped = _version_tuple(stamped_raw) if stamped_raw else None

    if stamped is not None and not _is_behind(stamped, installed):
        return ""

    return _format_block(root, installed_raw, stamped_raw, str(manifest.get("stamped_at", "") or ""))
