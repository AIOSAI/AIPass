# =================== AIPass ====================
# Name: write_ownership.py
# Version: 1.0.0
# Description: Who may write whose files: project roots and branch owners read from the registries
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-18
# Modified: 2026-09-18
# =============================================

"""Answers, for the edit gate's two lanes, whose file a write lands in and whether this seat may make it.

The owner's ruling, 2026-09-18 22:17 (devpulse 1d041cfc), after @memory's rollover
was found writing Vera Studio's .trinity files:

- An agent is sandboxed to its own files: the files in its directory.
- @devpulse edits anywhere, system-wide. The one seat (the verified admin rail,
  modules/admin_seat, never a name).
- @seedgo and @spawn edit any file inside AIPass and NEVER beyond it.
- A project's manager (its registry ``owner`` row: @vera in Vera Studio, like
  @devpulse in AIPass) edits her own project's files, within her project only.
- Everyone else: own files only. Reading is allowed; writing another's, never.

Until this module the gate drew those lines from path SHAPES: a project was any
directory holding a ``*_REGISTRY.json``, a branch was whatever sat at
src/<package>/<branch>, and three names were trusted wherever they stood. The
registry's rows were never read, so a manager had no standing, a Vera branch
called seedgo was trusted inside Vera, and a file outside every branch was
nobody's and open to everyone. Here the rows decide: a branch is a registry row
(its ``path``), a manager is a row with ``owner: true`` (spawn writes it to the
registry entry, the sealed authority, not the passport an agent can edit). The
src/<package>/<branch> shape survives only as the fallback where a project has
no rows to read.

WHAT THIS CANNOT SEE: a write made from Python by a service (a drone verb, a
rollover) never passes through a tool call, so no hook sees it. That fence is the
service's own to carry.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules.bash_writes import HELD_BY_INTERPRETER
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

#: Trusted AIPass-wide, and only inside the project whose registry is AIPASS_REGISTRY.json.
TRUSTED_CROSS_WRITERS: tuple[str, ...] = ("devpulse", "seedgo", "spawn")
AIPASS_REGISTRY = "AIPASS_REGISTRY.json"
# A project root is the nearest ancestor holding a *_REGISTRY.json, the marker
# @ai_mail's find_project_root uses (handlers/paths.py): the file fence and the mail
# fence draw the boundary in the same place, or an agent is refused a send and
# allowed the equivalent write (GH #733). One refinement, because trust no longer
# runs downward: a registry that PROVES it catalogues something else (a non-empty
# table with no "branches" key, like flow_json/PLAN_REGISTRY.json) marks no
# project, or @flow's own plan files would read as a foreign project to @flow.
# An unreadable or empty marker still counts: a boundary is never dropped on doubt.
PROJECT_MARKER = "*_REGISTRY.json"

_WHO = (
    "Who writes where (the owner's ruling, 2026-09-18): each agent its own branch; a project's manager "
    "(its registry owner) that whole project; @seedgo and @spawn all of AIPass; @devpulse everywhere."
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


def project_of(start: Path) -> Project | None:
    """The project *start* stands in: the nearest ancestor (itself included) holding a project registry.

    The walk starts AT *start*, not at its parent: a shell operand can name a
    directory, and starting one level up reads a write INTO a project root as a
    write into the tree that contains it. None when no project is found — a fence
    that cannot locate a boundary must not invent one.
    """
    current = _resolved(start)
    if current is None:
        return None
    for candidate in [current, *current.parents]:
        try:
            markers = sorted(candidate.glob(PROJECT_MARKER))
        except OSError as exc:
            logger.info("[HOOKS] write_ownership: project marker scan failed at %s: %s", candidate, exc)
            return None
        for marker in markers:
            data = _read(marker)
            if isinstance(data, dict) and data and "branches" not in data:
                continue
            return Project(candidate, marker, _branches(data, candidate))
    return None


def is_crossing(caller: Project | None, landing: Project | None) -> bool:
    """True when a write leaves the caller's project for another one, in ANY direction.

    Downward used to be trusted (the host writing into a project it contains), so
    every AIPass citizen could edit projects/baud. The ruling ended it: a nested
    project keeps its own registry, and only the verified admin seat reaches it.
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


def ownership_refusal(
    caller: Project | None, landing: Project | None, cwd: str, target: Path, how: str = ""
) -> str | None:
    """Why the seat at *cwd* may not write *target* inside its own project, or None when it may.

    Crossings are not decided here: the caller refuses them first and lets only
    the admin seat through. A target in no project at all (a temp file) is nobody's.
    *how* names the shell verb for the scripted lane; an interpreter's held paths
    are never convicted here, because a read cannot be told from a write and
    reading another branch is allowed.
    """
    if HELD_BY_INTERPRETER in how:
        return None
    if caller is not None and (landing is None or landing.root != caller.root):
        return None
    package = package_of(Path(cwd))
    seat = branch_at(caller, Path(cwd), package)
    if seat is None or seat.manager:
        return None
    if seat.name in TRUSTED_CROSS_WRITERS and (caller is None or caller.is_aipass):
        return None
    owner = branch_at(caller, target, package)
    if owner is not None and owner.path == seat.path:
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
