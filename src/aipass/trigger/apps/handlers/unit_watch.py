# =================== AIPass ====================
# Name: unit_watch.py
# Description: Systemd user units that restart-loop or fail, one mail per unit per incident
# Version: 1.0.0
# Created: 2026-11-10
# Modified: 2026-11-10
# =============================================

"""Systemd user units that restart-loop or fail: one mail per unit per incident.

A unit that dies at once and restarts every few seconds lives a second per run, so it shows in no
process list; only systemd's own restart counter sees it. Each check reads that counter for every
user service and compares it with the last check, kept in ``STATE_FILE``.
"""

import json
import subprocess
from typing import Any, Callable, Dict, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.config import TRIGGER_JSON_DIR, atomic_write_json
from aipass.trigger.apps.handlers.json import json_handler

STATE_FILE = TRIGGER_JSON_DIR / "unit_watch.json"

# A 5 s restart loop adds about 120 per 10-minute check; a healthy unit adds none.
LOOP_RESTARTS_PER_CHECK = 5

SYSTEMCTL_KEY = "(systemctl --user)"
PROPERTIES = "Id,NRestarts,ActiveState,SubState,FragmentPath"


def run_command(args: List[str]) -> str:
    """Run one read-only command and return its stdout; a non-zero exit raises with its stderr."""
    done = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def read_units() -> List[Dict[str, str]]:
    """Every user service's restart count and state, in two systemctl calls."""
    listing = run_command(["systemctl", "--user", "list-units", "--type=service", "--all", "--no-legend", "--plain"])
    names = [line.split()[0] for line in listing.splitlines() if line.strip()]
    if not names:
        return []
    shown = run_command(["systemctl", "--user", "show", f"--property={PROPERTIES}", *names])
    units = []
    for block in shown.strip().split("\n\n"):
        row = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if row.get("Id"):
            units.append(row)
    return units


def _last_line(unit: str) -> str:
    """The unit's own last journal line; systemd's 'Consumed CPU' line is not the unit speaking."""
    try:
        lines = run_command(
            ["journalctl", "--user", f"_SYSTEMD_USER_UNIT={unit}", "-n", "1", "--no-pager", "-o", "cat"]
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return f"(journal unreadable: {exc})"
    return lines.strip() or "(the unit wrote nothing to the journal)"


def _troubled(units: List[Dict[str, str]], previous: Dict[str, Any], seen: Dict[str, Any]) -> Dict[str, tuple]:
    """Units failed or looping now, each with its mail; fills *seen* with this check's counters."""
    troubled = {}
    for row in units:
        unit = row["Id"]
        restarts = int(row["NRestarts"]) if row.get("NRestarts", "").isdigit() else 0
        auto = row.get("SubState") == "auto-restart"
        seen[unit] = {"restarts": restarts, "auto": auto}
        before = previous.get(unit, {})
        rose = restarts - before.get("restarts", restarts)
        if row.get("ActiveState") == "failed":
            why = "has failed"
        elif rose > LOOP_RESTARTS_PER_CHECK or (auto and before.get("auto")):
            why = f"is restart-looping (+{rose} restarts since the last check)"
        else:
            continue
        body = (
            f"Unit: {unit}\nState: {row.get('ActiveState')}/{row.get('SubState')}\nRestarts: {restarts}\n"
            f"Last line: {_last_line(unit)}\nUnit file: {row.get('FragmentPath') or '(none)'}\n\n"
            f"A unit that restarts every few seconds shows in no process list. "
            f"Inspect: systemctl --user status {unit}"
        )
        troubled[unit] = (f"[UNIT] {unit} {why}", body)
    return troubled


def check(send: Callable[[str, str], bool]) -> List[str]:
    """One check of every user service; mails each unit newly in trouble and returns those subjects."""
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    previous, alerted = state.get("units", {}), set(state.get("alerted", []))
    seen: Dict[str, Any] = {}
    try:
        troubled = _troubled(read_units(), previous, seen)
        # An incident ends when its unit is healthy again (or systemctl readable); a later one mails again.
        alerted &= set(troubled)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning(f"[unit_watch] systemctl --user unreadable: {exc}")
        # Unreadable is an incident of its own; the units' last counters and open incidents stand.
        seen = previous
        troubled = {SYSTEMCTL_KEY: (f"[UNIT] {SYSTEMCTL_KEY} is unreadable", f"The unit check cannot run: {exc}")}

    sent = []
    for unit, (subject, body) in troubled.items():
        if unit not in alerted and send(subject, body):
            alerted.add(unit)
            sent.append(subject)
    atomic_write_json(STATE_FILE, {"units": seen, "alerted": sorted(alerted)})
    json_handler.log_operation("unit_check", {"units": len(seen), "troubled": sorted(troubled), "sent": len(sent)})
    return sent
