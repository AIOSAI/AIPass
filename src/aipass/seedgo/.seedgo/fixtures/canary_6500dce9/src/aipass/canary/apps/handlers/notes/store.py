# =================== AIPass ====================
# Name: store.py
# Description: Append-only JSON Lines note store - refuses a store it cannot parse
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-09-12
# =============================================

"""Append-only note store behind ``drone @canary note``.

Format: UTF-8 JSON Lines. Each record is one JSON object carrying exactly the
string keys ``text`` and ``timestamp``, terminated by ``\\n``. An empty or
missing file is an empty store.

The store is never rewritten. ``append_note`` parses every existing line first
and only then opens the file in append mode, so a store that will not parse
raises ``StoreCorrupt`` before a single byte is written. No code path here
truncates, resets or replaces the file: losing the notes to one bad read is
the failure this handler exists to prevent.

Deliberately NOT the fleet json service: its ``ensure_json_exists`` regenerates
an unreadable document from the in-code default, and ``load_json`` runs that
before every read - exactly the reset this store must never perform.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from aipass.canary.apps.handlers.json import json_handler

# store.py -> notes/ -> handlers/ -> apps/ -> canary/. __file__ is already
# absolute, so no resolve(): on Windows that reads the cwd and dies with it.
BRANCH_ROOT = Path(__file__).parents[3]

# docs.local/ is ignored by the repo-root .gitignore, so git never tracks it.
STORE_PATH = BRANCH_ROOT / "docs.local" / "notes.jsonl"

RECORD_KEYS = ("text", "timestamp")


class StoreCorrupt(Exception):
    """The store file exists but does not parse as the format this handler writes."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def _parse_record(path: Path, number: int, line: str) -> Dict[str, str]:
    """Parse one store line into a record, or refuse it by line number.

    Args:
        path: The store file, named in the refusal.
        number: 1-based line number, named in the refusal.
        line: The line without its terminator.

    Returns:
        The record.

    Raises:
        StoreCorrupt: The line is not JSON, or not a text/timestamp record.
    """
    try:
        record = json.loads(line)
    except json.JSONDecodeError as exc:
        raise StoreCorrupt(path, f"line {number} is not JSON ({exc.msg})") from exc

    if not isinstance(record, dict) or sorted(record) != sorted(RECORD_KEYS):
        raise StoreCorrupt(path, f"line {number} is not a note record (expected exactly: text, timestamp)")
    if not all(isinstance(record[key], str) for key in RECORD_KEYS):
        raise StoreCorrupt(path, f"line {number} has a text or timestamp that is not a string")
    return record


def read_notes(path: Path) -> List[Dict[str, str]]:
    """Parse every record in the store, oldest first.

    Args:
        path: The store file. A missing file is an empty store, and is not created.

    Returns:
        The records in file order.

    Raises:
        StoreCorrupt: The file exists but is not this handler's format - not
            UTF-8, a line that is not a record, or a final record with no
            terminator (a torn write; appending after it would glue two
            records into one bad line).
        OSError: The path exists but cannot be read as a file.
    """
    if not path.exists():
        return []

    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreCorrupt(path, f"not UTF-8 ({exc.reason} at byte {exc.start})") from exc

    if not content:
        return []
    if not content.endswith("\n"):
        raise StoreCorrupt(path, "last record has no line terminator (torn or foreign write)")

    return [_parse_record(path, number, line) for number, line in enumerate(content[:-1].split("\n"), start=1)]


def append_note(path: Path, text: str) -> Dict[str, str]:
    """Append one record, after proving the existing store parses.

    Args:
        path: The store file. Created, with its directory, on first add.
        text: The note text, stored verbatim.

    Returns:
        The record written.

    Raises:
        StoreCorrupt: The existing store will not parse. Raised before the file
            is opened for writing, so its bytes are untouched.
        OSError: The store cannot be read, or the directory or file cannot be written.
    """
    existing = read_notes(path)

    record = {"text": text, "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    json_handler.log_operation("note_appended", {"index": len(existing) + 1})
    return record
