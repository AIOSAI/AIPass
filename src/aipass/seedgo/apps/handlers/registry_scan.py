# =================== AIPass ====================
# Name: registry_scan.py
# Description: Case-Exact Registry Discovery
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""
Case-Exact Registry Discovery

One reader for "which files in this directory are registries", used by every
lane in seedgo that needs to find one.

WHY THIS EXISTS. Nine sites in this branch called
``parent.glob("*_REGISTRY.json")``. pathlib matches that pattern
CASE-INSENSITIVELY on Windows and on default macOS, so ``*_registry.json``
matched too, and every branch is full of bait: ten ``flow_json/*_registry.json``
plan counters and ``.spawn/.template_registry.json`` — which pathlib's ``*``
matches despite the leading dot, unlike the glob module. Measured on CI by
@drone: ``find_registry`` returned ``drone_command_registry.json`` as the
trust-anchor candidate (@devpulse, 2026-08-31, found on ef029782's
windows-setup leg).

WHAT IT COST HERE. An audit that discovers branches through a plan counter
audits the wrong world, and a bypass keyed off the wrong registry grants an
exemption where nobody declared one.

THE FIX. List the directory and re-check the NAME with a case-sensitive
``str.endswith``. The check is on the SUFFIX only, never the stem: external
projects name their registry after themselves and nothing promises an uppercase
stem — ``Vera-Studio_REGISTRY.json`` is a real one and must survive.

The cure already existed in the fleet (``prax/branch_detector.py`` and eight
aipass sites list-and-check) and never traveled to the sites that globbed. One
reader is what makes a tenth walk hard to write; a parse-tree pin in
``tests/test_registry_case_sweep.py`` makes it fail out loud.
"""

import os
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# CONSTANTS
# =============================================================================

#: The suffix a registry file's name must end with, EXACTLY. Cased on purpose:
#: this string is the whole defence, and comparing it case-insensitively puts
#: the defect straight back.
REGISTRY_SUFFIX = "_REGISTRY.json"

#: What a lane names when no registry exists anywhere above it. Kept identical
#: to the four private copies this module replaced, so the case fix changes the
#: case behaviour and nothing else.
DEFAULT_REGISTRY_NAME = "AIPASS_REGISTRY.json"

CALLER_CWD_VAR = "AIPASS_CALLER_CWD"


# =============================================================================
# PUBLIC API
# =============================================================================


def registries_in(directory: Path) -> List[Path]:
    """Registry files sitting directly in ``directory``, name-exact and sorted.

    Args:
        directory: Directory to list. Unreadable or missing directories answer
            [] rather than raising — a walk up the tree crosses both.

    Returns:
        Sorted list of paths whose NAME ends with ``_REGISTRY.json``, case
        exactly. Directories are excluded; a folder can carry any name.
    """
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        logger.info("registry_scan: cannot list %s: %s", directory, exc)
        return []
    return [entry for entry in entries if entry.name.endswith(REGISTRY_SUFFIX) and entry.is_file()]


def find_registry_upward(start: Path) -> Optional[Path]:
    """First registry at or above ``start``, or None if the walk finds none."""
    for parent in [start] + list(start.parents):
        found = registries_in(parent)
        if found:
            return found[0]
    return None


def find_registry() -> Path:
    """The registry this process should read: CWD first, then this file's tree.

    CWD-first matches drone's registry_handler search order and is what lets an
    external project with its own registry be audited from inside itself. The
    __file__ walk is the pip-editable-install fallback.

    Returns:
        Path to the registry found, or ``<cwd>/AIPASS_REGISTRY.json`` when the
        whole walk comes up empty. That last value is a NAME, not a file that
        exists; callers already treat a non-existent registry as an empty world.
    """
    from_cwd = find_registry_upward(Path.cwd())
    if from_cwd is not None:
        return from_cwd
    from_source = find_registry_upward(Path(__file__).resolve().parent)
    if from_source is not None:
        return from_source
    return Path.cwd() / DEFAULT_REGISTRY_NAME


def caller_registries() -> List[Path]:
    """Every registry in the first directory at or above the CALLING project.

    The caller's own working directory arrives in ``AIPASS_CALLER_CWD`` from
    drone, because seedgo's own cwd is seedgo. Unset means no caller context,
    which is not an error — it is how a direct run looks.
    """
    caller_cwd = os.environ.get(CALLER_CWD_VAR, "")
    if not caller_cwd:
        return []
    caller_path = Path(caller_cwd)
    for parent in [caller_path] + list(caller_path.parents):
        found = registries_in(parent)
        if found:
            json_handler.log_operation(
                "caller_registries_found",
                {"directory": str(parent), "count": len(found)},
            )
            return found
    return []
