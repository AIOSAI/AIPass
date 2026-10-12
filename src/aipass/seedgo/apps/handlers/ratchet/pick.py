# =================== AIPass ====================
# Name: pick.py
# Description: the ratchet pick - the unit probed least recently, read from the series
# Version: 1.0.0
# Created: 2026-10-12
# Modified: 2026-10-12
# =============================================

"""
LEAST RECENTLY PROBED, AND THE SERIES SAYS WHEN. A unit never probed comes
first; ties break alphabetically on the lowercased name. The registry's order
is not the tie-break: the registry is gitignored, so its order is a fact about
one host. Every probe line counts as a visit - weekly, recorded, refused - so a
branch whose suite is red does not win the pick every week and starve the lap.

The reason is returned as a sentence because it is written into the series
line: the next wake and a human both read why this unit was chosen.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from aipass.seedgo.apps.handlers.json import json_handler

MODULE_NAME = "ratchet.pick"


def last_probed(lines: Sequence[dict]) -> Dict[str, str]:
    """The newest probe date per branch, keyed by lowercased name."""
    latest: Dict[str, str] = {}
    for line in lines:
        name = str(line.get("branch") or "").lower()
        date = str(line.get("date") or "")
        if name and date > latest.get(name, ""):
            latest[name] = date
    return latest


def standings(names: Sequence[str], lines: Sequence[dict]) -> List[Tuple[str, Optional[str]]]:
    """Every branch with its last probe date (None = never), in pick order."""
    latest = last_probed(lines)
    rows = [(name, latest.get(name.lower())) for name in names]
    return sorted(rows, key=lambda row: (row[1] is not None, row[1] or "", row[0].lower()))


def choose(names: Sequence[str], lines: Sequence[dict]) -> Tuple[str, str]:
    """`(branch, reason)` for the next probe. Raises when there is no branch to pick."""
    rows = standings(names, lines)
    if not rows:
        raise ValueError("no branches were discovered, so there is nothing to pick")

    name, date = rows[0]
    if date is None:
        never = sum(1 for _, seen in rows if seen is None)
        reason = f"never probed; first alphabetically of {never} never-probed branch(es)"
    else:
        reason = f"least recently probed: last probe {date[:10]}, oldest of {len(rows)} branches"

    json_handler.log_operation("ratchet_picked", {"branch": name, "reason": reason}, module_name=MODULE_NAME)
    return name, reason
