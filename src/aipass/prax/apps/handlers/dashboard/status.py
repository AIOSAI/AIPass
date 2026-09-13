# =================== AIPass ====================
# Name: status.py
# Description: Dashboard Status Calculation Handler
# Version: 0.4.0
# Created: 2026-02-25
# Modified: 2026-09-11
# =============================================

"""
Dashboard Status Handler

Handles status calculations and branch path resolution.
All business logic for dashboard status operations.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.monitoring.branch_detector import _exact_case_registries
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = get_direct_logger()


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd.

    Delegates to ``handlers/repo_root.py``. Prax carried eight private copies of
    this walk, every one ending ``return Path.cwd()`` — @memory reported the
    consequence with a traceback on 2026-08-31: the walk runs at IMPORT time in
    most of the fleet, so a deleted working directory crashed the import, and a
    registry-less checkout (every clean CI clone) resolved against wherever the
    shell stood.
    """
    return find_repo_root(Path(__file__))


AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def _read_todo_count(branch_path: Path) -> int:
    """Read todos[] length from .trinity/local.json."""
    local_path = branch_path / ".trinity" / "local.json"
    if not local_path.exists():
        return 0
    try:
        data = json.loads(local_path.read_text())
        return len(data.get("todos", []))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read todos from %s: %s", local_path, exc)
        return 0


def _read_mail_counts(branch_path: Path) -> tuple:
    """Read new/opened mail counts from .ai_mail.local/inbox.json."""
    inbox_path = branch_path / ".ai_mail.local" / "inbox.json"
    if not inbox_path.exists():
        return (0, 0)
    try:
        data = json.loads(inbox_path.read_text())
        new_mail = 0
        opened_mail = 0
        for msg in data.get("messages", []):
            status = msg.get("status", "")
            if status == "new" or (not status and not msg.get("read", False)):
                new_mail += 1
            elif status == "opened":
                opened_mail += 1
        return (new_mail, opened_mail)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read inbox from %s: %s", inbox_path, exc)
        return (0, 0)


def count_active_plans(flow_section: Dict) -> int:
    """Read a plan count out of the flow section, whichever shape it arrived in.

    Both writers now publish ``active_plans`` as an INT — @flow's module 2.0.0
    (2026-08-16, Patrick's ruling) dropped the full open-plan list from the
    section, and ``active_count`` no longer ships at all.

    The list branch stays for the dashboards written before that date: they carry
    the old shape on disk until their next write, and comparing a list against 0
    raises TypeError, which `update_section` swallows into a silent no-op
    (reported by @flow 2026-08-12).
    """
    raw = flow_section.get("active_plans", 0)
    if isinstance(raw, list):
        return len(raw)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        logger.warning(
            "Dashboard flow section carried an unreadable active_plans value (%r); counting it as 0. "
            "The rest of the quick status is unaffected and nothing was written to the flow section.",
            raw,
        )
        return 0


def merge_quick_status(existing: "Dict | None", computed: Dict) -> Dict:
    """Overlay freshly computed keys onto the existing block, keeping the rest.

    quick_status has several writers (prax refresh, @flow's push, write_section).
    Each used to assign a fresh dict over the whole block, so every writer
    silently deleted the keys it did not know about — Patrick saw a devpulse card
    reporting 0 todos against a local.json holding 9. The invariant, agreed with
    @flow: no writer deletes a key it did not write.
    """
    merged = dict(existing or {})
    merged.update(computed)
    return merged


def read_existing_quick_status(branch_path: "Path | None") -> Dict:
    """Read the quick_status block already on disk, for merging into a fresh build.

    The refresh path builds each dashboard from the template, so the previous
    block is gone before the merge can see it. This fetches it back.
    """
    if not branch_path:
        return {}
    dashboard_path = Path(branch_path) / "DASHBOARD.local.json"
    if not dashboard_path.exists():
        return {}
    try:
        data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Could not read the existing dashboard at %s (%s), so keys written by other services "
            "cannot be preserved on this refresh. prax's own counters are still correct and the "
            "file is rewritten, not deleted.",
            dashboard_path,
            type(exc).__name__,
        )
        return {}
    block = data.get("quick_status", {})
    return block if isinstance(block, dict) else {}


def calculate_quick_status(sections: Dict, branch_path: "Path | None" = None) -> Dict:
    """
    Calculate quick status from branch data sources.

    Sources counts directly from local files (inbox.json, local.json).

    This is the single implementation — `refresh.py` and `operations.py` delegate
    here. It used to exist as three near-identical copies, and only one of them
    grew the list-shape guard, which is exactly how the other two kept the bug.

    Args:
        sections: All dashboard sections
        branch_path: Optional path to branch root (for sourcing counts)

    Returns:
        Quick status dict with summary data
    """
    flow = sections.get("flow", {})

    if branch_path:
        new_mail, opened_mail = _read_mail_counts(branch_path)
        todo_count = _read_todo_count(branch_path)
    else:
        new_mail, opened_mail, todo_count = 0, 0, 0
    active_plans = count_active_plans(flow)

    # Every counter this function renders in `summary` also raises the flag.
    # It used to skip todo_count, so a branch with pending todos published
    # "1 todos" and action_required: False in the same block — @flow measured
    # the disagreement against their own writer, which does count them.
    action_required = new_mail > 0 or active_plans > 0 or todo_count > 0

    summary_parts = []
    if new_mail > 0:
        summary_parts.append(f"{new_mail} new emails")
    if opened_mail > 0:
        summary_parts.append(f"{opened_mail} opened")
    if active_plans > 0:
        summary_parts.append(f"{active_plans} active plans")
    if todo_count > 0:
        summary_parts.append(f"{todo_count} todos")

    result = {
        "new_mail": new_mail,
        "opened_mail": opened_mail,
        "active_plans": active_plans,
        "todo_count": todo_count,
        "action_required": action_required,
        "summary": ", ".join(summary_parts) if summary_parts else "All clear",
    }

    json_handler.log_operation(
        "status_calculated",
        {
            "action_required": action_required,
            "new_mail": new_mail,
            "active_plans": active_plans,
            "todo_count": todo_count,
        },
    )

    return result


def get_branch_paths() -> List[Path]:
    """
    Get all branch paths from registry

    Returns:
        List of branch paths

    Raises:
        FileNotFoundError: If AIPASS_REGISTRY.json doesn't exist
        json.JSONDecodeError: If registry is corrupted
    """
    if not AIPASS_REGISTRY.exists():
        raise FileNotFoundError(f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}")

    repo_root = _find_repo_root()
    data = json.loads(AIPASS_REGISTRY.read_text())
    paths = []
    for b in data.get("branches", []):
        raw = Path(b.get("path", ""))
        paths.append(raw if raw.is_absolute() else repo_root / raw)
    return paths


def _nearest_registries(start: Path) -> List[Path]:
    """The ``*_REGISTRY.json`` files in the nearest directory at or above ``start`` that holds any.

    Nearest wins, the way ``aipass init`` stamps one registry at a project root:
    a caller in ``Vera-Studio/src/vera_studio/verify`` gets
    ``Vera-Studio/VERA-STUDIO_REGISTRY.json``, and a caller anywhere in the
    AIPass tree gets ``AIPASS_REGISTRY.json`` itself.
    """
    for directory in (start, *start.parents):
        registries = _exact_case_registries(directory)
        if registries:
            return registries
    return []


def _declared_path(registry_file: Path, name: str) -> Optional[Path]:
    """The path ``registry_file`` declares for ``name``, or None.

    A relative path resolves against the registry's OWN directory, never the
    process cwd or AIPass's root: that is where the project that wrote it lives.
    """
    try:
        data = json.loads(registry_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Project registry %s is unreadable (%s); it resolves nothing", registry_file, exc)
        return None

    branches = data.get("branches", []) if isinstance(data, dict) else []
    for branch in branches:
        if not isinstance(branch, dict) or str(branch.get("name", "")).upper() != name:
            continue
        path_str = branch.get("path")
        if path_str:
            raw = Path(path_str)
            return raw if raw.is_absolute() else registry_file.parent / raw
    return None


def _caller_project_match(name: str, caller: Optional[Path]) -> Optional[Tuple[Path, Path]]:
    """``(registry file, branch path)`` for ``name`` in the caller's project registry, or None.

    The core registry is skipped here: it was already asked, and a caller
    inside AIPass finds it as its nearest.
    """
    if caller is None:
        return None

    core = AIPASS_REGISTRY.resolve()
    for registry_file in _nearest_registries(caller):
        if registry_file.resolve() == core:
            continue
        path = _declared_path(registry_file, name)
        if path is not None:
            return registry_file, path
    return None


def resolve_branch_path(branch_ref: str, caller: Optional[Path] = None) -> Path:
    """
    Resolve @branch reference to filesystem path.

    AIPASS_REGISTRY.json first, unchanged. On a miss, the caller's own project
    registry: the nearest ``*_REGISTRY.json`` at or above ``caller``
    (devpulse's ruling 2026-09-11, Vera Studio 77f3335d). Before that second
    step, ``drone @prax dashboard refresh @verify`` run from inside Vera-Studio
    answered "not found" and the branch's dashboard stayed stale. A name in
    both registries resolves to core, and the log says so.

    ``caller`` is an argument, never read here: a handler does not read the
    working directory (tests/test_repo_root.py sweeps for it). The dashboard
    module answers where the caller stands. With no caller this is core only,
    exactly what it was before.

    Handler-layer function: performs file I/O to read registry and
    resolve branch name to its directory path.

    Args:
        branch_ref: Branch reference like "@flow" or "@vera"
        caller: The directory the caller stands in, or None for core only

    Returns:
        Path to the branch directory

    Raises:
        FileNotFoundError: If registry missing or branch not found
    """
    name = branch_ref.lstrip("@").upper()

    if not AIPASS_REGISTRY.exists():
        raise FileNotFoundError("AIPASS_REGISTRY.json not found")

    repo_root = _find_repo_root()
    data = json.loads(AIPASS_REGISTRY.read_text())
    for branch in data.get("branches", []):
        if branch.get("name", "").upper() == name:
            raw = Path(branch["path"])
            path = raw if raw.is_absolute() else repo_root / raw
            if not path.exists():
                raise FileNotFoundError(f"Branch path does not exist: {path}")
            shadowed = _caller_project_match(name, caller)
            if shadowed is not None:
                logger.warning(
                    "@%s is declared in AIPASS_REGISTRY.json and in %s; the core row wins (%s), "
                    "so %s is not reachable by this name",
                    name.lower(),
                    shadowed[0],
                    path,
                    shadowed[1],
                )
            return path

    project = _caller_project_match(name, caller)
    if project is not None:
        registry_file, path = project
        if not path.exists():
            raise FileNotFoundError(f"Branch path does not exist: {path} (declared in {registry_file})")
        logger.info("Resolved @%s through the caller's project registry %s: %s", name.lower(), registry_file, path)
        return path

    raise FileNotFoundError(
        f"Branch '{name}' not found in registry (AIPASS_REGISTRY.json, then the caller's project registry)"
    )
