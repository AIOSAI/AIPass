# =================== AIPass ====================
# Name: branch_scope.py
# Description: Launch-time branch scoping for Mission Control
# Version: 1.0.0
# Created: 2026-08-11
# Modified: 2026-08-11
# =============================================

"""Branch scoping for `drone @prax monitor run <branches>`.

The monitor labels every event with a display label built by branch_detector
and filesystem_handler. Those labels are richer than a bare branch name:

    PRAX                        a branch log line
    AIPASS/DEVPULSE/opus        a Claude session, project prefix + model tag
    AIPASS/DEVPULSE SUB agent   a sub-agent session
    AIPL/POLYGLOT TESTS         an external project's test output

Scoping therefore matches NAMES inside a label, not the label as a whole:
a label is split on ``/`` and each segment's first word is a candidate name
(``SUB``/``agent``/``TESTS`` are decoration, never the name).

Command events also carry attribution - the caller branch and, in ``action``
as ``executed:<target>``, the branch being acted upon. ``devpulse -> prax``
belongs on both a devpulse screen and a prax screen, so both count.

This module is pure: no logging, no IO. The operator-facing wording lives in
monitor.py, which owns the screen.
"""

from typing import Iterable, List, Optional, Sequence, Set

from aipass.prax.apps.handlers.json import json_handler

# Words appended to a name for display; they are never part of the name itself.
_DECORATORS = frozenset({"SUB", "AGENT", "TESTS"})

# Widening keyword - `monitor run all` is the explicit spelling of "everything".
_ALL_KEYWORD = "ALL"


def label_tokens(label: str) -> Set[str]:
    """Return the branch/project names a display label refers to.

    Args:
        label: Event branch label, e.g. ``'AIPASS/DEVPULSE SUB agent'``

    Returns:
        Uppercase names found in the label (empty set for a blank label).
    """
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
    """The set of branches a monitor run was asked to show.

    An empty scope means "all branches" - the historical behaviour - so an
    unscoped run costs one falsy check per event and nothing else.
    """

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

        Matches the event's own branch label, the caller that issued a command,
        and the command's target branch (stored as ``action='executed:<target>'``
        because MonitoringEvent has no target field).
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

        An empty or missing set means the registry could not be read - that is
        an unknown, not a typo, so nothing is reported.
        """
        if not known_branches or not self.is_scoped:
            return []
        known_upper = {str(b).upper() for b in known_branches}
        return [name for name in self.names if name not in known_upper]

    def __repr__(self) -> str:
        return f"BranchScope({self.describe()})"


def parse_scope(args: Sequence[str]) -> BranchScope:
    """Build a scope from raw `monitor run` arguments.

    Accepts the documented comma form (``seedgo,cli``) and a shell-split list
    (``seedgo cli``). Flags are ignored, and ``all`` anywhere in the list
    widens the run back to every branch.

    Args:
        args: Arguments following ``monitor run``

    Returns:
        BranchScope - unscoped when no branch names are present.
    """
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
    # Logged once per monitor start. Deliberately NOT in matches_event(): that
    # runs per event, and this handler's log is one the monitor itself tails.
    json_handler.log_operation("monitor_scope_parsed", {"branches": list(scope.names)})
    return scope
