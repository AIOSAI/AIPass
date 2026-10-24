# =================== AIPass ====================
# Name: router_handler.py
# Description: Handler for command routing implementation; the caller stamp for routed children and in-process modules
# Version: 1.4.1
# Created: 2026-03-09
# Modified: 2026-10-23
# =============================================

"""
Handler for command routing implementation.
"""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, NamedTuple, Optional

from aipass.prax.apps.modules.logger import system_logger
from .exceptions import CommandExecutionError
from .executor import DEFAULT_TIMEOUT, CommandResult, execute_command
from aipass.drone.apps.handlers.json import json_handler

logger = system_logger

# Identity is fixed per process yet resolved twice per route; keyed so a NEW disagreement still logs.
_LOGGED_IDENTITY_SIGNATURES: set[str] = set()


def _log_identity_once(signature: str, level: str, message: str, *args: object) -> bool:
    """Log an identity message once per process per signature; True if this call emitted."""
    if signature in _LOGGED_IDENTITY_SIGNATURES:
        return False
    _LOGGED_IDENTITY_SIGNATURES.add(signature)
    getattr(logger, level)(message, *args)
    return True


class CallerSignal(NamedTuple):
    """A caller-identity answer plus its evidence: 'passport' says WHO, 'project' only WHERE."""

    name: str | None
    source: str | None  # "passport" | "project" | None


class CallerIdentity(NamedTuple):
    """Who is calling, and which KIND of evidence said so (``project`` is never a citizen)."""

    name: str | None
    source: str | None  # "assigned" | "passport" | "project" | None


def find_entry_point(branch_path: str, branch_name: str) -> Path:
    """Locate the apps/{branch_name}.py entry point for a branch."""
    entry_point = Path(branch_path) / "apps" / f"{branch_name}.py"
    if not entry_point.exists():
        raise CommandExecutionError(f"Entry point not found for branch '{branch_name}': {entry_point}")
    return entry_point


_REGISTRY_SUFFIX = "_REGISTRY.json"
_REGISTRY_GLOB = f"*{_REGISTRY_SUFFIX}"


def _registry_candidates(directory: Path) -> List[Path]:
    """What the FILESYSTEM answers for ``*_REGISTRY.json`` in *directory* — untrusted.

    Test seam: Linux cannot produce a case-folding listing, so tests supply one here.
    """
    return list(directory.glob(_REGISTRY_GLOB))


def registries_in(directory: Path) -> List[Path]:
    """Every ``*_REGISTRY.json`` in *directory*, exact-case, sorted.

    The glob is not the filter: case-insensitive filesystems also match ``*_registry.json``
    (drone_command_registry.json), and a registry is a trust anchor. Suffix only, never the stem.
    """
    return sorted(p for p in _registry_candidates(directory) if p.name.endswith(_REGISTRY_SUFFIX))


def _project_name_from_registry(reg_file: Path) -> str | None:
    """Project name from declared metadata, else the filename (AIPASS_REGISTRY.json → 'aipass'); None if unreadable."""
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Caller detection: registry %s found but unreadable: %s", reg_file, exc)
        return None

    meta = data.get("metadata", {}) if isinstance(data, dict) else {}
    declared = meta.get("project_name") or meta.get("name")
    if declared:
        return str(declared).lower().replace(" ", "-")

    derived = reg_file.name[: -len(_REGISTRY_SUFFIX)].lower().replace(" ", "-")
    if not derived:
        logger.warning("Caller detection: registry %s yields no usable project name", reg_file)
        return None

    logger.info(
        "Caller detection: registry %s declares no metadata.name — using filename-derived '%s'",
        reg_file.name,
        derived,
    )
    return derived


def _working_directory() -> Path:
    """The one raw read of where this process stands. Raises ENOENT when that is gone.

    Unguarded test seam beneath ``caller_cwd``: Windows cannot stand in a deleted directory.
    """
    return Path.cwd()


def caller_cwd() -> Path | None:
    """The caller's working directory, or None when it was deleted (no location signal)."""
    try:
        return _working_directory()
    except OSError as exc:
        logger.info("No current directory — it was deleted out from under this process (%s)", exc)
        return None


def find_project_root() -> Path | None:
    """Walk up from CWD to find *_REGISTRY.json; return its parent as project root.

    With no cwd (the caller deleted it) the walk is skipped and AIPASS_HOME answers.
    """
    cwd = caller_cwd()
    for parent in [cwd, *cwd.parents] if cwd is not None else []:
        if registries_in(parent):
            return parent.resolve()
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and registries_in(home):
            return home.resolve()
    return None


def detect_caller_signal(cwd: Path) -> CallerSignal:
    """Walk up from cwd for a passport, then fall back to the registry project (never a citizen)."""
    current = cwd.resolve()
    for _ in range(10):
        passport = current / ".trinity" / "passport.json"
        if passport.exists():
            try:
                with open(passport, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # v1 full passport, then v2 minimal (Docker) passport.
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                if name:
                    return CallerSignal(name, "passport")
                logger.warning("Passport at %s names no branch — trying registry fallback", passport)
            except Exception as exc:
                logger.warning("Failed to read passport at %s: %s — trying registry fallback", passport, exc)
            # Unusable passport: stop, since a parent branch's passport would misattribute.
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    current = cwd.resolve()
    for _ in range(10):
        for reg_file in registries_in(current):
            project_name = _project_name_from_registry(reg_file)
            if project_name:
                return CallerSignal(project_name, "project")
        parent = current.parent
        if parent == current:
            break
        current = parent

    # INFO: anonymous is a correct outcome (a human outside any branch); whoever refuses work owns the alarm.
    _log_identity_once(
        f"undetected:{cwd}",
        "info",
        "Caller identity: anonymous — no passport or registry found from cwd %s. "
        "Routing continues; work from here is attributed to no branch.",
        cwd,
    )
    return CallerSignal(None, None)


def resolve_caller_identity_signal(cwd: Path | None) -> CallerIdentity:
    """Resolve who is CALLING drone, WITH the provenance of the answer.

    AIPASS_BRANCH_NAME wins over the cwd passport: agents cd into other branches and stay
    themselves. Attribution only, never access; git's owner-tier reads passports directly.
    """
    assigned = os.environ.get("AIPASS_BRANCH_NAME") or None
    standing, source = detect_caller_signal(cwd) if cwd is not None else CallerSignal(None, None)

    if assigned and standing and assigned.lower() != standing.lower():
        if source == "passport":
            # Only place both claims coexist; downstream sees just the winner, so it stays loud.
            _log_identity_once(
                f"conflict:{cwd}:{assigned}:{standing}",
                "warning",
                "Caller identity conflict: AIPASS_BRANCH_NAME=%r but the passport at cwd %s "
                "claims %r — using %r (assigned identity wins). Two citizens claim this process.",
                assigned,
                cwd,
                standing,
                assigned,
            )
        else:
            _log_identity_once(
                f"in-project:{cwd}:{assigned}:{standing}",
                "info",
                "Caller identity: %r (assigned), running inside project %r from cwd %s. "
                "No passport here — the project name is location, not identity.",
                assigned,
                standing,
                cwd,
            )

    if assigned:
        return CallerIdentity(assigned, "assigned")
    if standing:
        return CallerIdentity(standing, source)
    return CallerIdentity(None, None)


# What drone stamps onto every command it routes, and what the verified-caller rail reads.
CALLER_STAMP_KEYS = ("AIPASS_CALLER_CWD", "AIPASS_CALLER_BRANCH", "AIPASS_CALLER_IDENTITY_SOURCE")


def caller_stamp_values() -> dict[str, str]:
    """The AIPASS_CALLER_* a routed command receives; a key is omitted when its answer is absent."""
    # Omitted when absent: a target must get no answer, not a sentinel it might resolve.
    cwd = caller_cwd()
    stamp: dict[str, str] = {}
    if cwd is not None:
        stamp["AIPASS_CALLER_CWD"] = str(cwd)
    # Provenance ships with the name: the consumer, in another process, cannot re-derive it.
    caller_branch, identity_source = resolve_caller_identity_signal(cwd)
    if caller_branch:
        stamp["AIPASS_CALLER_BRANCH"] = caller_branch
        stamp["AIPASS_CALLER_IDENTITY_SOURCE"] = identity_source or "unknown"
    return stamp


@contextmanager
def caller_stamp() -> Iterator[None]:
    """Stamp this process the way a routed child is stamped, for a module that runs in-process.

    Always fresh: an inherited stamp proves nothing about this process. Every prior value is put back.
    """
    saved = {key: os.environ.get(key) for key in CALLER_STAMP_KEYS}
    fresh = caller_stamp_values()
    for key in CALLER_STAMP_KEYS:
        if key in fresh:
            os.environ[key] = fresh[key]
        else:
            os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve_caller_identity(cwd: Path | None) -> str | None:
    """Resolve who is CALLING drone — the name alone, for attribution; decisions take the signal."""
    return resolve_caller_identity_signal(cwd).name


def execute_branch_command(
    branch_path: str,
    branch_name: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    interactive: bool = False,
    extend_on_output: bool = True,
) -> CommandResult:
    """Execute a command against a branch's entry point via subprocess; command None is introspection."""
    entry_point = find_entry_point(branch_path, branch_name)

    relative_entry = str(entry_point.relative_to(branch_path))
    cmd_args = [relative_entry]
    if command:
        cmd_args += [command] + list(args or [])

    caller_env = {"AIPASS_BRANCH_NAME": branch_name, **caller_stamp_values()}
    caller_branch = caller_env.get("AIPASS_CALLER_BRANCH", "")

    # Lazy: registry_handler imports this module for caller_cwd and registries_in.
    from aipass.drone.apps.handlers.registry_handler import branch_interpreter

    result = execute_command(
        executable=branch_interpreter(branch_path),
        args=cmd_args,
        cwd=branch_path,
        timeout=timeout,
        env=caller_env,
        interactive=interactive,
        extend_on_output=extend_on_output,
    )

    caller_tag = f" [CALLER:{caller_branch.upper()}]" if caller_branch else ""
    logger.info("Executed @%s%s %s → exit %d", branch_name, caller_tag, command or "(introspection)", result.exit_code)
    json_handler.log_operation(
        "execute_branch_command", {"branch": branch_name, "command": command or "", "exit_code": result.exit_code}
    )

    return CommandResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        branch=branch_name,
        command=command or "",
    )
