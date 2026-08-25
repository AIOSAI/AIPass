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
from aipass.spawn.apps.handlers.registry import (
    load_registry,
    find_registry,
    add_to_registry,
    get_next_citizen_number,
    fix_passport_registry_id,
    ensure_project_has_owner,
)
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as _get_template_dir,
    validate_class as validate_class,
    get_default_class as get_default_class,
    get_available_classes as get_available_classes,
    refuse_forbidden_class as refuse_forbidden_class,
)
from aipass.spawn.apps.handlers.json import json_handler

# Default template location (relative to spawn package root)
DEFAULT_TEMPLATE = Path(__file__).parents[2] / "templates" / "aipass_framework"

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
    traits="",
    purpose="",
    profile=None,
    template_dir=None,
    registry_path=None,
    citizen_class="aipass_framework",
):
    """
    Create a new AIPass agent from template.

    Args:
        target_path: Where to create the agent (must not exist)
        role: Agent's role description
        traits: Agent's personality traits
        purpose: Agent's purpose (brief description)
        profile: AIPass profile override (default: auto-detect)
        template_dir: Custom template directory (default: class-based lookup)
        registry_path: Path to AIPASS_REGISTRY.json (default: auto-discover)
        citizen_class: Citizen class name (default: "aipass_framework")

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
    # Forbidden values refuse before any filesystem work — "admin" is a
    # devpulse-only registry privilege, never a class and never a template
    # directory (DPLAN-0288). Both doors are checked, including the API.
    for candidate in (citizen_class, Path(template_dir).name if template_dir else ""):
        refusal = refuse_forbidden_class(candidate)
        if refusal:
            return _error(refusal)

    target = Path(target_path).resolve()
    if template_dir:
        template = Path(template_dir)
    else:
        template = _get_template_dir(citizen_class)

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

    # Build placeholder replacements
    meta_tabs = _load_meta_tabs()
    replacements = build_replacements_dict(
        target,
        folder_name,
        role=role,
        traits=traits,
        purpose=purpose or "New agent - purpose TBD",
        profile=detected_profile,
        citizen_number=citizen_number,
        citizen_class=citizen_class,
        meta_tabs=meta_tabs,
        registry_id=resolved_registry_id,
        citizen_id=citizen_id,
    )

    # Step 1: Copy template with placeholder replacement in content
    ensure_directory(target)
    copied, skipped = copy_template(template, target, replacements)

    # Step 2: Rename any {{BRANCH}} dirs/files that weren't caught by path replacement
    renamed = rename_placeholder_paths(target, folder_name)

    # Step 2b: Set owner field — first agent in the project is the owner
    passport_path = target / ".trinity" / "passport.json"
    if passport_path.exists():
        passport_data = json_handler.read_json(passport_path)
        if passport_data:
            passport_data.setdefault("citizenship", {})["owner"] = citizen_number == 1
            json_handler.write_json(passport_path, passport_data)

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
    issues = validate_no_placeholders(target)

    json_handler.log_operation("branch_created", data={"branch": branch_upper})

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


def _adopt_existing(target, purpose, profile, registry_path):
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

    Returns:
        Result dict matching _spawn_agent return format.
    """
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)

    # Read purpose from passport if not provided
    if not purpose:
        passport_path = target / ".trinity" / "passport.json"
        # read_json returns None on failure (and logs) — same pattern as line ~250.
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
    )

    ensure_project_has_owner(reg_path)

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


def _error(message):
    """Return error result dict."""
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
