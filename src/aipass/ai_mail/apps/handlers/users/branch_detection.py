# =================== AIPass ====================
# Name: branch_detection.py
# Description: Branch Auto-Detection Handler
# Version: 1.3.0
# Created: 2025-11-18
# Modified: 2026-08-21
# =============================================

"""
Branch Auto-Detection Handler

Detects which branch is calling AI_MAIL based on PWD/CWD.
Walks up directory tree to find branch root (has .trinity/passport.json).
"""

# =============================================
# IMPORTS
# =============================================
import os
import sys
import json
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# =============================================
# CONSTANTS
# =============================================
BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"

# Values of AIPASS_CALLER_IDENTITY_SOURCE that are EVIDENCE OF WHO, not of WHERE,
# and so survive a caller standing outside any branch. "project" is deliberately
# absent: it names a directory, and a directory that happens to spell a citizen is
# how a dispatch from the repo root sent as @aipass (@devpulse, 0bb77ec2).
_CREDENTIAL_SOURCES = frozenset({"assigned", "passport"})

# Strategies where AIPASS_CALLER_BRANCH did not merely exist but actually RESOLVED
# against a catalog. `caller_branch:synthesized` is deliberately absent: it invents
# a citizen from env vars alone, so nothing vouched for the name.
_ENV_VAR_RESOLVED_STRATEGIES = frozenset({"caller_branch:registry", "caller_branch:contact"})


def _get_contact_info(branch_name: str) -> Optional[Dict]:
    """Look up branch info from the contacts address book.

    Fastest path for sender detection — works for external projects that
    have previously registered via contacts, bypassing registry/CWD walk.

    Args:
        branch_name: Branch name or email (e.g., 'devpulse' or '@devpulse').

    Returns:
        Synthetic branch info dict compatible with registry format, or None.
    """
    try:
        from aipass.ai_mail.apps.handlers.email.contacts import get_contact

        contact = get_contact(branch_name)
        if not contact:
            return None
        inbox_path = Path(contact["inbox"])
        branch_path = inbox_path.parent.parent  # .ai_mail.local -> branch root
        if not branch_path.is_dir():
            # A row whose branch root no longer exists on disk is stale — a
            # dead pytest tmp_path or a cleaned-up scratchpad probe. Trusting
            # it here handed callers a "verified" identity backed by a dead
            # path (found live, 2026-08-16, @devpulse: an unisolated test
            # suite's poisoned rows were served as real contacts). Fall
            # through to the next resolution strategy instead.
            return None
        name_key = branch_name.lstrip("@").lower()

        # DEFENCE IN DEPTH, and it is here to make poisoning AUDIBLE. The caller
        # above now asks the registry first, so a contradicting row is no longer
        # reachable from that lane — but a row claiming a citizen's name while
        # pointing at a different branch is CORRUPT DATA, not a cache miss, and a
        # silent fall-through would leave it in the file to surprise the next
        # reader. Refuse it and say so, loudly enough to be found.
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
    except Exception as e:
        logger.warning("[identity] _get_contact_info(%s) failed: %s", branch_name, e)
        return None


def _find_caller_registry() -> Optional[Path]:
    """Find the caller's project registry by walking up from AIPASS_CALLER_CWD.

    Used to resolve external project branches that aren't in the AIPass registry.
    External projects name their registry PROJECTNAME_REGISTRY.json — Vera-Studio's
    is VERA-STUDIO_REGISTRY.json — so this globs *_REGISTRY.json. Matching the one
    hardcoded name meant the fallback could never fire for any external project,
    i.e. it could never serve the only callers it exists for. Same bug class @drone
    fixed twice in their own resolution paths (2d1a5ff7, 60a3fb72); sorted() for the
    same reason they used it — deterministic pick when a dir holds several.

    Skips the AIPass registry itself to avoid redundant double-lookup.

    Returns:
        Path to the caller's registry file, or None if not found or same as main registry.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd:
        return None
    candidate = Path(caller_cwd)
    aipass_registry = BRANCH_REGISTRY_PATH.resolve()
    for path in [candidate] + list(candidate.parents)[:10]:
        for registry in sorted(path.glob("*_REGISTRY.json")):
            try:
                if registry.resolve() != aipass_registry:
                    return registry
            except Exception as e:
                logger.warning("[identity] _find_caller_registry() resolve failed for %s: %s", registry, e)
    return None


def _get_branches_list(registry: dict) -> list:
    """Normalize branches from registry to a list of dicts.

    Handles both formats:
    - List: [{"name": "DEVPULSE", ...}, ...]
    - Dict: {"devpulse": {"name": "devpulse", ...}, ...}
    """
    branches = registry.get("branches", [])
    if isinstance(branches, dict):
        return list(branches.values())
    return branches


# =============================================
# BRANCH DETECTION FUNCTIONS
# =============================================


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

    Before this, resolve_sender() logged only its pre-resolution input, so a message
    filed under the wrong citizen left no trace of how it got there — @aipass spent
    hours of cross-mailbox forensics on one misattribution and still could not tell
    which strategy fired. Every exit from detect_branch_from_pwd() goes through here.

    `confidence` is "verified" when the identity came from a passport or registry
    entry, "unverified" when it was taken on trust from the environment or from this
    process's own cwd. An unverified win that later proves wrong is the thing to grep.

    Args:
        branch_info: Resolved branch dict, or None if resolution failed.
        strategy: Which resolution path produced it (input source : method).
        confidence: "verified" or "unverified".

    Returns:
        branch_info unchanged — this is a pass-through recorder.
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

    # Both caller signals present but pointing at different branches: we silently
    # pick AIPASS_CALLER_BRANCH. Legitimate when the caller stood outside any branch
    # (drone falls back to the env var), so this warns rather than raises — but it is
    # the one disagreement visible from inside this process, so it gets recorded.
    #
    # UNLESS THE ENV VAR CARRIES A CREDENTIAL, in which case there is no disagreement
    # to name. A credential travels and a location does not: an agent that cds into
    # another branch is still itself (S102), so `assigned`/`passport` naming one
    # branch while the cwd sits in another is the DESIGNED precedence working, not a
    # conflict. 104 lifetime warnings said AMBIGUOUS about correctly-resolved sweeps
    # — every one CALLER_BRANCH='ai_mail' with the cwd walking the whole fleet — and
    # a warning that fires on the known-good case buries the one it exists for.
    #
    # Two things deliberately keep warning, because neither is proven good:
    #   • provenance `project` — a registry-derived DIRECTORY name, which answers
    #     "which project am I in", never "who am I". @aipass the directory and
    #     @aipass the citizen spell the same; that is the $1.41 wake, and it must
    #     stay loud forever.
    #   • provenance missing or `unknown` (an older drone, or no drone) — unprovable
    #     is not proven, and this lane fails toward noise rather than toward silence.
    # A credential naming a citizen the registry has never heard of also still warns:
    # resolution falls through to synthesis, and the provenance only says who STAMPED
    # the name, never that anything vouched for it.
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
    """
    Detect which branch is calling based on current working directory.

    Walks up directory tree from PWD to find branch root (directory with .trinity/passport.json).
    Then looks up branch info in AIPASS_REGISTRY.json.

    Every exit is recorded by _record_resolution() with the winning strategy, so a
    wrong sender can be traced to the path that produced it.

    Returns:
        Dict with branch info if detected, or None.
    """
    json_handler.log_operation("detect_branch_from_pwd", {"cwd": str(Path.cwd())})

    try:
        # AIPASS_CALLER_CWD is EVIDENCE of where the caller stood; AIPASS_CALLER_BRANCH
        # is only a CLAIM about who they are, and the claim may not outvote the evidence.
        # drone stamps CALLER_BRANCH from the nearest PROJECT directory name, so at the
        # repo root it stamps 'aipass' — which collides with the @aipass citizen, whose
        # contact row then resolves it "verified" and hands over that mailbox. That is
        # how a dispatch run from the repo root sent as @aipass and woke the wrong
        # citizen: 11 turns, $1.41 (@devpulse, 0bb77ec2; ruling in 096c9a42).
        #
        # ABSENT evidence is not CONTRADICTING evidence: an unset CALLER_CWD leaves the
        # strategies below untouched, which is what in-process callers depend on
        # (@trigger's delivery import, @daemon's wake import, the dispatch spawn env).
        caller_cwd_env = os.environ.get("AIPASS_CALLER_CWD")
        if caller_cwd_env and not find_branch_root(Path(caller_cwd_env)):
            # The provenance decides, not the location. @drone stamps WHICH KIND of
            # evidence named the caller (shipped 2026-08-21, at this branch's
            # request): a CREDENTIAL travels, a location does not.
            #
            #   assigned — AIPASS_BRANCH_NAME, set when the process was created.
            #              True from any directory; refusing it broke S102, where
            #              an agent that cds into another branch is still itself.
            #   passport — a passport under the caller's feet. drone saw the real
            #              caller cwd and this process did not; trust the prover.
            #   project  — a registry-derived PROJECT name. Answers "which project
            #              am I in", never "who am I". @aipass the directory and
            #              @aipass the citizen spell the same and are not the same.
            #              This is the $1.41 wake; it stays refused forever.
            #
            # Anything else — absent (older drone, or no drone at all) or a value
            # this code does not know — falls through to refusal. The lift is
            # opt-in and fails closed.
            if os.environ.get("AIPASS_CALLER_IDENTITY_SOURCE") not in _CREDENTIAL_SOURCES:
                return _record_resolution(None, "caller_cwd:outside_branch", "refused")

        caller_branch = os.environ.get("AIPASS_CALLER_BRANCH")
        if caller_branch:
            # THE REGISTRY IS ASKED FIRST, and the order is the whole fix.
            # AIPASS_REGISTRY.json is the authoritative catalog; contacts.json is
            # a LEARNED, WRITABLE cache. Asking the cache first let ONE poisoned
            # row outrank the catalog for a citizen the catalog knew perfectly
            # well — found live on 2026-08-23, when `drone @ai_mail inbox` served
            # @flow's mailbox from inside @ai_mail's own directory. The identity
            # log recorded it as name AI_MAIL, email @ai_mail, path .../flow,
            # confidence "verified", which is the worst possible combination:
            # correct enough to look right, wrong where it counts, and confident.
            #
            # The is_dir() staleness guard in _get_contact_info could never have
            # caught it. That guard asks whether the branch root still exists;
            # the wrong root was a live branch with a real mailbox in it.
            #
            # Contacts keep their actual job — resolving EXTERNAL callers that the
            # registry has never heard of, which is what their own docstring
            # describes. They simply stop overruling the catalog for citizens.
            branch_info = _lookup_branch_by_name(caller_branch)
            if branch_info:
                return _record_resolution(branch_info, "caller_branch:registry", "verified")
            contact = _get_contact_info(caller_branch)
            if contact:
                return _record_resolution(contact, "caller_branch:contact", "verified")
            # Invents a citizen from env vars alone — no passport, no registry entry.
            return _record_resolution(
                _synthesize_external_branch(caller_branch), "caller_branch:synthesized", "unverified"
            )

        caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
        # No caller env at all means identity comes from THIS process's cwd, which is
        # the target branch under dispatch — correct there, silently wrong anywhere else.
        strategy = "caller_cwd:passport_walk" if caller_cwd else "process_cwd:passport_walk"
        confidence = "verified" if caller_cwd else "unverified"
        cwd = Path(caller_cwd) if caller_cwd else Path.cwd()

        branch_root = find_branch_root(cwd)
        if not branch_root:
            return _record_resolution(None, strategy, confidence)

        return _record_resolution(get_branch_info_from_registry(branch_root), strategy, confidence)

    except Exception as e:
        logger.warning("[identity] detect_branch_from_pwd() failed: %s", e)
        return None


def _rooted(branch: Dict, registry_path: Path) -> Dict:
    """Return *branch* with its ``path`` made absolute against its OWN registry.

    A registry row's ``path`` is relative to THE REGISTRY THAT HOLDS IT, and a
    row handed back raw carries no memory of which registry answered. Every
    consumer then joins it to the AIPass repo root — right for AIPass citizens
    by coincidence, wrong for every project citizen.

    Found live 2026-08-24 (@devpulse 10400b9b, measured by @baud): a projects/*
    citizen read "Inbox is empty" with four unread messages in the file under
    his feet, and `reply <id>` answered "Message not found" for an id read out
    of that same file. ``projects/baud`` + ``src/baud/baud`` had been resolved
    as ``<aipass>/src/baud/baud``.

    IT FABRICATED RATHER THAN FAILING. The wrong path sits inside the AIPass
    tree, so the mail lane CREATED it — a phantom .ai_mail.local/sent/ holding
    the reply he believed he had sent, in a directory belonging to no citizen.
    A refusal would have been loud; a confident wrong address was not.

    Absolutising HERE, at the one place a registry is read, rather than at the
    nine call sites that join a registry path: a consumer cannot re-derive a
    root it was never given, and nine copies of that join is how they drift.
    Rows that are already absolute are returned untouched.
    """
    path = str(branch.get("path", ""))
    if not path or Path(path).is_absolute():
        return branch

    rooted = dict(branch)
    rooted["path"] = str((registry_path.parent / path).resolve())
    return rooted


def _lookup_branch_by_name(branch_name: str) -> Optional[Dict]:
    """
    Look up branch in the registry by name (case-insensitive).

    Handles both registry formats:
    - List format: {"branches": [{"name": "DEVPULSE", ...}, ...]}
    - Dict format: {"branches": {"devpulse": {"name": "devpulse", ...}, ...}}

    Args:
        branch_name: Branch name (e.g., "DEVPULSE", "devpulse")

    Returns:
        Dict with branch info from registry, or None if not found
    """
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

    # Fallback: caller's registry (external project branches not in AIPass registry)
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
    """
    Walk up directory tree to find branch root.

    Branch root = directory containing .trinity/passport.json.
    Example: src/aipass/seedgo/ contains .trinity/passport.json

    Args:
        start_path: Directory to start searching from (usually PWD)

    Returns:
        Path to branch root directory, or None if not found
    """
    current = start_path.resolve()

    # Walk up directory tree (max 10 levels to prevent infinite loop)
    for _ in range(10):
        # Check for .trinity/passport.json (AIPass identity pattern)
        if (current / ".trinity" / "passport.json").exists():
            return current

        # Move up one level
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    return None


def get_branch_info_from_registry(branch_path: Path) -> Optional[Dict]:
    """
    Look up branch information in AIPASS_REGISTRY.json by path.

    Args:
        branch_path: Path to branch directory

    Returns:
        Dict with branch info from registry, or None if not found
    """
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

    # Fallback: caller's registry (external project branches not in AIPass registry)
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
