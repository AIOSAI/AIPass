# =================== AIPass ====================
# Name: auth.py
# Description: Passport-based authorization for devpulse operations
# Version: 1.0.1
# Created: 2026-03-30
# Modified: 2026-08-11
# =============================================

"""Passport-based authorization for git operations.

Identifies the calling branch by walking up from CWD to locate
``.trinity/passport.json``. Read-only commands need only a valid passport.
Write commands are authorized per-repo against that project's own registry:
manager class, matching tenancy, owner flag, and a passport presented from the
registry-recorded home. See ``_owner_tier_refusal`` for the full rule.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NamedTuple

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.repo_context import AIPASS_REGISTRY_NAME
from aipass.drone.apps.modules.registry import (
    RegistryMismatchError,
    get_registry_path,
    load_registry,
)

GIT_ACCESS_TIERS: dict[str, dict] = {
    "global": {
        "commands": [
            "status",
            "diff",
            "log",
            "show",
            "remote",
            "lock",
            "issue",
            "run",
            "workflow",
            "branches",
            "tag-list",
        ],
        "description": "Read-only — available to all branches",
    },
    "owner": {
        "commands": [
            "commit",
            "checkout",
            "sync",
            "unlock",
            "merge",
            "smart-sync",
            "fix",
            "dev-pr",
            "pr",
            "close-pr",
            "delete-branch",
            "prune-temp",
            "tag",
        ],
        "description": "Write operations — the project's own manager only",
    },
}

# Owner-tier is earned, not listed (DPLAN-0281, Patrick ruling). A caller holds it
# iff ALL of these hold — devpulse-in-AIPass qualifies through the general rule,
# with no special case, and any project's manager qualifies in their own repo:
#   1. passport citizen_class == manager
#   2. tenancy: passport citizenship.registry_id == registry metadata.id  (F59 4.1)
#   3. the registry for THAT repo lists the caller with owner: true
#   4. path-binding: the passport lives at/under the registry-recorded path (F59 4.2a)
#
# Check 4 is the one that closes T-A: a rogue sub-agent can forge a passport naming
# any branch and copy the registry id off local disk, but it cannot place that
# passport inside the real manager's directory without defeating the pre-edit hook
# layer and OS permissions first.
_MANAGER_CLASS = "manager"

# Rollback is one env var (F59 6.1). 'warn' logs the refusal and allows, for
# migration triage; anything else enforces. Deliberately not a config file —
# a rollback that needs an edit is not a rollback.
_AUTH_MODE_ENV = "AIPASS_GIT_AUTH_MODE"

# Owner-tier verbs that encode AIPass's OWN dev→PR→main flow: they assume a `dev`
# branch, our PR conventions, or pyproject versioning. Against an arbitrary project
# repo they would half-run and leave a mess, so they refuse honestly until
# translated. `commit` and `sync` translated in DPLAN-0281 P2; `tag` in DPLAN-0290
# item 1 — an external seat tags its own HEAD, so it is no longer on this list.
_AIPASS_FLOW_VERBS = frozenset({"dev-pr", "pr", "close-pr", "merge", "smart-sync", "fix", "delete-branch"})

# Verbs that DO work from an external seat, named in the refusal so a manager who
# hits one of the above learns what they can use instead of guessing.
_TRANSLATED_VERBS = "'commit', 'sync' and 'tag'"


# Real git verbs drone deliberately does not expose — staging and remote work are
# folded into higher-level commands. Without a pointer the refusal is a dead end.
_REROUTED_VERBS: dict[str, str] = {
    "add": "Staging is part of commit — use 'commit --all' or 'commit \"<msg>\" <files>'.",
    "push": "Use 'dev-pr' to push dev and open a PR.",
    "pull": "Use 'sync'.",
}


def _rerouted_hint(command: str) -> str:
    """Return a ' <hint>' suffix for git verbs drone routes elsewhere, else ''."""
    hint = _REROUTED_VERBS.get(command)
    return f" {hint}" if hint else ""


class Caller(NamedTuple):
    """An identified caller: who they claim to be, and where they said it from.

    ``home`` is load-bearing — it is the directory the passport was found in, and
    owner-tier binds authority to that location (F59 4.2a). A name alone is
    self-reported and forgeable; a name plus a location the attacker cannot
    occupy is not.
    """

    name: str
    home: Path
    passport: dict


def _resolve_caller() -> Caller:
    """Walk up from CWD to find passport.json and return the caller's identity.

    Raises PermissionError if no readable, named passport is found.
    """
    current = Path.cwd().resolve()
    for _ in range(10):
        passport_path = current / ".trinity" / "passport.json"
        if passport_path.exists():
            try:
                with open(passport_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                if not name:
                    msg = f"Passport at {passport_path} has no branch_name"
                    logger.error(msg)
                    raise PermissionError(msg)
                return Caller(name=name, home=current, passport=data)
            except PermissionError:
                raise
            except Exception as exc:
                logger.error("Failed to read passport at %s: %s", passport_path, exc)
                raise PermissionError(f"Failed to read passport at {passport_path}: {exc}") from exc
        parent = current.parent
        if parent == current:
            break
        current = parent

    # WARNING, not ERROR: the gate failing closed on a non-branch CWD is designed
    # behaviour, not a fault. Logged loud enough to diagnose, quiet enough not to
    # page anyone (@trigger log-fix 906263c8ff2e). The caller's cwd is the one
    # fact that identifies WHO tripped the gate; trigger's normalizer collapses
    # it to <path>, so repeat signatures stay unified across callers.
    msg = f"No .trinity/passport.json found in directory hierarchy (caller cwd: {Path.cwd()}) — cannot verify caller"
    logger.warning(msg)
    raise PermissionError(msg)


def _find_caller() -> str:
    """Return just the calling branch's name (global tier needs nothing more)."""
    return _resolve_caller().name


def _citizen_class(passport: dict) -> str:
    """Read citizen_class from either passport layout, '' when absent."""
    identity = passport.get("identity", {})
    branch_info = passport.get("branch_info", {})
    return identity.get("citizen_class") or branch_info.get("citizen_class") or ""


def _registry_entry(registry_data: dict, name: str) -> dict | None:
    """Find a branch's entry in a registry, case-insensitively.

    Registries differ on casing — AIPass records 'devpulse', Vera-Studio 'VERA' —
    and ``_load_registry_data`` lowercases the keys only for the LIST shape it
    normalizes. A registry authored as a dict is passed through untouched, keys
    and all, so a plain lowercase lookup would miss 'VERA' and read as "not
    listed" — a denial that has nothing to do with authority. Both shapes are
    matched case-insensitively (F59 4.1: wrap the shared loader, don't change it).
    """
    branches = registry_data.get("branches", {})
    key = name.lower()
    if isinstance(branches, dict):
        entry = branches.get(key)
        if entry is not None:
            return entry
        return next((v for k, v in branches.items() if str(k).lower() == key), None)
    for entry in branches:
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == key:
            return entry
    return None


def _recorded_home(entry: dict, repo_root: Path) -> Path | None:
    """Resolve a registry entry's recorded path, or None when it records none.

    Registries record these relative ('src/aipass/devpulse'), and
    ``_load_registry_data`` resolves them to absolute — but only for the LIST
    shape it normalizes. A dict-authored registry arrives with its paths exactly
    as written, so resolve here too rather than trusting the loader to have done
    it: an unresolved relative path would resolve against CWD and bind authority
    to wherever the caller happened to be standing.
    """
    raw = entry.get("path")
    if not raw:
        return None
    recorded = Path(raw)
    if not recorded.is_absolute():
        recorded = repo_root / recorded
    try:
        return recorded.resolve()
    except OSError as exc:
        # Returning None here reads downstream as "records no path", which would
        # send someone hunting a registry entry that is in fact present and fine.
        logger.warning("Registry path %s could not be resolved: %s", recorded, exc)
        return None


def _owner_tier_refusal(command: str, caller: Caller) -> str | None:
    """Return why owner-tier is refused for this caller, or None if authorized.

    Every branch names the check that refused, so a passport/registry drift is
    diagnosable from a single log line instead of a bisect. Fails CLOSED: any
    check that cannot be completed is a refusal, never a silent pass.
    """
    citizen_class = _citizen_class(caller.passport)
    if citizen_class != _MANAGER_CLASS:
        return (
            f"caller '{caller.name}' is citizen_class '{citizen_class or 'unset'}' — "
            f"owner-tier requires '{_MANAGER_CLASS}'"
        )

    try:
        registry_path = get_registry_path()
        registry_data = load_registry()
    except RegistryMismatchError as exc:
        # The shared loader runs its own credential check and raises before
        # returning, so it lands here rather than at the tenancy check below.
        # Same verdict, named the same way — a refusal must not depend on which
        # layer happened to notice first.
        logger.warning("owner-tier refused for '%s': registry credential mismatch: %s", caller.name, exc)
        return f"caller '{caller.name}' does not hold citizenship in this project's registry ({exc})"
    except Exception as exc:
        logger.warning("owner-tier refused for '%s': registry unreadable: %s", caller.name, exc)
        return f"the project registry could not be read ({exc}) — cannot verify ownership"

    registry_id = registry_data.get("metadata", {}).get("id")
    passport_id = caller.passport.get("citizenship", {}).get("registry_id")
    if not registry_id:
        return f"registry {registry_path.name} declares no metadata.id — cannot verify tenancy"
    if not passport_id:
        return (
            f"caller '{caller.name}' passport has no citizenship.registry_id — "
            "needs a registry backfill before it can hold owner-tier"
        )
    if passport_id != registry_id:
        return (
            f"caller '{caller.name}' belongs to registry {passport_id}, but this repo is "
            f"{registry_id} — a manager of one project holds nothing in another"
        )

    entry = _registry_entry(registry_data, caller.name)
    if entry is None:
        return f"caller '{caller.name}' is not listed in {registry_path.name}"
    if entry.get("owner") is not True:
        return f"caller '{caller.name}' is listed in {registry_path.name} without owner: true"

    # The registry file's own directory is the repo root by construction, which
    # keeps path-binding anchored to the SAME registry the checks above used.
    repo_root = registry_path.parent.resolve()
    recorded = _recorded_home(entry, repo_root)
    if recorded is None:
        return f"registry entry for '{caller.name}' records no path — cannot bind authority to a location"
    if caller.home != recorded and recorded not in caller.home.parents:
        return (
            f"caller '{caller.name}' presented a passport from {caller.home}, but the registry "
            f"binds that name to {recorded} — a passport outside its recorded home proves nothing"
        )

    if registry_path.name != AIPASS_REGISTRY_NAME and command in _AIPASS_FLOW_VERBS:
        return (
            f"'{command}' encodes AIPass's own dev→PR→main flow and is not translated for "
            f"external repos yet — {_TRANSLATED_VERBS} work here today (DPLAN-0281 P2, DPLAN-0290)"
        )

    return None


def verify_git_access(command: str) -> str:
    """Check if the calling branch is authorized for this git command.

    Uses GIT_ACCESS_TIERS to determine access level. Global-tier commands are
    available to all branches. Owner-tier is earned per-repo: the caller must be
    a manager, of THIS project, listed as its owner, presenting a passport from
    its registry-recorded home (DPLAN-0281). No branch is hardcoded — devpulse
    holds git in AIPass through the same rule that gives any project's manager
    git in theirs.

    Returns:
        The caller's branch name if authorized.

    Raises:
        PermissionError: If the caller is not authorized for this command.
    """
    global_cmds = GIT_ACCESS_TIERS["global"]["commands"]
    owner_tier = GIT_ACCESS_TIERS["owner"]

    if command in global_cmds:
        caller = _find_caller()
        json_handler.log_operation(
            "git_access_verify",
            {"caller": caller, "command": command, "tier": "global"},
        )
        return caller

    if command in owner_tier["commands"]:
        caller_info = _resolve_caller()
        refusal = _owner_tier_refusal(command, caller_info)
        warn_only = os.environ.get(_AUTH_MODE_ENV, "").strip().lower() == "warn"
        if refusal and not warn_only:
            msg = f"Branch '{caller_info.name}' is not authorized for '{command}': {refusal}."
            logger.error(msg)
            raise PermissionError(msg)
        if refusal:
            # Rollback mode: record exactly what enforcement WOULD have refused,
            # so the blast radius is read off the logs rather than guessed at.
            logger.warning(
                "git auth warn-mode: '%s' for '%s' would be denied under enforcement: %s",
                command,
                caller_info.name,
                refusal,
            )
        json_handler.log_operation(
            "git_access_verify",
            {
                "caller": caller_info.name,
                "command": command,
                "tier": "owner",
                "mode": "warn" if warn_only else "enforce",
                "would_refuse": refusal,
            },
        )
        return caller_info.name

    raise PermissionError(f"Unknown git command: '{command}'.{_rerouted_hint(command)}")
