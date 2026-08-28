# =================== AIPass ====================
# Name: placeholders.py
# Description: Placeholder replacement engine
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-13
# =============================================

"""Placeholder replacement engine for agent templates."""

import json
import re
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.metadata import detect_profile
from aipass.spawn.apps.handlers.registry import find_registry


def replace_placeholders(content, replacements):
    """Replace {{PLACEHOLDER}} patterns in content string."""
    for placeholder, value in replacements.items():
        content = content.replace("{{" + placeholder + "}}", str(value))
    return content


def build_replacements_dict(target_dir, branch_name, **overrides):
    """
    Build the full placeholder -> value mapping.

    Args:
        target_dir: Path to target directory
        branch_name: Raw folder name
        **overrides: Optional overrides for ROLE, TRAITS, PURPOSE_BRIEF, PROFILE,
                     CITIZEN_NUMBER, CITIZEN_ID, MODULE, etc.

    Returns:
        Dict mapping placeholder names to replacement values
    """
    upper = branch_name.upper().replace("-", "_")
    lower = branch_name.lower().replace("-", "_")
    now = datetime.now()

    # CITIZEN_ID is the citizen's OWN unique id, stamped into the passport as
    # citizenship.citizen_id and rendered by faces as the passport number.
    # REGISTRY_ID below is a different fact: the id of the REGISTRY that holds
    # the citizen (shared by every citizen in a project). One name apart, two
    # meanings — see the citizenship block in the template passports.
    citizen_id = overrides.get("citizen_id", "")

    registry_id = overrides.get("registry_id", "")
    if not registry_id:
        registry_path = find_registry(start_path=Path(target_dir).parent)
        if registry_path.exists():
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_id = data.get("metadata", {}).get("id", "")

    replacements = {
        "BRANCHNAME": upper,
        "branchname": lower,
        "BRANCH": lower,
        "CWD": Path(target_dir).as_posix(),
        "DATE": now.strftime("%Y-%m-%d"),
        "MODULE": lower,
        "EMAIL": f"@{lower}",
        # PROFILE is the AIPass profile the citizen is registered under, and it is
        # what a birth certificate records as metadata.template. The default is
        # derived from the target path rather than hardcoded: update_ops calls this
        # builder with no profile override, so a hardcoded "AIPass Workshop" would
        # render the wrong profile into every /business/ branch it touched.
        "PROFILE": overrides.get("profile") or detect_profile(target_dir),
        "ROLE": overrides.get("role", ""),
        "TRAITS": overrides.get("traits", ""),
        "PURPOSE_BRIEF": overrides.get("purpose", "New agent - purpose TBD"),
        "CITIZEN_NUMBER": str(overrides.get("citizen_number", 0)),
        "CITIZEN_CLASS": overrides.get("citizen_class", "aipass_framework"),
        "REGISTRY_ID": registry_id,
        "CITIZEN_ID": citizen_id,
        "KEY_CAPABILITIES": "",
        "DEPENDS_ON": "",
        "PROVIDES_TO": "",
    }

    meta_tabs = overrides.get("meta_tabs")
    if meta_tabs:
        replacements.update(meta_tabs)

    return replacements


def validate_no_placeholders(target_dir):
    """
    Scan all text files in target_dir for unreplaced {{X}} patterns.

    Returns:
        List of (file_path, list_of_placeholders) tuples. Empty if clean.
    """
    pattern = re.compile(r"\{\{([^}]+)\}\}")
    issues = []

    for file_path in Path(target_dir).rglob("*"):
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError) as e:
            logger.warning(f"Could not read file for placeholder validation {file_path}: {e}")
            continue

        found = pattern.findall(content)
        if found:
            issues.append((str(file_path), list(set(found))))

    return issues
