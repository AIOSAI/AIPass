# =================== AIPass ====================
# Name: store.py
# Description: Key/value store on disk - one key, one tab, one value per line; owns every kv refusal
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-10-17
# =============================================

"""The store behind ``drone @canary kv``.

Reference: docs/kv_module.md.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, NoReturn, Optional, Tuple

from aipass.canary.apps.handlers.json import json_handler

SEPARATOR = "\t"

LINE_END = "\n"

# The carriage return is here because the reader strips a trailing one: a stored one would not round-trip.
FORBIDDEN = ((SEPARATOR, "a tab"), (LINE_END, "a newline"), ("\r", "a carriage return"))

PAIR = Tuple[str, str]


class StoreInvalid(Exception):
    """The argument, the key or the store file is not something kv will work with."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it."""
    json_handler.log_operation("kv_refused", {"reason": reason})
    raise StoreInvalid(reason)


def check_key(key: str) -> None:
    """Refuse a key the store cannot hold.

    Callers check before opening the file, so a bad key is refused as unstorable, not as "no such key".
    """
    if not key:
        _refuse("KEY is empty (a key is the name a value is filed under)")
    _check_separators("KEY", key)


def check_value(value: str) -> None:
    """Refuse a value the store cannot hold; an empty value is allowed."""
    _check_separators("VALUE", value)


def _check_separators(what: str, text: str) -> None:
    """Refuse text carrying a character that would break the line format."""
    for char, name in FORBIDDEN:
        if char in text:
            _refuse(f"{what} contains {name}, which separates the store's lines and fields")


def _parse_line(path: Path, number: int, line: str) -> PAIR:
    """Split one store line into its pair, or refuse it by line number."""
    fields = line.split(SEPARATOR)
    if len(fields) != 2:
        found = "no tab" if len(fields) == 1 else f"{len(fields) - 1} tabs"
        _refuse(f"{path}: line {number} is not a key, a tab and a value ({found})")

    key, value = fields
    if not key:
        _refuse(f"{path}: line {number} has an empty key")
    return key, value


def read_pairs(path: Path) -> List[PAIR]:
    """Parse the whole store, in file order; a store not on disk is refused, not read as empty."""
    if not path.exists():
        _refuse(f"store not found: {path}")

    return _parse(path)


def _parse(path: Path) -> List[PAIR]:
    """Read and parse a store that is known to be on disk."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _refuse(f"cannot read {path} ({exc.strerror or exc})")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse(f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start})")

    lines = content.split(LINE_END)
    # Only the empty tail after the final terminator is dropped; an unterminated last line is still a pair.
    if lines and lines[-1] == "":
        lines.pop()

    pairs: List[PAIR] = []
    seen: Dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        key, value = _parse_line(path, number, line[:-1] if line.endswith("\r") else line)
        if key in seen:
            _refuse(f"{path}: line {number} repeats the key '{key}' (first on line {seen[key]})")

        seen[key] = number
        pairs.append((key, value))

    return pairs


def _default_mode() -> int:
    """Return the mode a newly created file gets under this process's umask.

    Setting and restoring the umask is safe only because this CLI process is single-threaded.
    """
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def write_pairs(path: Path, pairs: List[PAIR]) -> None:
    """Replace the store with these pairs, in one step.

    The temporary file sits in the store's own directory: a move across filesystems is an interruptible copy.
    """
    directory = path.parent
    if not directory.exists():
        _refuse(f"cannot write {path}: the directory {directory} is not there")

    payload = "".join(f"{key}{SEPARATOR}{value}{LINE_END}" for key, value in pairs)
    mode = path.stat().st_mode & 0o777 if path.exists() else _default_mode()

    temp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline=LINE_END, dir=directory, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(payload)

        # tempfile creates 0600; without this a store goes private on its next write.
        os.chmod(temp_name, mode)

        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        _refuse(f"cannot write {path} ({exc.strerror or exc})")


def set_value(path: Path, key: str, value: str) -> None:
    """Store one pair, replacing a key that is already there without moving it."""
    check_key(key)
    check_value(value)

    pairs = _parse(path) if path.exists() else []
    for index, (existing, _) in enumerate(pairs):
        if existing == key:
            pairs[index] = (key, value)
            break
    else:
        pairs.append((key, value))

    write_pairs(path, pairs)


def get_value(path: Path, key: str) -> str:
    """Return the value filed under one key."""
    check_key(key)

    for existing, value in read_pairs(path):
        if existing == key:
            return value

    return _refuse(f"no such key: '{key}' in {path}")


def delete_key(path: Path, key: str) -> None:
    """Remove the pair filed under one key."""
    check_key(key)

    pairs = read_pairs(path)
    kept = [pair for pair in pairs if pair[0] != key]
    if len(kept) == len(pairs):
        _refuse(f"no such key: '{key}' in {path}")

    write_pairs(path, kept)


def list_pairs(path: Path) -> List[PAIR]:
    """Return every pair, sorted by key by code point (no locale or case folding)."""
    return sorted(read_pairs(path), key=lambda pair: pair[0])
