# =================== AIPass ====================
# Name: repo_context.py
# Description: Which repo a git command operates on — AIPass's own, or an external project's
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""Which repository a git command is operating on.

One answer, so the auth gate and the handlers cannot drift apart on it.
"""

from __future__ import annotations

from pathlib import Path

from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

# Any other registry name marks an external project.
AIPASS_REGISTRY_NAME = "AIPASS_REGISTRY.json"


def is_aipass_repo(repo_root: Path | None = None) -> bool:
    """Return True when *repo_root* (the root git will actually run in) is the AIPass framework repo itself."""
    root = repo_root if repo_root is not None else find_repo_root()
    return (root / AIPASS_REGISTRY_NAME).is_file()
