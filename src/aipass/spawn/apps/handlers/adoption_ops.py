# =================== AIPass ====================
# Name: adoption_ops.py
# Description: The target-exists lane — adopt a passported directory, or birth one from its tracked seed
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""The target-exists lane of ``spawn create`` (split out of modules/core.py).

``_spawn_agent`` handles three shapes of an EXISTING target directory:

- live passport present  -> ``adopt_existing`` — register it, seat an owner,
  stamp a receipt if none, sync missing template files.
- no passport but a tracked seed -> ``birth_from_seed`` — mint the live passport
  from ``.aipass/passport.seed.json`` (fresh machine-local ids + the
  ``citizenship.seed`` stamp), then delegate to ``adopt_existing``. This IS the
  fresh-clone shape: branch code ships tracked, ``.trinity/`` is gitignored.
- neither -> the caller refuses ("Target already exists"), byte-for-byte the
  pre-seed behaviour.

These are handler-level: every dependency is another handler. core.py keeps the
routing and re-exports these under their old private names so the module seam
stays where the tests and callers know it.
"""

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
    """Return error result dict in ``_spawn_agent``'s format."""
    return {
        "success": False,
        "error": message,
        "branch_name": "",
        "path": "",
        "files_copied": 0,
        "dirs_created": 0,
        "files_skipped": 0,
        "renamed": [],
        "registry_updated": False,
        "registry_path": "",
        "citizen_number": 0,
        "validation_issues": [],
    }


def birth_from_seed(target, seed_file, purpose, profile, registry_path):
    """Mint a citizen's passport from its own tracked seed, then adopt it.

    The seed carries the IDENTITY (role, purpose, principles, dates, residency —
    everything the agent grew into). The three machine-local facts are minted
    FRESH here exactly as a template mint mints them: ``registered``, this
    project's ``registry_id`` credential, and a new ``citizen_id``. The rendered
    passport also carries ``citizenship.seed``, the stamp naming the seed version
    and file hash it came from — a template mint gets no stamp, because it came
    from no seed.

    REFUSAL IS THE SAFE DIRECTION. The seed is validated on load and the rendered
    passport is validated before the write, so an invalid seed produces a loud
    error and NOTHING on disk — never a citizen holding a malformed identity.

    Registration is delegated to ``adopt_existing`` rather than duplicated: the
    directory already holds its own code, so what is left after the passport is
    exactly what adoption does (registry entry, owner seating, birth receipt,
    template sync for anything the clone is missing).

    Args:
        target: The existing branch directory carrying the seed.
        seed_file: Path to that branch's ``.aipass/passport.seed.json``.
        purpose: Optional purpose override. Empty reads it from the passport.
        profile: AIPass profile override.
        registry_path: Path to the registry, or None to auto-discover.

    Returns:
        Result dict matching ``_spawn_agent``'s format, with ``seeded: True``.
    """
    branch_lower = normalize_branch_name(get_branch_name(target), "lower")
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)

    # Same mint-once ordering as the template path: the credential and the
    # citizen id are resolved BEFORE the passport is written, so the file and the
    # registry entry that follows it carry one value each, not two.
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
        # A refused seed is a fact about a tracked file every clone will read,
        # so it goes on the record as well as back to the caller.
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

    result = adopt_existing(target, purpose, profile, reg_path, citizen_id=citizen_id)
    result["seeded"] = True
    result["seed_path"] = str(seed_file)
    return result


def adopt_existing(target, purpose, profile, registry_path, citizen_id=""):
    """Register an existing directory that already has a passport.

    Enhanced to also:
    - Fix registry_id mismatch in passport (caused by registry recreation)
    - Run template update to sync scaffolding files

    Used when 'spawn create @existing' targets a directory the user already
    moved code into. Instead of failing with "Target already exists",
    we register it and sync its template files.

    Args:
        target: Path to the existing directory with .trinity/passport.json
        purpose: Optional purpose description
        profile: AIPass profile override
        registry_path: Path to registry (or None for auto-discover)
        citizen_id: Pre-minted per-citizen UUID to reuse for the registry entry.
            Supplied by a caller that has ALREADY stamped it into the passport
            (``birth_from_seed``), so the two copies of that one fact agree.
            Empty — plain adoption, where the passport predates this call and
            was not written by us — lets add_to_registry mint the entry's own.

    Returns:
        Result dict matching _spawn_agent return format.
    """
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        # Adoption registers an EXISTING citizen into an EXISTING project. With
        # no registry above the target there is nothing to adopt it into, and
        # choosing a location would be spawn deciding where a project begins.
        msg = f"Cannot adopt {target}: no *_REGISTRY.json found above it"
        logger.error("[adopt] %s", msg)
        return {"branch": get_branch_name(target), "success": False, "error": msg}

    # Read purpose from passport if not provided
    if not purpose:
        passport_path = target / ".trinity" / "passport.json"
        # read_json returns None on failure (and logs) — same pattern as core's create path.
        passport = json_handler.read_json(passport_path)
        purpose = (passport or {}).get("identity", {}).get("purpose", "Adopted agent")

    # Fix registry_id in passport if it doesn't match the current registry
    fix_passport_registry_id(target, reg_path)

    # Store path relative to registry location
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
    )

    ensure_project_has_owner(reg_path)

    # An adopted directory becomes a citizen here, so it needs a receipt too —
    # but ONLY if it has none. A branch @memory's push already stamped carries
    # "memory push"; restamping it "spawn birth" would overwrite a true record
    # of which lane last touched those files with a false one. Adoption fills a
    # hole; it does not rewrite history.
    if not (target / ".trinity" / RECEIPT_NAME).exists():
        adopt_receipt = write_birth_receipt(target / ".trinity")
        if not adopt_receipt["success"]:
            logger.warning("[spawn] Adopted %s without a trinity receipt: %s", branch_upper, adopt_receipt["error"])

    json_handler.log_operation("branch_adopted", data={"branch": branch_upper})
    logger.info("[spawn] Adopted existing branch: %s (registered in %s)", branch_upper, reg_path.name)

    # Run template update to sync scaffolding files.
    # Preserves: .trinity/, .ai_mail.local/, memories, all .py files.
    # Only adds missing template files and merges JSON configs.
    update_additions = 0
    try:
        from aipass.spawn.apps.handlers.update_ops import update_branch

        update_result = update_branch(branch_lower)
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
        "renamed": [],
        "registry_updated": registry_updated,
        "registry_path": str(reg_path),
        "citizen_number": 0,
        "validation_issues": [],
        "adopted": True,
    }
