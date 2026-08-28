# =================== AIPass ====================
# Name: core.py
# Description: Main orchestrator for agent spawning
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-10
# =============================================

"""
Spawn Module — Create new AIPass agents from templates.

Orchestrates the full agent creation workflow:
1. Validate target path
2. Copy template to target
3. Rename placeholder paths
4. Replace all {{PLACEHOLDER}} patterns
5. Regenerate .template_registry.json
6. Register in AIPASS_REGISTRY.json
7. Validate no unreplaced placeholders remain
"""

import uuid
from pathlib import Path
from typing import List

from aipass.prax import logger

try:
    from aipass.cli.apps.modules.display import console
except ImportError as e:
    logger.warning("Failed to import aipass.cli.apps.modules.display, falling back to rich.console: %s", e)
    from rich.console import Console

    console = Console()

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
from aipass.spawn.apps.handlers.receipt_ops import write_birth_receipt
from aipass.spawn.apps.handlers.registry import (
    load_registry,
    find_registry,
    add_to_registry,
    get_next_citizen_number,
    ensure_project_has_owner,
)
from aipass.spawn.apps.handlers.seed_ops import find_seed
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing, birth_from_seed, error_result
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as _get_template_dir,
    validate_class as validate_class,
    get_default_class as get_default_class,
    get_available_classes as get_available_classes,
    refuse_forbidden_class as refuse_forbidden_class,
    refuse_retired_or_forbidden as refuse_retired_or_forbidden,
    class_for_citizen_number as class_for_citizen_number,
)
from aipass.spawn.apps.handlers.json import json_handler

# Default template location (relative to spawn package root). One template for
# every citizen — the class no longer picks a scaffold (DPLAN-0319 R3).
DEFAULT_TEMPLATE = Path(__file__).parents[2] / "templates" / "citizen"

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


_META_TAB_KEYS = {"TODOS_META", "KEY_LEARNINGS_META", "SESSIONS_META", "OBSERVATIONS_META"}


def _load_meta_tabs():
    """Load memory meta-tab values from @memory's renderer.

    Returns empty dict when @memory is unavailable (standalone project).
    """
    try:
        from aipass.memory.apps.handlers.tracking.tab_renderer import render_all_meta_tabs
    except ImportError:
        logger.info("[spawn] @memory not available — meta-tab placeholders will be empty")
        return {}

    tabs = render_all_meta_tabs()
    missing = _META_TAB_KEYS - set(tabs or {})
    if missing:
        raise RuntimeError(f"render_all_meta_tabs() missing keys: {sorted(missing)}")
    return tabs


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]core Module[/bold cyan]")
    console.print("Agent creation orchestrator — full spawn workflow from template to registry")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- metadata.py (get_branch_name, normalize_branch_name, detect_profile — branch identity)[/dim]"
    )
    console.print(
        "    [dim]- placeholders.py (build_replacements_dict, validate_no_placeholders — template substitution)[/dim]"
    )
    console.print(
        "    [dim]- file_ops.py (copy_template, rename_placeholder_paths,"
        " regenerate_template_registry, ensure_directory — filesystem ops)[/dim]"
    )
    console.print(
        "    [dim]- meta_ops.py"
        " (load_template_registry, generate_branch_meta, save_branch_meta — branch metadata)[/dim]"
    )
    console.print(
        "    [dim]- registry.py"
        " (find_registry, add_to_registry, get_next_citizen_number — AIPASS_REGISTRY management)[/dim]"
    )
    console.print(
        "    [dim]- class_registry.py (validate_class, get_default_class,"
        " get_available_classes, get_template_dir — citizen class lookup)[/dim]"
    )
    console.print(
        "    [dim]- seed_ops.py (find_seed, load_seed, mint_from_seed — mint a citizen from its tracked seed)[/dim]"
    )
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Route spawn commands to implementation.

    Args:
        command: The command string (e.g. "create")
        args: List of arguments for the command

    Returns:
        True if command succeeded, False otherwise
    """
    # No args → introspection
    if not args:
        print_introspection()
        return True

    if "--help" in args:
        print_introspection()
        return True

    if command == "create":
        if not args:
            logger.error("spawn create requires a target path")
            return False
        target_path = args[0]
        kwargs = {}
        i = 1
        while i < len(args):
            if args[i] == "--role" and i + 1 < len(args):
                kwargs["role"] = args[i + 1]
                i += 2
            elif args[i] == "--traits" and i + 1 < len(args):
                kwargs["traits"] = args[i + 1]
                i += 2
            elif args[i] == "--purpose" and i + 1 < len(args):
                kwargs["purpose"] = args[i + 1]
                i += 2
            elif args[i] == "--template" and i + 1 < len(args):
                template_val = args[i + 1]
                # A retired class name reaching here would otherwise be read as a
                # DIRECTORY path and fail with "Template not found: aipass_framework",
                # naming the wrong problem. Refuse by name instead (DPLAN-0319).
                refusal = refuse_retired_or_forbidden(template_val)
                if refusal:
                    logger.error(refusal)
                    return False
                if validate_class(template_val):
                    kwargs["citizen_class"] = template_val
                else:
                    kwargs["template_dir"] = template_val
                i += 2
            elif args[i] == "--registry" and i + 1 < len(args):
                kwargs["registry_path"] = args[i + 1]
                i += 2
            else:
                i += 1
        result = _spawn_agent(target_path, **kwargs)
        return result["success"]
    else:
        logger.error(f"Unknown spawn command: {command}")
        return False


def _spawn_agent(
    target_path,
    role="",
    traits: str | list[str] | tuple[str, ...] = "",
    purpose="",
    profile=None,
    template_dir=None,
    registry_path=None,
    citizen_class=None,
):
    """
    Create a new AIPass agent from template.

    Args:
        target_path: Where to create the agent (must not exist)
        role: Agent's role description
        traits: Agent's personality traits. A bare string becomes a one-element
            list; a list/tuple is stored as given. identity.traits is a LIST in
            the 2.0 schema (DPLAN-0319 R7), and the annotation says so — the
            list branch below has always been reachable from the Python API, it
            was just invisible to a type checker reading the ``""`` default.
        purpose: Agent's purpose (brief description)
        profile: AIPass profile override (default: auto-detect)
        template_dir: Custom template directory (default: the citizen template)
        registry_path: Path to AIPASS_REGISTRY.json (default: auto-discover)
        citizen_class: Explicit citizen class ("manager" or "specialist").
            Default None means DECIDE AT MINT from the citizen number — the
            project's first citizen is its manager, everyone after is a
            specialist (DPLAN-0319 R3). An explicit value still wins; a retired
            name ("aipass_framework", "project_agent", "builder") is refused by
            name, never quietly translated.

    Returns:
        Dict with creation results:
            - success: bool
            - branch_name: str (uppercase)
            - path: str
            - files_copied: int
            - registry_updated: bool
            - validation_issues: list
            - error: str (only if success=False)
    """
    # Forbidden and RETIRED values refuse before any filesystem work — "admin" is
    # a devpulse-only registry privilege, never a class and never a template
    # directory (DPLAN-0288); "aipass_framework"/"project_agent"/"builder" are
    # renamed classes that spawn refuses to translate silently (DPLAN-0319 R4).
    # Both doors are checked, including the API — @aipass's new_project still
    # passes citizen_class="project_agent" today, and a loud refusal is the
    # correct answer until its parallel fix lands.
    for candidate in (citizen_class, Path(template_dir).name if template_dir else ""):
        refusal = refuse_retired_or_forbidden(candidate)
        if refusal:
            return _error(refusal)

    target = Path(target_path).resolve()
    if template_dir:
        template = Path(template_dir)
    else:
        # Both classes share one template dir, so this lookup is class-independent
        # — the real class decision happens at mint, once citizen_number is known.
        template = _get_template_dir(citizen_class or get_default_class())

    # Guard: block creating agent inside another agent's directory
    for parent in target.parents:
        if (parent / ".trinity" / "passport.json").is_file():
            return _error(
                f"BLOCKED: Cannot create agent inside existing agent '{parent.name}' "
                f"(found .trinity/passport.json at {parent})"
            )
        if parent == parent.parent:
            break

    # Validate
    if target.exists():
        # If target has a passport, adopt it (register without re-creating)
        passport_path = target / ".trinity" / "passport.json"
        if passport_path.exists():
            return _adopt_existing(target, purpose, profile, registry_path)

        # A directory with no live passport but WITH a tracked seed is the
        # fresh-clone shape (TDPLAN-0017): the branch's code came down with the
        # repo, its passport did not — .trinity/ is gitignored. That citizen is
        # not "already existing", it is waiting to be born, and its identity is
        # sitting right there in .aipass/passport.seed.json.
        #
        # This is also the ONLY door a seed can ever be found at. A seed lives
        # inside the branch directory it describes, so a mint into a target that
        # does not exist yet has no seed to prefer — the template path below is
        # correct there by construction, not by omission.
        seed_file = find_seed(target)
        if seed_file:
            return _birth_from_seed(target, seed_file, purpose, profile, registry_path)

        return _error(f"Target already exists: {target}")
    if not template.exists():
        return _error(f"Template not found: {template}")

    # Extract names
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    # Determine registry — per-project, never borrow another project's
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    try:
        target.relative_to(reg_path.parent)
    except ValueError:
        logger.info("[spawn] Target %s outside registry %s — resolving project-local registry", target, reg_path)
        reg_path = _find_project_registry(target)
    citizen_number = get_next_citizen_number(reg_path)

    # Resolve the PROJECT credential (the registry's own metadata.id) for the
    # passport's citizenship.registry_id. load_registry mints one when the
    # registry does not exist yet, which is what a brand-new external project
    # is — resolving it HERE rather than at registration time is the whole
    # point: the passport is written at step 1 and the registry at step 4, so
    # reading it later would stamp the passport with a credential that had not
    # been minted yet and fall back to AIPass's own id. Same mint-once ordering
    # as citizen_id below; the value is handed to add_to_registry so the file
    # that eventually lands carries the id the passport already claims.
    resolved_registry_id = load_registry(reg_path).get("metadata", {}).get("id", "")

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
    meta_tabs = _load_meta_tabs()
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
        return _error(
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


# The target-exists lane (adopt / birth-from-seed / the shared error dict) lives
# in handlers/adoption_ops.py — split out when this module crossed the 600-line
# standard. Re-exported under the old private names so the module seam the tests
# and callers know stays put.
_birth_from_seed = birth_from_seed
_adopt_existing = adopt_existing
_error = error_result
