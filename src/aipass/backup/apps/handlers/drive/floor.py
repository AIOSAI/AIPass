# =================== AIPass ====================
# Name: floor.py
# Description: Never-leaves floor — paths the Drive lane refuses to upload
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Never-leaves floor for the Drive lane.

The patterns here are applied by drive_sync after the project's own ignore
spec, as a separate spec, so no line in a project's .backupignore (a ``!``
negation included) can reopen them. The local stores keep these files: a
backup that cannot restore a project's keys is not a backup. Only the lane
that leaves the machine refuses them.
"""

from pathlib import Path

import pathspec

from ..audit import trail

# gitwildmatch, as .backupignore is: a pattern with no slash matches at any
# depth, and "**/" lets the two token-store patterns do the same.
NEVER_LEAVES_MACHINE: tuple[str, ...] = (
    ".secrets/",  # any directory named .secrets, anywhere
    "*.key",  # private keys
    "*.pem",  # certificates and keys
    ".env",  # environment files
    ".env.*",
    "**/*_json/tokens_data.json",  # the host API's token store
    "**/*_json/tokens_config.json",
)

_FLOOR_SPEC = pathspec.PathSpec.from_lines("gitignore", NEVER_LEAVES_MACHINE)


def hold_back(files: list[Path], store_path: Path) -> tuple[list[Path], int]:
    """Split a store's files into those that may leave the machine and a count of the rest.

    Args:
        files: Absolute paths of files under store_path.
        store_path: The store root the floor patterns are matched against.

    Returns:
        (files the floor does not match, number of files it held back).
    """
    kept = [f for f in files if not _FLOOR_SPEC.match_file(f.relative_to(store_path).as_posix())]
    held = len(files) - len(kept)
    if held:
        trail.log_operation("never_leaves_held_back", {"store": str(store_path), "held_back": held})
    return kept, held


# =============================================
