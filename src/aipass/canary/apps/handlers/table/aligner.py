# =================== AIPass ====================
# Name: aligner.py
# Description: Text table reader - rows of fields to aligned lines, or a named refusal
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-10-17
# =============================================

"""Read a plain-text table and line its columns up.

Reference: docs/align_module.md.
"""

import re
from pathlib import Path
from typing import List, NoReturn

from aipass.canary.apps.handlers.json import json_handler

# Not str.split(): that also splits on a no-break space, which is data inside a field.
SEPARATOR = re.compile(r"[ \t]+")

MIN_FIELDS = 2

COLUMN_GAP = "  "


class TableInvalid(Exception):
    """The argument or the file is not something this reader will align."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it."""
    json_handler.log_operation("table_refused", {"reason": reason})
    raise TableInvalid(reason)


def _split_row(path: Path, number: int, line: str) -> List[str]:
    """Split one non-blank line into its fields, or refuse it by line number."""
    fields = SEPARATOR.split(line.strip())
    if len(fields) < MIN_FIELDS:
        _refuse(f"{path}: line {number} has fewer than two fields ('{line.strip()}')")

    return fields


def read_rows(path: Path) -> List[List[str]]:
    """Read every non-blank line as a row of fields; a missing or empty table is refused."""
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
    """Measure each column against its widest value, in code points, not terminal cells."""
    return [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]


def render(rows: List[List[str]]) -> List[str]:
    """Lay the rows out as aligned lines, the last column unpadded so no line ends in whitespace."""
    column_widths = widths(rows)

    lines: List[str] = []
    for row in rows:
        cells = [field.ljust(column_widths[index]) for index, field in enumerate(row[:-1])]
        cells.append(row[-1])
        lines.append(COLUMN_GAP.join(cells))

    return lines
