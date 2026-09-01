# =================== AIPass ====================
# Name: router_handler.py
# Description: Handler for command routing implementation
# Version: 1.2.0
# Created: 2026-03-09
# Modified: 2026-08-31
# =============================================

"""
Handler for command routing implementation.

Handles entry point resolution, caller detection, environment building,
and subprocess execution for branch command routing.
"""

import json
import os
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

from aipass.prax.apps.modules.logger import system_logger
from .exceptions import CommandExecutionError
from .executor import DEFAULT_TIMEOUT, CommandResult, execute_command
from aipass.drone.apps.handlers.json import json_handler

logger = system_logger

# Identity messages describe a process-wide, unchanging fact: who is calling and
# from where. Neither the env var nor the cwd moves under a running process, so
# the SECOND identical line carries no information the first did not — and there
# is always a second, because resolve_caller_identity() is called twice per
# route (modules/router.py for the CALLER: tag, then here for the stamp).
# Long-lived callers turned that into a warning per drone call, forever.
# Keyed per (kind, cwd, signals) so a genuinely NEW disagreement still speaks.
#
# Tests clear this directly (see tests/conftest.py). There is deliberately no
# public reset(): nothing in production has a reason to forget what it has
# already said, and a production function that only tests call is exactly what
# seedgo's unused_function standard exists to catch.
_LOGGED_IDENTITY_SIGNATURES: set[str] = set()


def _log_identity_once(signature: str, level: str, message: str, *args: object) -> bool:
    """Log an identity message once per process per signature.

    Returns True if this call emitted, False if the signature was already seen.
    Suppression is per-process only — a real conflict recurring across separate
    invocations still accumulates and still escalates, which is the point.
    """
    if signature in _LOGGED_IDENTITY_SIGNATURES:
        return False
    _LOGGED_IDENTITY_SIGNATURES.add(signature)
    getattr(logger, level)(message, *args)
    return True


class CallerSignal(NamedTuple):
    """A caller-identity answer plus the evidence it came from.

    ``source`` is the whole point: 'passport' is a competing claim about WHO a
    caller is, 'project' is only a statement about WHERE they are standing. The
    bare name cannot tell them apart, and treating them alike is what made a
    process launched at a repo root look like an identity conflict.
    """

    name: str | None
    source: str | None  # "passport" | "project" | None


class CallerIdentity(NamedTuple):
    """Who is calling, and which KIND of evidence said so.

    ``source`` is what a consumer in another process needs and could not have:

      - ``assigned``  — AIPASS_BRANCH_NAME, set when the process was created.
        A credential. Valid from any directory, which is the whole point (S102).
      - ``passport``  — a passport under the caller's feet. Identity inferred
        from location; true for a human standing in their own branch.
      - ``project``   — a registry-derived PROJECT name. Answers "which project
        am I in", never "who am I". @aipass the project directory and @aipass
        the citizen are different things that spell the same.

    Collapsing these to a bare string is what let a dispatch from the repo root
    send as the citizen @aipass and wake the wrong branch (DPLAN-0315 item 3).
    """

    name: str | None
    source: str | None  # "assigned" | "passport" | "project" | None


def find_entry_point(branch_path: str, branch_name: str) -> Path:
    """Locate the apps/{branch_name}.py entry point for a branch.

    Raises:
        CommandExecutionError: If entry point does not exist
    """
    entry_point = Path(branch_path) / "apps" / f"{branch_name}.py"
    if not entry_point.exists():
        raise CommandExecutionError(f"Entry point not found for branch '{branch_name}': {entry_point}")
    return entry_point


_REGISTRY_SUFFIX = "_REGISTRY.json"
_REGISTRY_GLOB = f"*{_REGISTRY_SUFFIX}"


def registries_in(directory: Path) -> List[Path]:
    """Every ``*_REGISTRY.json`` in *directory*, exact-case, sorted.

    THE GLOB IS NOT THE FILTER. ``Path.glob`` asks the FILESYSTEM to match, and
    on a case-insensitive one — Windows, and macOS by default — ``*_REGISTRY.json``
    also matches ``*_registry.json``. That is not hypothetical: this repository
    ships ``drone_command_registry.json`` beside the drone package, plus
    ``flow_json/fplan_registry.json`` and a ``.spawn/.template_registry.json`` in
    every branch (pathlib's ``*`` matches dotfiles, unlike the ``glob`` module).
    Windows CI caught it as a test red — ``find_registry()`` returned
    ``src/aipass/drone/drone_command_registry.json`` — but the red was the
    smaller half. A registry file is a project's TRUST ANCHOR: it decides which
    installation a caller belongs to, which project name gets stamped on their
    identity, and where the delete lane thinks the project root is. A plan-id
    counter served in that role answers a question it was never asked.

    So the name is re-checked in Python, where ``str.endswith`` is case-sensitive
    on every platform. Suffix only, never the stem: external projects name their
    registry after themselves and nothing promises the stem is uppercase.

    One reader, called from every walk in this tree — the tenth private copy of
    ``glob("*_REGISTRY.json")`` is how a fix lands on some of N identical paths.
    """
    return sorted(p for p in directory.glob(_REGISTRY_GLOB) if p.name.endswith(_REGISTRY_SUFFIX))


def _project_name_from_registry(reg_file: Path) -> str | None:
    """Derive a project name from a registry file, or None if it cannot be read.

    Prefers a declared ``metadata.project_name``/``name``, then falls back to the
    filename: AIPASS_REGISTRY.json → 'aipass', VERA-STUDIO_REGISTRY.json →
    'vera-studio'. The filename is the one thing every registry provably has —
    AIPass's own metadata carries only version/last_updated/total_branches/id, so
    requiring a declared name made the framework repo the one place this fallback
    could never fire.
    """
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
        # A file named exactly '_REGISTRY.json' leaves nothing to derive from.
        logger.warning("Caller detection: registry %s yields no usable project name", reg_file)
        return None

    logger.info(
        "Caller detection: registry %s declares no metadata.name — using filename-derived '%s'",
        reg_file.name,
        derived,
    )
    return derived


def caller_cwd() -> Path | None:
    """The caller's working directory, or None when the process has none.

    ``Path.cwd()`` raises ENOENT once the directory it names is gone, and a
    caller standing in a directory that was just deleted is now an ordinary
    state rather than a crash — the delete lane was fixed to survive it first,
    which is exactly what put a live process here to route a second command.

    None is the absence of the location signal, not a failure to read it. Who a
    process IS was never derived from where it stood (S102), so an assigned
    identity still answers from here; only the inference from a passport under
    the caller's feet has nothing left to read.

    Lives in this module because it is the caller-location signal and this
    module owns caller identity — deletion_log imports it rather than keeping a
    second copy, which is the direction the dependency already runs.
    """
    try:
        return Path.cwd()
    except OSError as exc:
        logger.info("No current directory — it was deleted out from under this process (%s)", exc)
        return None


def detect_caller_signal(cwd: Path) -> CallerSignal:
    """Walk up from cwd for a passport, then fall back to the registry project.

    Returns the answer AND its provenance. Callers that only need the name use
    :func:`detect_caller_branch_name`; callers weighing this against an assigned
    identity need the source, because the two answers are not the same kind of
    claim (see :class:`CallerSignal`).

    Falls back to the project name from the registry when no passport is found —
    a caller standing at a project root rather than in a branch. That resolves to
    the PROJECT, never to a citizen, and deliberately so: CWD is identity, and a
    registry file proves which project you are in, not who you are. Nothing here
    grants authority; git's owner-tier reads passports directly and a name
    derived here can never satisfy it.
    """
    current = cwd.resolve()
    for _ in range(10):
        passport = current / ".trinity" / "passport.json"
        if passport.exists():
            try:
                with open(passport, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Handle both passport formats:
                # v1: branch_info.branch_name (local/full passport)
                # v2: identity.name (Docker/minimal passport)
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                if name:
                    return CallerSignal(name, "passport")
                logger.warning("Passport at %s names no branch — trying registry fallback", passport)
            except Exception as exc:
                logger.warning("Failed to read passport at %s: %s — trying registry fallback", passport, exc)
            # A passport was found but is unusable. Stop the walk-up rather than
            # continue: a parent branch's passport would misattribute identity.
            # Fall through to the registry fallback, which the docstring promises
            # and the old `return None` here silently skipped.
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: detect project name from registry file (callers at a project root)
    current = cwd.resolve()
    for _ in range(10):
        # registries_in() sorts, so a directory holding two registries resolves
        # the same way every time, matching registry_handler._first_registry_in
        # — and drops the case-insensitive filesystem's extra matches, which
        # here would have stamped the caller with a project name derived from
        # whatever lowercase *_registry.json the walk passed first.
        for reg_file in registries_in(current):
            project_name = _project_name_from_registry(reg_file)
            if project_name:
                return CallerSignal(project_name, "project")
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Single log site for a lost caller identity — every caller of this function
    # gets the breadcrumb without any of them re-logging it.
    #
    # INFO, not WARNING: an anonymous caller is a correct OUTCOME, not a fault.
    # A human running `drone @prax monitor` from their home directory has no
    # identity to find, and saying so ten times an hour is not a diagnosis — it
    # is the router complaining that a normal operator action is normal. The
    # consequence is bounded and visible where it lands: AIPASS_CALLER_BRANCH
    # goes unset and downstream attribution reads 'unknown'. Whoever REFUSES
    # work for want of an identity owns the page (see auth.py) — the same rule
    # that already keeps this site off ERROR.
    #
    # Once per process per cwd: the cwd cannot change under a running process,
    # so a repeat is the same fact restated.
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

    Two signals can answer "who is calling", and they are not the same kind of
    claim:

      - ``AIPASS_BRANCH_NAME`` — identity ASSIGNED to this process when it was
        created. ai_mail's dispatch_monitor sets it from the dispatched address,
        a branch entry point setdefaults its own name, and drone's own executor
        sets it to the target below. All three mean the same thing: who this
        process IS.
      - the cwd passport — identity INFERRED from where the process happens to
        be standing.

    The env var wins. An agent that cds into another branch to read its code or
    run its tests is still itself; the passport under its feet belongs to
    whoever lives there. The inference is only ever as good as the assumption
    "an agent works in its own home" — and agents legitimately leave home.
    Trusting it stamped a commons-authored dispatch as @aipass, filed it in
    aipass's sent store, and routed the reply to the wrong citizen (S102).

    cwd still answers when nothing was assigned: a human in a terminal has no
    AIPASS_BRANCH_NAME, and standing in a branch is the only signal they give.

    Nothing here grants authority — git's owner-tier reads passports directly
    (see plugins/devpulse_ops/auth.py) and never consults this. That is what
    makes preferring an env var acceptable: it decides attribution, not access.

    Only a PASSPORT can contradict an assigned identity. A registry-derived
    project name answers a different question ("which project am I in"), so a
    process launched at a repo root carrying its own branch name is not in
    conflict with anything — it is the ordinary shape of every long-lived
    service in this system.
    """
    assigned = os.environ.get("AIPASS_BRANCH_NAME") or None
    # None means the process has NO working directory — the caller deleted the
    # one it was standing in. That is not a cwd we failed to read, it is the
    # absence of the signal, and inferring from a directory that no longer
    # exists would answer a question nobody can answer. The assigned identity
    # still holds: who this process IS never depended on where it stood.
    standing, source = detect_caller_signal(cwd) if cwd is not None else CallerSignal(None, None)

    if assigned and standing and assigned.lower() != standing.lower():
        if source == "passport":
            # Two competing claims about WHO the caller is, and this process is
            # the only place both coexist — unlogged, the disagreement is
            # unrecoverable downstream (ai_mail sees only the winner). This is
            # S102's shape; it stays loud. Deduped per process only, so the
            # same conflict from a fresh invocation still counts and still
            # escalates.
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
            # Not a conflict: a project name is not a rival claim of identity.
            # The old message called this one anyway AND named a passport that
            # was never there — /home/patrick/Projects/AIPass holds no
            # .trinity/passport.json, only AIPASS_REGISTRY.json — so it sent
            # readers hunting for evidence that does not exist. INFO, once.
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


def resolve_caller_identity(cwd: Path | None) -> str | None:
    """Resolve who is CALLING drone — the name alone.

    The bare-name view of :func:`resolve_caller_identity_signal`, kept because
    attribution sites (the ``[CALLER:X]`` tag, the deletion record) want a name
    and nothing more. Anything that must DECIDE on an identity — grant, refuse,
    send as — takes the signal instead: a name on its own cannot tell a
    credential from a directory name.
    """
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
    """Execute a command against a branch's entry point via subprocess.

    Resolves the entry point, builds caller environment, and delegates
    to the subprocess executor.

    When command is None, runs the branch with no args (introspection).

    ``extend_on_output`` is carried, not decided, here: the router knows whether
    the operator named an explicit timeout, and this layer never second-guesses
    that. The default matches the executor's own — extension on.

    Returns:
        CommandResult with stdout, stderr, exit_code, branch, and command
    """
    entry_point = find_entry_point(branch_path, branch_name)

    relative_entry = str(entry_point.relative_to(branch_path))
    cmd_args = [relative_entry]
    if command:
        cmd_args += [command] + list(args or [])

    # Pass caller's CWD so target branches can detect who invoked them.
    # Omitted entirely when there is none, matching how the identity keys below
    # handle their own absence: a target that reads this as a location must get
    # no answer rather than a sentinel it might try to resolve.
    cwd = caller_cwd()
    caller_env = {"AIPASS_BRANCH_NAME": branch_name}
    if cwd is not None:
        caller_env["AIPASS_CALLER_CWD"] = str(cwd)

    # Who is calling: assigned identity first, cwd passport only as fallback.
    # The provenance ships WITH the name: a consumer deciding whether to trust
    # this identity cannot re-derive it — it is in another process, with a
    # different cwd and no access to our environment. Unstamped, "commons
    # standing in /tmp" and "nobody standing at a repo root" arrive identical.
    caller_branch, identity_source = resolve_caller_identity_signal(cwd)
    if caller_branch:
        caller_env["AIPASS_CALLER_BRANCH"] = caller_branch
        caller_env["AIPASS_CALLER_IDENTITY_SOURCE"] = identity_source or "unknown"

    result = execute_command(
        executable=sys.executable,
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
