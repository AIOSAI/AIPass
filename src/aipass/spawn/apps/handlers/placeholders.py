# =================== AIPass ====================
# Name: placeholders.py
# Description: Placeholder replacement engine
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-08-27
# =============================================

"""Placeholder replacement engine for agent templates."""

import json
import re
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.metadata import detect_profile
from aipass.spawn.apps.handlers.registry import find_registry

# AIPass's own installation root, derived from where the ``aipass`` package
# actually sits — the one shared detector (aipass.shared.project_home), not a
# copy that can drift from it. Underscore-private there, but it is the single
# source of truth for this fact and duplicating it here would be the worse sin.
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

    The passport DECLARES residency; the sealed registry stays the trust anchor.

    Args:
        target_dir: Path to the citizen's directory.

    Returns:
        "core" — inside AIPass's own ``src/aipass/``.
        "resident" — inside AIPass's ``projects/`` (a project hosted in this repo).
        "external" — anywhere else, including a standalone project on disk.
    """
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

    A passport is a tracked, public file: an absolute path in it leaks the
    author's home directory and is wrong on every other machine. The anchor
    depends on where the citizen lives:

      core     → the AIPass repo root       (``src/aipass/spawn``)
      resident → that project's own root    (``src/baud/baud``)
      external → the nearest registry's dir (best effort)

    Args:
        target_dir: Path to the citizen's directory.
        registry_path: The registry this citizen is being written into, when the
            caller already resolved it. Passing it keeps the passport's ``path``
            and the registry entry's ``path`` anchored to the same root.

    Returns:
        POSIX-style relative path. Falls back to the bare directory name rather
        than ever emitting an absolute path.
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
    """
    Build the full placeholder -> value mapping.

    Args:
        target_dir: Path to target directory
        branch_name: Raw folder name
        **overrides: Optional overrides for ROLE, PURPOSE_BRIEF, PROFILE,
                     CITIZEN_NUMBER, CITIZEN_ID, CITIZEN_CLASS, MODULE,
                     REGISTRY_ID, RESIDENCY, registry_path, etc.

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
    # meanings — see the citizenship block in the template passport.
    citizen_id = overrides.get("citizen_id", "")

    caller_registry_path = overrides.get("registry_path")

    registry_id = overrides.get("registry_id", "")
    if not registry_id:
        registry_path = (
            Path(caller_registry_path) if caller_registry_path else find_registry(start_path=Path(target_dir).parent)
        )
        if registry_path.exists():
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_id = data.get("metadata", {}).get("id", "")

    replacements = {
        "BRANCHNAME": upper,
        "branchname": lower,
        "BRANCH": lower,
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
        "PURPOSE_BRIEF": overrides.get("purpose", "New agent - purpose TBD"),
        "CITIZEN_NUMBER": str(overrides.get("citizen_number", 0)),
        "CITIZEN_CLASS": overrides.get("citizen_class") or "specialist",
        "REGISTRY_ID": registry_id,
        "CITIZEN_ID": citizen_id,
        # PATH replaces the old CWD placeholder, which rendered an ABSOLUTE path
        # into a tracked public file (DPLAN-0319). RESIDENCY is R5's new
        # citizenship field. Both are derived from the target, never typed.
        "PATH": overrides.get("path") or resolve_relative_path(target_dir, caller_registry_path),
        "RESIDENCY": overrides.get("residency") or resolve_residency(target_dir),
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
