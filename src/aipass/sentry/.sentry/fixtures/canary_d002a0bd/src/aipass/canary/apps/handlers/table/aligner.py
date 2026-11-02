# =================== AIPass ====================
# Name: aligner.py
# Description: Text table reader - rows of fields to aligned lines, or a named refusal
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Read a plain-text table and line its columns up.

The file is UTF-8 text. Every non-blank line is two or more fields separated by
one or more spaces - ``alice 12 red``. Leading and trailing whitespace on a line
is ignored and blank lines are skipped. The first non-blank line sets how many
columns the file has; every later row must have the same number.

Rendering pads each field to the widest value in its column with spaces on the
right, joins the columns with exactly two spaces, and leaves the LAST column
unpadded, so no line can end in whitespace. Rows keep the order they were
written in - this is a formatter, not a sorter.

Rulings made where the dispatched contract was silent, each one consistent with
what the rest of this branch already does:

* **A tab separates fields, like a space does.** The contract says "one or more
  spaces", and a tab is not a space - but a text table is written with either,
  and ``leaderboard/reader.py`` already reads ``alice\t12`` the same as
  ``alice 12``. Splitting on runs of spaces and tabs also means no field can
  contain a tab, which matters: a tab is one character to ``len()`` and a jump
  to the next tab stop on a terminal, so a field holding one would be padded to
  a width it does not print at.
* **Every other whitespace character is data.** A no-break space, an en quad:
  ``str.split()`` breaks a row on both of them - ``"a b".split()`` is two
  fields - which turns a value somebody deliberately typed as one into two.
  Only the two characters a table is actually written with separate columns
  here. A vertical tab or a form feed never reaches this decision at all:
  ``str.splitlines()`` treats them as line boundaries, so they split the FILE
  before anything splits a row.
* **Width is counted in code points, not terminal cells.** ``zoë`` is three
  characters wide, and a double-width CJK character counts as one. Counting
  cells means either a dependency or a guess about the reader's terminal, and a
  guess is the thing this branch exists to refuse.
* **A row with fewer than two fields is named as that, never as a count
  mismatch.** The check runs before the column-count comparison, so a one-field
  line halfway down a file is refused by what is actually wrong with it rather
  than by the first check that happens to notice.

Unlike ``leaderboard/reader.py``, a file with nothing in it is a refusal here
rather than an empty answer: the contract lists "a file with no non-blank lines
at all" among the refusals. An empty ranking is a result, an empty table is not.
"""

import re
from pathlib import Path
from typing import List, NoReturn

from aipass.canary.apps.handlers.json import json_handler

SEPARATOR = re.compile(r"[ \t]+")

MIN_FIELDS = 2

COLUMN_GAP = "  "


class TableInvalid(Exception):
    """The argument or the file is not something this reader will align."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it.

    Every refusal in this handler goes through here, so the trail carries the
    ones nobody was watching: a row with one field halfway down a long file is
    the interesting half of this command, and a reason that only ever reached a
    terminal is one nobody can count afterwards.

    Args:
        reason: What is wrong, named part first.

    Raises:
        TableInvalid: Always.
    """
    json_handler.log_operation("table_refused", {"reason": reason})
    raise TableInvalid(reason)


def _split_row(path: Path, number: int, line: str) -> List[str]:
    """Split one non-blank line into its fields, or refuse it by line number.

    Args:
        path: The file being read, named in the refusal.
        number: 1-based line number, named in the refusal.
        line: The line without its terminator, not yet stripped.

    Returns:
        The fields, in the order they were written.

    Raises:
        TableInvalid: The line holds fewer than two fields.
    """
    fields = SEPARATOR.split(line.strip())
    if len(fields) < MIN_FIELDS:
        _refuse(f"{path}: line {number} has fewer than two fields ('{line.strip()}')")

    return fields


def read_rows(path: Path) -> List[List[str]]:
    """Read every non-blank line as a row of fields.

    Args:
        path: The table file. A missing file is refused, never read as an empty
            one - "no such file" and "an empty table" are different answers and
            neither of them is a result here.

    Returns:
        One list of fields per non-blank line, in file order.

    Raises:
        TableInvalid: The file does not exist, cannot be read, is not valid
            UTF-8, holds a row with fewer than two fields, holds a row whose
            field count differs from the first row's, or holds no non-blank
            lines at all.
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

    rows: List[List[str]] = []
    columns = 0
    for number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue

        fields = _split_row(path, number, line)
        if not rows:
            columns = len(fields)
        elif len(fields) != columns:
            _refuse(f"{path}: line {number} has {len(fields)} fields, the first row set {columns}")

        rows.append(fields)

    if not rows:
        _refuse(f"{path} has no non-blank lines")

    return rows


def widths(rows: List[List[str]]) -> List[int]:
    """Measure each column against its widest value.

    Args:
        rows: The rows, every one of them the same length.

    Returns:
        One width per column, counted in code points.
    """
    return [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]


def render(rows: List[List[str]]) -> List[str]:
    """Lay the rows out as aligned lines.

    Args:
        rows: The rows, in the order they are to be printed.

    Returns:
        One line per row: every column left-aligned to its width, columns two
        spaces apart, and no trailing whitespace - the last column is never
        padded, so there is none to strip.
    """
    column_widths = widths(rows)

    lines: List[str] = []
    for row in rows:
        cells = [field.ljust(column_widths[index]) for index, field in enumerate(row[:-1])]
        cells.append(row[-1])
        lines.append(COLUMN_GAP.join(cells))

    return lines
