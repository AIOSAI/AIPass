# =================== AIPass ====================
# Name: branch_detection.py
# Description: Branch Auto-Detection Handler
# Version: 1.4.0
# Created: 2025-11-18
# Modified: 2026-10-17
# =============================================

"""
Branch Auto-Detection Handler

Reference: docs/identity_and_boundaries.md
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root, registries_in

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"

# Caller identity sources that are evidence of WHO, not WHERE. "project" is absent: it names a directory.
_CREDENTIAL_SOURCES = frozenset({"assigned", "passport"})

# Strategies where CALLER_BRANCH resolved against a catalog; synthesized is absent (nothing vouched for it).
_ENV_VAR_RESOLVED_STRATEGIES = frozenset({"caller_branch:registry", "caller_branch:contact"})


def _get_contact_info(branch_name: str) -> Optional[Dict]:
    """Look up branch info from the contacts address book.

    None for no row, a stale row (root gone from disk) or a poisoned row; RuntimeError if the book is unreadable.
    """
    from aipass.ai_mail.apps.handlers.email.contacts import get_contact

    contact = get_contact(branch_name)
    if not contact:
        return None
    inbox_path = Path(contact["inbox"])
    branch_path = inbox_path.parent.parent  # .ai_mail.local -> branch root
    if not branch_path.is_dir():
        return None
    name_key = branch_name.lstrip("@").lower()

    # Defence in depth: a row claiming a citizen's name at a different path is corrupt data; refuse it loudly.
    registry_entry = _lookup_branch_by_name(name_key)
    if registry_entry:
        registry_path = Path(str(registry_entry.get("path", "")))
        if not registry_path.is_absolute():
            registry_path = (BRANCH_REGISTRY_PATH.parent / registry_path).resolve()
        if registry_path != branch_path.resolve():
            logger.error(
                "[identity] POISONED CONTACT ROW: %r claims branch %s but the registry places "
                "that citizen at %s. Refusing the row — serving it would hand this caller "
                "another citizen's mailbox. Repair the 'inbox' field for %r in contacts.json.",
                name_key,
                branch_path,
                registry_path,
                name_key,
            )
            return None

    return {
        "name": name_key.upper(),
        "email": "@" + name_key,
        "path": str(branch_path),
        "project": contact.get("project", ""),
    }


def _find_caller_registry() -> Optional[Path]:
    """Find the caller's project registry by walking up from AIPASS_CALLER_CWD.

    Globs *_REGISTRY.json (external projects name theirs after themselves), skipping the AIPass registry.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return None
    candidate = Path(caller_cwd)
    aipass_registry = BRANCH_REGISTRY_PATH.resolve()
    for path in [candidate] + list(candidate.parents)[:10]:
        for registry in registries_in(path):
            try:
                if registry.resolve() != aipass_registry:
                    return registry
            except Exception as e:
                logger.warning("[identity] _find_caller_registry() resolve failed for %s: %s", registry, e)
    return None


def _get_branches_list(registry: dict) -> list:
    """Normalize branches from registry to a list of dicts."""
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        return list(branches.values())
    return branches


def _synthesize_external_branch(caller_branch: str) -> Optional[Dict]:
    """Build a synthetic branch info dict from env vars for an external project."""
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return None
    cwd_path = Path(caller_cwd)
    name_key = caller_branch.lstrip("@").lower()
    return {
        "name": name_key,
        "path": str(cwd_path),
        "email": f"@{name_key}",
        "status": "active",
        "type": "external",
    }


def _record_resolution(branch_info: Optional[Dict], strategy: str, confidence: str) -> Optional[Dict]:
    """Log WHO the sender resolved to and WHICH strategy won, then pass the result through.

    Every exit from detect_branch_from_pwd() goes through here. ``confidence`` is "unverified" when the identity
    was taken on trust from env or process cwd: an unverified win that later proves wrong is the thing to grep.
    """
    caller_branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    resolved_name = (branch_info or {}).get("name", "")
    resolved_email = (branch_info or {}).get("email", "")

    json_handler.log_operation(
        "resolve_identity",
        {
            "strategy": strategy,
            "confidence": confidence,
            "resolved_name": resolved_name,
            "resolved_email": resolved_email,
            "resolved_path": (branch_info or {}).get("path", ""),
            "in_caller_branch": caller_branch,
            "in_caller_cwd": caller_cwd,
            "process_cwd": str(Path.cwd()),
        },
    )

    if not branch_info:
        logger.warning(
            "[identity] UNRESOLVED via %s (caller_branch=%r caller_cwd=%r)",
            strategy,
            caller_branch,
            caller_cwd,
        )
        return branch_info

    log = logger.info if confidence == "verified" else logger.warning
    log(
        "[identity] resolved %s (%s) via %s [%s]",
        resolved_email or "?",
        resolved_name or "?",
        strategy,
        confidence,
    )

    # Warn when CALLER_BRANCH and CALLER_CWD name different branches, unless a credential source (assigned/passport)
    # resolved via the catalog: a credential travels and a location does not. "project" provenance always warns.
    if caller_branch and caller_cwd:
        cwd_root = find_branch_root(Path(caller_cwd))
        if cwd_root and cwd_root.name.lower() != caller_branch.lstrip("@").lower():
            vouched = (
                os.environ.get("AIPASS_CALLER_IDENTITY_SOURCE") in _CREDENTIAL_SOURCES
                and strategy in _ENV_VAR_RESOLVED_STRATEGIES
            )
            log_disagreement = logger.debug if vouched else logger.warning
            log_disagreement(
                "[identity] AMBIGUOUS: AIPASS_CALLER_BRANCH=%r but AIPASS_CALLER_CWD sits in branch %r "
                "— resolved as %s from the env var. If this message is misattributed, the caller's cwd is why.",
                caller_branch,
                cwd_root.name,
                resolved_email or resolved_name,
            )

    return branch_info


def detect_branch_from_pwd() -> Optional[Dict]:
    """Detect which branch is calling based on current working directory.

    Raises RuntimeError when a step faults, so a fault never reads as "no branch".
    """
    json_handler.log_operation("detect_branch_from_pwd", {"cwd": str(Path.cwd())})

    try:
        # CALLER_CWD is evidence; CALLER_BRANCH is a claim (drone stamps 'aipass' at the repo root) and cannot
        # outvote it. Unset CALLER_CWD is no evidence: in-process callers (@trigger, @daemon, dispatch) depend on that.
        caller_cwd_env = os.environ.get("AIPASS_CALLER_CWD")
        if caller_cwd_env and not find_branch_root(Path(caller_cwd_env)):
            # Only a credential source survives a caller outside any branch; absent or unknown fails closed.
            if os.environ.get("AIPASS_CALLER_IDENTITY_SOURCE") not in _CREDENTIAL_SOURCES:
                return _record_resolution(None, "caller_cwd:outside_branch", "refused")

        caller_branch = os.environ.get("AIPASS_CALLER_BRANCH")
        if caller_branch:
            # Registry first: contacts.json is a writable cache, and a poisoned row must not outrank the catalog.
            branch_info = _lookup_branch_by_name(caller_branch)
            if branch_info:
                return _record_resolution(branch_info, "caller_branch:registry", "verified")
            contact = _get_contact_info(caller_branch)
            if contact:
                return _record_resolution(contact, "caller_branch:contact", "verified")
            return _record_resolution(
                _synthesize_external_branch(caller_branch), "caller_branch:synthesized", "unverified"
            )

        caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
        # No caller env: identity comes from this process's cwd, correct only under dispatch.
        strategy = "caller_cwd:passport_walk" if caller_cwd else "process_cwd:passport_walk"
        confidence = "verified" if caller_cwd else "unverified"
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()

        branch_root = find_branch_root(cwd)
        if not branch_root:
            return _record_resolution(None, strategy, confidence)

        return _record_resolution(get_branch_info_from_registry(branch_root), strategy, confidence)

    except Exception as e:
        logger.error("[identity] detect_branch_from_pwd() failed: %s", e)
        raise RuntimeError(f"Caller identity could not be resolved: {e}") from e


def _rooted(branch: Dict, registry_path: Path) -> Dict:
    """Return *branch* with its ``path`` made absolute against its OWN registry.

    Done here, where the registry is read: a consumer joining to the AIPass root mis-roots every project citizen.
    """
    path = str(branch.get("path", ""))
    if not path or Path(path).is_absolute():
        return branch

    rooted = dict(branch)
    rooted["path"] = str((registry_path.parent / path).resolve())
    return rooted


def _lookup_branch_by_name(branch_name: str) -> Optional[Dict]:
    """Look up branch in the registry by name (case-insensitive)."""
    name_lower = branch_name.lower()

    if BRANCH_REGISTRY_PATH.exists():
        try:
            with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for branch in _get_branches_list(registry):
                if branch.get("name", "").lower() == name_lower:
                    return _rooted(branch, BRANCH_REGISTRY_PATH)
        except Exception as e:
            logger.warning("[identity] _lookup_branch_by_name(%s) failed: %s", branch_name, e)

    caller_registry = _find_caller_registry()
    if caller_registry:
        try:
            with open(caller_registry, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for branch in _get_branches_list(registry):
                if branch.get("name", "").lower() == name_lower:
                    return _rooted(branch, caller_registry)
        except Exception as e:
            logger.warning(
                "[identity] _lookup_branch_by_name(%s) caller registry %s failed: %s", branch_name, caller_registry, e
            )

    return None


def find_branch_root(start_path: Path) -> Optional[Path]:
    """Walk up directory tree to find branch root."""
    current = start_path.resolve()

    # Walk up directory tree (max 10 levels to prevent infinite loop)
    for _ in range(10):
        if (current / ".trinity" / "passport.json").exists():
            return current

        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    return None


def get_branch_info_from_registry(branch_path: Path) -> Optional[Dict]:
    """Look up branch information in AIPASS_REGISTRY.json by path."""
    branch_path_resolved = branch_path.resolve()

    if BRANCH_REGISTRY_PATH.exists():
        try:
            with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
            registry_dir = BRANCH_REGISTRY_PATH.parent
            for branch in _get_branches_list(registry):
                reg_path = Path(branch["path"])
                if not reg_path.is_absolute():
                    reg_path = (registry_dir / reg_path).resolve()
                else:
                    reg_path = reg_path.resolve()
                if reg_path == branch_path_resolved:
                    return _rooted(branch, BRANCH_REGISTRY_PATH)
        except Exception as e:
            logger.warning("[identity] get_branch_info_from_registry(%s) failed: %s", branch_path, e)

    caller_registry = _find_caller_registry()
    if caller_registry:
        try:
            with open(caller_registry, "r", encoding="utf-8") as f:
                registry = json.load(f)
            registry_dir = caller_registry.parent
            for branch in _get_branches_list(registry):
                reg_path = Path(branch["path"])
                if not reg_path.is_absolute():
                    reg_path = (registry_dir / reg_path).resolve()
                else:
                    reg_path = reg_path.resolve()
                if reg_path == branch_path_resolved:
                    return _rooted(branch, caller_registry)
        except Exception as e:
            logger.warning("[identity] get_branch_info_from_registry(%s) caller registry failed: %s", branch_path, e)

    return None


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("BRANCH AUTO-DETECTION HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Detects which branch is calling AI_MAIL based on PWD/CWD")
    console.print("  Walks up directory tree to find branch root")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - detect_branch_from_pwd() -> Optional[Dict]")
    console.print("  - find_branch_root(start_path) -> Optional[Path]")
    console.print("  - get_branch_info_from_registry(branch_path) -> Optional[Dict]")
    console.print()
    console.print("HANDLER CHARACTERISTICS:")
    console.print("  [green]+[/green] Independent - no module dependencies")
    console.print("  [green]+[/green] Can import Prax (service provider)")
    console.print("  [green]+[/green] Pure business logic")
    console.print("  [dim]-[/dim] CANNOT import parent modules")
    console.print()
    console.print("DETECTION FLOW:")
    console.print("  1. Get current working directory (PWD)")
    console.print("  2. Walk up tree to find .trinity/passport.json")
    console.print("  3. Look up branch path in AIPASS_REGISTRY.json")
    console.print("  4. Return branch info (name, email, path, etc.)")
    console.print()
    console.print("=" * 70 + "\n")
