# =================== AIPass ====================
# Name: verbs.py
# Description: Host API Verb Handler — wake, kill, lock and new-project, each a proxy
# Version: 1.1.2
# Created: 2026-08-14
# Modified: 2026-10-24
# =============================================

"""
Host API Verb Handler

Reference: docs/host_surfaces.md (the verb lane), docs/host_api.md (the {ok, detail} line).
No subprocess machinery here (tests read this source): this lane must not grow its own verb.
"""

import re
from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import reads as host_reads

# Kill execs through fleet.py, which owns @baud's binary, so this module runs nothing itself.
from aipass.api.apps.handlers.host import fleet as host_fleet

import aipass.drone as drone

# @skills' published in-process door; lib/ is their public shape, not internals.
from aipass.skills.lib.screen_lock import handler as screen_lock

from aipass.aipass.apps.modules import new_project as project_door

WAKE_TIMEOUT_SECONDS = 120

# Over the cap is REFUSED, never trimmed: a trimmed instruction still runs.
MAX_MESSAGE_CHARS = 2000

# Operational kill switch, like fleet.SNAPSHOT_READY: closed means an honest 503, never a fake outcome.
KILL_SEAM_READY = True

KILL_SEAM_ASK = (
    "a headless room kill on the baud binary — a flag that ends one NAMED room "
    "in a NAMED project and exits with a status, the way --snapshot reads one"
)


class VerbRefused(Exception):
    """The caller asked for something invalid. Their fault, and they may know."""


class VerbUnavailable(Exception):
    """The verb could not be performed for a reason that is not the caller's."""


def wake_branch(branch: str, project: str, message: str = "", fresh: bool = False) -> Dict[str, Any]:
    """Wake a citizen through @ai_mail's dispatch door."""
    # Through the CLI, not @ai_mail's wake_branch(): the CLI parses no `admin`, so no request reaches it.
    require_project(project)

    # Before resolving: else an oversized message answers VerbUnavailable when the registry is down.
    if len(message) > MAX_MESSAGE_CHARS:
        raise VerbRefused(f"Message is {len(message)} characters, over the {MAX_MESSAGE_CHARS} character cap")

    # @ai_mail's dispatch scans every arg for flags: a dash-led message would become --fresh or --help.
    if message.strip().startswith("-"):
        raise VerbRefused("Message cannot start with '-': it would be read as a flag")

    target = citizen_address(branch, project)

    # Positional: branch then message. An empty message is omitted, never sent as a blank prompt.
    args = ["wake", target]
    if message:
        args.append(message)
    if fresh:
        args.append("--fresh")

    json_handler.log_operation(
        "host_api_verb_wake",
        {"branch": target, "project": project, "fresh": fresh, "message": bool(message)},
    )

    result = _route("@ai_mail", "dispatch", args, WAKE_TIMEOUT_SECONDS)

    # The door answered either way: non-zero is ok=false (policy or dead spawn), their sentence says which.
    ok = result.exit_code == 0
    detail = _sentence(result.stdout if ok else (result.stderr or result.stdout))

    if ok:
        logger.info("[host_api] wake dispatched for %s (fresh=%s)", target, fresh)
    else:
        logger.warning("[host_api] wake refused for %s: %s", target, detail)

    return {
        "ok": ok,
        "detail": detail,
        "branch": target,
        "project": project,
        "fresh": fresh,
    }


def kill_room(branch: str, project: str) -> Dict[str, Any]:
    """End a branch's session. Gated — @baud owns the only door that does this."""
    # Target validated BEFORE the gate, so the no-default-target rules stay tested while gated.
    require_project(project)
    target = citizen_address(branch, project)

    if not KILL_SEAM_READY:
        logger.warning("[host_api] kill refused for %s — the seam switch is closed", target)
        json_handler.log_operation("host_api_verb_kill_gated", {"branch": target, "project": project})
        raise VerbUnavailable(
            "Ending a session is switched off on this host (verbs.KILL_SEAM_READY is False). "
            f"The door it routes to: {KILL_SEAM_ASK}. No session is ended by another route — "
            "@baud's is the one door (the owner, 2026-08-10)."
        )

    # @baud's door takes the bare NAME and refuses anything carrying a separator.
    name = target.lstrip("@")

    try:
        envelope = host_fleet.end_room(name, project.strip())
    except host_fleet.FleetUnavailable as e:
        raise VerbUnavailable(str(e)) from e

    refusal = _sentence(envelope.get("error"))
    ok = not refusal
    # A FACT, not a success flag: false with ok true means nothing to end (the goal state).
    ended = bool(envelope.get("ended"))

    if ok:
        logger.info("[host_api] room kill for %s: ended=%s", name, ended)
    else:
        logger.warning("[host_api] room kill refused for %s: %s", name, refusal)

    return {
        "ok": ok,
        "detail": _sentence(envelope.get("detail")) if ok else refusal,
        "branch": target,
        "project": project,
        "room": envelope.get("room"),
        "ended": ended,
    }


def lock_screen() -> Dict[str, Any]:
    """Lock the machine's screen. Never gated."""
    # @skills' doctrine: lock must work from anywhere, so nothing is checked first.
    result = screen_lock.lock_screen()

    locked = bool(result.get("locked"))
    method = result.get("method")

    json_handler.log_operation("host_api_verb_lock", {"locked": locked, "method": method})

    if locked:
        logger.info("[host_api] screen locked via %s", method)
        detail = f"Screen locked via {method}" if method else "Screen locked"
    else:
        detail = _sentence(result.get("error")) or "The skill reported no detail"
        logger.error("[host_api] screen lock failed: %s", detail)

    return {
        "ok": locked,
        "detail": detail,
        "method": method,
        "session": result.get("session"),
    }


PROJECT_NAME_RULE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
PROJECT_NAME_SENTENCE = "A project name is a letter, then up to 63 more letters, digits, underscores or hyphens"
PROJECT_EXISTS_PREFIX = "Project already exists"
REGISTRY_SUFFIX = "_REGISTRY.json"
SEAM_MISSING = "aipass.aipass.apps.modules.new_project publishes no create_project and TEMPLATES"


class ProjectRefused(VerbRefused):
    """A new-project request refused; the route answers `status` and `code`, saying the sentence when `spoken`."""

    status = 400
    code = "project_refused"
    spoken = False


class ProjectNameRefused(ProjectRefused):
    """The name is outside the rule. The sentence is PROJECT_NAME_SENTENCE."""

    code = "project_name_refused"
    spoken = True


class TemplateRefused(ProjectRefused):
    """The template is not one of the door's TEMPLATES. The sentence lists them."""

    code = "template_refused"
    spoken = True


class ProjectExists(ProjectRefused):
    """create_project's "Project already exists: <target>", verbatim."""

    status = 409
    code = "project_exists"
    spoken = True


class ProjectDoorFailed(VerbUnavailable):
    """The door could not make the project: git, spawn, the root, the disk, or a missing seam."""

    status = 503
    code = "project_door_failed"


def new_project(name: str, template: str = "empty") -> Dict[str, Any]:
    """Create a project and its manager agent, as `aipass new <name> --template <t>`."""
    if not PROJECT_NAME_RULE.fullmatch(name):
        raise _project_refusal(ProjectNameRefused(PROJECT_NAME_SENTENCE), name, template)

    # Read off the door at call time; a door missing either name is a 503, never a 500.
    create = getattr(project_door, "create_project", None)
    templates = getattr(project_door, "TEMPLATES", None)
    if create is None or templates is None:
        raise _project_refusal(ProjectDoorFailed(SEAM_MISSING), name, template)
    if template not in templates:
        sentence = f"The template must be one of: {', '.join(templates)}"
        raise _project_refusal(TemplateRefused(sentence), name, template)

    try:
        result = create(name, template, no_agent=False, host=host_reads.repo_root())
    except ValueError as e:
        raise _project_refusal(ProjectRefused(str(e)), name, template) from e
    except RuntimeError as e:
        if str(e).startswith(PROJECT_EXISTS_PREFIX):
            raise _project_refusal(ProjectExists(str(e)), name, template) from e
        raise _project_refusal(ProjectDoorFailed(str(e)), name, template) from e
    except OSError as e:
        raise _project_refusal(ProjectDoorFailed(str(e)), name, template) from e

    json_handler.log_operation("host_api_verb_new_project", {"name": name, "template": template, "ok": True})
    logger.info("[host_api] project %s created (%s) at %s", name, template, result["target"])
    return {
        "ok": True,
        "name": name,
        "project": result["registry_file"][: -len(REGISTRY_SUFFIX)],
        "target": result["target"],
        "template": result["template"],
        "agent": result["spawn_result"]["branch_name"],
        "agent_home": result["agent_home"],
        "detail": f"Project {name} created with its manager agent",
    }


def _project_refusal(error: Any, name: str, template: str) -> Any:
    """Record a refused new-project request and hand back the error to raise."""
    if isinstance(error, ProjectDoorFailed):
        logger.error("[host_api] project %s could not be created: %s", name, error, exc_info=error.__cause__)
    record = {"name": name, "template": template, "ok": False, "code": error.code}
    json_handler.log_operation("host_api_verb_new_project", record)
    return error


# Public: the attach socket enforces these same rules; a second copy is how lanes disagree on a room.


def require_project(project: str) -> None:
    """Enforce that a room-targeting lane named its project."""
    # A room name carries its project; an inferred one silently picks a DIFFERENT room.
    if not project or not project.strip():
        raise VerbRefused("A project is required on this verb — it is never inferred from the server's seat")


def _sentence(text: Any) -> str:
    """Normalise a door's output into the one sentence an operator will read."""
    # Trims and nothing else: @baud renders `detail` verbatim, and a rewrite loses the diagnosis.
    return str(text or "").strip()


def citizen_address(branch: str, project: str = "") -> str:
    """Validate a branch name and return its citizen address."""
    if not branch or not branch.strip():
        # No verb picks its own target: a defaulted /kill once ended a live session.
        raise VerbRefused("A branch name is required — this lane has no default target")

    try:
        host_reads.resolve_branch_root(branch, project)
    except host_reads.ReadRefused as e:
        raise VerbRefused(str(e)) from e
    except host_reads.ReadUnavailable as e:
        raise VerbUnavailable(str(e)) from e

    return "@" + branch.strip().lstrip("@")


def _route(target: str, command: str, args: list, timeout: int) -> Any:
    """Run a command through drone's router."""
    try:
        return drone.route_command(target, command, args, timeout=timeout)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s %s: %s", target, command, e)
        raise VerbUnavailable(f"{target} {command} could not be run: {e}") from e
