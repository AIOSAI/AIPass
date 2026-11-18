# =================== AIPass ====================
# Name: registry_name.py
# Description: The registry file name predicate, stdlib only, served on drone's top file
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Whether a file name is a registry's: it ends exactly, case-sensitively, in ``_REGISTRY.json``.

A name in, a bool out. No logging, no env, no disk: other branches import it before drone
runs. Which directory entries to list, and whether a directory counts, is each caller's policy.
"""

REGISTRY_SUFFIX = "_REGISTRY.json"


def is_registry_filename(name: str) -> bool:
    """True when *name* ends exactly in ``_REGISTRY.json``; ``drone_command_registry.json`` is not one."""
    return name.endswith(REGISTRY_SUFFIX)
