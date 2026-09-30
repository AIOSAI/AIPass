# =================== AIPass ====================
# Name: mint_ops.py
# Description: The mint of a new citizen from the template, step by step
# Version: 1.0.0
# Created: 2026-09-28
# Modified: 2026-09-28
# =============================================

"""The mint body: a validated target becomes a registered citizen.

apps/modules/core.py decides the lane (refusals, adopt, birth from seed) and
hands a fresh target here. Moved out of core whole, step order unchanged
(spawn's decision, DPLAN-0354 leg 4); core keeps the meta-tab importer and hands
it in, so @memory's optional import stays where it was.
"""

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
from aipass.spawn.apps.handlers.adoption_ops import error_result
from aipass.spawn.apps.handlers.class_registry import class_for_citizen_number
from aipass.spawn.apps.handlers.json import json_handler

_PROJECT_MARKERS = (".git", "pyproject.toml", "setup.py", "setup.cfg")


def _find_project_registry(target: Path) -> Path:
    """Walk up from target to find a project root, return its registry path.

    Used when the default find_registry returned a registry outside the
    target's project (e.g. AIPass's own registry for an external target).
    """
    for parent in [target.parent] + list(target.parent.parents):
        if any((parent / m).exists() for m in _PROJECT_MARKERS):
            return parent / "AIPASS_REGISTRY.json"
        if parent == parent.parent:
            break
    return target.parent / "AIPASS_REGISTRY.json"


def mint_citizen(
    target: Path,
    template: Path,
    load_meta_tabs: Callable[[], dict],
    role="",
    traits: str | list[str] | tuple[str, ...] = "",
    purpose="",
    profile=None,
    registry_path=None,
    citizen_class=None,
) -> dict:
    """Mint a citizen at a target that does not exist yet, from template.

    Args:
        target: Resolved path of the new branch (must not exist)
        template: The template directory to copy
        load_meta_tabs: Answers @memory's meta-tab values; called at the
            same step as before the move, after the registry is resolved
        role, traits, purpose, profile, registry_path, citizen_class: as
            spawn_agent in apps/modules/core.py documents them

    Returns:
        The result dict spawn_agent returns (success, branch_name, path,
        files_copied, registry_updated, validation_issues, ...), or the
        error dict of error_result when the mint is refused.
    """
    # Extract names
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    # Determine registry — per-project, never borrow another project's
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        # No registry above the target. That is exactly the "outside any known
        # registry" case the ValueError arm below already resolves, so take the
        # same road rather than crashing on None (@aipass changed find_registry
        # to answer absence with None on 2026-08-31).
        logger.info("[spawn] No registry above %s — resolving project-local registry", target)
        reg_path = _find_project_registry(target)
    try:
        target.relative_to(reg_path.parent)
    except ValueError:
        logger.info("[spawn] Target %s outside registry %s — resolving project-local registry", target, reg_path)
        reg_path = _find_project_registry(target)
    citizen_number = get_next_citizen_number(reg_path)

    # Resolve the PROJECT credential (the registry's own metadata.id) for the
    # passport's citizenship.registry_id. resolve_project_credential mints one
    # when the registry does not exist yet, which is what a brand-new external
    # project is — resolving it HERE rather than at registration time is the
    # whole point: the passport is written at step 1 and the registry at step 4,
    # so reading it later would stamp the passport with a credential that had
    # not been minted yet and fall back to AIPass's own id. Same mint-once
    # ordering as citizen_id below; the value is handed to add_to_registry so
    # the file that eventually lands carries the id the passport already claims.
    #
    # The mint is asked for BY NAME. It used to be a side effect of loading a
    # path that did not exist, which meant every reader of a missing registry
    # minted one too (@memory, 2026-08-31). This site is a creator and says so.
    resolved_registry_id = resolve_project_credential(reg_path)

    # Mint the citizen's own unique id ONCE, here, so the passport and the
    # registry entry carry the same value. Minting it inside add_to_registry
    # (step 4) would be too late: the passport is written at step 1, so the two
    # facts would be two different UUIDs for one citizen.
    citizen_id = str(uuid.uuid4())

    # The class is decided HERE, at mint, from the citizen number: a project's
    # first citizen manages it, everyone after is a specialist (DPLAN-0319 R3).
    # citizen_number is only known now — after the registry was resolved — which
    # is why the decision cannot live in the signature default. An explicit
    # caller-supplied class still wins; retired names already refused above.
    resolved_class = citizen_class or class_for_citizen_number(citizen_number)

    # Build placeholder replacements
    meta_tabs = load_meta_tabs()
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

    # Step 1: Copy template with placeholder replacement in content
    ensure_directory(target)
    copied, skipped = copy_template(template, target, replacements)

    # Step 2: Rename any {{BRANCH}} dirs/files that weren't caught by path replacement
    renamed = rename_placeholder_paths(target, folder_name)

    # Step 2b: Write caller-supplied traits into the passport.
    #
    # citizenship.owner used to be written here. R8 DROPPED that field from the
    # schema — the registry entry's owner:true flag (ensure_project_has_owner,
    # step 5) is the sealed authority and a second copy in the passport was a
    # self-declared duplicate of it.
    #
    # traits is a post-render write because the 2.0 template makes identity.traits
    # an empty LIST and no longer carries a {{TRAITS}} placeholder. Without this,
    # `spawn create --traits ...` would accept the value and silently drop it.
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

    # Step 3: Regenerate .template_registry.json with fresh hashes
    regenerate_template_registry(target)

    # Step 3b: Generate branch metadata for tracking
    template_registry = load_template_registry(target)
    if template_registry:
        branch_meta = generate_branch_meta(target, template_registry)
        save_branch_meta(target, branch_meta)

    # Step 3c: The mint must have delivered what the template claims — refuse
    # loudly if not. Deliberately placed BEFORE the registry write: a citizen
    # that cannot be born must not exist in the registry at all, and refusing
    # first means there is nothing to roll back (a rollback that itself fails
    # leaves the half-citizen this guard is here to prevent). The partial tree
    # is left on disk on purpose — spawn refuses, it does not delete a
    # directory the caller may want to inspect.
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

    # Step 3d: Stamp the trinity receipt. A newborn without one scores 0 on the
    # receipt group and 80 on the file set from its first minute — born in
    # violation of a standard it never had a chance to break. Placed AFTER mint
    # verification (the receipt is spawn's own stamp, not a file the template
    # claims) and BEFORE registration, so a registered citizen always carries one.
    # A failure here does not abandon the birth: the gold templates belong to
    # another branch, and a citizen that cannot be born because @memory's files
    # are unreadable is a worse outcome than a citizen missing a receipt. It is
    # surfaced instead of swallowed — validation_issues is what the CLI prints.
    receipt_result = write_birth_receipt(target / ".trinity")
    receipt_issues = [] if receipt_result["success"] else [f"Birth receipt not stamped: {receipt_result['error']}"]

    # Step 3e: The same stamp one step over — @seedgo's test template receipt in
    # tests/, plus the page itself (DPLAN-0354). Same rules as 3d: the gold
    # manifest is another branch's file, so a miss is surfaced and the birth
    # continues, and a manifest that cannot be read leaves no receipt at all.
    test_template_result = write_test_template_receipt(target / "tests")
    if not test_template_result["success"]:
        receipt_issues.append(f"Test template receipt not stamped: {test_template_result['error']}")

    # Step 4: Register in project registry
    # Store path relative to registry location (works for both AIPass and external projects)
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

    # Step 5: Ensure at least one agent in the project is the owner
    ensure_project_has_owner(reg_path)

    # Step 6: Validate no unreplaced placeholders
    issues = validate_no_placeholders(target) + receipt_issues + traits_issues

    # Birth is observable: the log names who was born, where, and which trinity
    # template version they carry. @trigger's bus has no subscriber for a birth
    # event today, so a listener nobody fires for would be scaffolding, not signal.
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
