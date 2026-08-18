# =================== AIPass ====================
# Name: mint_verify.py
# Description: Post-copy completeness check — did the mint deliver the template?
# Version: 1.0.0
# Created: 2026-08-17
# Modified: 2026-08-17
# =============================================

"""Verify a freshly minted citizen against the template that minted it.

Why this exists: on 2026-08-17 the repo-root ``.gitignore`` was found to swallow
six of ``templates/project_agent``'s eighteen files — blanket ignores for
``.ai_mail.local/``, ``DASHBOARD.local.json``, ``logs/`` and ``artifacts/`` with
no negation for that template. Every fresh clone therefore held an INCOMPLETE
template, and the mint copied whatever it found: exit 0, "Agent created",
"Registry: updated" — and a citizen with an empty ``artifacts/`` (no birth
certificate) and an empty ``.ai_mail.local/`` (no ``inbox.json``, so it could not
receive mail at all). The hospital worked only on the machine that authored the
template, and said nothing anywhere else.

The invariant this module enforces:

    A mint must produce every file its template CLAIMS to carry. Not a
    hardcoded list — the template's own claim.

Two sources make up that claim, unioned:

* ``.spawn/.template_registry.json`` — the template's manifest. This is the
  load-bearing half: it is a tracked file, so it survives a truncated clone and
  keeps naming files the clone no longer has. A check that only walked the
  template on disk would see nothing wrong, because the missing files are
  missing from the source too — that is exactly how the bug stayed silent.
* the template's on-disk contents — catches the other direction, a file that is
  present in the template but never landed in the target (a copy that failed
  quietly, a manifest that predates a new file).

Path claims are mapped through the same two transforms the copy performs
(``{{PLACEHOLDER}}`` substitution per path component, then the ``{{BRANCH}}``
rename pass), so ``apps/{{BRANCH}}.py`` is checked as ``apps/my_agent.py``.

Custom templates (``create --template <dir>``) usually carry no manifest. That
is not a defect and must never be treated as one: with nothing declared, the
on-disk half alone applies, which cannot false-positive because it is derived
from the very tree the copy read.
"""

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

    Mirrors ``file_ops._replace_path_placeholders`` (substitution per component)
    followed by ``file_ops.rename_placeholder_paths`` (the ``{{BRANCH}}`` pass),
    so a claim can be compared against what actually landed on disk.
    """
    parts = []
    for part in Path(rel_path).parts:
        part = replace_placeholders(part, replacements or {})
        part = part.replace("{{BRANCH}}", branch_lower)
        parts.append(part)
    return Path(*parts).as_posix() if parts else rel_path


def expected_mint_paths(template_dir, replacements: dict, branch_lower: str) -> List[str]:
    """Return every target-relative file path the template claims, sorted.

    Args:
        template_dir: The template the mint copied from.
        replacements: The placeholder mapping used for this mint.
        branch_lower: Lowercased branch folder name (the ``{{BRANCH}}`` value).

    Returns:
        Sorted list of POSIX-style relative paths expected under the target.
    """
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
    """Return the claimed paths that never landed in the target — empty is good.

    Args:
        template_dir: The template the mint copied from.
        target_dir: The freshly minted citizen directory.
        replacements: The placeholder mapping used for this mint.
        branch_lower: Lowercased branch folder name (the ``{{BRANCH}}`` value).

    Returns:
        Sorted list of missing target-relative paths. Empty when the mint
        delivered everything its template claims.
    """
    target_dir = Path(target_dir)
    return [
        rel for rel in expected_mint_paths(template_dir, replacements, branch_lower) if not (target_dir / rel).is_file()
    ]
