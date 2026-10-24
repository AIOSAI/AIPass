# =================== AIPass ====================
# Name: adoption_ops.py
# Description: The target-exists lane — adopt a passported directory, or birth one from its tracked seed
# Version: 1.1.0
# Created: 2026-08-28
# Modified: 2026-10-24
# =============================================

"""The target-exists lane of ``spawn create``: adopt a passported directory, or birth it from its seed."""

import uuid
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.metadata import get_branch_name, normalize_branch_name, detect_profile
from aipass.spawn.apps.handlers.receipt_ops import RECEIPT_NAME, write_birth_receipt
from aipass.spawn.apps.handlers.registry import (
    resolve_project_credential,
    find_registry,
    add_to_registry,
    fix_passport_registry_id,
    ensure_project_has_owner,
)
from aipass.spawn.apps.handlers.seed_ops import SeedError, mint_and_write

__all__ = ["adopt_existing", "birth_from_seed", "error_result"]


def error_result(message):
    """Return error result dict in ``spawn_agent``'s format."""
    return {
        "success": False,
        "error": message,
        "branch_name": "",
        "path": "",
        "files_copied": 0,
        "dirs_created": 0,
        "files_skipped": 0,
        "registry_updated": False,
        "registry_path": "",
        "citizen_number": 0,
        "validation_issues": [],
    }


def birth_from_seed(target, seed_file, purpose, profile, registry_path):
    """Mint a citizen's passport from its own tracked seed, then adopt it.

    An invalid seed is refused with nothing written to disk.
    """
    branch_lower = normalize_branch_name(get_branch_name(target), "lower")
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        return error_result(f"Cannot birth {target} from its seed: no *_REGISTRY.json found above it")

    # Minted once, before the write, so passport and registry entry carry the same ids.
    resolved_registry_id = resolve_project_credential(reg_path)
    citizen_id = str(uuid.uuid4())

    passport_path = target / ".trinity" / "passport.json"
    try:
        passport = mint_and_write(
            seed_file,
            passport_path,
            branch_name=branch_lower,
            registry_id=resolved_registry_id,
            citizen_id=citizen_id,
        )
    except SeedError as exc:
        logger.error("[spawn] Seed refused for %s (%s): %s", branch_lower, seed_file, exc)
        json_handler.log_operation("seed_mint_refused", data={"branch": branch_lower, "seed": str(seed_file)})
        return error_result(f"SEED REFUSED: {exc}\nNothing was written; {target} is untouched.")
    except OSError as exc:
        logger.error("[spawn] Passport write failed for %s at %s: %s", branch_lower, passport_path, exc)
        return error_result(f"Passport rendered from {seed_file} could not be written to {passport_path}: {exc}")

    logger.info(
        "[spawn] BORN FROM SEED %s at %s (seed %s)",
        branch_lower,
        target,
        passport["citizenship"]["seed"]["sha256"][:12],
    )
    json_handler.log_operation(
        "branch_seeded",
        data={"branch": branch_lower, "seed_sha256": passport["citizenship"]["seed"]["sha256"]},
    )

    result = adopt_existing(target, purpose, profile, reg_path, citizen_id=citizen_id, credential=resolved_registry_id)
    result["seeded"] = True
    result["seed_path"] = str(seed_file)
    return result


def adopt_existing(target, purpose, profile, registry_path, citizen_id="", credential=""):
    """Register an existing directory that already has a passport.

    citizen_id: pass the id already stamped into the passport; empty lets the registry mint one.
    credential: the registry_id already stamped into the passport, for a registry created by this add.
    """
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        # Refuse rather than pick a location: spawn does not decide where a project begins.
        msg = f"Cannot adopt {target}: no *_REGISTRY.json found above it"
        logger.error("[adopt] %s", msg)
        return {"branch": get_branch_name(target), "success": False, "error": msg}

    identity = (json_handler.read_json(target / ".trinity" / "passport.json") or {}).get("identity", {})
    purpose = purpose or identity.get("purpose", "Adopted agent")

    fix_passport_registry_id(target, reg_path)

    try:
        registry_branch_path = target.relative_to(reg_path.parent).as_posix()
    except ValueError as e:
        logger.warning("Cannot relativize path %s to registry %s: %s", target, reg_path.parent, e)
        registry_branch_path = target.as_posix()

    registry_updated = add_to_registry(
        reg_path,
        branch_upper,
        registry_branch_path,
        detected_profile,
        f"@{branch_lower}",
        purpose,
        citizen_id=citizen_id,
        credential=credential,
    )

    ensure_project_has_owner(reg_path)

    # Only when absent: an existing "memory push" receipt is a true record to keep.
    if not (target / ".trinity" / RECEIPT_NAME).exists():
        adopt_receipt = write_birth_receipt(target / ".trinity")
        if not adopt_receipt["success"]:
            logger.warning("[spawn] Adopted %s without a trinity receipt: %s", branch_upper, adopt_receipt["error"])

    json_handler.log_operation("branch_adopted", data={"branch": branch_upper})
    logger.info("[spawn] Adopted existing branch: %s (registered in %s)", branch_upper, reg_path.name)

    update_additions = 0
    try:
        from aipass.spawn.apps.handlers.update_ops import update_branch

        # Pass reg_path: the CWD's registry may be another project's.
        update_result = update_branch(branch_lower, registry_path=reg_path)
        update_additions = update_result.get("additions", 0)
        if update_result.get("errors"):
            logger.warning("[spawn] Template update had errors for %s: %s", branch_upper, update_result["errors"])
    except Exception as exc:
        logger.warning("[spawn] Template update failed for %s (adoption succeeded): %s", branch_upper, exc)

    return {
        "success": True,
        "branch_name": branch_upper,
        "path": str(target),
        "files_copied": update_additions,
        "dirs_created": 0,
        "files_skipped": 0,
        "registry_updated": registry_updated,
        "registry_path": str(reg_path),
        "citizen_number": 0,
        "citizen_class": identity.get("citizen_class", ""),
        "validation_issues": [],
        "adopted": True,
    }
