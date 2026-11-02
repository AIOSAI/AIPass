# =================== AIPass ====================
# Name: reader.py
# Description: Leaderboard file reader - "name count" lines to ranked totals, or a named refusal
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Read a plain-text leaderboard and rank it.

The file is UTF-8 text. Every non-blank line is a name, whitespace, and an
integer count - ``alice 12``. Leading and trailing whitespace is ignored and
blank lines are skipped. A name may appear on more than one line; its counts
are added together before anything is ranked, so the file is a tally, not a
table of final scores.

Ranking is by count descending, and ties are broken by name ascending, so the
same file always produces the same order. Without the tie-break the order would
be dictionary insertion order - stable within one run, and therefore a result
that looks deterministic while being a property of how the file happened to be
written.

Deliberately strict where a friendly reader would guess:

* ``alice 12 extra`` is refused rather than read as a name and a count with
  something ignored on the end - a reader that silently drops a field cannot be
  measured from outside.
* A negative count is refused by its own name, not folded into "not an integer":
  ``-3`` IS an integer, and the reason has to point at what is actually wrong.
* ``+3`` is not an integer count here. A plain integer is an optional ``-`` and
  ASCII digits; nothing else is inferred.
* Non-ASCII digits are refused even though ``int()`` accepts them: ``int("٣")``
  is 3, so an ASCII-only check is the only thing between a ranking and a number
  nobody typed.

Leading zeros ARE accepted (``007``): a plain integer is what is asked for, and
``007`` is one. ``-0`` is accepted for the same reason - it equals zero, and a
count of zero is not a negative count.
"""

from pathlib import Path
from typing import Dict, List, NoReturn, Tuple

from aipass.canary.apps.handlers.json import json_handler

DIGITS = frozenset("0123456789")

FIELDS_PER_ROW = 2


class LeaderboardInvalid(Exception):
    """The argument or the file is not something this reader will rank."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it.

    Every refusal in this handler goes through here, so the trail carries the
    ones nobody was watching: a malformed row halfway down a long file is the
    interesting half of this command, and a reason that only ever reached a
    terminal is lost.

    Args:
        reason: What is wrong, named part first.

    Raises:
        LeaderboardInvalid: Always.
    """
    json_handler.log_operation("leaderboard_refused", {"reason": reason})
    raise LeaderboardInvalid(reason)


def _is_plain_digits(number: str) -> bool:
    """Return whether the text is one or more ASCII digits and nothing else.

    Args:
        number: The candidate number, sign already stripped by the caller.

    Returns:
        True for one or more ASCII digits and nothing else.
    """
    return bool(number) and all(char in DIGITS for char in number)


def parse_n(text: str) -> int:
    """Turn the N argument into a positive integer, or refuse it.

    Args:
        text: The N argument exactly as it was typed.

    Returns:
        How many rows to print, always at least 1.

    Raises:
        LeaderboardInvalid: N is not a plain positive integer. Zero is refused
            with the rest: "the top 0" is an empty answer dressed as a result.
    """
    if not _is_plain_digits(text):
        _refuse(f"N must be a positive integer, got '{text}'")

    count = int(text)
    if count < 1:
        _refuse(f"N must be a positive integer, got '{text}'")

    return count


def _parse_row(path: Path, number: int, line: str) -> Tuple[str, int]:
    """Parse one non-blank line into a (name, count) pair, or refuse it by line number.

    Args:
        path: The file being read, named in the refusal.
        number: 1-based line number, named in the refusal.
        line: The line without its terminator, not yet stripped.

    Returns:
        The name and its count.

    Raises:
        LeaderboardInvalid: The line is not exactly a name and an integer
            count, or the count is negative.
    """
    fields = line.split()
    if len(fields) != FIELDS_PER_ROW:
        _refuse(f"{path}: line {number} is not exactly a name and an integer count ({len(fields)} fields)")

    name, written = fields
    digits = written[1:] if written.startswith("-") else written
    if not _is_plain_digits(digits):
        _refuse(f"{path}: line {number} has a count that is not an integer ('{written}')")

    count = int(written)
    if count < 0:
        _refuse(f"{path}: line {number} has a negative count ({written})")

    return name, count


def read_totals(path: Path) -> Dict[str, int]:
    """Read every row and add up each name's counts.

    Args:
        path: The leaderboard file. A missing file is refused, never treated as
            an empty one - "no such file" and "nobody scored" are different
            answers and only one of them is a result.

    Returns:
        Each name mapped to the sum of its counts, in first-seen order.

    Raises:
        LeaderboardInvalid: The file does not exist, cannot be read, is not
            valid UTF-8, or holds a row this reader will not read.
    """
    if not path.exists():
        _refuse(f"file not found: {path}")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        _refuse(f"cannot read {path} ({exc.strerror or exc})")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse(f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start})")

    totals: Dict[str, int] = {}
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        name, count = _parse_row(path, number, line)
        totals[name] = totals.get(name, 0) + count

    return totals


def rank(totals: Dict[str, int], wanted: int) -> List[Tuple[str, int]]:
    """Order the totals and take the head of the list.

    Args:
        totals: Each name mapped to its summed count.
        wanted: How many rows to return; fewer are returned when that is all
            there is, which is an answer rather than a refusal.

    Returns:
        Up to `wanted` (name, count) pairs, count descending and name ascending
        within a count.
    """
    ordered = sorted(totals.items(), key=lambda row: (-row[1], row[0]))
    return ordered[:wanted]
