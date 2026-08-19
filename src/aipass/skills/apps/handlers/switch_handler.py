# =================== AIPass ====================
# Name: switch_handler.py
# Description: Per-skill off-switch — state, declaration, systemd actuation
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""
Skill Off-Switch Handler

Core logic for the per-skill ON/OFF toggle designed in DPLAN-0306.

OFF means a skill is disconnected from AIPass, and a skill's processes have
two doors:

  * the process door — systemd user units the skill declares, closed with
    stop + disable + mask (mask is what refuses a respawn, not merely a boot)
  * the runner door — run_skill(), gated before the handler is imported

Both are held here. The toggle's value is a document on disk, so it survives
a restart, a reboot, and a fresh checkout.

Purpose:
    Implementation logic for the off-switch, separated from the
    orchestration layer to satisfy the thin-module standard.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

STATE_FILENAME = "switch_state.json"

# systemd is asked, never told to wait forever: a hung systemctl must not hang
# the switch. The verbs used here are all local bookkeeping plus a unit stop.
_SYSTEMCTL_TIMEOUT = 15

# Frontmatter block a skill uses to declare what belongs to it.
_DECLARATION_KEY = "switch"
_SYSTEMD_KIND = "systemd_user"


class SwitchStateUnreadable(RuntimeError):
    """The state document exists but cannot be trusted.

    Deliberately NOT a "default everything to on" condition. The switch's whole
    purpose is that OFF stays off; answering an unreadable document with "all
    on" resurrects exactly the processes an operator deliberately killed.
    """


# =============================================
# STATE
# =============================================


def get_state_path() -> Path:
    """Return the switch state document's path.

    Resolved at call time, not import time, so the branch's JSON directory can
    be relocated (and isolated in tests) without this handler holding a stale
    copy of where it used to be.

    Returns:
        Path: Location of switch_state.json.
    """
    return Path(json_handler.SKILLS_JSON_DIR) / STATE_FILENAME


def read_state() -> Dict[str, Any]:
    """Read the recorded switch state.

    Three worlds, kept distinct:
        missing        -> {} (nothing has ever been toggled; every skill is on)
        parseable      -> the recorded truth
        anything else  -> SwitchStateUnreadable

    Note:
        This does NOT go through json_handler.load_json. That path calls
        ensure_json_exists, which answers an unparseable document by writing a
        fresh template over it — for a toggle that silently flips every skill
        back ON and destroys the record of why they were off.

    Returns:
        dict: Mapping of skill name -> {"enabled": bool, ...}. Empty if unset.

    Raises:
        SwitchStateUnreadable: The document exists but cannot be parsed.
    """
    state_path = get_state_path()
    if not state_path.exists():
        return {}

    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SwitchStateUnreadable(
            f"Could not read the skill switch state at {state_path}: {exc}. "
            f"Fix the file's permissions, or delete it to reset every skill to ON."
        ) from exc

    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise SwitchStateUnreadable(
            f"The skill switch state at {state_path} is not valid JSON: {exc}. "
            f"Repair it, or delete {STATE_FILENAME} to reset every skill to ON."
        ) from exc

    if not isinstance(document, dict) or not isinstance(document.get("skills"), dict):
        raise SwitchStateUnreadable(
            f"The skill switch state at {state_path} has no 'skills' map, so which "
            f"skills are off cannot be told. Repair it, or delete {STATE_FILENAME} "
            f"to reset every skill to ON."
        )

    return document["skills"]


def write_state(skills: Dict[str, Any]) -> bool:
    """Persist the switch state through the branch's atomic writer.

    Args:
        skills: Mapping of skill name -> entry dict.

    Returns:
        bool: True when the document landed.
    """
    state_path = get_state_path()
    today = datetime.now().date().isoformat()

    created = today
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                created = existing.get("created", today)
        except (OSError, ValueError) as exc:
            # A rewrite over an unreadable document is the one write that is
            # always allowed — it is how an operator recovers.
            logger.warning("Rewriting an unreadable switch state document: %s", exc)

    document = {
        "module_name": "switch",
        "created": created,
        "last_updated": today,
        "skills": skills,
    }

    try:
        Path(json_handler.SKILLS_JSON_DIR).mkdir(parents=True, exist_ok=True)
        json_handler.atomic_write_json(state_path, document)
        return True
    except OSError as exc:
        logger.error("Failed to write the skill switch state to %s: %s", state_path, exc)
        return False


def is_enabled(skill_name: str) -> bool:
    """Report whether a skill is switched on.

    Args:
        skill_name: Skill to check.

    Returns:
        bool: True when on. A skill with no recorded entry is on.

    Raises:
        SwitchStateUnreadable: The state document cannot be trusted.
    """
    entry = read_state().get(skill_name)
    if not isinstance(entry, dict):
        return True
    return bool(entry.get("enabled", True))


def set_enabled(skill_name: str, enabled: bool, reason: str | None = None) -> bool:
    """Record a skill's on/off value.

    Args:
        skill_name: Skill to record.
        enabled: True for on, False for off.
        reason: Optional note kept with the entry.

    Returns:
        bool: True when the document landed.
    """
    try:
        skills = read_state()
    except SwitchStateUnreadable as exc:
        # Recording over a broken document is recovery, not data loss: the
        # operator is stating the intent the file could no longer carry.
        logger.warning("Replacing an unreadable switch state document: %s", exc)
        skills = {}

    previous = skills.get(skill_name)
    previous = previous if isinstance(previous, dict) else {}
    value_moved = bool(previous.get("enabled", True)) != enabled

    entry: Dict[str, Any] = {"enabled": enabled}

    # "changed" must name when the value actually moved. Advancing it on a
    # repeat of the same instruction reports a change that never happened, in
    # the one document meant to be the durable truth.
    if value_moved or "changed" not in previous:
        entry["changed"] = datetime.now().isoformat()
    else:
        entry["changed"] = previous["changed"]

    if reason:
        entry["reason"] = reason
    elif not value_moved and previous.get("reason"):
        # A repeat of the same instruction keeps the recorded WHY. Found live:
        # `off telegram "<why>"` followed by a bare `off telegram` erased it.
        # A reason is dropped only when the value flips, because it describes
        # the state it was attached to.
        entry["reason"] = previous["reason"]

    skills[skill_name] = entry
    saved = write_state(skills)

    json_handler.log_operation(
        "switch_set",
        {"skill": skill_name, "enabled": enabled, "saved": saved},
    )
    return saved


# =============================================
# DECLARATION
# =============================================


def _discovered_skills() -> List[dict]:
    """Build the skill registry using handler-layer pieces only.

    Deliberately not modules.discovery.discover_all: a handler importing an
    orchestration module inverts the layering this branch is built on. The
    registry is assembled from the same handler functions that module calls.

    Returns:
        list[dict]: Discovered skills, deduplicated by name.
    """
    from aipass.skills.apps.handlers.discovery_handler import (
        discover_skills_in_path,
        get_search_paths,
    )
    from aipass.skills.apps.handlers.registry import build_registry

    return build_registry(get_search_paths(), discover_skills_in_path)


def declared_units(skill_name: str) -> List[str]:
    """Return the systemd user units a skill declares as its own.

    Read straight from SKILL.md frontmatter rather than through load_skill,
    which would import the skill's handler — the switch must be able to reason
    about a skill without executing any of its code.

    Args:
        skill_name: Skill to inspect.

    Returns:
        list[str]: Declared unit names, empty when the skill declares none.
    """
    from aipass.skills.apps.handlers.discovery_handler import parse_frontmatter
    from aipass.skills.apps.handlers.loader_handler import find_skill_in_registry

    entry = find_skill_in_registry(skill_name, _discovered_skills())
    if entry is None:
        return []

    metadata = parse_frontmatter(Path(entry["path"]) / "SKILL.md")
    if not isinstance(metadata, dict):
        return []

    declaration = metadata.get(_DECLARATION_KEY)
    if not isinstance(declaration, dict):
        return []

    units = declaration.get(_SYSTEMD_KIND, [])
    if isinstance(units, str):
        units = [units]
    if not isinstance(units, list):
        return []

    return [str(unit) for unit in units if unit]


# =============================================
# SYSTEMD ACTUATION
# =============================================


def _systemctl(*args: str, timeout: int = _SYSTEMCTL_TIMEOUT) -> tuple[int, str, str]:
    """Run one `systemctl --user` verb.

    Args:
        *args: Verb and operands, e.g. ("stop", "telegram-bot@base").
        timeout: Seconds before the call is abandoned.

    Returns:
        tuple: (returncode, stdout, stderr). A call that could not run at all
            returns a non-zero code with the reason in stderr, never an
            exception — the caller decides what a failure means.
    """
    try:
        completed = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.warning("systemctl --user %s timed out", " ".join(args))
        return 1, "", f"systemctl --user {' '.join(args)} timed out"
    except OSError as exc:
        logger.warning("systemctl --user %s failed to run: %s", " ".join(args), exc)
        return 1, "", f"systemctl could not run: {exc}"


def unit_is_active(unit: str) -> bool:
    """Report whether a systemd user unit is currently active.

    Args:
        unit: Unit name.

    Returns:
        bool: True when systemd reports it active.
    """
    code, out, _ = _systemctl("is-active", unit)
    return code == 0 and out == "active"


def active_units(units: List[str]) -> List[str]:
    """Return which of the given units are still alive.

    Args:
        units: Unit names to poll.

    Returns:
        list[str]: The subset systemd reports as active.
    """
    return [unit for unit in units if unit_is_active(unit)]


# =============================================
# THE TOGGLE
# =============================================


def turn_off(skill_name: str, reason: str | None = None) -> Dict[str, Any]:
    """Switch a skill off: record it, stop its processes, block their respawn.

    Order matters. The intent is recorded BEFORE systemd is touched, so a crash
    mid-actuation leaves a machine going dark with a record of why rather than
    a silent one. The runner gate reads that same record, so it holds from the
    first moment too.

    Args:
        skill_name: Skill to switch off.
        reason: Optional note kept with the entry.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    if not set_enabled(skill_name, False, reason=reason):
        return {
            "success": False,
            "output": "",
            "error": f"Could not record '{skill_name}' as off — state not written, nothing stopped.",
        }

    units = declared_units(skill_name)
    lines = [f"Skill '{skill_name}' is OFF."]

    for unit in units:
        _systemctl("stop", unit)
        _systemctl("disable", unit)
        # Disable closes the boot path only. Mask is what makes a respawn
        # impossible — manual start, dependency pull, or a script that thinks
        # it knows better all get refused while the skill is off.
        _systemctl("mask", unit)

    survivors = active_units(units)
    if survivors:
        return {
            "success": False,
            "output": "\n".join(lines),
            "error": (
                f"Recorded '{skill_name}' as off, but these units are STILL RUNNING: "
                f"{', '.join(survivors)}. The skill is not dark."
            ),
        }

    if units:
        lines.append(f"Stopped, disabled and masked {len(units)} unit(s): {', '.join(units)}")
        lines.append("Verified: no declared unit is running.")
    else:
        lines.append("No processes declared — the skill is gated but owns nothing to stop.")

    logger.info("Skill '%s' switched off (%d unit(s))", skill_name, len(units))
    return {"success": True, "output": "\n".join(lines), "error": None}


def turn_on(skill_name: str) -> Dict[str, Any]:
    """Switch a skill on: record it, unblock its processes, start them.

    ON means running now AND after the next reboot, so the units are enabled as
    well as started.

    Args:
        skill_name: Skill to switch on.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    if not set_enabled(skill_name, True):
        return {
            "success": False,
            "output": "",
            "error": f"Could not record '{skill_name}' as on — state not written, nothing started.",
        }

    units = declared_units(skill_name)
    lines = [f"Skill '{skill_name}' is ON."]

    for unit in units:
        # Unmask first: a start issued against a masked unit is refused
        # outright, so the order here is the contract, not a preference.
        _systemctl("unmask", unit)
        _systemctl("enable", unit)
        _systemctl("start", unit)

    dead = [unit for unit in units if not unit_is_active(unit)]
    if dead:
        return {
            "success": False,
            "output": "\n".join(lines),
            "error": (
                f"Recorded '{skill_name}' as on, but these units did NOT start: "
                f"{', '.join(dead)}. Check: systemctl --user status {dead[0]}"
            ),
        }

    if units:
        lines.append(f"Unmasked, enabled and started {len(units)} unit(s): {', '.join(units)}")
        lines.append("Verified: every declared unit is running.")
    else:
        lines.append("No processes declared — the skill is simply runnable again.")

    logger.info("Skill '%s' switched on (%d unit(s))", skill_name, len(units))
    return {"success": True, "output": "\n".join(lines), "error": None}


def switch_rows() -> List[Dict[str, Any]]:
    """Build one status row per discovered skill.

    A row reports what the STATE says and what the MACHINE says, separately. A
    skill recorded as off whose units are still alive is the case worth looking
    for, so it is never collapsed into the state's own claim.

    Returns:
        list[dict]: Rows with name, enabled, reason, units, live_units.

    Raises:
        SwitchStateUnreadable: The state document cannot be trusted.
    """
    skills = read_state()
    rows = []

    for skill in _discovered_skills():
        name = skill["name"]
        recorded = skills.get(name)
        entry = recorded if isinstance(recorded, dict) else {}
        enabled = bool(entry.get("enabled", True))
        units = declared_units(name)

        rows.append(
            {
                "name": name,
                "enabled": enabled,
                "reason": entry.get("reason"),
                "changed": entry.get("changed"),
                "units": units,
                # Only an off skill's units are polled: an on skill's units are
                # meant to be running, and polling every unit of every skill
                # would spend a subprocess per unit on every status call.
                "live_units": active_units(units) if not enabled else [],
            }
        )

    return rows
