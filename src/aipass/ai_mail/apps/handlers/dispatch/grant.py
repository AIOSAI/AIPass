# =================== AIPass ====================
# Name: grant.py
# Description: A dispatch's scoped write grant into a foreign project: validation, overlap, the gate's decision
# Version: 1.0.0
# Created: 2026-11-03
# Modified: 2026-11-03
# =============================================

"""
A dispatch's scoped write grant into a foreign project.

The grant is one key on the dispatch register's open row, so it is open exactly while the
row is: every path that closes the row (monitor exit, reply, stop, close) revokes it, with
no second store to agree. It is keyed to the dispatch id, never the seat: only the process
the wake stamped with AIPASS_DISPATCH_ID carries it, so the seat's other sessions do not.
Reference: docs/dispatch_register_and_feed.md
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.dispatch import register
from aipass.ai_mail.apps.handlers.json import json_handler

GRANT_KEY = register.GRANT_KEY


class GrantRefused(Exception):
    """A grant that must not be issued; the message names the reason and the path."""


def parse_grant(root_raw: Optional[str], paths_raw: Optional[str], repo_root: Path) -> Dict[str, Any]:
    """The validated grant {root, files, dirs} for --grant-root and --grant; raises GrantRefused naming the path."""
    if not root_raw or not paths_raw:
        raise GrantRefused("--grant-root <dir> and --grant <p1,p2,...> go together, each with a value")
    root_given = Path(root_raw).expanduser()
    if not root_given.is_dir():
        raise GrantRefused(f"grant root {root_raw} is not a directory")
    root = root_given.resolve()
    repo = repo_root.resolve()
    if root.is_relative_to(repo) or repo.is_relative_to(root):
        raise GrantRefused(f"grant root {root} overlaps the AIPass repo; a grant reaches a foreign project only")

    files: List[str] = []
    dirs: List[str] = []
    for raw in (part.strip() for part in paths_raw.split(",")):
        rel = Path(raw)
        if not raw or rel.is_absolute() or ".." in rel.parts:
            raise GrantRefused(f"grant path {raw!r} must be relative to {root}, without ..")
        full = (root / rel).resolve()
        if not full.is_relative_to(root):
            raise GrantRefused(f"grant path {raw} resolves outside {root}")
        if full == root:
            raise GrantRefused(f"grant path {raw} is the root itself; grant a directory under it")
        inside = full.relative_to(root)
        if ".git" in inside.parts:
            raise GrantRefused(f"grant path {raw} is under .git; git stays with @devpulse")
        if full.is_file():
            files.append(inside.as_posix())
        elif full.is_dir():
            dirs.append(inside.as_posix())
        else:
            raise GrantRefused(f"grant path {raw} does not exist under {root}")
    return {"root": str(root), "files": files, "dirs": dirs}


def from_send_args(
    flags: Dict[str, Any], positional: List[str], grant_flags: Tuple[str, ...], target: str, is_admin: bool
) -> Optional[Dict[str, Any]]:
    """The grant the dispatch flags ask for (None when they ask for none); raises GrantRefused before any send.

    A grant flag left among the positionals had no value: the parser leaves it there rather than drop it.
    """
    if not any(flag in flags or flag in positional for flag in grant_flags):
        return None
    dangling = [flag for flag in grant_flags if flag in positional]
    if dangling:
        raise GrantRefused(f"{dangling[0]} needs a value")
    return check_before_send(flags.get(grant_flags[0]), flags.get(grant_flags[1]), target, is_admin)


def check_before_send(root_raw: Optional[str], paths_raw: Optional[str], target: str, is_admin: bool) -> Dict[str, Any]:
    """The grant a dispatch to *target* may carry, checked before any mail goes; raises GrantRefused naming why."""
    from aipass.ai_mail.apps.handlers.dispatch.wake import is_manager
    from aipass.ai_mail.apps.handlers.paths import find_repo_root

    if not is_admin:
        raise GrantRefused("only the verified admin seat may send a grant")
    if is_manager(target):
        raise GrantRefused(
            f"{target} is a manager; a grant rides a headless dispatch row, which a manager wake never opens"
        )
    grant = parse_grant(root_raw, paths_raw, find_repo_root())
    try:
        clash = overlapping(grant, register.outstanding())
    except OSError as exc:
        raise GrantRefused(f"the dispatch register is unreadable ({exc}), so overlap cannot be ruled out") from exc
    if clash:
        raise GrantRefused(f"the grant overlaps open dispatch {clash}")
    return grant


def _granted_paths(grant: Dict[str, Any]) -> List[Path]:
    """Absolute paths a grant covers; raises (KeyError, TypeError) on a malformed grant."""
    root = Path(grant["root"])
    return [root / p for p in list(grant["files"]) + list(grant["dirs"])]


def overlapping(grant: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> Optional[str]:
    """The id of an open row whose grant shares a path with *grant* (either under the other), else None."""
    mine = _granted_paths(grant)
    for row in rows:
        other = row.get(GRANT_KEY)
        if other is None:
            continue
        try:
            theirs = _granted_paths(other)
        except (KeyError, TypeError) as exc:
            # Cannot tell what it covers, so it may cover this: refuse rather than guess.
            logger.warning("[grant] malformed open grant on %s counted as overlapping: %s", row.get("dispatch_id"), exc)
            return str(row.get("dispatch_id"))
        if any(a.is_relative_to(b) or b.is_relative_to(a) for a in mine for b in theirs):
            return str(row.get("dispatch_id"))
    return None


def render_block(grant: Dict[str, Any]) -> str:
    """The Grant block for the delivered body, built from the same values written to the row."""
    lines = [
        "--- GRANT ---",
        f"Write access in {grant['root']} while this dispatch is open; it is revoked when the dispatch closes.",
    ]
    if grant["files"]:
        lines.append("Files: " + ", ".join(grant["files"]))
    if grant["dirs"]:
        lines.append("Directories (new files allowed under these): " + ", ".join(grant["dirs"]))
    lines.append("Nothing else under the root is writable. No git: @devpulse commits.")
    return "\n".join(lines)


def _seat(address: Any) -> str:
    return "@" + str(address or "").lstrip("@").lower()


def open_grants(repo_root: Optional[Path] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every outstanding register row that carries a grant, newest first. Raises OSError if unreadable."""
    return [row for row in register.outstanding(repo_root=repo_root, now=now) if row.get(GRANT_KEY) is not None]


def granted(
    caller_branch: str,
    dispatch_id: Optional[str],
    target_path: str,
    repo_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """The gate's decision {allowed, dispatch_id, reason} for one write, liveness derived at this read.

    target_path is taken as given (absolute, already resolved by the caller): nothing under the
    grant's root is read here, only the caller project's register.
    """
    json_handler.log_operation("grant_decision", {"caller": caller_branch, "dispatch_id": dispatch_id})

    def refuse(reason: str) -> Dict[str, Any]:
        """A refusal decision naming why."""
        return {"allowed": False, "dispatch_id": dispatch_id, "reason": reason}

    if not dispatch_id:
        return refuse("no AIPASS_DISPATCH_ID: only a dispatched session carries a grant")
    try:
        rows = open_grants(repo_root=repo_root, now=now)
    except OSError as exc:
        logger.warning("[grant] register unreadable, write refused for %s: %s", caller_branch, exc)
        return refuse(f"the dispatch register is unreadable: {exc}")
    row = next((r for r in rows if r.get("dispatch_id") == dispatch_id), None)
    if row is None:
        return refuse(f"dispatch {dispatch_id} is not open with a grant")
    if _seat(row.get("target")) != _seat(caller_branch):
        return refuse(f"dispatch {dispatch_id} was sent to {row.get('target')}, not {caller_branch}")
    if row.get("overdue"):
        return refuse(f"dispatch {dispatch_id} is past its expected_by")
    if row.get("monitor_alive") is not True:
        return refuse(f"dispatch {dispatch_id} has no monitor known to be alive")
    try:
        root = Path(row[GRANT_KEY]["root"])
        files = [root / f for f in row[GRANT_KEY]["files"]]
        dirs = [root / d for d in row[GRANT_KEY]["dirs"]]
    except (KeyError, TypeError) as exc:
        logger.warning("[grant] malformed grant on dispatch %s refused: %s", dispatch_id, exc)
        return refuse(f"dispatch {dispatch_id} carries a malformed grant")

    target = Path(os.path.normpath(os.path.abspath(target_path)))
    if target in files:
        return {"allowed": True, "dispatch_id": dispatch_id, "reason": f"{target} is a granted file"}
    if any(target.is_relative_to(d) for d in dirs):
        return {"allowed": True, "dispatch_id": dispatch_id, "reason": f"{target} is under a granted directory"}
    return refuse(f"{target} is outside dispatch {dispatch_id}'s grant")
