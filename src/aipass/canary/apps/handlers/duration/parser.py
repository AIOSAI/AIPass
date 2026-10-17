# =================== AIPass ====================
# Name: parser.py
# Description: Duration text parser - "1d 2h 3m 4s" to a total in seconds, or a named refusal
# Version: 1.0.1
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""Parse a duration the way people write them: ``2d 4h``, ``90m``, ``1h30m``.

Reference: docs/span_module.md.
"""

from typing import Dict, List, NoReturn, Set, Tuple

from aipass.canary.apps.handlers.json import json_handler

SECONDS_PER_UNIT: Dict[str, int] = {"d": 86400, "h": 3600, "m": 60, "s": 1}

UNIT_LIST = "d, h, m, s"

MAX_DAYS = 366

MAX_SECONDS = MAX_DAYS * SECONDS_PER_UNIT["d"]

# Not str.isdigit(): int() accepts non-ASCII digits (int("٣") is 3), a number nobody typed.
DIGITS = frozenset("0123456789")


class DurationInvalid(Exception):
    """The text is not a duration this parser will turn into a number of seconds."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it."""
    # Every refusal goes through here: a reason that only reached a terminal is lost.
    json_handler.log_operation("duration_refused", {"reason": reason})
    raise DurationInvalid(reason)


def _is_plain_integer(number: str) -> bool:
    """Return whether the text is a plain non-negative ASCII integer."""
    return bool(number) and all(char in DIGITS for char in number)


def _split_number_unit_pairs(compact: str) -> List[Tuple[str, str]]:
    """Split whitespace-free text into (number, unit) pairs without judging them."""
    # Split by character class, not validity: ``1.5h`` must be refused as a bad number, not unit ``.``.
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
    """Refuse one part, or record its unit as used."""
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
    """Turn a written duration into a total number of seconds."""
    compact = "".join(text.split())
    if not compact:
        _refuse("no duration text (write one like: 2d 4h, 90m, 1h30m)")

    seen: Set[str] = set()
    total = 0

    for number, unit in _split_number_unit_pairs(compact):
        _validate(number, unit, seen)
        total += int(number) * SECONDS_PER_UNIT[unit]

    if total > MAX_SECONDS:
        _refuse(f"total is over the {MAX_DAYS}-day limit ({total} seconds, limit {MAX_SECONDS})")

    return total
