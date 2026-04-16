# =================== AIPass ====================
# Name: passport_ops.py
# Description: Passport command — grants birthright citizenship to a directory
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Passport command implementation for granting birthright citizenship.

Creates minimal citizen identity (.trinity/, .aipass/, README.md) and
registers in AIPASS_REGISTRY.json without creating the full 3-layer scaffold.
"""

from pathlib import Path

from aipass.prax import logger
from aipass.spawn.apps.handlers.metadata import (
    get_branch_name,
    normalize_branch_name,
    detect_profile,
)
from aipass.spawn.apps.handlers.placeholders import (
    build_replacements_dict,
    validate_no_placeholders,
)
from aipass.spawn.apps.handlers.file_ops import (
    copy_template,
    rename_placeholder_paths,
    regenerate_template_registry,
    ensure_directory,
)
from aipass.spawn.apps.handlers.registry import (
    find_registry,
    add_to_registry,
    get_next_citizen_number,
)
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.json import json_handler


def grant_passport(
    target_path: str,
    role: str = "",
    purpose: str = "",
) -> dict:
    """Grant birthright citizenship to a directory.

    Creates .trinity/, .aipass/, README.md and registers in AIPASS_REGISTRY.json.
    Does NOT create apps/ scaffold -- that's for builder class.

    Args:
        target_path: Path to the target directory (created if doesn't exist).
        role: Optional role description for the passport.
        purpose: Optional purpose description.

    Returns:
        Dict with results (success, branch_name, path, etc.)
    """
    target = Path(target_path).resolve()

    # Check if already a citizen
    trinity_dir = target / ".trinity"
    if trinity_dir.exists():
        return _error(f"Already a citizen -- .trinity/ exists at {target}")

    # Get birthright template
    template = get_template_dir("birthright")
    if not template.exists():
        return _error(f"Birthright template not found: {template}")

    # Extract names
    folder_name = get_branch_name(target)
    branch_upper = normalize_branch_name(folder_name, "upper")
    branch_lower = normalize_branch_name(folder_name, "lower")
    detected_profile = detect_profile(target)

    # Registry setup
    reg_path = find_registry(target.parent)
    citizen_number = get_next_citizen_number(reg_path)

    # Build placeholder replacements
    replacements = build_replacements_dict(
        target,
        folder_name,
        role=role,
        purpose=purpose or "Birthright citizen - purpose TBD",
        profile=detected_profile,
        citizen_number=citizen_number,
    )

    # Create directory if needed
    ensure_directory(target)

    # Copy birthright template with placeholder replacement
    copied, _ = copy_template(template, target, replacements)

    # Rename any placeholder paths
    _ = rename_placeholder_paths(target, folder_name)

    # Regenerate template registry
    regenerate_template_registry(target)

    # Register in AIPASS_REGISTRY.json (store relative path for portability)
    try:
        registry_branch_path = str(target.relative_to(reg_path.parent))
    except ValueError:
        logger.warning("[passport] Cannot relativize path %s to registry %s, storing absolute", target, reg_path.parent)
        registry_branch_path = str(target)
    registry_updated = add_to_registry(
        reg_path,
        branch_upper,
        registry_branch_path,
        detected_profile,
        f"@{branch_lower}",
        purpose or "Birthright citizen - purpose TBD",
    )

    # Validate
    issues = validate_no_placeholders(target)

    logger.info(f"[passport] Granted birthright to {branch_upper} at {target}")
    json_handler.log_operation("passport_created", data={"target": str(target)})

    return {
        "success": True,
        "branch_name": branch_upper,
        "path": str(target),
        "citizen_class": "birthright",
        "files_copied": len([c for c in copied if "(dir)" not in c]),
        "registry_updated": registry_updated,
        "registry_path": str(reg_path),
        "validation_issues": issues,
    }


def _error(message: str) -> dict:
    """Return error result dict."""
    return {
        "success": False,
        "error": message,
        "branch_name": "",
        "path": "",
        "citizen_class": "",
        "files_copied": 0,
        "registry_updated": False,
        "registry_path": "",
        "validation_issues": [],
    }
