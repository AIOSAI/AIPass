# =================== AIPass ====================
# Name: repo_context.py
# Description: Which repo a git command operates on — AIPass's own, or an external project's
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Which repository a git command is operating on.

Drone's git verbs run from AIPass itself and from external project seats
(``projects/baud``, a cloned repo elsewhere). Some verbs encode AIPass's own
release conventions and must translate — or refuse — when the repo underfoot is
someone else's. This module answers the one question that decision rests on, in
one place, so the auth gate and the handlers cannot drift apart on it.
"""

from __future__ import annotations

from pathlib import Path

from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

# The framework repo's own registry filename. A repo whose registry is named
# anything else is an external project consuming AIPass as a service.
AIPASS_REGISTRY_NAME = "AIPASS_REGISTRY.json"


def is_aipass_repo(repo_root: Path | None = None) -> bool:
    """Return True when *repo_root* is the AIPass framework repo itself.

    Handlers pass the root they are about to run git in, so the answer describes
    the repo that will actually be touched — not whichever registry the caller's
    environment happens to resolve to. Defaults to ``find_repo_root()``.
    """
    root = repo_root if repo_root is not None else find_repo_root()
    return (root / AIPASS_REGISTRY_NAME).is_file()
