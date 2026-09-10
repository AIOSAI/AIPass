# =================== AIPass ====================
# Name: managers.py
# Description: Manager discovery — passports on this machine that own a project
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Manager discovery for release-notify (DPLAN-0335 leg 1).

Answers one question: which citizens on this machine own a project that
``aipass init update`` could update? A manager is a passport whose
``citizen_class`` reads ``manager`` — the key sits at the top level on some
schema versions, under ``identity`` on the 1.x/2.x passports the fleet
actually carries, and under ``metadata`` on the oldest, so all three are read.

Where we look is DECLARED, never guessed: the active rows of
``AIPASS_ROOTS.json`` (@memory's roots doctrine — a root nobody wrote down is
not a root) plus every directory under ``<aipass root>/projects/``. The AIPass
source repo itself is skipped by name: ``aipass init update`` updates a
project's scaffold FROM the source repo, so the source repo has no scaffold of
its own to update and devpulse would be mailing itself.
"""

import json
import os
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file

MODULE_NAME = "release_notify"

ROOTS_FILE = "AIPASS_ROOTS.json"
PROJECTS_DIRNAME = "projects"

# Pruned during the walk. .archive/.backup hold retired copies of live
# passports (11 of them under Vera-Studio alone), and mailing a retired
# manager is mailing nobody.
SKIP_DIR_NAMES = frozenset({".archive", ".backup", "node_modules", ".venv", "__pycache__", ".git"})

_ACTIVE = "active"
_MANAGER = "manager"


def aipass_root() -> Path:
    """The AIPass repo root, resolved from this module's own location.

    Walks up from ``__file__`` looking for the marker every AIPass checkout
    carries (``src/aipass/devpulse``) rather than counting parents, so a
    re-homed checkout or a different install prefix still resolves. No literal
    path anywhere: the module knows where it lives.

    Returns:
        The repository root that contains this branch.
    """
    here = module_file(__file__)
    for parent in here.parents:
        if (parent / "src" / "aipass" / "devpulse").is_dir():
            return parent
    # Fixed-layout fallback: handlers/release_notify/managers.py -> handlers ->
    # apps -> devpulse -> aipass -> src -> root. Reached only when the marker
    # walk fails, which means this file was copied out of its branch.
    parents = here.parents
    logger.warning(f"[{MODULE_NAME}] AIPass root marker not found above {here} — using the fixed layout")
    return parents[6] if len(parents) > 6 else here.parent


def devpulse_root() -> Path:
    """This branch's directory — the cwd every drone call is made from.

    Returns:
        The devpulse branch directory.
    """
    return module_file(__file__).parents[3]


def declared_roots(root: Path) -> tuple[list[Path], list[dict]]:
    """Read ``AIPASS_ROOTS.json`` and return its active roots.

    Args:
        root: The AIPass repo root, which is also what relative rows resolve against.

    Returns:
        tuple: (existing active root paths, skipped rows as {path, reason} dicts).
    """
    roots_file = root / ROOTS_FILE
    if not roots_file.exists():
        logger.warning(f"[{MODULE_NAME}] {ROOTS_FILE} not found at {roots_file} — external roots skipped")
        return [], [{"path": str(roots_file), "reason": f"{ROOTS_FILE} not found"}]

    try:
        declared = json.loads(roots_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error(f"[{MODULE_NAME}] {ROOTS_FILE} unreadable: {type(exc).__name__}: {exc}")
        return [], [{"path": str(roots_file), "reason": f"unreadable: {type(exc).__name__}: {exc}"}]

    found: list[Path] = []
    skipped: list[dict] = []
    for row in declared.get("roots", []):
        raw = str(row.get("path", "")).strip()
        status = str(row.get("status", "")).strip()
        if not raw:
            skipped.append({"path": "(blank)", "reason": "row carries no path"})
            continue
        if status != _ACTIVE:
            skipped.append({"path": raw, "reason": f"status is {status or '(none)'}, not {_ACTIVE}"})
            continue
        candidate = Path(raw)
        resolved = candidate if candidate.is_absolute() else (root / candidate)
        if not resolved.is_dir():
            skipped.append({"path": str(resolved), "reason": "declared root does not exist on this machine"})
            continue
        found.append(resolved.resolve())

    return found, skipped


def project_roots(root: Path) -> tuple[list[Path], list[dict]]:
    """Every live project directory under ``<aipass root>/projects/``.

    A dot-prefixed entry is not a project: ``projects/.archive/`` holds
    retired ones, and its passports are real managers of nothing — the first
    run of this command found @marketstand in there. Pruning inside the walk
    could not catch it, because the archive was the walk's own starting point.

    Args:
        root: The AIPass repo root.

    Returns:
        tuple: (project directories sorted by name, skipped {path, reason} dicts).
    """
    projects = root / PROJECTS_DIRNAME
    if not projects.is_dir():
        logger.info(f"[{MODULE_NAME}] no {PROJECTS_DIRNAME}/ directory under {root}")
        return [], []

    found: list[Path] = []
    skipped: list[dict] = []
    for path in sorted(projects.iterdir(), key=lambda p: p.name):
        if not path.is_dir():
            continue
        if path.name.startswith(".") or path.name in SKIP_DIR_NAMES:
            skipped.append({"path": str(path), "reason": "not a live project directory"})
            continue
        found.append(path.resolve())
    return found, skipped


def find_passports(search_root: Path) -> list[Path]:
    """Every ``.trinity/passport.json`` under ``search_root``, archives pruned.

    Prunes ``SKIP_DIR_NAMES`` from the walk in place rather than filtering
    paths afterwards — .venv in a project is a symlink to the AIPass runtime,
    and descending it would walk the whole fleet. ``os.walk`` and not
    ``Path.walk`` for the same reason ``Path.rglob`` is not used: the walk is
    the one place a directory NAME has to be edited mid-iteration; every path
    that comes out of it is a Path again.

    Args:
        search_root: A project root to search.

    Returns:
        Passport paths, sorted.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(search_root, onerror=_walk_error, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        directory = Path(dirpath)
        if directory.name == ".trinity" and "passport.json" in filenames:
            found.append(directory / "passport.json")
    return sorted(found)


def _walk_error(exc: OSError) -> None:
    """Report a directory the walk could not read instead of swallowing it.

    Args:
        exc: The OSError Path.walk hit on one directory.
    """
    logger.warning(f"[{MODULE_NAME}] cannot read {getattr(exc, 'filename', '?')}: {type(exc).__name__}: {exc}")


def read_passport(path: Path) -> dict | None:
    """Load one passport.

    Args:
        path: The passport.json to read.

    Returns:
        The passport dict, or None when it cannot be read or is not an object.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"[{MODULE_NAME}] passport unreadable {path}: {type(exc).__name__}: {exc}")
        return None
    if not isinstance(data, dict):
        logger.warning(f"[{MODULE_NAME}] passport at {path} is {type(data).__name__}, not an object")
        return None
    return data


def passport_citizen_class(passport: dict) -> str:
    """The passport's citizen_class, wherever the schema version put it.

    Args:
        passport: A loaded passport.

    Returns:
        The class string, or "" when the passport declares none.
    """
    for holder in (passport, passport.get("identity"), passport.get("metadata")):
        if isinstance(holder, dict):
            value = holder.get("citizen_class")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def passport_name(passport: dict, path: Path) -> str:
    """The citizen's name.

    Args:
        passport: A loaded passport.
        path: That passport's path, the last-resort source of the name.

    Returns:
        The declared name, else the directory that holds the .trinity/ folder.
    """
    sources = (
        (passport.get("branch_info"), "branch_name"),
        (passport, "name"),
        (passport.get("identity"), "name"),
    )
    for holder, key in sources:
        if isinstance(holder, dict):
            value = holder.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return path.parents[1].name


def passport_address(passport: dict, path: Path) -> str:
    """The ai_mail address to write to.

    ``identity.email`` first (the schema this command was specified against),
    then ``branch_info.email`` — which is where every live passport on this
    machine actually carries it — then a top-level ``email``, and finally the
    name lowercased with an @ in front.

    Args:
        passport: A loaded passport.
        path: That passport's path, for the name fallback.

    Returns:
        An @-prefixed address.
    """
    for holder in (passport.get("identity"), passport.get("branch_info"), passport):
        if isinstance(holder, dict):
            value = holder.get("email")
            if isinstance(value, str) and value.strip():
                address = value.strip()
                return address if address.startswith("@") else f"@{address}"
    return f"@{passport_name(passport, path).lower()}"


def discover_managers() -> dict:
    """Find every project manager on this machine.

    Returns:
        dict with ``roots`` (searched paths as strings), ``managers``
        (address / name / passport / root dicts, deduped by address, sorted by
        address) and ``skipped`` ({path, reason} dicts — an inactive root, an
        unreadable passport, a non-manager citizen, the source repo).
    """
    json_handler.log_operation("discover_managers", module_name=MODULE_NAME)
    root = aipass_root()
    source_repo = root / "src" / "aipass"

    external, skipped = declared_roots(root)
    internal, archived = project_roots(root)
    skipped.extend(archived)
    searched: list[Path] = []
    for candidate in external + internal:
        if candidate not in searched:
            searched.append(candidate)

    managers: list[dict] = []
    seen: set[str] = set()
    for search_root in searched:
        for passport_path in find_passports(search_root):
            if source_repo == passport_path or source_repo in passport_path.parents:
                skipped.append(
                    {
                        "path": str(passport_path),
                        "reason": "AIPass source repo — no scaffold of its own to update",
                    }
                )
                continue
            passport = read_passport(passport_path)
            if passport is None:
                skipped.append({"path": str(passport_path), "reason": "passport unreadable — see the log"})
                continue
            citizen_class = passport_citizen_class(passport)
            if citizen_class != _MANAGER:
                stated = citizen_class or "(none)"
                skipped.append(
                    {
                        "path": str(passport_path),
                        "reason": f"citizen_class is {stated}, not {_MANAGER}",
                    }
                )
                continue
            address = passport_address(passport, passport_path)
            if address in seen:
                skipped.append({"path": str(passport_path), "reason": f"{address} already found under another root"})
                continue
            seen.add(address)
            managers.append(
                {
                    "address": address,
                    "name": passport_name(passport, passport_path),
                    "passport": str(passport_path),
                    "root": str(search_root),
                }
            )

    managers.sort(key=lambda entry: entry["address"])
    logger.info(f"[{MODULE_NAME}] {len(managers)} managers across {len(searched)} roots, {len(skipped)} skipped")
    return {"roots": [str(path) for path in searched], "managers": managers, "skipped": skipped}
