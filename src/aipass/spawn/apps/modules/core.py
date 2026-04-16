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
from aipass.spawn.apps.handlers.registry import (
    find_registry,
    add_to_registry,
    get_next_citizen_number,
    fix_passport_registry_id,
)
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as _get_template_dir,
    validate_class as validate_class,
    get_default_class as get_default_class,
    get_available_classes as get_available_classes,
)
from aipass.spawn.apps.handlers.json import json_handler

# Default template location (relative to spawn package root)
DEFAULT_TEMPLATE = Path(__file__).parents[2] / "templates" / "builder"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("core Module")
    console.print("Agent creation orchestrator — full spawn workflow from template to registry")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - metadata.py (get_branch_name, normalize_branch_name, detect_profile — branch identity)")
    console.print("    - placeholders.py (build_replacements_dict, validate_no_placeholders — template substitution)")
    console.print(
        "    - file_ops.py (copy_template, rename_placeholder_paths, regenerate_template_registry, ensure_directory — filesystem ops)"
    )
    console.print(
        "    - meta_ops.py (load_template_registry, generate_branch_meta, save_branch_meta — branch metadata)"
    )
    console.print(
        "    - registry.py (find_registry, add_to_registry, get_next_citizen_number — AIPASS_REGISTRY management)"
    )
    console.print(
        "    - class_registry.py (validate_class, get_default_class, get_available_classes, get_template_dir — citizen class lookup)"
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
    citizen_class="builder",
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
        citizen_class: Citizen class name (default: "builder")

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
    target = Path(target_path).resolve()
    if template_dir:
        template = Path(template_dir)
    else:
        template = _get_template_dir(citizen_class)

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

    # Determine citizen number from registry
    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)
    citizen_number = get_next_citizen_number(reg_path)

    # Build placeholder replacements
    replacements = build_replacements_dict(
        target,
        folder_name,
        role=role,
        traits=traits,
        purpose=purpose or "New agent - purpose TBD",
        profile=detected_profile,
        citizen_number=citizen_number,
    )

    # Step 1: Copy template with placeholder replacement in content
    ensure_directory(target)
    copied, skipped = copy_template(template, target, replacements)

    # Step 2: Rename any {{BRANCH}} dirs/files that weren't caught by path replacement
    renamed = rename_placeholder_paths(target, folder_name)

    # Step 3: Regenerate .template_registry.json with fresh hashes
    regenerate_template_registry(target)

    # Step 3b: Generate branch metadata for tracking
    template_registry = load_template_registry(target)
    if template_registry:
        branch_meta = generate_branch_meta(target, template_registry)
        save_branch_meta(target, branch_meta)

    # Step 4: Register in project registry
    # Store path relative to registry location (works for both AIPass and external projects)
    try:
        registry_branch_path = str(target.relative_to(reg_path.parent))
    except ValueError as e:
        logger.warning("Cannot relativize path %s to registry %s: %s", target, reg_path.parent, e)
        registry_branch_path = str(target)
    registry_updated = add_to_registry(
        reg_path,
        branch_upper,
        registry_branch_path,
        detected_profile,
        f"@{branch_lower}",
        purpose or "New agent - purpose TBD",
    )

    # Step 5: Validate no unreplaced placeholders
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
    import json as _json

    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = profile or detect_profile(target)

    reg_path = Path(registry_path) if registry_path else find_registry(target.parent)

    # Read purpose from passport if not provided
    if not purpose:
        passport_path = target / ".trinity" / "passport.json"
        try:
            passport = _json.loads(passport_path.read_text(encoding="utf-8"))
            purpose = passport.get("identity", {}).get("purpose", "Adopted agent")
        except (ValueError, OSError) as e:
            logger.warning("Failed to read passport for purpose: %s", e)
            purpose = "Adopted agent"

    # Fix registry_id in passport if it doesn't match the current registry
    fix_passport_registry_id(target, reg_path)

    # Store path relative to registry location
    try:
        registry_branch_path = str(target.relative_to(reg_path.parent))
    except ValueError as e:
        logger.warning("Cannot relativize path %s to registry %s: %s", target, reg_path.parent, e)
        registry_branch_path = str(target)

    registry_updated = add_to_registry(
        reg_path,
        branch_upper,
        registry_branch_path,
        detected_profile,
        f"@{branch_lower}",
        purpose,
    )

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
