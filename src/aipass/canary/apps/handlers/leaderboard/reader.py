# =================== AIPass ====================
# Name: reader.py
# Description: Leaderboard file reader - "name count" lines to ranked totals, or a named refusal
# Version: 1.1.0
# Created: 2026-09-19
# Modified: 2026-10-20
# =============================================

"""Read a plain-text leaderboard and rank it.

Reference: docs/top_module.md.
"""

import re
from pathlib import Path
from typing import Dict, List, NoReturn, Tuple

from aipass.canary.apps.handlers.json import json_handler

# ASCII only: int() also accepts other scripts' digits (int("\u0663") is 3), a number nobody typed.
DIGITS = frozenset("0123456789")

# Not str.split(): that also splits on a no-break space, which is data inside a name.
SEPARATOR = re.compile(r"[ \t]+")

FIELDS_PER_ROW = 2


class LeaderboardInvalid(Exception):
    """The argument or the file is not something this reader will rank."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it."""
    json_handler.log_operation("leaderboard_refused", {"reason": reason})
    raise LeaderboardInvalid(reason)


def _is_plain_digits(number: str) -> bool:
    """Return whether the text is one or more ASCII digits and nothing else."""
    return bool(number) and all(char in DIGITS for char in number)


def parse_n(text: str) -> int:
    """Turn the N argument into a positive integer, or refuse it."""
    if not _is_plain_digits(text):
        _refuse(f"N must be a positive integer, got '{text}'")

    count = int(text)
    if count < 1:
        _refuse(f"N must be a positive integer, got '{text}'")

    return count


def _parse_row(path: Path, number: int, line: str) -> Tuple[str, int]:
    """Parse one non-blank line into a (name, count) pair, or refuse it by line number."""
    fields = SEPARATOR.split(line.strip())
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
    """Read every row and add up each name's counts; a missing file is refused, not read as empty."""
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

    Ties break by name so the order never depends on how the file was written.
    """
    ordered = sorted(totals.items(), key=lambda row: (-row[1], row[0]))
    return ordered[:wanted]
