# =================== AIPass ====================
# Name: placeholders.py
# Description: Placeholder replacement engine
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""Placeholder replacement engine for agent templates."""

import json
import re
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.metadata import detect_profile
from aipass.spawn.apps.handlers.registry import find_registry

# Underscore-private, but the one shared home detector; a local copy would drift from it.
from aipass.aipass.shared.project_home import _detect_aipass_home


def replace_placeholders(content, replacements):
    """Replace {{PLACEHOLDER}} patterns in content string."""
    for placeholder, value in replacements.items():
        content = content.replace("{{" + placeholder + "}}", str(value))
    return content


def _aipass_home():
    """Return the AIPass installation root as a Path, or None when undetectable."""
    home = _detect_aipass_home()
    if not home:
        logger.info("[spawn] AIPass home not detectable — residency falls back to 'external'")
        return None
    return Path(home).resolve()


def resolve_residency(target_dir) -> str:
    """Classify where a citizen lives (DPLAN-0319 R5).

    The passport declares residency; the sealed registry stays the trust anchor."""
    target = Path(target_dir).resolve()
    home = _aipass_home()
    if home:
        if target.is_relative_to(home / "src" / "aipass"):
            return "core"
        if target.is_relative_to(home / "projects"):
            return "resident"
    return "external"


def resolve_relative_path(target_dir, registry_path=None) -> str:
    """Render a citizen's path RELATIVE — never an absolute /home/... path.

    A passport is tracked and public: an absolute path leaks the author's home directory.
    Pass registry_path so the passport and the registry entry anchor to the same root.
    """
    target = Path(target_dir).resolve()
    home = _aipass_home()

    if home:
        if target.is_relative_to(home / "src" / "aipass"):
            return target.relative_to(home).as_posix()
        projects_root = home / "projects"
        if target.is_relative_to(projects_root):
            parts = target.relative_to(projects_root).parts
            if parts:
                return target.relative_to(projects_root / parts[0]).as_posix()

    reg_path = Path(registry_path) if registry_path else find_registry(start_path=target.parent)
    if reg_path is None:
        logger.warning("[spawn] No registry found above %s — passport path falls back to the bare name", target)
        return target.name
    try:
        return target.relative_to(Path(reg_path).resolve().parent).as_posix()
    except ValueError:
        logger.warning(
            "[spawn] %s is not under registry root %s — passport path falls back to the bare name",
            target,
            reg_path,
        )
        return target.name


def build_replacements_dict(target_dir, branch_name, **overrides):
    """Build the full placeholder -> value mapping."""
    upper = branch_name.upper().replace("-", "_")
    lower = branch_name.lower().replace("-", "_")
    now = datetime.now()

    # CITIZEN_ID is the citizen's own id (the passport number); REGISTRY_ID is the id of
    # the registry holding it, shared by every citizen in a project.
    citizen_id = overrides.get("citizen_id", "")

    caller_registry_path = overrides.get("registry_path")

    registry_id = overrides.get("registry_id", "")
    if not registry_id:
        registry_path = (
            Path(caller_registry_path) if caller_registry_path else find_registry(start_path=Path(target_dir).parent)
        )
        # No registry: leave registry_id empty, never substitute a credential nobody issued.
        if registry_path is not None and registry_path.exists():
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_id = data.get("metadata", {}).get("id", "")

    replacements = {
        "BRANCHNAME": upper,
        "branchname": lower,
        "BRANCH": lower,
        "DATE": now.strftime("%Y-%m-%d"),
        "MODULE": lower,
        "EMAIL": f"@{lower}",
        # Derived, not hardcoded: update_ops passes no profile, so a fixed default
        # would mislabel every /business/ branch.
        "PROFILE": overrides.get("profile") or detect_profile(target_dir),
        "ROLE": overrides.get("role", ""),
        "PURPOSE_BRIEF": overrides.get("purpose", "New agent - purpose TBD"),
        "CITIZEN_NUMBER": str(overrides.get("citizen_number", 0)),
        "CITIZEN_CLASS": overrides.get("citizen_class") or "specialist",
        "REGISTRY_ID": registry_id,
        "CITIZEN_ID": citizen_id,
        "PATH": overrides.get("path") or resolve_relative_path(target_dir, caller_registry_path),
        "RESIDENCY": overrides.get("residency") or resolve_residency(target_dir),
    }

    meta_tabs = overrides.get("meta_tabs")
    if meta_tabs:
        replacements.update(meta_tabs)

    return replacements


def validate_no_placeholders(target_dir):
    """Scan all text files in target_dir for unreplaced {{X}} patterns."""
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
