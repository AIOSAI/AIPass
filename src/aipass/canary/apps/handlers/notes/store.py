# =================== AIPass ====================
# Name: store.py
# Description: Append-only JSON Lines note store - refuses a store it cannot parse
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-10-17
# =============================================

"""Append-only note store behind ``drone @canary note``.

Not the fleet json service: its ``load_json`` regenerates an unreadable file, a reset this store must never do.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from aipass.canary.apps.handlers.json import json_handler

# No resolve(): __file__ is already absolute, and on Windows resolve() reads the cwd and dies with it.
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
    """Parse one store line into a record, or refuse it by line number."""
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
    """Parse every record in the store, oldest first."""
    if not path.exists():
        return []

    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreCorrupt(path, f"not UTF-8 ({exc.reason} at byte {exc.start})") from exc

    if not content:
        return []
    # Appending after an unterminated record would glue two records into one bad line.
    if not content.endswith("\n"):
        raise StoreCorrupt(path, "last record has no line terminator (torn or foreign write)")

    return [_parse_record(path, number, line) for number, line in enumerate(content[:-1].split("\n"), start=1)]


def append_note(path: Path, text: str) -> Dict[str, str]:
    """Append one record, after proving the existing store parses."""
    existing = read_notes(path)

    record = {"text": text, "timestamp": datetime.now().astimezone().isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    json_handler.log_operation("note_appended", {"index": len(existing) + 1})
    return record
