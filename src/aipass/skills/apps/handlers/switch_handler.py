# =================== AIPass ====================
# Name: switch_handler.py
# Description: Per-skill off-switch — state, declaration, systemd actuation
# Version: 1.2.0
# Created: 2026-08-18
# Modified: 2026-10-24
# =============================================

"""
Skill Off-Switch Handler

Reference: docs/off_switch.md
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

STATE_FILENAME = "switch_state.json"

# A hung systemctl must not hang the switch.
_SYSTEMCTL_TIMEOUT = 15

# The SKILL.md frontmatter block a skill uses to declare what belongs to it.
_DECLARATION_KEY = "switch"
_SYSTEMD_KIND = "systemd_user"


class SwitchStateUnreadable(RuntimeError):
    """The state document exists but cannot be trusted.

    Never answer it with "all on": that resurrects the processes an operator switched off."""


def get_state_path() -> Path:
    """Return the switch state document's path.

    Asked of the fleet service at call time (it reads AIPASS_TEST_LOG_DIR per call), so it cannot go stale."""
    return json_handler.get_json_path("switch", "data").parent / STATE_FILENAME


def read_state() -> Dict[str, Any]:
    """Read the recorded switch state.

    Not json_handler.load_json: it overwrites an unparseable document with a fresh
    template, which would flip every skill back ON and erase why they were off."""
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
    """Persist the switch state through the fleet's atomic writer."""
    state_path = get_state_path()
    today = datetime.now().date().isoformat()

    created = today
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                created = existing.get("created", today)
        except (OSError, ValueError) as exc:
            # A rewrite over an unreadable document is always allowed: it is how an operator recovers.
            logger.warning("Rewriting an unreadable switch state document: %s", exc)

    document = {
        "module_name": "switch",
        "created": created,
        "last_updated": today,
        "skills": skills,
    }

    if not json_handler.write_json(state_path, document):
        logger.error("Failed to write the skill switch state to %s", state_path)
        return False

    return True


def is_enabled(skill_name: str) -> bool:
    """Report whether a skill is switched on."""
    entry = read_state().get(skill_name)
    if not isinstance(entry, dict):
        return True
    return bool(entry.get("enabled", True))


def off_reason(skill_name: str) -> str | None:
    """The reason recorded with a skill's switch entry."""
    entry = read_state().get(skill_name)
    if not isinstance(entry, dict):
        return None
    return entry.get("reason") or None


def set_enabled(skill_name: str, enabled: bool, reason: str | None = None) -> bool:
    """Record a skill's on/off value."""
    try:
        skills = read_state()
    except SwitchStateUnreadable as exc:
        # Recovery, not data loss: the operator states the intent the file could no longer carry.
        logger.warning("Replacing an unreadable switch state document: %s", exc)
        skills = {}

    previous = skills.get(skill_name)
    previous = previous if isinstance(previous, dict) else {}
    value_moved = bool(previous.get("enabled", True)) != enabled

    entry: Dict[str, Any] = {"enabled": enabled}

    # "changed" names when the value actually moved; a repeat instruction must not advance it.
    if value_moved or "changed" not in previous:
        entry["changed"] = datetime.now().isoformat()
    else:
        entry["changed"] = previous["changed"]

    if reason:
        entry["reason"] = reason
    elif not value_moved and previous.get("reason"):
        # A bare repeat keeps the recorded reason; it is dropped only when the value flips.
        entry["reason"] = previous["reason"]

    skills[skill_name] = entry
    saved = write_state(skills)

    json_handler.log_operation(
        "switch_set",
        {"skill": skill_name, "enabled": enabled, "saved": saved},
    )
    return saved


def _discovered_skills() -> List[dict]:
    """Build the skill registry using handler-layer pieces only.

    Not modules.discovery.discover_all: a handler importing a module inverts the branch's layering."""
    from aipass.skills.apps.handlers.discovery_handler import (
        discover_skills_in_path,
        get_search_paths,
    )
    from aipass.skills.apps.handlers.registry import build_registry

    return build_registry(get_search_paths(), discover_skills_in_path)


def declared_units(skill_name: str, registry: List[dict] | None = None) -> List[str]:
    """Return the systemd user units a skill declares as its own.

    Read from frontmatter, not load_skill: the switch must never import or run a skill's code.
    Pass a registry already built to skip a discovery per call."""
    from aipass.skills.apps.handlers.discovery_handler import parse_frontmatter
    from aipass.skills.apps.handlers.registry import get_skill

    entry = get_skill(skill_name, registry if registry is not None else _discovered_skills())
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


def _systemctl(*args: str, timeout: int = _SYSTEMCTL_TIMEOUT) -> tuple[int, str, str]:
    """Run one `systemctl --user` verb.

    Never raises: a call that cannot run returns non-zero with the reason in stderr."""
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
    """Report whether a systemd user unit is currently active."""
    code, out, _ = _systemctl("is-active", unit)
    return code == 0 and out == "active"


def active_units(units: List[str]) -> List[str]:
    """Return which of the given units are still alive."""
    return [unit for unit in units if unit_is_active(unit)]


def turn_off(skill_name: str, reason: str | None = None) -> Dict[str, Any]:
    """Switch a skill off: record it, stop its processes, block their respawn.

    The record lands before systemd is touched: a crash mid-actuation keeps the why,
    and the runner gate, which reads the same record, holds from the first moment."""
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
        # Disable closes only the boot path; mask is what refuses a manual start or dependency pull.
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

    ON means running now and after the next reboot, so units are enabled as well as started."""
    if not set_enabled(skill_name, True):
        return {
            "success": False,
            "output": "",
            "error": f"Could not record '{skill_name}' as on — state not written, nothing started.",
        }

    units = declared_units(skill_name)
    lines = [f"Skill '{skill_name}' is ON."]

    for unit in units:
        # Unmask first: systemd refuses a start against a masked unit.
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

    State and machine are reported separately: an off skill with live units is the case to catch."""
    skills = read_state()
    registry = _discovered_skills()
    rows = []

    for skill in registry:
        name = skill["name"]
        recorded = skills.get(name)
        entry = recorded if isinstance(recorded, dict) else {}
        enabled = bool(entry.get("enabled", True))
        units = declared_units(name, registry)

        rows.append(
            {
                "name": name,
                "enabled": enabled,
                "reason": entry.get("reason"),
                "changed": entry.get("changed"),
                "units": units,
                # Only off skills are polled: one subprocess per unit per status call is the cost.
                "live_units": active_units(units) if not enabled else [],
            }
        )

    return rows
