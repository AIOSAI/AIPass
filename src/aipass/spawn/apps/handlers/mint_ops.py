# =================== AIPass ====================
# Name: mint_ops.py
# Description: The mint of a new citizen from the template, step by step
# Version: 1.1.1
# Created: 2026-09-28
# Modified: 2026-10-17
# =============================================

"""The mint body: a validated target becomes a registered citizen."""

import uuid
from collections.abc import Callable
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.metadata import get_branch_name, normalize_branch_name, detect_profile
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, validate_no_placeholders
from aipass.spawn.apps.handlers.file_ops import (
    copy_template,
    rename_placeholder_paths,
    regenerate_template_registry,
    ensure_directory,
)
from aipass.spawn.apps.handlers.meta_ops import load_template_registry, generate_branch_meta, save_branch_meta
from aipass.spawn.apps.handlers.mint_verify import verify_mint
from aipass.spawn.apps.handlers.receipt_ops import write_birth_receipt, write_test_template_receipt
from aipass.spawn.apps.handlers.registry import (
    resolve_project_credential,
    find_registry,
    add_to_registry,
    get_next_citizen_number,
    ensure_project_has_owner,
)
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing, birth_from_seed, error_result
from aipass.spawn.apps.handlers.class_registry import (
    class_for_citizen_number,
    get_default_class,
    get_template_dir,
    refuse_retired_or_forbidden,
)
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.seed_ops import find_seed

_PROJECT_MARKERS = (".git", "pyproject.toml", "setup.py", "setup.cfg")


def spawn_at(
    target_path,
    load_meta_tabs: Callable[[str], dict],
    role="",
    traits: str | list[str] | tuple[str, ...] = "",
    purpose="",
    profile=None,
    template_dir=None,
    registry_path=None,
    citizen_class=None,
) -> dict:
    """Decide the lane for a target and run it: refuse, adopt, birth from seed, or mint.

    citizen_class None means decide at mint from the citizen number; retired names are refused.
    traits: a bare string becomes a one-element list (identity.traits is a list)."""
    # Forbidden and retired values refuse before any filesystem work, through every door.
    for candidate in (citizen_class, Path(template_dir).name if template_dir else ""):
        refusal = refuse_retired_or_forbidden(candidate)
        if refusal:
            json_handler.log_operation("mint_refused", data={"class": candidate, "reason": refusal})
            return error_result(refusal)

    target = Path(target_path).resolve()
    if template_dir:
        template = Path(template_dir)
    else:
        # Class-independent lookup; the real class is decided at mint, once citizen_number is known.
        template = get_template_dir(citizen_class or get_default_class())

    for parent in target.parents:
        if (parent / ".trinity" / "passport.json").is_file():
            return error_result(
                f"BLOCKED: Cannot create agent inside existing agent '{parent.name}' "
                f"(found .trinity/passport.json at {parent})"
            )
        if parent == parent.parent:
            break

    if target.exists():
        passport_path = target / ".trinity" / "passport.json"
        if passport_path.exists():
            return adopt_existing(target, purpose, profile, registry_path)

        # A fresh clone carries the seed but not the gitignored .trinity/; the only door a seed is found at.
        seed_file = find_seed(target)
        if seed_file:
            return birth_from_seed(target, seed_file, purpose, profile, registry_path)

        return error_result(f"Target already exists: {target}")
    if not template.exists():
        return error_result(f"Template not found: {template}")

    return mint_citizen(
        target,
        template,
        load_meta_tabs,
        role=role,
        traits=traits,
        purpose=purpose,
        profile=profile,
        registry_path=registry_path,
        citizen_class=citizen_class,
    )


def _find_project_registry(target: Path) -> Path:
    """Walk up from target to find a project root, return its registry path."""
    for parent in [target.parent] + list(target.parent.parents):
        if any((parent / m).exists() for m in _PROJECT_MARKERS):
            return parent / "AIPASS_REGISTRY.json"
        if parent == parent.parent:
            break
    return target.parent / "AIPASS_REGISTRY.json"


def mint_citizen(
    target: Path,
    template: Path,
    load_meta_tabs: Callable[[str], dict],
    role="",
    traits: str | list[str] | tuple[str, ...] = "",
    purpose="",
    profile=None,
    registry_path=None,
    citizen_class=None,
) -> dict:
    """Mint a citizen at a target that does not exist yet, from template."""
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    # Per-project registry: never borrow another project's.
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        logger.info("[spawn] No registry above %s — resolving project-local registry", target)
        reg_path = _find_project_registry(target)
    try:
        target.relative_to(reg_path.parent)
    except ValueError:
        logger.info("[spawn] Target %s outside registry %s — resolving project-local registry", target, reg_path)
        reg_path = _find_project_registry(target)
    citizen_number = get_next_citizen_number(reg_path)

    # Resolved before the copy: the passport is written before the registry, so both must carry this id.
    resolved_registry_id = resolve_project_credential(reg_path)

    # Minted once here: inside add_to_registry the passport and registry would get two UUIDs.
    citizen_id = str(uuid.uuid4())

    # citizen_number is only known now, so the class cannot be a signature default.
    resolved_class = citizen_class or class_for_citizen_number(citizen_number)

    meta_tabs = load_meta_tabs(folder_name)
    replacements = build_replacements_dict(
        target,
        folder_name,
        role=role,
        purpose=purpose or "New agent - purpose TBD",
        profile=detected_profile,
        citizen_number=citizen_number,
        citizen_class=resolved_class,
        meta_tabs=meta_tabs,
        registry_id=resolved_registry_id,
        citizen_id=citizen_id,
        registry_path=reg_path,
    )

    ensure_directory(target)
    copied, skipped = copy_template(template, target, replacements)

    renamed = rename_placeholder_paths(target, folder_name)

    # The template has no {{TRAITS}} placeholder, so traits are written after render or silently dropped.
    traits_issues = []
    if traits:
        passport_path = target / ".trinity" / "passport.json"
        passport_data = json_handler.read_json(passport_path) if passport_path.exists() else None
        if passport_data:
            passport_data.setdefault("identity", {})["traits"] = (
                list(traits) if isinstance(traits, (list, tuple)) else [traits]
            )
            if not json_handler.write_json(passport_path, passport_data):
                traits_issues.append(f"Traits not written to passport: {passport_path} could not be saved")
        else:
            traits_issues.append(f"Traits not written to passport: no readable passport at {passport_path}")
        for issue in traits_issues:
            logger.warning("[spawn] %s", issue)

    regenerate_template_registry(target)

    template_registry = load_template_registry(target)
    if template_registry:
        branch_meta = generate_branch_meta(target, template_registry)
        save_branch_meta(target, branch_meta)

    # Verified before the registry write, so a refusal has nothing to roll back; the partial tree stays.
    missing = verify_mint(template, target, replacements, branch_lower)
    if missing:
        json_handler.log_operation("mint_refused", data={"branch": branch_upper, "missing": missing})
        shown = ", ".join(missing[:12])
        if len(missing) > 12:
            shown += f", +{len(missing) - 12} more"
        return error_result(
            f"INCOMPLETE MINT: {len(missing)} file(s) the template claims never landed in {target}: {shown}. "
            f"Template: {template}. The usual cause is an incomplete template on disk — a fresh clone whose "
            f"template files are gitignored ships fewer files than the template's own manifest declares. "
            f"Nothing was registered; the partial tree is left at {target} for inspection."
        )

    # Receipts go before registration; a failed stamp is surfaced, never fatal (the gold files are another branch's).
    receipt_result = write_birth_receipt(target / ".trinity")
    receipt_issues = [] if receipt_result["success"] else [f"Birth receipt not stamped: {receipt_result['error']}"]

    test_template_result = write_test_template_receipt(target / "tests")
    if not test_template_result["success"]:
        receipt_issues.append(f"Test template receipt not stamped: {test_template_result['error']}")

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
        purpose or "New agent - purpose TBD",
        citizen_id=citizen_id,
        credential=resolved_registry_id,
    )

    ensure_project_has_owner(reg_path)

    issues = validate_no_placeholders(target) + receipt_issues + traits_issues

    logger.info(
        "[spawn] BORN %s at %s (class %s, citizen %s, receipt %s)",
        branch_upper,
        target,
        resolved_class,
        citizen_number,
        receipt_result.get("receipt", {}).get("template_versions") if receipt_result["success"] else "NOT STAMPED",
    )
    json_handler.log_operation(
        "branch_created",
        data={
            "branch": branch_upper,
            "citizen_class": resolved_class,
            "receipt": receipt_result.get("receipt", {}).get("template_versions", {}),
        },
    )

    return {
        "success": True,
        "branch_name": branch_upper,
        "path": str(target),
        "files_copied": len([c for c in copied if "(dir)" not in c]),
        "dirs_created": len([c for c in copied if "(dir)" in c]),
        "files_skipped": len(skipped),
        "renamed": renamed,
        "registry_updated": registry_updated,
        "registry_path": str(reg_path),
        "citizen_number": citizen_number,
        "validation_issues": issues,
    }
