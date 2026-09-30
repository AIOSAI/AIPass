# =================== AIPass ====================
# Name: parser.py
# Description: Duration text parser - "1d 2h 3m 4s" to a total in seconds, or a named refusal
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Parse a duration the way people write them: ``2d 4h``, ``90m``, ``1h30m``.

Units are ``d``, ``h``, ``m``, ``s``, lowercase. Order does not matter and
whitespace is insignificant everywhere, so ``1h30m``, ``1h 30m`` and ``30m 1h``
are the same duration. Nothing is inferred: every refusal names the part of the
text that caused it, and no refusal returns a number.

Deliberately strict where a friendly parser would guess:

* ``2H`` is an unknown unit, not a case-folded ``2h`` - a parser that quietly
  accepts a spelling it was not given cannot be measured from outside.
* ``1.5h`` and ``-3h`` are refused rather than rounded or clamped.
* Non-ASCII digits are refused even though ``int()`` accepts them: ``int("٣")``
  is 3, so an ASCII-only check is the only thing between a store of seconds and
  a number nobody typed.

Leading zeros ARE accepted (``007h``): a plain non-negative integer is what is
asked for, and ``007`` is one.
"""

from typing import Dict, List, NoReturn, Set, Tuple

from aipass.canary.apps.handlers.json import json_handler

SECONDS_PER_UNIT: Dict[str, int] = {"d": 86400, "h": 3600, "m": 60, "s": 1}

UNIT_LIST = "d, h, m, s"

MAX_DAYS = 366

MAX_SECONDS = MAX_DAYS * SECONDS_PER_UNIT["d"]

DIGITS = frozenset("0123456789")


class DurationInvalid(Exception):
    """The text is not a duration this parser will turn into a number of seconds."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it.

    Every refusal in this handler goes through here, so the trail carries the
    ones nobody was watching: the parse refusals are the interesting half of
    this command, and a reason that only ever reached a terminal is lost.

    Args:
        reason: What is wrong with the text, named part first.

    Raises:
        DurationInvalid: Always.
    """
    json_handler.log_operation("duration_refused", {"reason": reason})
    raise DurationInvalid(reason)


def _is_plain_integer(number: str) -> bool:
    """Return whether the text is a plain non-negative ASCII integer.

    Args:
        number: The candidate number, already split off from its unit.

    Returns:
        True for one or more ASCII digits and nothing else.
    """
    return bool(number) and all(char in DIGITS for char in number)


def _split_parts(compact: str) -> List[Tuple[str, str]]:
    """Split whitespace-free text into (number, unit) pairs without judging them.

    The split is by character class, not by a pattern of what is valid: the
    number is everything up to the next letter, the unit is the letter run.
    ``1.5h`` therefore arrives as ``("1.5", "h")`` and is refused as a bad
    number, not as an unknown unit ``.`` - the refusal has to point at the part
    the writer actually got wrong.

    Args:
        compact: The duration text with all whitespace already removed.

    Returns:
        One (number, unit) pair per part, in the order written. Either half of
        a pair can be empty; validation is the caller's job.
    """
    parts: List[Tuple[str, str]] = []
    index = 0

    while index < len(compact):
        number_start = index
        while index < len(compact) and not compact[index].isalpha():
            index += 1
        number = compact[number_start:index]

        unit_start = index
        while index < len(compact) and compact[index].isalpha():
            index += 1
        unit = compact[unit_start:index]

        parts.append((number, unit))

    return parts


def _validate(number: str, unit: str, seen: Set[str]) -> None:
    """Refuse one part, or record its unit as used.

    Args:
        number: The number half of the part, possibly empty.
        unit: The unit half of the part, possibly empty.
        seen: Units already used, added to here.

    Raises:
        DurationInvalid: The part is not a number followed by a known, unused unit.
    """
    if number and not _is_plain_integer(number):
        _refuse(f"'{number}' is not a plain non-negative integer")
    if not unit:
        _refuse(f"'{number}' is a bare number with no unit (units are {UNIT_LIST})")
    if not number:
        _refuse(f"unit '{unit}' has no number in front of it")
    if unit not in SECONDS_PER_UNIT:
        _refuse(f"unknown unit '{unit}' (units are {UNIT_LIST}, lowercase)")
    if unit in seen:
        _refuse(f"unit '{unit}' is given more than once")

    seen.add(unit)


def parse_duration(text: str) -> int:
    """Turn a written duration into a total number of seconds.

    Args:
        text: The duration as written, e.g. ``2d 4h`` or ``1h30m``.

    Returns:
        The total in seconds, never negative.

    Raises:
        DurationInvalid: The text is empty or whitespace-only, repeats a unit,
            names an unknown unit, carries a number that is not a plain
            non-negative integer, leaves a number without a unit, or totals
            more than MAX_DAYS days.
    """
    compact = "".join(text.split())
    if not compact:
        _refuse("no duration text (write one like: 2d 4h, 90m, 1h30m)")

    seen: Set[str] = set()
    total = 0

    for number, unit in _split_parts(compact):
        _validate(number, unit, seen)
        total += int(number) * SECONDS_PER_UNIT[unit]

    if total > MAX_SECONDS:
        _refuse(f"total is over the {MAX_DAYS}-day limit ({total} seconds, limit {MAX_SECONDS})")

    return total
