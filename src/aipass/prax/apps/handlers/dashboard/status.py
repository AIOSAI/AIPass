# =================== AIPass ====================
# Name: status.py
# Description: Dashboard Status Calculation Handler
# Version: 0.5.0
# Created: 2026-02-25
# Modified: 2026-10-23
# =============================================

"""
Dashboard Status Handler

Reference: docs/dashboard.md
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
    """Walk up from this file to find the repo root, never reading the cwd."""
    return find_repo_root(Path(__file__))


AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def _read_todo_count(branch_path: Path) -> Optional[int]:
    """Read todos[] length from .trinity/local.json."""
    # None, not 0, for an unreadable file: 0 would publish a false empty count.
    local_path = branch_path / ".trinity" / "local.json"
    if not local_path.exists():
        return 0
    try:
        data = json.loads(local_path.read_text())
        return len(data.get("todos", []))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read todos from %s: %s", local_path, exc)
        return None


def _read_mail_counts(branch_path: Path) -> "Tuple[int, int] | None":
    """Read new/opened mail counts from .ai_mail.local/inbox.json; None when it is unreadable."""
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
    except (json.JSONDecodeError, OSError, AttributeError) as exc:
        logger.warning("Failed to read inbox from %s: %s", inbox_path, exc)
        return None


def count_active_plans(flow_section: Dict) -> int:
    """Read a plan count out of the flow section, whichever shape it arrived in."""
    # Writers publish an int; old dashboards on disk still carry a list until rewritten.
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
    """Overlay freshly computed keys onto the existing block, keeping the rest."""
    # Several writers share quick_status; the invariant with @flow: no writer deletes a key it did not write.
    merged = dict(existing or {})
    merged.update(computed)
    return merged


def calculate_quick_status(sections: Dict, branch_path: "Path | None" = None) -> Dict:
    """Calculate quick status from branch data sources."""
    # The single implementation: refresh.py, operations.py and template_pusher.py all call it.
    flow = sections.get("flow", {})

    if branch_path:
        mail_counts = _read_mail_counts(branch_path)
        todo_count = _read_todo_count(branch_path)
    else:
        mail_counts, todo_count = (0, 0), 0
    active_plans = count_active_plans(flow)
    # Unreadable local.json or inbox: its keys are left out so the merge keeps the last counts written.
    mail_unknown = mail_counts is None
    new_mail, opened_mail = mail_counts or (0, 0)
    todos_unknown = todo_count is None
    todo_count = todo_count or 0

    # Every counter rendered in `summary` raises the flag; @flow's writer counts todos the same way.
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
    if mail_unknown:
        summary_parts.append("mail unreadable")
    if todos_unknown:
        summary_parts.append("todos unreadable")

    result = {
        "new_mail": new_mail,
        "opened_mail": opened_mail,
        "active_plans": active_plans,
        "todo_count": todo_count,
        "action_required": action_required,
        "summary": ", ".join(summary_parts) if summary_parts else "All clear",
    }
    if mail_unknown:
        del result["new_mail"], result["opened_mail"]
    if todos_unknown:
        del result["todo_count"]

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
    """Get all branch paths from registry"""
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
    """The ``*_REGISTRY.json`` files in the nearest directory at or above ``start`` that holds any."""
    for directory in (start, *start.parents):
        registries = _exact_case_registries(directory)
        if registries:
            return registries
    return []


def _declared_path(registry_file: Path, name: str) -> Optional[Path]:
    """The path ``registry_file`` declares for ``name``, or None."""
    # Relative paths resolve against the registry's own directory, not the cwd or AIPass's root.
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
    """``(registry file, branch path)`` for ``name`` in the caller's project registry, or None."""
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
    """Resolve @branch reference to filesystem path."""
    # Core registry first, then the caller's nearest project registry. caller is passed in:
    # handlers never read the cwd (tests/test_repo_root.py sweeps for it).
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
