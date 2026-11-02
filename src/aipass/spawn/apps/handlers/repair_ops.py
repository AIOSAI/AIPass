# =================== AIPass ====================
# Name: repair_ops.py
# Description: Repair handler — move branches, update registry paths, clean pollution
# Version: 1.1.0
# Created: 2026-05-15
# Modified: 2026-11-02
# =============================================

"""Repair handler implementation for project structure fixes.
Reference: docs/registry_and_repair.md
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    is_protected,
    load_registry,
    registry_lock,
    save_registry,
    branches_as_list,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler

# Rebuildable noise only: .git history and .chroma vectors go into the archive, since the original is removed.
ARCHIVE_EXCLUDE = {".venv", "__pycache__", "node_modules", ".pytest_cache"}


REGISTRY_SUFFIX = "_REGISTRY.json"


def _list_registry_candidates(root):
    """Return what the filesystem lists for ``*_REGISTRY.json`` inside ``root`` — a test seam for the glob."""
    return root.glob("*" + REGISTRY_SUFFIX)


def _registry_in(root):
    """Return the fleet registry directly inside ``root``, or None.

    The suffix is re-checked case-SENSITIVELY: on case-insensitive volumes the glob also returns dotted
    lowercase ``*_registry.json`` files (``.template_registry.json``), which sort first. Never check the
    stem: external projects name their registry after themselves.
    """
    root = Path(root)
    for candidate in sorted(_list_registry_candidates(root)):
        if candidate.name.endswith(REGISTRY_SUFFIX):
            return candidate
    return None


def update_registry_path(registry_path, branch_name, new_path):
    """Update a branch's path in the registry without re-creating the entry.

    Returns False if the branch is not found; every other field is preserved.
    """
    registry_path = Path(registry_path)
    with registry_lock(registry_path):
        registry = load_registry(registry_path)
        branches = registry.get("branches", [])
        branch_list = branches_as_list(branches)

        updated = False
        for entry in branch_list:
            if entry.get("name", "").lower() == branch_name.lower():
                old_path = entry.get("path", "")
                entry["path"] = Path(new_path).as_posix()
                entry["last_active"] = datetime.now().strftime("%Y-%m-%d")
                logger.info(
                    "[repair] Updated registry path for %s: %s → %s",
                    branch_name,
                    old_path,
                    new_path,
                )
                updated = True
                break

        if not updated:
            logger.warning("[repair] Branch '%s' not found in registry", branch_name)
            return False

        registry["branches"] = branch_list
        return save_registry(registry_path, registry)


def _update_passport_paths(branch_dir, new_relative_path, project_name=None):
    """Update passport.json branch_info paths after a move.

    Returns False only when there is no passport (a skip); an unreadable passport raises ValueError and
    a failed write raises OSError, so a skip and a failure never read the same.
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return False

    passport = json_handler.read_json(passport_path)
    if passport is None:
        raise ValueError(f"passport at {passport_path} could not be read")

    branch_info = passport.get("branch_info", {})
    branch_info["path"] = new_relative_path

    if project_name:
        branch_name = branch_dir.name
        branch_info["module"] = f"{project_name}.{branch_name}"

    passport["branch_info"] = branch_info
    if not json_handler.write_json(passport_path, passport):
        raise OSError(f"passport at {passport_path} could not be written")
    return True


def _detect_project_package(branch_rel_path):
    """Detect the project package name from the branch's relative path.

    E.g., "src/compass/navigator" → "compass"
    """
    parts = Path(branch_rel_path).parts
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1]
    return None


def _move_chroma(src, dst):
    """Move the project-root .chroma/ to ``dst`` — a test seam, so a pin can fail this one move."""
    return shutil.move(src, dst)


def _relocate_chroma(project_root, branch_dir, branches):
    """Move project-root .chroma/ into a branch when only one branch exists.

    Returns False only for a skip (no .chroma/, not exactly one branch, or one already there); a failed
    move raises OSError, never reads as a skip.
    """
    chroma_src = project_root / ".chroma"
    if not chroma_src.is_dir():
        return False

    if len(branches) != 1:
        logger.info("[repair] Skipping .chroma relocation — %d branches (need exactly 1)", len(branches))
        return False

    chroma_dest = branch_dir / ".chroma"
    if chroma_dest.exists():
        logger.warning("[repair] .chroma already exists in branch dir, skipping relocation")
        return False

    _move_chroma(str(chroma_src), str(chroma_dest))
    logger.info("[repair] Relocated .chroma/ into %s", branch_dir.name)
    return True


def move_branch(branch_name, new_path, registry_path=None, dry_run=False, relocate_artifacts=False):
    """Move a branch to a new location, updating registry and passport.

    Archive-first: creates backup before any destructive operation.
    """
    if registry_path is None:
        registry_path = find_registry()
    if registry_path is None:
        msg = "No *_REGISTRY.json found above the current directory — nothing to relocate against"
        logger.error("[repair] %s", msg)
        return {"success": False, "error": msg, "moved": False, "registry_updated": False}
    registry_path = Path(registry_path)
    project_root = registry_path.resolve().parent

    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    entry = None
    for b in branches:
        if b.get("name", "").lower() == branch_name.lower():
            entry = b
            break

    if entry is None:
        return {"success": False, "error": f"Branch '{branch_name}' not found in registry"}

    old_rel_path = entry.get("path", "")
    old_abs_path = (project_root / old_rel_path).resolve()

    # Resolved before the containment check: /proj/../outside is lexically inside /proj.
    new_abs_path = (project_root / new_path).resolve()

    try:
        new_rel_path = new_abs_path.relative_to(project_root).as_posix()
    except ValueError:
        logger.warning("[repair] Path %s is outside project root %s", new_abs_path, project_root)
        return {
            "success": False,
            "error": f"New path {new_abs_path} is outside project root {project_root}",
        }

    if not old_abs_path.exists():
        return {"success": False, "error": f"Source directory does not exist: {old_abs_path}"}

    if new_abs_path.exists():
        return {"success": False, "error": f"Target directory already exists: {new_abs_path}"}

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "branch": branch_name,
            "old_path": old_rel_path,
            "new_path": new_rel_path,
            "actions": [
                f"Archive {old_rel_path} to .archive/repair_moves/",
                f"Move {old_rel_path} → {new_rel_path}",
                "Update registry path",
                "Update passport paths",
            ],
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = project_root / ".archive" / "repair_moves" / f"{branch_name}_{timestamp}"
    archive_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copytree(
            str(old_abs_path),
            str(archive_dir),
            ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE),
        )
        logger.info("[repair] Archived %s to %s", branch_name, archive_dir)
    except Exception as e:
        logger.error("[repair] Archive failed for %s: %s", branch_name, e)
        return {"success": False, "error": f"Archive failed: {e}"}

    new_abs_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(old_abs_path), str(new_abs_path))
        logger.info("[repair] Moved %s → %s", old_abs_path, new_abs_path)
    except Exception as e:
        logger.error("[repair] Move failed for %s: %s", branch_name, e)
        return {"success": False, "error": f"Move failed: {e}", "archive_path": str(archive_dir)}

    if not update_registry_path(registry_path, branch_name, new_rel_path):
        # The registry still names the old path, so the tree goes back to where it points.
        shutil.move(str(new_abs_path), str(old_abs_path))
        logger.error("[repair] Registry not updated for %s — moved back to %s", branch_name, old_rel_path)
        return {
            "success": False,
            "error": f"Registry could not be updated — {branch_name} moved back to {old_rel_path}",
            "archive_path": str(archive_dir),
        }

    # A helper's False is a skip; its failure raises and is named here, never read as a skip.
    project_name = _detect_project_package(new_rel_path)
    passport_updated = False
    passport_error = None
    try:
        passport_updated = _update_passport_paths(new_abs_path, new_rel_path, project_name)
    except Exception as e:
        logger.error("[repair] Failed to update passport paths: %s", e)
        passport_error = str(e)

    chroma_relocated = False
    chroma_error = None
    if relocate_artifacts:
        try:
            chroma_relocated = _relocate_chroma(project_root, new_abs_path, branches)
        except Exception as e:
            logger.error("[repair] Failed to relocate .chroma: %s", e)
            chroma_error = str(e)

    json_handler.log_operation(
        "branch_moved",
        data={"branch": branch_name, "old_path": old_rel_path, "new_path": new_rel_path},
    )

    return {
        "success": True,
        "branch": branch_name,
        "old_path": old_rel_path,
        "new_path": new_rel_path,
        "archive_path": str(archive_dir),
        "registry_updated": True,
        "passport_updated": passport_updated,
        "passport_error": passport_error,
        "chroma_relocated": chroma_relocated,
        "chroma_error": chroma_error,
    }


def rename_branch(old_name, new_name, registry_path=None, dry_run=True):
    """Re-point a citizen's registry entry and passport at its already-renamed directory.

    The registry is the one named, else AIPass's, else the first projects/*/*_REGISTRY.json holding old.
    Every path segment named old becomes new, so a project's namesake seat carries its sibling rows and,
    when metadata.name is OLD, the registry file. Ids and every other field are kept; of the identity
    prose only the purpose word changes."""
    old, new = old_name.lstrip("@").lower(), new_name.lstrip("@").lower()
    registry_path = Path(registry_path) if registry_path else _registry_holding(old)
    if registry_path is None:
        return _rename_refused(f"'{old}' is not in AIPASS_REGISTRY.json or any projects/*/*_REGISTRY.json")
    project_root = registry_path.resolve().parent

    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))
    entry = next((b for b in branches if b.get("name", "").lower() == old), None)
    if entry is None:
        return _rename_refused(f"'{old}' is not in {registry_path.name}")
    if any(b.get("name", "").lower() == new for b in branches):
        return _rename_refused(f"'{new}' is already in {registry_path.name}")
    namesake = registry.get("metadata", {}).get("name", "").upper() == old.upper()
    new_registry = registry_path.with_name(f"{new.upper()}_REGISTRY.json") if namesake else registry_path
    if namesake and new_registry.exists():
        return _rename_refused(f"{new_registry} already exists")

    moves = {}
    for row in branches:
        old_abs = Path(row.get("path", ""))
        old_abs = (old_abs if old_abs.is_absolute() else project_root / old_abs).resolve()
        if not old_abs.is_relative_to(project_root.resolve()):
            if row is entry:
                return _rename_refused(f"{old_abs} is outside project root {project_root}")
            continue
        parts = old_abs.relative_to(project_root.resolve()).parts
        if old not in parts:
            if row is entry:
                return _rename_refused(f"the path of '{old}' has no segment named {old}")
            continue
        new_rel = Path(*[new if part == old else part for part in parts]).as_posix()
        if old_abs.exists():
            return _rename_refused(f"{old_abs} still exists — rename the directory first, then the citizen")
        passport_path = project_root / new_rel / ".trinity" / "passport.json"
        passport = json_handler.read_json(passport_path) if passport_path.is_file() else None
        if not isinstance(passport, dict):
            return _rename_refused(f"no readable passport at {passport_path}")
        # The row's registry_id is the citizen's own id: it proves the directory is this citizen.
        if passport.get("citizenship", {}).get("citizen_id") != row.get("registry_id"):
            return _rename_refused(f"the passport at {passport_path} is not the citizen of entry '{row.get('name')}'")
        moves[row.get("name", "").lower()] = (new_rel, passport_path, passport)

    result = {
        "success": True,
        "dry_run": dry_run,
        "old": old,
        "new": new,
        "new_path": moves[old][0],
        "registry": new_registry.name,
        "repathed": {name: rel for name, (rel, _p, _d) in moves.items() if name != old},
    }
    if dry_run:
        return result

    originals = {path: path.read_text(encoding="utf-8") for _rel, path, _d in moves.values()}
    try:
        for name, (new_rel, passport_path, passport) in moves.items():
            info = passport.setdefault("branch_info", {})
            info["path"] = new_rel
            info["module"] = ".".join(new if seg == old else seg for seg in info.get("module", "").split("."))
            if name == old:
                passport.setdefault("document_metadata", {}).update(
                    document_name=f"{new}.PASSPORT", managed_by=new, last_updated=datetime.now().strftime("%Y-%m-%d")
                )
                info.update(branch_name=new, email=f"@{new}")
                identity = passport.get("identity", {})
                if isinstance(identity.get("purpose"), str):
                    identity["purpose"] = _swap_word(identity["purpose"], old, new)
            if not json_handler.write_json(passport_path, passport):
                raise OSError(f"passport at {passport_path} could not be written")
    except OSError as exc:
        _restore(originals)
        return _rename_refused(f"{exc} — every passport was restored")

    with registry_lock(registry_path):
        registry = load_registry(registry_path)
        rows = branches_as_list(registry.get("branches", []))
        for row in rows:
            name = row.get("name", "").lower()
            if name not in moves:
                continue
            row["path"] = moves[name][0]
            row["description"] = _swap_word(row.get("description", ""), old, new)
            if name == old:
                row.update(name=new.upper(), email=f"@{new}")
        registry["branches"] = rows
        if namesake:
            registry["metadata"]["name"] = new.upper()
        saved = save_registry(registry_path, registry)
    if not saved:
        # A passport must not name a citizen the registry does not know.
        _restore(originals)
        return _rename_refused(f"{registry_path.name} could not be written — every passport was restored")

    if namesake:
        registry_path.rename(new_registry)
        lock = registry_path.parent / f".{registry_path.stem}.lock"
        if lock.exists():
            archive = lock.parent / ".archive"
            archive.mkdir(exist_ok=True)
            shutil.move(str(lock), str(archive / f"{lock.name}.{datetime.now().strftime('%Y%m%d_%H%M%S')}"))

    logger.info("[repair] Renamed citizen %s -> %s at %s in %s", old, new, result["new_path"], new_registry.name)
    json_handler.log_operation("branch_renamed", data={"old": old, "new": new, "registry": str(new_registry)})
    return result


def _registry_holding(name):
    """The first registry with a row named ``name``: AIPass's, then each projects/*/*_REGISTRY.json."""
    root_registry = find_registry()
    if root_registry is None:
        return None
    projects = root_registry.parent / "projects"
    found = [_registry_in(d) for d in sorted(projects.iterdir()) if d.is_dir()] if projects.is_dir() else []
    for candidate in [root_registry, *[f for f in found if f is not None]]:
        rows = branches_as_list(load_registry(candidate).get("branches", []))
        if any(b.get("name", "").lower() == name for b in rows):
            return candidate
    return None


def _swap_word(text, old, new):
    """Replace old as a whole word, keeping its case: beo -> seed, Beo -> Seed, BEO -> SEED."""

    def _cased(match):
        word = match.group(0)
        return new.upper() if word.isupper() else new.capitalize() if word[0].isupper() else new

    return re.sub(rf"\b{re.escape(old)}\b", _cased, text, flags=re.IGNORECASE)


def _restore(originals):
    """Write each passport's original text back."""
    for path, text in originals.items():
        atomic_write_text(path, text)


def _rename_refused(reason):
    """Log and return a rename refusal; nothing has been written."""
    logger.warning("[repair] Rename refused: %s", reason)
    return {"success": False, "error": reason}


def _check_nested_pollution(nested_dir, label, project_root, registry_path):
    """Check if a nested duplicate directory is real pollution.

    None when the directory is a protected branch (active passport, registry owner, infrastructure floor)
    or a flat-layout package (holds __init__.py).
    """
    if (nested_dir / "__init__.py").exists():
        return None
    protected, _reason = is_protected(
        nested_dir.name,
        branch_dir=nested_dir,
        registry_path=registry_path,
    )
    if protected:
        return None

    rel = nested_dir.relative_to(project_root).as_posix()
    return {
        "type": "duplicate_nested_dir",
        "path": rel,
        "description": f"Duplicate nested directory: {label}/",
    }


def detect_pollution(project_root):
    """Detect init pollution — duplicate nested directories (e.g. compass/compass/), skipping protected branches."""
    project_root = Path(project_root)
    issues = []
    project_name = project_root.name

    registry_path = _registry_in(project_root)

    nested = project_root / project_name
    if nested.is_dir():
        issue = _check_nested_pollution(
            nested,
            f"{project_name}/{project_name}",
            project_root,
            registry_path,
        )
        if issue:
            issues.append(issue)

    src_dir = project_root / "src"
    if src_dir.is_dir():
        for child in sorted(src_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name.startswith("__"):
                continue
            nested_dup = child / child.name
            if not nested_dup.is_dir():
                continue
            issue = _check_nested_pollution(
                nested_dup,
                f"src/{child.name}/{child.name}",
                project_root,
                registry_path,
            )
            if issue:
                issues.append(issue)

    return issues


def cleanup_pollution(project_root, dry_run=False):
    """Archive and remove detected pollution directories."""
    project_root = Path(project_root)
    issues = detect_pollution(project_root)

    if not issues:
        return {"success": True, "issues_found": 0, "cleaned": []}

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "issues_found": len(issues),
            "issues": issues,
        }

    cleaned = []
    errors = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for issue in issues:
        pollution_path = project_root / issue["path"]
        if not pollution_path.exists():
            continue

        archive_dir = project_root / ".archive" / "pollution" / f"{pollution_path.name}_{timestamp}"
        archive_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copytree(
                str(pollution_path),
                str(archive_dir),
                ignore=shutil.ignore_patterns(*ARCHIVE_EXCLUDE),
            )
            shutil.rmtree(str(pollution_path))
            logger.info("[repair] Cleaned pollution: %s (archived to %s)", issue["path"], archive_dir)
            cleaned.append({"path": issue["path"], "archive": str(archive_dir)})
        except Exception as e:
            logger.error("[repair] Failed to clean pollution at %s: %s", issue["path"], e)
            errors.append({"path": issue["path"], "error": str(e)})

    json_handler.log_operation(
        "pollution_cleaned",
        data={"project": project_root.name, "cleaned": len(cleaned)},
    )

    return {
        "success": len(errors) == 0,
        "issues_found": len(issues),
        "cleaned": cleaned,
        "errors": errors,
    }


def repair_project(project_path, dry_run=False):
    """Scan a project for structural issues and report findings.

    Read-only either way: init pollution and registered paths missing on disk.
    """
    project_path = Path(project_path).resolve()
    if not project_path.is_dir():
        return {"success": False, "error": f"Project path does not exist: {project_path}"}

    registry_path = _registry_in(project_path)

    if registry_path is None:
        return {"success": False, "error": f"No *_REGISTRY.json found in {project_path}"}

    results = {
        "project": project_path.name,
        "registry": registry_path.name,
        "dry_run": dry_run,
        "pollution": detect_pollution(project_path),
        "registry_mismatches": [],
        "actions_taken": [],
    }

    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    for entry in branches:
        rel_path = entry.get("path", "")
        abs_path = (project_path / rel_path).resolve()

        if not abs_path.exists():
            results["registry_mismatches"].append(
                {
                    "branch": entry.get("name", "?"),
                    "registered_path": rel_path,
                    "issue": "Directory missing — registered path does not exist",
                }
            )

    total_issues = len(results["pollution"]) + len(results["registry_mismatches"])
    results["total_issues"] = total_issues
    results["success"] = True

    return results
