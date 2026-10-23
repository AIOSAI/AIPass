# =================== AIPass ====================
# Name: auth.py
# Description: Passport-based authorization for devpulse operations
# Version: 1.8.0
# Created: 2026-03-30
# Modified: 2026-10-22
# =============================================

"""Passport-based authorization for git operations.

Reference: docs/git_access.md
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NamedTuple

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.repo_context import AIPASS_REGISTRY_NAME
from aipass.drone.apps.modules.router import caller_cwd
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
            "blame",
            "tracked",
            "export",
            "remote",
            "lock",
            "issue",
            "run",
            "workflow",
            "release",
            "label",
            "alerts",
            "branches",
            "tag-list",
        ],
        # export reads the repo and writes only the empty directory it is handed
        "description": "Read-only — available to all branches",
    },
    "owner": {
        "commands": [
            "commit",
            "untrack",
            "restore",
            "checkout",
            "sync",
            "merge-main",
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
            "issue-write",
            "run-write",
            "workflow-write",
            "release-write",
            "label-write",
            "alerts-write",
        ],
        "description": "Write operations — the project's own manager only",
    },
    "ci-cure": {
        "commands": ["ci-cure"],
        "description": "Commit and push a CI cure on dev — the one citizen whose registry entry carries ci_cure: true",
    },
}

# A read asks the gate for the command (global tier), a write for "<command>-write"
# (owner tier); a subcommand in neither list is refused.
GH_SUBCOMMANDS: dict[str, dict[str, tuple[str, ...]]] = {
    "issue": {
        "read": ("list", "view", "status"),
        "write": (
            "create",
            "close",
            "comment",
            "delete",
            "develop",
            "edit",
            "lock",
            "pin",
            "reopen",
            "transfer",
            "unlock",
            "unpin",
        ),
    },
    "run": {"read": ("list", "view", "watch"), "write": ("cancel", "delete", "download", "rerun")},
    "workflow": {"read": ("list", "view"), "write": ("disable", "enable", "run")},
}

# drone's own GitHub chores, gated the same way; an unknown subcommand is the handler's to refuse.
CHORE_SUBCOMMANDS: dict[str, dict[str, tuple[str, ...]]] = {
    "release": {"read": ("list",), "write": ("edit",)},
    "label": {"read": ("list",), "write": ("create",)},
    "alerts": {"read": ("list",), "write": ("dismiss",)},
}


def gh_access_key(command: str, args: list[str]) -> str | None:
    """The tier key a gh passthrough asks the gate for, or None when its subcommand is unknown.

    No subcommand at all is gh's own usage page, a read. The subcommand must sit
    in the first slot: a flag there (gh takes `issue -R x/y create`) is unknown.
    """
    if not args:
        return command
    table = GH_SUBCOMMANDS.get(command) or CHORE_SUBCOMMANDS[command]
    if args[0] in table["read"]:
        return command
    if args[0] in table["write"]:
        return f"{command}-write"
    return None


# The registry entry fields that grant a tier; ci_cure must sit on exactly one entry.
_OWNER_FACT = "owner"
_CI_CURE_FACT = "ci_cure"

# Owner-tier: manager class, matching tenancy, owner: true, and a passport under the
# registry-recorded path, which a copied registry id alone cannot forge.
_MANAGER_CLASS = "manager"

# 'warn' logs authority refusals and allows; an env var because a rollback that needs an edit is not one.
_AUTH_MODE_ENV = "AIPASS_GIT_AUTH_MODE"

# These encode AIPass's own flow and would half-run in another project's repo.
_AIPASS_FLOW_VERBS = frozenset({"pr", "close-pr", "smart-sync", "fix", "delete-branch", "ci-cure"})

# authority: not shown to be the owner, ERROR, warn-mode lifts it.
# capability: proven owner, untranslated verb, WARNING, warn-mode must NOT lift it.
_AUTHORITY = "authority"
_CAPABILITY = "capability"


# Without a pointer the refusal of a real git verb is a dead end.
_REROUTED_VERBS: dict[str, str] = {
    "add": "Staging is part of commit — use 'commit --all' or 'commit \"<msg>\" <files>'.",
    "push": "Use 'dev-pr' to push dev and open a PR. An external repo: 'push --repo <path>' (admin seat only).",
    "pull": "Use 'sync'.",
    "fetch": "Fetching is part of 'sync'. An external repo: 'fetch --repo <path>' (admin seat only).",
}


def external_owner_verbs() -> list[str]:
    """The owner-tier verbs a project's manager may run in its own repo, in tier order, gh writes as '<cmd> <write>'."""
    return [
        verb.replace("-write", " <write>")
        for verb in GIT_ACCESS_TIERS["owner"]["commands"]
        if verb not in _AIPASS_FLOW_VERBS
    ]


def _rerouted_hint(command: str) -> str:
    """Return a ' <hint>' suffix for git verbs drone routes elsewhere, else ''."""
    hint = _REROUTED_VERBS.get(command)
    return f" {hint}" if hint else ""


class Caller(NamedTuple):
    """An identified caller: who they claim to be, and where they said it from.

    ``home`` is where the passport was found; owner-tier binds authority to it.
    """

    name: str
    home: Path
    passport: dict


class Refusal(NamedTuple):
    """Why owner-tier was refused, and which species of refusal it is."""

    reason: str
    kind: str


def _resolve_caller() -> Caller:
    """Walk up from CWD to find passport.json and return the caller's identity.

    Raises PermissionError if no readable, named passport is found, or there is no cwd (fails closed).
    """
    cwd = caller_cwd()
    if cwd is None:
        msg = (
            "This process has no current directory — it was deleted out from under it. "
            "Caller identity is inferred by walking up from where you stand, so there is "
            "nothing to verify against and owner-tier access is refused."
        )
        logger.warning(msg)
        raise PermissionError(msg)

    current = cwd.resolve()
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

    # WARNING: failing closed on a non-branch cwd is designed behaviour, not a fault.
    msg = f"No .trinity/passport.json found in directory hierarchy (caller cwd: {cwd}) — cannot verify caller"
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

    The loader lowercases keys only for the list shape; a dict registry keeps 'VERA' as written.
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


def _resolve_location(path: Path) -> Path:
    """Resolve a path the owner gate binds authority to: the registry's directory or a recorded home.

    Tests patch this name: a resolve failure cannot be built portably in tmp_path.
    """
    return path.resolve()


def _recorded_home(entry: dict, repo_root: Path) -> Path | None:
    """Resolve a registry entry's recorded path, or None when it records none.

    Resolved against repo_root: a dict registry keeps relative paths, which would bind to CWD.
    Raises OSError when a present path cannot be resolved, never None ("records no path").
    """
    raw = entry.get("path")
    if not raw:
        return None
    recorded = Path(raw)
    if not recorded.is_absolute():
        recorded = repo_root / recorded
    try:
        return _resolve_location(recorded)
    except OSError as exc:
        logger.warning("Registry path %s could not be resolved: %s", recorded, exc)
        raise
    except RuntimeError as exc:
        # Python 3.12 raises RuntimeError for a symlink loop; re-raised as OSError so the gate refuses.
        logger.warning("Registry path %s could not be resolved: %s: %s", recorded, type(exc).__name__, exc)
        raise OSError(f"{type(exc).__name__}: {exc}") from exc


def _owner_tier_refusal(command: str, caller: Caller) -> Refusal | None:
    """Return why owner-tier is refused for this caller, or None if authorized.

    Fails CLOSED: a check that cannot complete is a refusal naming that check.
    """
    citizen_class = _citizen_class(caller.passport)
    if citizen_class != _MANAGER_CLASS:
        return Refusal(
            (
                f"caller '{caller.name}' is citizen_class '{citizen_class or 'unset'}' — "
                f"owner-tier requires '{_MANAGER_CLASS}'"
            ),
            _AUTHORITY,
        )
    return _registry_fact_refusal(command, caller, _OWNER_FACT)


def _registry_fact_refusal(command: str, caller: Caller, fact: str) -> Refusal | None:
    """Return why the tier granted by *fact* is refused for this caller, or None if it holds.

    Tenancy, an entry carrying ``<fact>: true``, path-binding, then the external-repo capability check.
    ci_cure must also sit on exactly one entry. Fails CLOSED like the owner gate.
    """
    try:
        registry_path = get_registry_path()
        registry_data = load_registry()
    except RegistryMismatchError as exc:
        # The loader's own credential check; same verdict as the tenancy check below.
        logger.warning("%s-tier refused for '%s': registry credential mismatch: %s", fact, caller.name, exc)
        return Refusal(
            f"caller '{caller.name}' does not hold citizenship in this project's registry ({exc})", _AUTHORITY
        )
    except Exception as exc:
        logger.warning("%s-tier refused for '%s': registry unreadable: %s", fact, caller.name, exc)
        return Refusal(f"the project registry could not be read ({exc}) — cannot verify {fact}", _AUTHORITY)

    registry_id = registry_data.get("metadata", {}).get("id")
    passport_id = caller.passport.get("citizenship", {}).get("registry_id")
    if not registry_id:
        return Refusal(f"registry {registry_path.name} declares no metadata.id — cannot verify tenancy", _AUTHORITY)
    if not passport_id:
        return Refusal(
            (
                f"caller '{caller.name}' passport has no citizenship.registry_id — "
                f"needs a registry backfill before it can hold {fact}-tier"
            ),
            _AUTHORITY,
        )
    if passport_id != registry_id:
        return Refusal(
            (
                f"caller '{caller.name}' belongs to registry {passport_id}, but this repo is "
                f"{registry_id} — a manager of one project holds nothing in another"
            ),
            _AUTHORITY,
        )

    entry = _registry_entry(registry_data, caller.name)
    if entry is None:
        return Refusal(f"caller '{caller.name}' is not listed in {registry_path.name}", _AUTHORITY)
    if entry.get(fact) is not True:
        return Refusal(f"caller '{caller.name}' is listed in {registry_path.name} without {fact}: true", _AUTHORITY)
    if fact == _CI_CURE_FACT:
        holders = _fact_holders(registry_data, fact)
        if len(holders) != 1:
            return Refusal(
                f"{len(holders)} entries in {registry_path.name} carry {fact}: true ({', '.join(holders)}) — "
                "the tier is held by one citizen alone",
                _AUTHORITY,
            )

    # Anchors path-binding to the SAME registry the checks above used.
    try:
        repo_root = _resolve_location(registry_path.parent)
    except (OSError, RuntimeError) as exc:
        logger.warning(
            "Registry directory %s could not be resolved: %s: %s", registry_path.parent, type(exc).__name__, exc
        )
        return Refusal(
            (
                f"the directory of {registry_path.name} could not be resolved ({type(exc).__name__}: {exc}) — "
                "cannot bind authority to a location"
            ),
            _AUTHORITY,
        )
    try:
        recorded = _recorded_home(entry, repo_root)
    except OSError as exc:
        return Refusal(
            f"registry path for '{caller.name}' could not be resolved ({exc}) — cannot bind authority to a location",
            _AUTHORITY,
        )
    if recorded is None:
        return Refusal(
            f"registry entry for '{caller.name}' records no path — cannot bind authority to a location", _AUTHORITY
        )
    if caller.home != recorded and recorded not in caller.home.parents:
        return Refusal(
            (
                f"caller '{caller.name}' presented a passport from {caller.home}, but the registry "
                f"binds that name to {recorded} — a passport outside its recorded home proves nothing"
            ),
            _AUTHORITY,
        )

    # Must stay after the authority checks: only a proven owner gets _CAPABILITY.
    if registry_path.name != AIPASS_REGISTRY_NAME and command in _AIPASS_FLOW_VERBS:
        return Refusal(
            f"'{command}' encodes AIPass's own flow and is not translated for external repos yet — "
            f"these work here: {', '.join(external_owner_verbs())}",
            _CAPABILITY,
        )

    return None


def _fact_holders(registry_data: dict, fact: str) -> list[str]:
    """The names of every registry entry carrying ``<fact>: true``, either registry shape."""
    branches = registry_data.get("branches", {})
    entries = branches.items() if isinstance(branches, dict) else ((e.get("name", "?"), e) for e in branches)
    return [str(name) for name, entry in entries if isinstance(entry, dict) and entry.get(fact) is True]


def _ci_cure_access(command: str) -> str:
    """The ci-cure tier: the registry fact alone grants it; warn-mode never lifts it, it predates no migration."""
    caller_info = _resolve_caller()
    refusal = _registry_fact_refusal(command, caller_info, _CI_CURE_FACT)
    if refusal and refusal.kind == _CAPABILITY:
        msg = f"Branch '{caller_info.name}' cannot run '{command}' in this repo: {refusal.reason}."
        logger.warning(msg)
        raise PermissionError(msg)
    if refusal:
        msg = f"Branch '{caller_info.name}' is not authorized for '{command}': {refusal.reason}."
        logger.error(msg)
        raise PermissionError(msg)
    json_handler.log_operation("git_access_verify", {"caller": caller_info.name, "command": command, "tier": "ci-cure"})
    return caller_info.name


def verify_git_access(command: str) -> str:
    """Check if the calling branch is authorized for this git command.

    Returns the caller's branch name; raises PermissionError when refused. No branch is hardcoded.
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
        if refusal and refusal.kind == _CAPABILITY:
            # warn_only is not consulted here; "cannot run", since this caller IS authorized.
            msg = f"Branch '{caller_info.name}' cannot run '{command}' in this repo: {refusal.reason}."
            logger.warning(msg)
            raise PermissionError(msg)
        if refusal and not warn_only:
            msg = f"Branch '{caller_info.name}' is not authorized for '{command}': {refusal.reason}."
            logger.error(msg)
            raise PermissionError(msg)
        if refusal:
            logger.warning(
                "git auth warn-mode: '%s' for '%s' would be denied under enforcement: %s",
                command,
                caller_info.name,
                refusal.reason,
            )
        json_handler.log_operation(
            "git_access_verify",
            {
                "caller": caller_info.name,
                "command": command,
                "tier": "owner",
                "mode": "warn" if warn_only else "enforce",
                "would_refuse": refusal.reason if refusal else None,
            },
        )
        return caller_info.name

    if command in GIT_ACCESS_TIERS["ci-cure"]["commands"]:
        return _ci_cure_access(command)

    raise PermissionError(f"Unknown git command: '{command}'.{_rerouted_hint(command)}")
