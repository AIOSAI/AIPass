# =================== AIPass ====================
# Name: branch_scope.py
# Description: Launch-time branch scoping for Mission Control
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-10-17
# =============================================

"""Branch scoping for `drone @prax monitor run <branches>`.

Matches names inside a display label (``AIPASS/DEVPULSE/opus``), not the whole label.
Reference: docs/monitor.md
"""

from typing import Iterable, List, Optional, Sequence, Set

from aipass.prax.apps.handlers.json import json_handler

# Words appended to a name for display; they are never part of the name itself.
_DECORATORS = frozenset({"SUB", "AGENT", "TESTS"})

_ALL_KEYWORD = "ALL"


def label_tokens(label: str) -> Set[str]:
    """Return the branch/project names a display label refers to."""
    if not label:
        return set()

    tokens: Set[str] = set()
    for segment in str(label).split("/"):
        for word in segment.split():
            name = word.strip().upper()
            if name and name not in _DECORATORS:
                tokens.add(name)
                break  # first word of a segment is the name; the rest decorate it
    return tokens


class BranchScope:
    """The set of branches a monitor run was asked to show; empty means all."""

    def __init__(self, names: Iterable[str] = ()):
        ordered: List[str] = []
        seen: Set[str] = set()
        for raw in names or ():
            name = str(raw).strip().upper()
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        self.names = tuple(ordered)
        self._lookup = frozenset(ordered)

    @property
    def is_scoped(self) -> bool:
        """True when the run was given a branch list."""
        return bool(self.names)

    def matches_label(self, label: str) -> bool:
        """Check whether a display label belongs to this scope."""
        if not self.is_scoped:
            return True
        return bool(label_tokens(label) & self._lookup)

    def matches_event(self, event) -> bool:
        """Check whether an event belongs to this scope.

        The target lives in ``action='executed:<target>'``: MonitoringEvent has no target field.
        """
        if not self.is_scoped:
            return True

        if self.matches_label(getattr(event, "branch", "") or ""):
            return True

        caller = getattr(event, "caller", None)
        if caller and self.matches_label(caller):
            return True

        action = getattr(event, "action", "") or ""
        if action.startswith("executed:"):
            target = action.split(":", 1)[1]
            if target and self.matches_label(target):
                return True

        return False

    def describe(self) -> str:
        """Operator-facing name of the scope, in the order it was requested."""
        return ", ".join(self.names) if self.is_scoped else "all branches"

    def unknown_names(self, known_branches: Optional[Set[str]]) -> List[str]:
        """Return requested names that are not in the known-branch set.

        An empty set means the registry could not be read: an unknown, not a typo.
        """
        if not known_branches or not self.is_scoped:
            return []
        known_upper = {str(b).upper() for b in known_branches}
        return [name for name in self.names if name not in known_upper]

    def __repr__(self) -> str:
        return f"BranchScope({self.describe()})"


def parse_scope(args: Sequence[str]) -> BranchScope:
    """Build a scope from raw `monitor run` arguments (``seedgo,cli`` or ``seedgo cli``)."""
    names: List[str] = []
    widened = False
    for arg in args or ():
        text = str(arg)
        if text.startswith("-"):
            continue
        for part in text.replace(",", " ").split():
            name = part.strip().upper()
            if not name:
                continue
            if name == _ALL_KEYWORD:
                widened = True
                names = []
                break
            names.append(name)
        if widened:
            break

    scope = BranchScope(names)
    # Not in matches_event(): that runs per event, into a log the monitor tails.
    json_handler.log_operation("monitor_scope_parsed", {"branches": list(scope.names)})
    return scope
