# =================== AIPass ====================
# Name: pick.py
# Description: the ratchet pick - the unit probed least recently, read from the series
# Version: 1.1.0
# Created: 2026-10-12
# Modified: 2026-10-25
# =============================================

"""LEAST RECENTLY PROBED, AND THE SERIES SAYS WHEN. Never-probed first, ties on the lowercased name, not the registry's order.
Every line is a visit, so a red suite cannot win every pick; a budget fragment comes back first, finished slice by slice."""

from typing import Dict, List, Optional, Sequence, Tuple

from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.ratchet import series

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

    fragments = sorted(
        (str(chain[-1].get("date") or ""), name.lower(), name, len(chain))
        for name in names
        if (chain := series.fragment_chain(name, lines))
    )
    name, date = rows[0]
    if fragments:
        date, _, name, done = fragments[0]
        reason = f"continuing a budget fragment: slice {done + 1}, last fragment {date[:10]}"
    elif date is None:
        never = sum(1 for _, seen in rows if seen is None)
        reason = f"never probed; first alphabetically of {never} never-probed branch(es)"
    else:
        reason = f"least recently probed: last probe {date[:10]}, oldest of {len(rows)} branches"

    json_handler.log_operation("ratchet_picked", {"branch": name, "reason": reason}, module_name=MODULE_NAME)
    return name, reason
