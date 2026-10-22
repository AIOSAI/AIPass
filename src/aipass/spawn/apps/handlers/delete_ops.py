# =================== AIPass ====================
# Name: delete_ops.py
# Description: Delete handler — branch deletion by name or path, and whole-project retirement
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-22
# =============================================

"""Delete handler implementation for branch lifecycle management."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.aipass.shared.registry_discovery import registries_in
from aipass.ai_mail.apps.modules.door_verified_caller import is_verified_admin_caller, resolve_verified_caller
from aipass.hooks.apps.modules.door_trust_registry import read_registry as read_trust, registry_path as trust_path
from aipass.hooks.apps.modules.door_trust_registry import revoke as revoke_trust
from aipass.spawn.apps.handlers.deletion_receipts import build_receipt, measure, receipt_problem, write_receipts
from aipass.spawn.apps.handlers.passport_migration import repo_root
from aipass.spawn.apps.handlers.registry import (
    find_registry,
    is_protected,
    load_registry,
    save_registry,
    branches_as_list,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.repair_ops import ARCHIVE_EXCLUDE
from aipass.spawn.apps.handlers.json import json_handler


def _resolve_branch_dir(branch_name, registry_path, registry):
    """Find branch entry and directory from registry; (None, None) if not found."""
    project_root = registry_path.parent
    for entry in branches_as_list(registry.get("branches", [])):
        if entry.get("name", "").lower() == branch_name.lower():
            rel_path = entry.get("path", "")
            branch_dir = (project_root / rel_path).resolve() if rel_path else None
            return entry, branch_dir
    return None, None


def resolve_path_target(target):
    """Name the branch at a path from the registry that seals it; (name, registry_path, error)."""
    branch_dir = Path(target).expanduser().resolve()
    registry_path = find_registry(start_path=branch_dir)
    if registry_path is None:
        return "", None, f"No *_REGISTRY.json seals {branch_dir}"
    for entry in branches_as_list(load_registry(registry_path).get("branches", [])):
        rel_path = entry.get("path", "")
        if rel_path and (registry_path.parent / rel_path).resolve() == branch_dir:
            return entry.get("name", ""), registry_path, None
    return "", None, f"No branch at {branch_dir} in {registry_path}"


def _archive_branch(branch_dir, archive_dir):
    """Copy branch to archive directory, cleaning up on failure. Returns error text, None on success."""
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(str(branch_dir), str(archive_dir), ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE))
        logger.info(f"[delete] Archived to {archive_dir}")
        return None
    except Exception as exc:
        msg = f"Failed to create archive: {exc}"
        logger.error(f"[delete] {msg}")
        _cleanup_partial_archive(archive_dir)
        return msg


def _cleanup_partial_archive(archive_dir):
    """Remove partially-created archive directory."""
    if not archive_dir.exists():
        return
    try:
        shutil.rmtree(str(archive_dir))
    except Exception as cleanup_exc:
        logger.warning("[delete] Failed to clean up partial archive %s: %s", archive_dir, cleanup_exc)


def _unregister_archived_passport(archive_dir):
    """Set citizenship.registered false in the archived passport; error text, None on success or no passport."""
    passport_path = archive_dir / ".trinity" / "passport.json"
    if not passport_path.is_file():
        return None
    try:
        passport = json.loads(passport_path.read_text(encoding="utf-8"))
        passport.setdefault("citizenship", {})["registered"] = False
        atomic_write_text(passport_path, json.dumps(passport, indent=2, ensure_ascii=False) + "\n")
    except (OSError, ValueError, AttributeError) as exc:
        msg = f"Failed to unregister the archived passport {passport_path}: {exc}"
        logger.error(f"[delete] {msg}")
        return msg
    return None


def _remove_from_registry(registry, branch_name, registry_path):
    """Remove branch from registry and save; True if the save succeeded."""
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        for key in list(branches.keys()):
            if key.lower() == branch_name.lower() or branches[key].get("name", "").lower() == branch_name.lower():
                del branches[key]
        registry["branches"] = branches
    else:
        registry["branches"] = [b for b in branches if b.get("name", "").lower() != branch_name.lower()]
    registry["metadata"]["total_branches"] = len(branches_as_list(registry["branches"]))
    return save_registry(registry_path, registry)


def _error_result(branch_name, msg, archive_path="", registry_updated=False):
    """Build a failure result dict."""
    return {
        "branch": branch_name,
        "success": False,
        "archive_path": archive_path,
        "registry_updated": registry_updated,
        "error": msg,
    }


def delete_branch(
    branch_name: str,
    confirm: bool = True,
    dry_run: bool = False,
    retire: bool = False,
    registry_path=None,
    requested: str = "",
) -> dict:
    """Archive and deregister a branch; the archive is always written before removal.

    retire=True lets an active citizen through and archives its passport with registered false;
    the floor and the registry owner stay refused. registry_path=None reads the cwd's registry.
    """
    registry_path = registry_path or find_registry()
    if registry_path is None:
        # Without a registry the protection check cannot run, so the delete must not.
        msg = "Cannot delete: no *_REGISTRY.json found above the current directory"
        logger.error("[delete] %s", msg)
        return _error_result(branch_name, msg)

    protected, reason = is_protected(branch_name, registry_path=registry_path, count_passport=not retire)
    if protected:
        msg = f"Cannot delete '{branch_name}' — protected ({reason})"
        if not is_protected(branch_name, registry_path=registry_path, count_passport=False)[0]:
            msg += "; retire it with: drone @spawn delete @" + branch_name + " --retire"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)
    project_root = registry_path.parent
    registry = load_registry(registry_path)
    branch_entry, branch_dir = _resolve_branch_dir(branch_name, registry_path, registry)

    if branch_entry is None:
        msg = f"Branch '{branch_name}' not found in registry"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    if branch_dir is None or not branch_dir.is_dir():
        msg = f"Branch directory does not exist: {branch_dir}"
        logger.warning(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    # Protection is by name; this guards by location before the archive and removal see the path.
    root = project_root.resolve()
    if branch_dir == root or not branch_dir.is_relative_to(root):
        msg = f"Branch directory {branch_dir} is outside the project {root} - refusing to archive or remove it"
        logger.error(f"[delete] {msg}")
        return _error_result(branch_name, msg)

    if confirm and not dry_run:
        try:
            answer = input("Are you sure? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt) as e:
            logger.warning("Delete confirmation prompt interrupted: %s", e)
            answer = ""
        if answer != "y":
            return _error_result(branch_name, "Cancelled by user")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = project_root / ".archive" / "deleted_branches" / f"{branch_name}_{timestamp}"

    caller = resolve_verified_caller() or "unknown"
    receipt = build_receipt(
        lane="spawn_delete",
        caller=caller,
        requested=requested or branch_name,
        resolved=branch_dir,
        target=archive_dir,
        reason=f"deregistered from {registry_path}",
        measurement=measure(branch_dir),
    )

    if dry_run:
        logger.info(f"[delete] Dry run: would archive {branch_name} to {archive_dir}")
        return {
            "branch": branch_name,
            "success": True,
            "archive_path": str(archive_dir),
            "registry_updated": False,
            "dry_run": True,
            "retired": retire,
        }

    problem = receipt_problem([receipt])
    if problem:
        logger.error(f"[delete] {problem}")
        return _error_result(branch_name, problem)

    archive_error = _archive_branch(branch_dir, archive_dir)
    if archive_error:
        return _error_result(branch_name, archive_error)

    # The archived copy is flipped, never the live tree: a failure here leaves the branch registered and whole.
    if retire:
        unregister_error = _unregister_archived_passport(archive_dir)
        if unregister_error:
            _cleanup_partial_archive(archive_dir)
            return _error_result(branch_name, unregister_error)

    registry_updated = _remove_from_registry(registry, branch_name, registry_path)
    if registry_updated:
        logger.info(f"[delete] Removed {branch_name} from registry")
    else:
        logger.error(f"[delete] Failed to update registry after removing {branch_name}")

    try:
        shutil.rmtree(str(branch_dir))
        logger.info(f"[delete] Removed branch directory: {branch_dir}")
    except Exception as exc:
        msg = f"Archive created but failed to remove directory: {exc}"
        logger.error(f"[delete] {msg}")
        write_receipts([receipt], "failed", repo_root())
        return _error_result(branch_name, msg, str(archive_dir), registry_updated)

    write_receipts([receipt], "retired" if retire else "deleted", repo_root())

    # The archive is now the only copy, so whether .trinity went with it is logged here.
    archived_trinity = (
        sorted(p.name for p in (archive_dir / ".trinity").glob("*")) if (archive_dir / ".trinity").is_dir() else []
    )
    logger.info(
        "[spawn] RETIRED %s — archived to %s (trinity carried: %s)",
        branch_name,
        archive_dir,
        ", ".join(archived_trinity) if archived_trinity else "NONE",
    )
    json_handler.log_operation(
        "delete_executed",
        data={
            "branch": branch_name,
            "archive": str(archive_dir),
            "trinity_carried": archived_trinity,
            "caller": caller,
            "registry": str(registry_path),
        },
    )

    return {
        "branch": branch_name,
        "success": True,
        "archive_path": str(archive_dir),
        "registry_updated": registry_updated,
        "retired": retire,
    }


def _admin_seat() -> bool:
    """The ai_mail rail's five-leg admin verdict; a raising verifier refuses."""
    try:
        return bool(is_verified_admin_caller())
    except Exception as exc:
        logger.warning("[retire] admin verification raised, refusing: %s", exc)
        return False


def _refused(requested, msg):
    """A retire-project refusal: logged, nothing written."""
    logger.warning("[retire] %s", msg)
    return {"project": str(requested), "success": False, "error": msg, "rows": [], "archive_path": ""}


def _retire_rows(root, registry_path, archive_dir, requested, caller):
    """One row per thing retire-project removes: each citizen, the registry, the project root, the trust entry."""
    reason = f"retired project {root.name}, sealed by {registry_path}"
    citizens = []
    for entry in branches_as_list(load_registry(registry_path).get("branches", [])):
        branch_dir = (root / entry.get("path", "")).resolve()
        if entry.get("path") and branch_dir.is_dir() and branch_dir.is_relative_to(root) and branch_dir != root:
            citizens.append(branch_dir)
    things = [*citizens, registry_path, root]
    rows = [
        build_receipt(
            lane="spawn_retire",
            caller=caller,
            requested=requested,
            resolved=thing,
            target=archive_dir,
            reason=reason,
            measurement=measure(thing),
        )
        for thing in things
    ]
    if str(root) in read_trust()["projects"]:
        rows.append(
            build_receipt(
                lane="spawn_retire",
                caller=caller,
                requested=requested,
                resolved=trust_path(),
                target=archive_dir,
                reason=f"hooks trust entry for {root} revoked; {reason}",
                measurement={"kind": "trust_entry", "size_bytes": None, "entry_count": 1, "measured": "exact"},
            )
        )
    return citizens, rows


def retire_project(requested: str, dry_run: bool = False) -> dict:
    """Retire a whole project from the admin seat: archive into AIPass, flip passports, revoke trust, remove last.

    Every receipt row is built and validated before anything is written; dry_run reports them and writes nothing.
    """
    root = Path(requested).expanduser().resolve()
    aipass_root = repo_root().resolve()
    if aipass_root.is_relative_to(root):
        return _refused(requested, f"{root} is or holds the AIPass root - retire-project never removes it")
    if not root.is_dir():
        return _refused(requested, f"{root} is not a directory")
    sealing = registries_in(root)
    if not sealing:
        return _refused(requested, f"No *_REGISTRY.json in {root} - not a project root")
    admin = _admin_seat()
    if not dry_run and not admin:
        return _refused(requested, "retire-project runs from the verified admin seat only")

    registry_path = sealing[0].resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # The fleet's deleted-branches store: a retired project's own .archive leaves with its tree.
    archive_dir = aipass_root / ".archive" / "deleted_branches" / f"{root.name}_{timestamp}"
    citizens, rows = _retire_rows(root, registry_path, archive_dir, str(requested), resolve_verified_caller())
    result = {
        "project": str(root),
        "success": True,
        "dry_run": dry_run,
        "admin": admin,
        "rows": rows,
        "archive_path": str(archive_dir),
        "error": "",
    }
    if dry_run:
        logger.info("[retire] Dry run: %s would go, %d rows, archive %s", root, len(rows), archive_dir)
        return result

    problem = receipt_problem(rows)
    if problem:
        return _refused(requested, problem)

    archive_error = _archive_branch(root, archive_dir)
    if archive_error:
        return _refused(requested, archive_error)
    for citizen in citizens:
        unregister_error = _unregister_archived_passport(archive_dir / citizen.relative_to(root))
        if unregister_error:
            _cleanup_partial_archive(archive_dir)
            return _refused(requested, unregister_error)
    try:
        revoke_trust(str(root))
    except (OSError, ValueError) as exc:
        _cleanup_partial_archive(archive_dir)
        return _refused(requested, f"Could not revoke the hooks trust entry for {root}: {exc}")

    try:
        shutil.rmtree(str(root))
        outcome = "retired"
    except OSError as exc:
        outcome = "failed"
        result.update(success=False, error=f"Archived to {archive_dir} but the tree did not fully go: {exc}")
        logger.error("[retire] %s", result["error"])
    write_receipts(rows, outcome, aipass_root)
    logger.info("[spawn] RETIRED PROJECT %s — archived to %s, %d receipt rows", root, archive_dir, len(rows))
    json_handler.log_operation(
        "project_retired",
        data={"project": str(root), "archive": str(archive_dir), "caller": rows[0]["caller"], "outcome": outcome},
    )
    return result
