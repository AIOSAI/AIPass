# =================== AIPass ====================
# Name: refusal.py
# Description: audit-tests refusal vocabulary and exit mapping
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""
The refusal vocabulary — the lane's most load-bearing distinction.

A refusal is never a score. The exit code is a convenience (`seedgo.py` returns 0
on any truthy route); `status` and the `REFUSED:` stdout line are the signals.
Law ARGV: an unrecognised argument is refused by name with a working command, never dropped.
"""

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import List, Optional, Sequence

from aipass.seedgo.apps.handlers.json import json_handler

EXIT_PASSED = 0
EXIT_SCORED_FAILED = 1
EXIT_UNPROVEN = 2
EXIT_NO_UNITS = 3
EXIT_NO_ADAPTER = 4
EXIT_WRONG_PACK_KIND = 5
EXIT_BUDGET_EXHAUSTED = 6
EXIT_UNKNOWN_ARGUMENT = 7

REFUSAL_CODES: frozenset = frozenset(
    {
        EXIT_UNPROVEN,
        EXIT_NO_UNITS,
        EXIT_NO_ADAPTER,
        EXIT_WRONG_PACK_KIND,
        EXIT_BUDGET_EXHAUSTED,
        EXIT_UNKNOWN_ARGUMENT,
    }
)

#: Fleet severity, higher index worse: an unproven harness, then a run that never happened,
#: rank above a suite that failed honestly.
SEVERITY_ORDER: tuple = (
    EXIT_PASSED,
    EXIT_SCORED_FAILED,
    EXIT_NO_UNITS,
    EXIT_NO_ADAPTER,
    EXIT_WRONG_PACK_KIND,
    EXIT_BUDGET_EXHAUSTED,
    EXIT_UNKNOWN_ARGUMENT,
    EXIT_UNPROVEN,
)

REFUSAL_LAW = {
    EXIT_UNPROVEN: "T10",
    EXIT_NO_UNITS: "S1",
    EXIT_NO_ADAPTER: "S1",
    EXIT_WRONG_PACK_KIND: "M1",
    EXIT_BUDGET_EXHAUSTED: "T-BUDGET",
    EXIT_UNKNOWN_ARGUMENT: "ARGV",
}


@dataclass
class Refusal:
    """A refusal, carrying the law it refuses under and why."""

    code: int
    reason: str
    detail: List[str] = field(default_factory=list)

    @property
    def law(self) -> str:
        """The law this refusal cites."""
        return REFUSAL_LAW.get(self.code, "T10")

    def to_document(self) -> dict:
        """The artifact's `refusal` block."""
        return {
            "law": self.law,
            "code": self.code,
            "reason": self.reason,
            "detail": list(self.detail),
        }

    def stdout_line(self) -> str:
        """The load-bearing stdout signal (design section 6.3b)."""
        return f"REFUSED: [{self.law}] {self.reason}"

    def record(self) -> None:
        """Log this refusal to the operations log.

        Called when acted on, not at construction, so a discarded refusal is never logged.
        """
        json_handler.log_operation(
            "lane_refused",
            {"law": self.law, "code": self.code, "reason": self.reason, "detail": self.detail},
        )


def is_refusal(code: int) -> bool:
    """True if this exit code means the lane refused to publish."""
    return code in REFUSAL_CODES


def worst_code(codes: List[int]) -> int:
    """The worst code across a fleet run, per SEVERITY_ORDER; an unknown code ranks worst."""
    if not codes:
        return EXIT_PASSED

    def rank(code: int) -> int:
        """Severity rank; anything unrecognised sorts worse than every known code."""
        if code in SEVERITY_ORDER:
            return SEVERITY_ORDER.index(code)
        return len(SEVERITY_ORDER)

    return max(codes, key=rank)


def refusal_for_budget(elapsed: float, budget: int, group: str) -> Refusal:
    """Build the T-BUDGET refusal (design section 4.7)."""
    return Refusal(
        code=EXIT_BUDGET_EXHAUSTED,
        reason=f"budget_exhausted: group '{group}' exceeded its wall-clock budget",
        detail=[
            f"group: {group}",
            f"budget_seconds: {budget}",
            f"elapsed_seconds: {elapsed:.1f}",
            "no partial measurement is published - a partial suite that reports a number is forgery by omission",
        ],
    )


#: difflib's default; below it the "did you mean" starts inventing.
SIMILARITY = 0.6

COMMAND_PREFIX = "drone @seedgo"


def sibling_verb(token: str, verb: str, sibling_verbs: Sequence[str]) -> str:
    """The sibling verb a stray token was probably trying to spell.

    The space spelling (`audit tests`) is tried first; the verb already typed is never offered.
    """
    stem = token.lstrip("-")
    if not stem:
        return ""

    for spelling in (f"{verb} {stem}", f"{verb}-{stem}", f"{verb}_{stem}", stem):
        if spelling != verb and spelling in sibling_verbs:
            return spelling

    # Fuzzy-match only the distinguishing part: the shared `audit-` prefix inflates the score.
    distinguishing: dict = {}
    for name in sibling_verbs:
        if name == verb:
            continue
        key = name
        for separator in ("-", "_"):
            prefix = f"{verb}{separator}"
            if name.startswith(prefix):
                key = name[len(prefix) :]
                break
        distinguishing.setdefault(key, name)

    close = get_close_matches(stem, list(distinguishing), n=1, cutoff=SIMILARITY)
    return distinguishing[close[0]] if close else ""


def nearest_flag(token: str, flags: Sequence[str]) -> str:
    """The flag this token most nearly spells, or "" when it spells none."""
    if not token.startswith("-"):
        return ""
    close = get_close_matches(token, list(flags), n=1, cutoff=SIMILARITY)
    return close[0] if close else ""


def suggested_command(
    token: str,
    verb: str,
    args: Sequence[str],
    flags: Sequence[str] = (),
    sibling_verbs: Sequence[str] = (),
) -> str:
    """The command the caller probably meant, rebuilt from what they typed.

    Sibling verb first, else a fuzzy flag match would offer a flag for a non-flag token.
    """
    rest = list(args)

    glued = sibling_verb(token, verb, sibling_verbs)
    if glued:
        rest.remove(token)
        return " ".join([COMMAND_PREFIX, glued, *rest]).strip()

    flag = nearest_flag(token, flags)
    if flag:
        rest[rest.index(token)] = flag
        return " ".join([COMMAND_PREFIX, verb, *rest]).strip()

    if not token.startswith("-"):
        rest.remove(token)
        return " ".join([COMMAND_PREFIX, verb, *rest]).strip()

    return f"{COMMAND_PREFIX} {verb} --help"


def refusal_for_unknown_argument(token: str, suggestion: str, verb: str) -> Refusal:
    """Build the ARGV refusal — a token the verb did not recognise.

    The one-line `reason` names the token and the working command; logs keep that line.
    """
    return Refusal(
        code=EXIT_UNKNOWN_ARGUMENT,
        reason=f"unknown argument {token!r}, did you mean: {suggestion}",
        detail=[
            f"verb: {verb}",
            f"unrecognised: {token}",
            f"try: {suggestion}",
            "nothing ran - a silently dropped argument is a command the caller never gave",
        ],
    )


def refusal_for_ambiguous_lane_word(word: str, verb: str, lane: str = "audit-tests") -> Refusal:
    """Refuse a word two surfaces could both claim (Law ARGV); neither meaning is picked quietly."""
    return Refusal(
        code=EXIT_UNKNOWN_ARGUMENT,
        reason=(
            f"ambiguous argument {word!r}: both the {lane} lane and a {word!r} "
            f"standards pack answer to it, so nothing ran"
        ),
        detail=[
            f"verb: {verb}",
            f"ambiguous: {word}",
            f"for the execution lane, say: {COMMAND_PREFIX} {lane} <target>",
            f"for the pack, say: {COMMAND_PREFIX} {verb} {word}_standards",
            "nothing ran - a word with two meanings is never resolved by preference",
        ],
    )


def refusal_for_canary(detail: Optional[List[str]] = None) -> Refusal:
    """Build the canary refusal (Law T10 / M2)."""
    return Refusal(
        code=EXIT_UNPROVEN,
        reason="the hygiene gate did not catch its own planted canary write",
        detail=list(detail or []) or ["the gate was installed but did not fire; a score from it would be unproven"],
    )
