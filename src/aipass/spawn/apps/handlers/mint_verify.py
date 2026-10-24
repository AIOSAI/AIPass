# =================== AIPass ====================
# Name: mint_verify.py
# Description: Post-copy completeness check — did the mint deliver the template?
# Version: 1.0.1
# Created: 2026-08-17
# Modified: 2026-10-24
# =============================================

"""Verify a freshly minted citizen against the template that minted it.

A mint must produce every file its template claims: the tracked manifest (it survives a
clone that dropped ignored files) unioned with the on-disk contents. Reference: docs/birth.md"""

from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES
from aipass.spawn.apps.handlers.meta_ops import load_template_registry
from aipass.spawn.apps.handlers.placeholders import replace_placeholders

__all__ = ["expected_mint_paths", "verify_mint"]


def _is_skipped(rel_path: str) -> bool:
    """True when the copy engine would never have carried this path."""
    return any(part in SKIP_NAMES for part in Path(rel_path).parts)


def _map_path(rel_path: str, replacements: dict, branch_lower: str) -> str:
    """Render a template-relative path the way the copy renders it.

    Must mirror file_ops._replace_path_placeholders."""
    parts = []
    for part in Path(rel_path).parts:
        part = replace_placeholders(part, replacements or {})
        part = part.replace("{{BRANCH}}", branch_lower)
        parts.append(part)
    return Path(*parts).as_posix() if parts else rel_path


def expected_mint_paths(template_dir, replacements: dict, branch_lower: str) -> List[str]:
    """Return every target-relative file path the template claims, sorted."""
    template_dir = Path(template_dir)
    claimed = set()

    registry = load_template_registry(template_dir)
    if registry:
        for entry in (registry.get("files") or {}).values():
            path = (entry or {}).get("path", "")
            if path and not _is_skipped(path):
                claimed.add(_map_path(path, replacements, branch_lower))
    else:
        logger.info("[spawn] Template %s carries no manifest — verifying against its on-disk contents", template_dir)

    for item in template_dir.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(template_dir).as_posix()
        if _is_skipped(rel):
            continue
        claimed.add(_map_path(rel, replacements, branch_lower))

    return sorted(claimed)


def verify_mint(template_dir, target_dir, replacements: dict, branch_lower: str) -> List[str]:
    """Return the claimed paths that never landed in the target — empty is good."""
    target_dir = Path(target_dir)
    return [
        rel for rel in expected_mint_paths(template_dir, replacements, branch_lower) if not (target_dir / rel).is_file()
    ]
