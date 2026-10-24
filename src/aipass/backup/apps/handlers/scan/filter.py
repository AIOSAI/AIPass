# =================== AIPass ====================
# Name: filter.py
# Description: Post-walk path filtering against ignore/whitelist/size rules
# Version: 2.0.1
# Created: 2026-04-16
# Modified: 2026-10-24
# =============================================

"""Path filter."""

import os

import pathspec

from aipass.prax import logger

from ..ignore.patterns import is_ignored
from ..ignore.whitelist import is_whitelisted
from ..audit import trail


def is_excluded(rel_path: str, spec: pathspec.PathSpec, whitelist: list[str]) -> bool:
    """True when the ignore spec matches a path and no whitelist entry rescues it; filter_paths' own rule."""
    return is_ignored(rel_path, spec) and not is_whitelisted(rel_path, whitelist)


def filter_paths(
    paths: list[tuple[str, str]],
    spec: pathspec.PathSpec,
    whitelist: list[str],
    max_size_mb: int,
) -> list[tuple[str, str]]:
    """Filter (absolute, relative) candidate paths for a backup; a whitelisted path skips the size bound too."""
    max_bytes = max_size_mb * 1024 * 1024
    result = []
    skipped = 0

    for abs_path, rel_path in paths:
        if is_whitelisted(rel_path, whitelist):
            result.append((abs_path, rel_path))
            continue

        if is_ignored(rel_path, spec):
            skipped += 1
            continue

        try:
            size = os.path.getsize(abs_path)
        except OSError as e:
            logger.warning(f"Cannot stat {abs_path}: {e}")
            skipped += 1
            continue

        if size > max_bytes:
            skipped += 1
            continue

        result.append((abs_path, rel_path))

    trail.log_operation(
        "filter_paths",
        {"total": len(paths), "included": len(result), "skipped": skipped},
    )
    return result
