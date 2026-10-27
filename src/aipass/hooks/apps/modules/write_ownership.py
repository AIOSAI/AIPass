# =================== AIPass ====================
# Name: write_ownership.py
# Version: 2.5.0
# Description: Who may write whose files: project roots and branch owners read from the registries
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-18
# Modified: 2026-10-26
# =============================================

"""Answers, for the edit gate's two lanes, whose file a write lands in and whether this seat may make it.

Each agent writes its own branch; a non-AIPass project's manager row writes its whole project,
its citizens' branches included; only the verified admin seat (a grant, never a name) writes anywhere.
Registry rows decide (``owner: true`` marks the manager); the src/<package>/<branch> shape is
the fallback only where a project has no rows. Blind spot: a write a service makes from Python.
"""

import errno
import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules import admin_seat
from aipass.hooks.apps.modules.bash_writes import HELD_BY_INTERPRETER
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

AIPASS_REGISTRY = "AIPASS_REGISTRY.json"
# Same marker as @ai_mail's find_project_root, so file and mail fences agree. A non-empty
# registry with no "branches" key (flow's plan registry) marks no project; an unreadable one still does.
PROJECT_MARKER = "*_REGISTRY.json"

# Windows has no pathconf, so its long-path ceiling stands in.
_WINDOWS_PATH_MAX = 32767
_SHOWN_CHARS = 120

_WHO = (
    "Who writes where (the owner's rulings, 2026-09-18 and 2026-09-30): each agent its own branch; "
    "a project's manager its project's files outside every branch row (2026-10-16) "
    "and inside its citizens' branches (2026-10-26), AIPass excepted; "
    "the verified admin seat (@devpulse) everywhere."
)


@dataclass(frozen=True)
class Branch:
    """A branch directory: a registry row, or the src/<package>/<branch> shape where there are no rows."""

    name: str
    path: Path
    manager: bool = False


@dataclass(frozen=True)
class Project:
    """A project root, the registry that marks it, and its rows (None when there is no table to read)."""

    root: Path
    registry: Path
    branches: tuple[Branch, ...] | None

    @property
    def is_aipass(self) -> bool:
        """True for the AIPass project itself: its registry is AIPASS_REGISTRY.json, as rollover reads it."""
        return self.registry.name == AIPASS_REGISTRY

    @property
    def manager(self) -> Branch | None:
        """The row flagged ``owner: true``, or None when the registry names no manager."""
        return next((b for b in self.branches or () if b.manager), None)


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        logger.info("[HOOKS] write_ownership: unresolvable path %s: %s", path, exc)
        return None


def _read(marker: Path) -> object:
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] write_ownership: registry unreadable, still a boundary: %s: %s", marker, exc)
        return None


def _branches(data: object, root: Path) -> tuple[Branch, ...] | None:
    """The rows of a registry's branches table, list or dict shaped (spawn's branches_as_list)."""
    table = data.get("branches") if isinstance(data, dict) else None
    if isinstance(table, dict):
        table = list(table.values())
    if not isinstance(table, list):
        return None
    rows = []
    for row in table:
        name = row.get("name") if isinstance(row, dict) else None
        where = row.get("path") if isinstance(row, dict) else None
        if not isinstance(name, str) or not isinstance(where, str) or not name or not where:
            continue
        path = _resolved(Path(where) if Path(where).is_absolute() else root / where)
        if path is not None:
            rows.append(Branch(name.lower(), path, row.get("owner") is True))
    return tuple(rows)


class ProjectUnreadable(OSError):
    """A directory on the project walk could not be listed: whose file a write lands in is unknown."""


def project_of(start: Path) -> Project | None:
    """The project *start* stands in: the nearest ancestor (itself included) holding a project registry.

    Starts AT *start*: a shell operand can name a project root itself.
    Raises ProjectUnreadable rather than read an unlistable directory as "no project".
    """
    current = _resolved(start)
    if current is None:
        return None
    for candidate in [current, *current.parents]:
        if not candidate.is_dir():  # a file, or a target not yet written: nothing to list (glob's [] there)
            continue
        try:
            with os.scandir(candidate) as entries:
                markers = sorted(Path(e.path) for e in entries if fnmatch.fnmatch(e.name, PROJECT_MARKER))
        except OSError as exc:
            raise ProjectUnreadable(f"{candidate} cannot be listed, so its registry cannot be read: {exc}") from exc
        for marker in markers:
            data = _read(marker)
            if isinstance(data, dict) and data and "branches" not in data:
                continue
            return Project(candidate, marker, _branches(data, candidate))
    return None


def _path_max() -> int:
    """The host's PATH_MAX; Windows publishes none, so its long-path ceiling. 0 when unknown: the probe alone judges."""
    pathconf = getattr(os, "pathconf", None)
    if pathconf is None:
        return _WINDOWS_PATH_MAX
    try:
        return pathconf("/", "PC_PATH_MAX")
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] write_ownership: PATH_MAX unpublished here, the probe alone judges length: %s", exc)
        return 0


def unprobeable(targets: list[tuple[Path, str]]) -> str | None:
    """Why a shell target cannot be placed on disk, in one line, or None when every one can (devpulse 729ffaa9).

    The call is still refused; this only turns project_of's OSError into a readable reason.
    """
    limit = _path_max()
    for target, how in targets:
        text = str(target)
        try:
            if limit and len(text) > limit:
                raise OSError(errno.ENAMETOOLONG, f"longer than PATH_MAX ({limit})")
            os.stat(target)
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTDIR):  # not written yet
                continue
            name = errno.errorcode.get(exc.errno or 0, type(exc).__name__)
            shown = text if len(text) <= _SHOWN_CHARS else f"{text[:_SHOWN_CHARS]}… ({len(text)} chars)"
            return f"edit_gate cannot probe a path this call names ({name}), so it is refused: {shown} ({how})"
    return None


def is_crossing(caller: Project | None, landing: Project | None) -> bool:
    """True when a write leaves the caller's project for another one, in ANY direction.

    Downward too: a nested project keeps its own registry; only the admin seat reaches it.
    """
    return caller is not None and landing is not None and landing.root != caller.root


def package_of(cwd: Path) -> str:
    """The <package> of a src/<package>/<branch> seat, for the path-shape fallback; "" when there is none."""
    parts = cwd.parts
    for i, part in enumerate(parts):
        if part == "src" and i + 2 < len(parts):
            return parts[i + 1]
    return ""


def branch_at(project: Project | None, path: Path, package: str) -> Branch | None:
    """The branch whose directory holds *path*: the deepest registry row, else the path shape."""
    resolved = _resolved(path)
    if resolved is None:
        return None
    if project is not None and project.branches:
        rows = [b for b in project.branches if b.path == resolved or b.path in resolved.parents]
        if rows:
            return max(rows, key=lambda b: len(b.path.parts))
    parts = resolved.parts
    for i, part in enumerate(parts):
        if package and part == package and i > 0 and parts[i - 1] == "src" and i + 1 < len(parts):
            return Branch(parts[i + 1].lower(), Path(*parts[: i + 2]))
    return None


def in_a_branch(path: Path) -> bool:
    """True when *path* is a branch directory or inside one: its project's rows, else the src/<package>/<branch> shape.

    src/aipass itself, a project root or anything above a branch is no branch's.
    """
    return branch_at(project_of(path), path, package_of(path)) is not None


def ownership_refusal(
    caller: Project | None, landing: Project | None, cwd: str, target: Path, how: str = ""
) -> str | None:
    """Why the seat at *cwd* may not write *target* inside its own project, or None when it may.

    Crossings are the caller's to refuse. The admin grant is asked last: the rail does file I/O.
    Interpreter-held paths pass: a read cannot be told from a write, and reading is allowed.
    """
    if HELD_BY_INTERPRETER in how:
        return None
    if caller is not None and (landing is None or landing.root != caller.root):
        return None
    package = package_of(Path(cwd))
    seat = branch_at(caller, Path(cwd), package)
    if seat is None:
        return None
    owner = branch_at(caller, target, package)
    if owner is not None and owner.path == seat.path:
        return None
    refusal = _refusal(caller, seat, owner, target, how)
    if refusal is None or admin_seat.is_admin_seat(cwd):
        return None
    return refusal


def _refusal(caller: Project | None, seat: Branch, owner: Branch | None, target: Path, how: str) -> str | None:
    """The refusal text for a write by *seat* that lands outside it, or None when the target is nobody's or the seat is its project's manager."""
    if caller is not None and caller.manager is not None and caller.manager.path == seat.path and not caller.is_aipass:
        return None
    lane = f" ({how})" if how else ""
    if owner is not None:
        verb = "email" if owner.manager else "dispatch"
        return (
            f"Cross-branch write blocked{lane}: '{seat.name}' cannot write to '{owner.name}'.\nTarget: {target}\n"
            f'{_WHO}\nTo change it, ask its owner: drone @ai_mail {verb} @{owner.name} "Subject" "Body"'
        )
    if caller is None or caller.branches is None:
        return None
    manager = caller.manager.name if caller.manager else "the project manager"
    return (
        f"Project-level write blocked{lane}: '{seat.name}' cannot write {target}.\n"
        f"It sits in project '{caller.root.name}' outside every branch row, so it is @{manager}'s.\n"
        f'{_WHO}\nTo change it: drone @ai_mail email @{manager} "Subject" "Body"'
    )


def print_introspection() -> None:
    """Print module structure for drone routing: the rule and its one blind spot, never a live verdict."""
    CONSOLE.print("[bold cyan]write_ownership[/bold cyan] — who may write whose files, read from the registries")
    CONSOLE.print("[dim]Consumed by handlers/security/edit_gate.py (tool lane and scripted lane).[/dim]")
    CONSOLE.print(f"[dim]{_WHO}[/dim]")
    CONSOLE.print("[yellow]Cannot see:[/yellow] a write a service makes from Python. That fence is the service's own.")
