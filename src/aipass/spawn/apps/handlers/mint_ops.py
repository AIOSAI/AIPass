# =================== AIPass ====================
# Name: mint_ops.py
# Description: The mint of a new citizen from the template, step by step
# Version: 1.5.1
# Created: 2026-09-28
# Modified: 2026-11-22
# =============================================

"""The mint body: a validated target becomes a registered citizen."""

import uuid
from collections.abc import Callable
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.metadata import (
    branch_name_refusal,
    get_branch_name,
    normalize_branch_name,
    detect_profile,
)
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, validate_no_placeholders
from aipass.spawn.apps.handlers.file_ops import (
    copy_template,
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
    branches_as_list,
    get_next_citizen_number,
    ensure_project_has_owner,
    load_registry,
    row_at,
)
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing, birth_from_seed, error_result
from aipass.spawn.apps.handlers.class_registry import (
    class_for_citizen_number,
    get_default_class,
    get_template_dir,
    refuse_retired_or_forbidden,
)
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.passport_migration import PassportTarget
from aipass.spawn.apps.handlers.project_defaults import (
    arrival_refusal,
    stamp_onboarding,
    stamp_test_policy,
    stamp_updateignore,
)
from aipass.spawn.apps.handlers.seed_ops import copy_seed_home, export_seed, find_seed

# Left in a tree the mint refused, so a retry refuses instead of adopting the partial tree.
INCOMPLETE_MARKER = "INCOMPLETE_MINT.txt"


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
    arrival=None,
) -> dict:
    """Decide the lane for a target and run it: refuse, adopt, birth from seed, or mint.

    citizen_class None means decide at mint from the citizen number; retired names are refused.
    traits: a bare string becomes a one-element list (identity.traits is a list).
    arrival: "fresh" or "adopted" stamps a project seat's defaults at mint; None stamps nothing."""
    # Forbidden and retired values refuse before any filesystem work, through every door.
    for candidate in (citizen_class, Path(template_dir).name if template_dir else ""):
        refusal = refuse_retired_or_forbidden(candidate)
        if refusal:
            json_handler.log_operation("mint_refused", data={"class": candidate, "reason": refusal})
            return error_result(refusal)
    refusal = arrival_refusal(arrival)
    if refusal:
        return error_result(refusal)

    # Role and purpose are substituted raw into the JSON passport template.
    for label, value in (("role", role), ("purpose", purpose)):
        if any(ch in '"\\' or ch < " " for ch in value or ""):
            return error_result(
                f"--{label} cannot contain a double quote, backslash, newline or other control character "
                f"(it is written into the JSON passport): {value!r}"
            )

    target = Path(target_path).resolve()
    # Every lane below (mint, adopt, seed birth) takes its name from the folder, so one check covers them all.
    refusal = branch_name_refusal(get_branch_name(target))
    if refusal:
        return error_result(refusal)
    # A relative registry would never contain the target, and the mint would fall back to a new registry.
    registry_path = Path(registry_path).resolve() if registry_path else None
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
        if (target / INCOMPLETE_MARKER).exists():
            return error_result(
                f"REFUSED: {target} is the partial tree of a refused mint (see {INCOMPLETE_MARKER} in it). "
                "Move it aside, fix the template, then create again."
            )
        passport_path = target / ".trinity" / "passport.json"
        # A fresh clone carries the seed but not the gitignored .trinity/; the only door a seed is found at.
        seed_file = None if passport_path.exists() else find_seed(target)

        if passport_path.exists():
            # A passport and a row is a live agent; a vault without a passport is a seat to bring back.
            refusal = live_row_refusal(target, registry_path)
            if refusal:
                logger.warning("[spawn] Create refused over a live agent: %s", target)
                return error_result(refusal)
            return adopt_existing(target, purpose, profile, registry_path)

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
        arrival=arrival,
    )


def live_row_refusal(target: Path, registry_path) -> str:
    """The refusal when the registry adopt would use already holds a row at target; empty when it holds none."""
    reg_path = registry_path or find_registry(target.parent)
    row = row_at(reg_path, target) if reg_path else None
    if reg_path is None or row is None:
        return ""
    name = normalize_branch_name(row.get("name") or get_branch_name(target), "lower")
    return (
        f"REFUSED: {target} is already registered as @{name} in {reg_path}; create would rewrite a live "
        f"agent, so nothing was written. To bring its scaffold up to the template: "
        f"drone @spawn update @{name} (preview first). To fix the project's structure: "
        f"drone @spawn repair {reg_path.parent}"
    )


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
    arrival=None,
) -> dict:
    """Mint a citizen at a target that does not exist yet, from template."""
    folder_name = get_branch_name(target)
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    # The registry must already exist above the target or be named explicitly; a mint never invents one.
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    if reg_path is None:
        logger.warning("[spawn] Mint refused: no registry above %s", target)
        return error_result(
            f"No registry above {target}: pass --registry <path>, or create the citizen inside a project that has one."
        )
    try:
        target.relative_to(reg_path.parent)
    except ValueError:
        logger.warning("[spawn] Mint refused: %s is outside registry %s", target, reg_path)
        return error_result(f"{target} is outside the project of registry {reg_path}; nothing was written.")
    if any(
        b.get("name", "").lower() == branch_lower for b in branches_as_list(load_registry(reg_path).get("branches", []))
    ):
        return error_result(f"{branch_lower} is already registered in {reg_path}; nothing was written.")
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
    if arrival and replacements["RESIDENCY"] == "core":
        return error_result(f"--arrival stamps a project seat's defaults; {target} is a core citizen. Nothing written.")

    ensure_directory(target)
    copied, skipped = copy_template(template, target, replacements)

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

    # Before the template registry and branch meta are generated, so both record the stamped prompt.
    arrival_record: dict = {}
    if arrival:
        try:
            arrival_record["first_wake"] = stamp_onboarding(target, arrival)
        except OSError as e:
            logger.warning("[spawn] First wake not stamped for %s: %s", branch_lower, e)
            arrival_record["first_wake"] = f"not stamped: {e}"

    regenerate_template_registry(target)

    template_registry = load_template_registry(target)
    if template_registry:
        branch_meta = generate_branch_meta(target, template_registry)
        save_branch_meta(target, branch_meta)

    # Verified before the registry write, so a refusal has nothing to roll back; the partial tree stays.
    missing = verify_mint(template, target, replacements, branch_lower)
    if missing:
        json_handler.log_operation("mint_refused", data={"branch": branch_lower, "missing": missing})
        shown = ", ".join(missing[:12])
        if len(missing) > 12:
            shown += f", +{len(missing) - 12} more"
        refusal = error_result(
            f"INCOMPLETE MINT: {len(missing)} file(s) the template claims never landed in {target}: {shown}. "
            f"Template: {template}. The usual cause is an incomplete template on disk — a fresh clone whose "
            f"template files are gitignored ships fewer files than the template's own manifest declares. "
            f"Nothing was registered; the partial tree is left at {target} for inspection."
        )
        try:
            atomic_write_text(target / INCOMPLETE_MARKER, refusal["error"] + "\n")
        except OSError as e:
            logger.warning("[spawn] Could not mark the refused tree %s: %s", target, e)
        return refusal

    # The passport vault is how a lost passport comes back, so a birth without one stops before it registers.
    # A bare --template that renders no passport has no identity to vault; that is reported, not refused.
    seed_issues = []
    passport_target = PassportTarget(
        target / ".trinity" / "passport.json", target, reg_path.parent, replacements["RESIDENCY"]
    )
    if passport_target.path.is_file():
        seed_record = export_seed(passport_target, confirm=True)
    else:
        seed_record = {"error": None}
        seed_issues.append(f"No passport vault written: the template rendered no passport at {passport_target.path}")
        logger.warning("[spawn] %s", seed_issues[0])
    if seed_record["error"]:
        refusal = error_result(
            f"BIRTH REFUSED: the passport vault for {branch_lower} could not be written ({seed_record['error']}). "
            f"Nothing was registered; the tree is left at {target}."
        )
        logger.error("[spawn] %s", refusal["error"])
        try:
            atomic_write_text(target / INCOMPLETE_MARKER, refusal["error"] + "\n")
        except OSError as e:
            logger.warning("[spawn] Could not mark the refused tree %s: %s", target, e)
        return refusal

    # Receipts go before registration; a failed stamp is surfaced, never fatal (the gold files are another branch's).
    receipt_result = write_birth_receipt(target / ".trinity")
    receipt_issues = [] if receipt_result["success"] else [f"Birth receipt not stamped: {receipt_result['error']}"]

    test_template_result = write_test_template_receipt(target / "tests")
    if not test_template_result["success"]:
        receipt_issues.append(f"Test template receipt not stamped: {test_template_result['error']}")

    # Containment was refused at the gate above, so this cannot raise.
    registry_branch_path = target.relative_to(reg_path.parent).as_posix()
    registry_updated = add_to_registry(
        reg_path,
        branch_lower,
        registry_branch_path,
        detected_profile,
        f"@{branch_lower}",
        purpose or "New agent - purpose TBD",
        citizen_id=citizen_id,
        credential=resolved_registry_id,
    )

    if not registry_updated:
        return error_result(
            f"Registry add failed for {branch_lower} in {reg_path}: the tree at {target} is minted but NOT registered."
        )

    ensure_project_has_owner(reg_path)

    if arrival:
        project_stamps = {
            "updateignore": lambda: stamp_updateignore(reg_path.parent, arrival),
            "test_policy": lambda: stamp_test_policy(reg_path.parent),
            # The seat's own seed may sit in a folder the product's git excludes; this copy survives a reclone.
            "home_seed": lambda: copy_seed_home(reg_path.parent, target),
        }
        for name, stamp in project_stamps.items():
            try:
                arrival_record[name] = stamp()
            except (OSError, RuntimeError) as e:
                logger.warning("[spawn] %s not stamped for %s: %s", name, branch_lower, e)
                arrival_record[name] = f"not stamped: {e}"

    placeholder_issues = [f"Unreplaced {sorted(names)} in {path}" for path, names in validate_no_placeholders(target)]
    arrival_issues = [f"{name} {state}" for name, state in arrival_record.items() if state.startswith("not stamped")]
    issues = placeholder_issues + receipt_issues + traits_issues + seed_issues + arrival_issues

    logger.info(
        "[spawn] BORN %s at %s (class %s, citizen %s, receipt %s)",
        branch_lower,
        target,
        resolved_class,
        citizen_number,
        receipt_result.get("receipt", {}).get("template_versions") if receipt_result["success"] else "NOT STAMPED",
    )
    json_handler.log_operation(
        "branch_created",
        data={
            "branch": branch_lower,
            "citizen_class": resolved_class,
            "receipt": receipt_result.get("receipt", {}).get("template_versions", {}),
        },
    )

    return {
        "success": True,
        "branch_name": branch_lower,
        "path": str(target),
        "files_copied": len([c for c in copied if "(dir)" not in c]),
        "dirs_created": len([c for c in copied if "(dir)" in c]),
        "files_skipped": len(skipped),
        "registry_updated": registry_updated,
        "registry_path": str(reg_path),
        "citizen_number": citizen_number,
        "citizen_class": resolved_class,
        "validation_issues": issues,
        "arrival": arrival_record,
    }
