# =================== AIPass ====================
# Name: metadata.py
# Description: Branch name extraction and profile detection
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-10
# =============================================

"""Branch name extraction and profile detection."""

from pathlib import Path


def get_branch_name(target_path):
    """Extract branch name from target path (last folder name)."""
    return Path(target_path).name


def normalize_branch_name(name, case="upper"):
    """Normalize branch name: replace hyphens with underscores, apply case."""
    normalized = name.replace("-", "_")
    return normalized.upper() if case == "upper" else normalized.lower()


def detect_profile(target_path):
    """Detect the AIPass profile from a path. Returns 'AIPass Workshop' by default.

    KEPT, not retired (DPLAN-0319 called this "your call" — measured before
    deciding). "AIPass Workshop" reads like a fossil, but it is a LIVE value with
    real consumers, so retiring it would break things that work:

      * ``{{PROFILE}}`` is still rendered by ``templates/citizen/artifacts/
        birth_certificate.json`` into ``metadata.template`` and the certificate
        description — 17 core branches carry "AIPass Workshop" there today.
      * ``_spawn_agent`` passes the result to ``add_to_registry`` as the registry
        entry's ``profile`` field.

    What it is NOT: a citizen class, a template directory, or anything the
    Passport 2.0 schema reads. The 2.0 passport has no profile field at all —
    residency (``citizenship.residency``) is the field that answers "where does
    this citizen live", and it is computed in placeholders.py, not here.

    The "/business/" branch is the only real detection rule; everything else
    falls through to the default.
    """
    path_str = str(target_path)
    if "/business/" in path_str.lower():
        return "Business"
    return "AIPass Workshop"
