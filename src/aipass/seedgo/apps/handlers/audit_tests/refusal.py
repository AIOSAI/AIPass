# =================== AIPass ====================
# Name: refusal.py
# Description: audit-tests refusal vocabulary and exit mapping
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The refusal vocabulary — the lane's most load-bearing distinction.

A REFUSAL IS NEVER A SCORE. The whole reason this lane exists is that a zero
from a gate that could not fire and a zero from a clean suite look identical
from the outside, and only an explicit refusal tells them apart.

Exit codes (design section 1.4). The code is a shell CONVENIENCE, never the
verdict: `seedgo.py` returns 0 on any truthy route, so a caller that reads the
exit code alone cannot see a refusal at all. The artifact's `status` field and
the `REFUSED:` stdout line are the load-bearing signals (design section 6.3b).

    0  published; every scored group passed
    1  published; a scored group failed
    2  refused - the harness could not prove it was entitled to publish
    3  refused - the target holds no runnable test units
    4  refused - no adapter claims this target
    5  refused - lane pointed at a static pack, or audit pointed at execution
    6  refused - the wall-clock budget expired (Law T-BUDGET)
    7  refused - an argument nobody recognised, so nothing ran (Law ARGV)

Multi-target form returns the WORST per-target code, ordered

    0 < 1 < 3 < 4 < 5 < 6 < 7 < 2

with 2 ranked worst deliberately: an unproven harness is a more serious
result than a suite that failed a gate honestly.

LAW ARGV — an argument nobody recognises is refused BY NAME, never dropped.
The CLI seam is where this vocabulary was missing: `drone @seedgo audit -tests
@backup` (a space where a hyphen belonged) had its `-tests` silently discarded
and ran the ordinary standards audit on cached data, so twenty minutes were
spent reading one lane's output as another's. That is the same species the
whole lane exists to end — a result that cannot be told apart from the result
that was asked for. A dropped argument is a command the caller never gave, so
it refuses, names the token, and prints the command that would have worked.
"""

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import List, Optional, Sequence

from aipass.seedgo.apps.handlers.json import json_handler

# =============================================================================
# EXIT CODES
# =============================================================================

EXIT_PASSED = 0
EXIT_SCORED_FAILED = 1
EXIT_UNPROVEN = 2
EXIT_NO_UNITS = 3
EXIT_NO_ADAPTER = 4
EXIT_WRONG_PACK_KIND = 5
EXIT_BUDGET_EXHAUSTED = 6
EXIT_UNKNOWN_ARGUMENT = 7

#: Every code that means "refused". Codes 0 and 1 are publications.
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

#: Worst-first severity for the multi-target fleet form. Index = severity rank;
#: a higher index is worse. `EXIT_UNPROVEN` is last because it is the worst.
#: `EXIT_UNKNOWN_ARGUMENT` sits just under it: a command nobody understood
#: measured NOTHING, and a run that never happened must never rank quieter
#: than one that ran and failed honestly.
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

#: The law each refusal cites, so a refusal always names the rule it refuses
#: under rather than only saying "no".
REFUSAL_LAW = {
    EXIT_UNPROVEN: "T10",
    EXIT_NO_UNITS: "S1",
    EXIT_NO_ADAPTER: "S1",
    EXIT_WRONG_PACK_KIND: "M1",
    EXIT_BUDGET_EXHAUSTED: "T-BUDGET",
    EXIT_UNKNOWN_ARGUMENT: "ARGV",
}


# =============================================================================
# THE REFUSAL RECORD
# =============================================================================


@dataclass
class Refusal:
    """A refusal, carrying the law it refuses under and why.

    `detail` holds the evidence a reader needs to act — the canary's own
    output, the paths that had no test units, the elapsed seconds against the
    budget. A refusal with an empty detail list is a refusal nobody can fix.
    """

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
        """The load-bearing stdout signal (design section 6.3b).

        Printed on every refusal because the exit code cannot survive
        `seedgo.py`'s return path.
        """
        return f"REFUSED: [{self.law}] {self.reason}"

    def record(self) -> None:
        """Log this refusal to the operations log.

        Called at the point a refusal is acted on rather than at construction,
        so a refusal built and discarded during assembly never pollutes the
        record with something that did not happen.
        """
        json_handler.log_operation(
            "lane_refused",
            {"law": self.law, "code": self.code, "reason": self.reason, "detail": self.detail},
        )


# =============================================================================
# HELPERS
# =============================================================================


def is_refusal(code: int) -> bool:
    """True if this exit code means the lane refused to publish."""
    return code in REFUSAL_CODES


def worst_code(codes: List[int]) -> int:
    """The worst code across a fleet run, per SEVERITY_ORDER.

    An unknown code is treated as the worst possible rather than ignored —
    silently downgrading a code we do not recognise is exactly how a refusal
    would come to look like a pass.
    """
    if not codes:
        return EXIT_PASSED

    def rank(code: int) -> int:
        """Severity rank; anything unrecognised sorts worse than every known code."""
        if code in SEVERITY_ORDER:
            return SEVERITY_ORDER.index(code)
        return len(SEVERITY_ORDER)

    return max(codes, key=rank)


def refusal_for_budget(elapsed: float, budget: int, group: str) -> Refusal:
    """Build the T-BUDGET refusal (design section 4.7).

    A partial measurement that reports a number is OBSERVER-FORGERY by
    omission, so the adapter must never return one — this is what it returns
    instead.
    """
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


# =============================================================================
# LAW ARGV - the did-you-mean, built from what the caller actually typed
# =============================================================================

#: How alike two spellings must be before one is offered as the other. 0.6 is
#: difflib's own default: below it the "did you mean" starts inventing.
SIMILARITY = 0.6

#: Every suggestion is printed as a command a reader can paste. The prefix is
#: fixed because the seam being fixed is reached through drone.
COMMAND_PREFIX = "drone @seedgo"


def sibling_verb(token: str, verb: str, sibling_verbs: Sequence[str]) -> str:
    """The sibling verb a stray token was probably trying to spell.

    ``-tests`` typed at ``audit`` is ``audit tests`` with a stray hyphen, so the
    token is glued back onto the verb before anything else is tried. A
    candidate equal to the verb already typed is rejected: suggesting the
    command the caller just ran is not a suggestion.

    The SPACE spelling is tried first because a two-word surface is the
    canonical one wherever both exist: ``audit tests <target>`` is offered
    ahead of ``audit-tests <target>``, and the hyphen form stays a valid
    spelling that is still offered whenever the space form is not on the list.
    """
    stem = token.lstrip("-")
    if not stem:
        return ""

    for spelling in (f"{verb} {stem}", f"{verb}-{stem}", f"{verb}_{stem}", stem):
        if spelling != verb and spelling in sibling_verbs:
            return spelling

    # Fuzzy matching compares the DISTINGUISHING part of each sibling, never
    # the whole glued spelling: `audit-` is shared, so measuring against
    # `audit-tests` scored `--zzz` at 0.6 and offered the wrong verb for a token
    # that was only ever a misspelt flag. `tests` against `zzz` scores nothing.
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

    Three answers in priority order, and the order is the point: the sibling
    verb is tried FIRST because that is the typo that motivated the rule, and a
    fuzzy flag match would otherwise offer a plausible flag for a token that
    was never a flag at all.
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
        # A bare extra word has no correct spelling — the command without it is
        # the only honest suggestion left.
        rest.remove(token)
        return " ".join([COMMAND_PREFIX, verb, *rest]).strip()

    return f"{COMMAND_PREFIX} {verb} --help"


def refusal_for_unknown_argument(token: str, suggestion: str, verb: str) -> Refusal:
    """Build the ARGV refusal — a token the verb did not recognise.

    The whole fix is in the `reason`: it NAMES the token and carries the
    command that would have worked, on ONE line, because that line is what a
    log keeps and what a phone shows. A refusal that only said "bad arguments"
    would tell the reader the run failed without telling them how to fix it,
    and the ruling this exists to answer was exactly that the command should
    have failed AND given the solution.
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
    """Refuse a word two surfaces could both claim (Law ARGV).

    `audit tests <target>` reaches the execution lane and `audit <pack>`
    reaches a pack directory, so a pack really named `tests` would give the one
    word two meanings. NEITHER may be picked quietly: a silently preferred
    meaning produces a run that cannot be told apart from the run that was
    asked for, which is exactly what the dropped `-tests` token did. Both
    meanings are named, each with the spelling that reaches only it.
    """
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
    """Build the canary refusal (Law T10 / M2).

    A run that cannot catch its own planted write has proved nothing, and must
    not publish. This is the refusal that makes a score of 100 mean anything
    at all.
    """
    return Refusal(
        code=EXIT_UNPROVEN,
        reason="the hygiene gate did not catch its own planted canary write",
        detail=list(detail or []) or ["the gate was installed but did not fire; a score from it would be unproven"],
    )
