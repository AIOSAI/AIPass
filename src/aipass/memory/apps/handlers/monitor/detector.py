# =================== AIPass ====================
# Name: detector.py
# Description: Rollover Trigger Detection Handler
# Version: 0.7.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""
Rollover Trigger Detection Handler

Todos are counted (check_todos, one branch) but never fed to the fleet walk: it would roll an awake agent's pad.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

from aipass.memory.apps.handlers import repo_root, write_fence
from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

logger = get_system_logger()


def _find_repo_root() -> Path:
    """Repo root for this lane, by ``handlers/repo_root.py``; a local name because tests patch it here."""
    return repo_root.find_repo_root(caller="detector")


_REPO_ROOT = _find_repo_root()


def _find_caller_registries() -> List[Path]:
    """Registries reachable from the caller's cwd, inside the AIPass root, for THIS call only.

    Nothing found here is remembered. A registry outside the root is logged and never returned.
    """
    import os

    aipass_registry = (_REPO_ROOT / "AIPASS_REGISTRY.json").resolve()
    fence_root = Path(write_fence.ROOT).resolve()

    caller_cwd = (
        Path(os.environ.get("AIPASS_CALLER_CWD", "")).resolve() if os.environ.get("AIPASS_CALLER_CWD") else Path.cwd()
    )

    cwd_found: List[Path] = []
    for parent in [caller_cwd] + list(caller_cwd.parents):
        # EXACT CASE: a folding filesystem serves any lowercase *_registry.json in the caller's
        # repo, and the `break` below would stop at that bait before the real registry above it.
        for reg in repo_root.exactly_named(sorted(parent.glob("*_REGISTRY.json")), "_REGISTRY.json"):
            if reg.resolve() != aipass_registry:
                cwd_found.append(reg)
        if cwd_found:
            break

    registries: List[Path] = []
    for reg in cwd_found:
        refusal = write_fence.outside_root(reg.resolve(), fence_root)
        if refusal is not None:
            logger.info(f"[detector] Caller registry {reg} left out of scope: {refusal}")
            continue
        registries.append(reg)

    return registries


@dataclass
class RolloverTrigger:
    """Represents a file that needs rollover (v2 entry-count based)"""

    branch: str
    memory_type: str  # 'observations' or 'local'
    file_path: Path
    current_lines: int
    schema_version: str = "3.0.0"
    v2_reason: str = ""

    def __str__(self):
        return f"{self.branch}.{self.memory_type} ({self.v2_reason})"


@dataclass
class UndrainableFile:
    """A file over its limit that rollover cannot drain (a capped container is not a list)."""

    branch: str
    memory_type: str
    file_path: Path
    reasons: List[str]

    def __str__(self):
        return f"{self.branch}.{self.memory_type} ({'; '.join(self.reasons)})"


class RegistryUnreadable(RuntimeError):
    """A registry file exists but cannot be read as a registry.

    Raised rather than ``[]``: a walk that reads "no branches" does no rollover and reports success.
    """


def _read_single_registry(registry_path: Path, root: Path) -> List[Dict[str, Any]]:
    """Read branches from a single registry file, resolving paths against root; unreadable raises."""
    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            branches = data.get("branches", [])

            for branch in branches:
                raw_path = branch.get("path", "")
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = root / raw_path
                branch["path"] = str(resolved)

            return branches
    except Exception as e:
        raise RegistryUnreadable(f"Unreadable registry {registry_path}: {e}") from e


def _rows_or_skip(registry_path: Path) -> List[Dict[str, Any]]:
    """A resident or caller registry's rows; an unreadable one is logged at error and gives none."""
    try:
        return _read_single_registry(registry_path, registry_path.parent)
    except RegistryUnreadable as e:
        logger.error(f"[detector] {e} — its branches are left out of this walk")
    return []


def _read_registry() -> List[Dict[str, Any]]:
    """
    Read every registry this fleet covers: core, residents, then callers.

    Residents are named, not discovered: the glob is generous and ``accepted_resident_paths()``
    (the passport's residency) is what makes it safe. Callers are fenced to the AIPass root and
    nothing they found outlives the call. An unreadable core registry raises ``RegistryUnreadable``.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope

    branches = _read_single_registry(_REPO_ROOT / "AIPASS_REGISTRY.json", _REPO_ROOT)

    seen_paths = {b.get("path") for b in branches}
    accepted = registry_scope.accepted_resident_paths(_REPO_ROOT)
    for reg_path in registry_scope.resident_registry_paths(_REPO_ROOT):
        for branch in _rows_or_skip(reg_path):
            if branch.get("path") not in accepted or branch.get("path") in seen_paths:
                continue
            branches.append(branch)
            seen_paths.add(branch.get("path"))

    fence_root = Path(write_fence.ROOT).resolve()
    for reg_path in _find_caller_registries():
        for branch in _rows_or_skip(reg_path):
            if branch.get("path") in seen_paths:
                continue
            refusal = write_fence.outside_root(Path(branch["path"]).resolve(), fence_root)
            if refusal is not None:
                logger.info(f"[detector] Branch {branch.get('name')} in {reg_path} left out of scope: {refusal}")
                continue
            branches.append(branch)
            seen_paths.add(branch.get("path"))

    return branches


def read_scope() -> List[Dict[str, Any]]:
    """Every branch a READ-ONLY lane may name: the write scope plus declared externals.

    ``_read_registry()`` is the WRITE scope and stops at the repo edge. Externals come only from
    roots declared in ``AIPASS_ROOTS.json``, never a caller's cwd. Nothing resolved here may be written.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope

    branches = _read_registry()
    seen_paths = {str(Path(branch["path"]).resolve()) for branch in branches if branch.get("path")}

    # name_from="path": the directory is the address; a registry may spell the name differently.
    for item in registry_scope.external_branches(_REPO_ROOT, name_from="path"):
        key = str(Path(item["path"]).resolve())
        if key in seen_paths:
            continue
        branches.append({**item, "path": str(item["path"])})
        seen_paths.add(key)

    return branches


def _get_memory_file_path(branch: Dict, memory_type: str) -> Path | None:
    """Path to a branch's ``.trinity/{memory_type}.json``, or None if not found."""
    raw_path = branch.get("path", "")
    if not raw_path:
        return None
    branch_path = Path(raw_path)
    if not branch_path.exists():
        return None

    file_path = branch_path / ".trinity" / f"{memory_type}.json"

    return file_path if file_path.exists() else None


def _count_file_lines(file_path: Path) -> int:
    """Count physical lines in memory file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return len(f.readlines())
    except Exception as e:
        logger.warning(f"[detector] Failed to count lines in {file_path}: {e}")
        return 0


_TEMPLATES_DIR = module_file(__file__).parents[3] / "templates"
_TEMPLATE_MAP = {
    "local": _TEMPLATES_DIR / "LOCAL.template.json",
    "observations": _TEMPLATES_DIR / "OBSERVATIONS.template.json",
}


def _recreate_trinity_file(branch_path: Path, branch_name: str, memory_type: str) -> Path | None:
    """Recreate a missing .trinity file from canonical template (never outside the AIPass root)."""
    trinity_dir = branch_path / ".trinity"
    file_path = trinity_dir / f"{memory_type}.json"
    # Refused before the mkdir, which is already a write.
    if write_fence.fence_write(file_path, lane="recreate_trinity_file") is not None:
        return None

    template_path = _TEMPLATE_MAP.get(memory_type)
    if not template_path or not template_path.exists():
        logger.warning(f"[detector] No template for {memory_type}")
        return None

    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[detector] Failed to read template {template_path}: {e}")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    lower_name = branch_name.lower()

    def _walk(val):
        if isinstance(val, str):
            return val.replace("{{BRANCH}}", lower_name).replace("{{DATE}}", today)
        if isinstance(val, list):
            return [_walk(item) for item in val]
        if isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    data = _walk(template)

    trinity_dir.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info(f"[detector] Recreated {file_path}")
        json_handler.log_operation(
            "recreate_trinity_file",
            {"branch": branch_name, "type": memory_type, "path": str(file_path)},
        )
        return file_path
    except OSError as e:
        logger.warning(f"[detector] Failed to write {file_path}: {e}")
        return None


def _limits_for(file_path: Path) -> tuple[str, str, Dict[str, Any]]:
    """The v2 limits for one memory file -> ``(branch_name, file_type, file_limits)``.

    per_branch[branch][file_type], falling back to defaults[file_type]; ``{}`` when neither has any.
    """
    if file_path.parent.name == ".trinity":
        branch_name = file_path.parents[1].name.lower()
        file_type = file_path.stem.split(".")[0]
    else:
        branch_name = file_path.stem.split(".")[0].lower()
        file_type = file_path.stem.split(".")[-1]

    cfg = config_loader.section("rollover")
    file_limits = cfg.get("per_branch", {}).get(branch_name, {}).get(file_type, {})
    if not file_limits:
        file_limits = cfg.get("defaults", {}).get(file_type, {})
    return branch_name, file_type, file_limits


# The capped containers, in the order a reason line names them.
_CAPPED_CONTAINERS = ("sessions", "key_learnings", "observations")


def undrainable_in(data: Any, file_limits: Dict[str, Any]) -> List[str]:
    """Capped containers over their count that rollover cannot drain — held as a dict, not a list.

    Only a list says which entries are oldest; a 2.0.0 dict never drains, so it is reported, not triggered.
    Pure and shared with the extractor, so the two cannot disagree.
    """
    if not isinstance(data, dict):
        return []
    meta = data.get("document_metadata")
    schema = meta.get("schema_version", "unknown") if isinstance(meta, dict) else "unknown"
    reasons = []
    for name in _CAPPED_CONTAINERS:
        limits = file_limits.get(name)
        count = limits.get("count") if isinstance(limits, dict) else None
        container = data.get(name)
        if count is not None and isinstance(container, dict) and len(container) > count:
            reasons.append(f"{len(container)}/{count} {name} held as a dict, not a list (schema {schema})")
    return reasons


def undrainable_containers(file_path: Path) -> List[str]:
    """``undrainable_in`` for one file on disk; ``[]`` when it cannot be read or has no limits.

    ``_should_rollover`` already reports both in the same walk.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    _branch, _type, file_limits = _limits_for(file_path)
    return undrainable_in(data, file_limits)


def _should_rollover(file_path: Path) -> tuple[bool, int, str, str]:
    """
    Check if file should rollover -> (should_rollover, current_lines, schema_version, v2_reason).

    Fires only ABOVE the limit: the extractor drains `len - limit`, so `>=` here would spin forever.
    """
    current_lines = _count_file_lines(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[detector] PARSE FAILURE for {file_path}: {e} — skipping rollover check")
        return (False, current_lines, "3.0.0", "parse failure — skipped")

    branch_name, file_type, file_limits = _limits_for(file_path)

    if not file_limits:
        logger.warning(
            f"[detector] CONFIG GAP: no v2 limits for branch={branch_name} file_type={file_type} "
            f"in per_branch or defaults — skipping rollover"
        )
        return (False, current_lines, "3.0.0", f"config gap for {branch_name}/{file_type}")

    reasons = []

    session_limits = file_limits.get("sessions", {})
    max_sessions = session_limits.get("count")
    auto_compact_cap = session_limits.get("auto_compact_cap")
    if max_sessions is not None or auto_compact_cap is not None:
        sessions = data.get("sessions", [])
        if isinstance(sessions, list):
            auto_count = sum(1 for e in sessions if isinstance(e, dict) and e.get("status") == "auto-compact")
            regular_count = len(sessions) - auto_count
            if auto_compact_cap is not None and auto_count > auto_compact_cap:
                reasons.append(f"{auto_count}/{auto_compact_cap} auto-compact snapshots")
            if max_sessions is not None and regular_count > max_sessions:
                reasons.append(f"{regular_count}/{max_sessions} sessions")

    # A list only: the extractor drains lists only, so a dict is reported by undrainable_containers().
    max_key_learnings = file_limits.get("key_learnings", {}).get("count")
    if max_key_learnings is not None:
        key_learnings = data.get("key_learnings", [])
        if isinstance(key_learnings, list) and len(key_learnings) > max_key_learnings:
            reasons.append(f"{len(key_learnings)}/{max_key_learnings} key_learnings")

    max_observations = file_limits.get("observations", {}).get("count")
    if max_observations is not None:
        observations = data.get("observations", [])
        if isinstance(observations, list) and len(observations) > max_observations:
            reasons.append(f"{len(observations)}/{max_observations} observations")

    if reasons:
        return (True, current_lines, "3.0.0", ", ".join(reasons))

    return (False, current_lines, "3.0.0", "")


def check_all_branches() -> Dict[str, Any]:
    """
    Check all branches for rollover triggers

    ``undrainable`` files never trigger and never go silent: one WARNING per file per walk.
    """
    triggers = []
    undrainable: List[UndrainableFile] = []

    try:
        branches = _read_registry()
    except RegistryUnreadable as e:
        logger.error(f"[detector] {e}")
        return {"success": False, "error": str(e), "triggers": [], "count": 0, "undrainable": []}
    if not branches:
        return {"success": True, "triggers": [], "count": 0, "undrainable": [], "message": "No branches in registry"}

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")

        for memory_type in ["observations", "local"]:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                branch_path = Path(branch.get("path", ""))
                if branch_path.exists():
                    file_path = _recreate_trinity_file(branch_path, branch_name, memory_type)
                if file_path is None:
                    continue

            should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

            if should_trigger:
                trigger = RolloverTrigger(
                    branch=branch_name,
                    memory_type=memory_type,
                    file_path=file_path,
                    current_lines=current_lines,
                    schema_version=schema_ver,
                    v2_reason=v2_reason,
                )
                triggers.append(trigger)

            reasons = undrainable_containers(file_path)
            if reasons:
                stuck = UndrainableFile(
                    branch=branch_name, memory_type=memory_type, file_path=file_path, reasons=reasons
                )
                undrainable.append(stuck)
                logger.warning(
                    f"[detector] UNDRAINABLE {stuck} — rollover drains lists only, so this stays over its "
                    f"limit on every run until the container is migrated to the 3.0.0 list shape"
                )

    json_handler.log_operation(
        "check_all_branches",
        {"branches_checked": len(branches), "triggers_found": len(triggers), "undrainable": len(undrainable)},
    )

    return {
        "success": True,
        "triggers": triggers,
        "count": len(triggers),
        "undrainable": undrainable,
        "message": f"Found {len(triggers)} rollover triggers" if triggers else "No rollover triggers detected",
    }


def check_single_file(file_path: Path) -> Dict[str, Any]:
    """Check single file for rollover trigger"""
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

    if should_trigger:
        if file_path.parent.name == ".trinity":
            branch_name = file_path.parents[1].name
            memory_type = file_path.stem  # "local" or "observations"
        else:
            # Legacy flat files: SEEDGO.observations.json
            parts = file_path.stem.split(".")
            branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
            memory_type = parts[1] if len(parts) > 1 else "unknown"

        trigger = RolloverTrigger(
            branch=branch_name,
            memory_type=memory_type,
            file_path=file_path,
            current_lines=current_lines,
            schema_version=schema_ver,
            v2_reason=v2_reason,
        )

        return {"success": True, "trigger": trigger, "should_rollover": True}
    else:
        return {
            "success": True,
            "should_rollover": False,
            "current_lines": current_lines,
            "schema_version": schema_ver,
            "v2_reason": v2_reason,
        }


def check_todos(file_path: Path, branch_name: str | None = None) -> Dict[str, Any]:
    """
    Count ONE branch's todo pad against its configured count. COUNT ONLY.

    Kept out of the fleet walk on purpose; the count shares the roll's resolver so they cannot disagree.
    """
    name = branch_name or file_path.parents[1].name
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(f"[detector] Cannot read todos from {file_path}: {e}")
        return {"success": False, "error": f"cannot read {file_path.name}: {e}"}

    todos = data.get("todos", []) if isinstance(data, dict) else None
    if not isinstance(todos, list):
        return {"success": False, "error": f"'todos' in {file_path.name} is not a list"}

    count = config_loader.get_todos_count(name)
    pad = len(todos)
    over = count is not None and pad > count
    return {
        "success": True,
        "branch": name,
        "pad": pad,
        "count": count,
        "over": over,
        "excess": pad - count if count is not None and over else 0,
    }


def get_rollover_stats() -> Dict[str, Any]:
    """Get rollover statistics for all branches"""
    stats = {
        "success": True,
        "total_branches": 0,
        "files_checked": 0,
        "files_ready": 0,
        "files_undrainable": 0,
        "branches": {},
    }

    try:
        branches = _read_registry()
    except RegistryUnreadable as e:
        logger.error(f"[detector] {e}")
        return {"success": False, "error": str(e)}
    stats["total_branches"] = len(branches)

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")
        branch_stats = {}

        for memory_type in ["observations", "local"]:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue

            stats["files_checked"] += 1
            should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

            stat_entry: Dict[str, Any] = {
                "current": current_lines,
                "ready": should_trigger,
                "schema_version": schema_ver,
            }
            if v2_reason:
                stat_entry["v2_reason"] = v2_reason
            undrainable = undrainable_containers(file_path)
            if undrainable:
                stat_entry["undrainable"] = undrainable
                stats["files_undrainable"] += 1

            branch_stats[memory_type] = stat_entry

            if should_trigger:
                stats["files_ready"] += 1

        if branch_stats:
            stats["branches"][branch_name] = branch_stats

    return stats
