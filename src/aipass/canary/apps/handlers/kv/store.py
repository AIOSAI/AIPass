# =================== AIPass ====================
# Name: store.py
# Description: Key/value store on disk - one key, one tab, one value per line; owns every kv refusal
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""The store behind ``drone @canary kv``.

Format: UTF-8 text, one pair per line, each line a key, a single tab, and a
value, terminated by ``\\n``. Keys are unique. An existing file with no bytes in
it is an empty store.

A read parses the whole file before any verb answers, and a write is prepared in
full and then swapped in with ``os.replace``, so a store is never left half
rewritten: the file a caller sees is either the old one or the new one.

Rulings made where the dispatched contract was silent, each one consistent with
what the rest of this branch already does:

* **A store that is not on disk is refused, not treated as empty.** The contract
  refuses "FILE missing", and ``table/aligner.py`` already refuses a missing
  table rather than reading it as an empty one - "no such file" and "an empty
  store" are different answers, and only one of them is a result. ``set`` is the
  single exception, because the contract creates the file there. The cost is
  that ``list`` on a typo'd path refuses instead of printing nothing, which is
  the point: a silent empty answer is the failure species this branch exists to
  catch.
* **A carriage return is refused in a KEY and in a VALUE, and a trailing one is
  stripped when reading.** The contract names the tab and the newline. A store
  written on Windows ends its lines ``\\r\\n``, so a reader that keeps the
  carriage return hands back every value with a stray byte on the end; a reader
  that strips it silently changes a value that genuinely ended in one. Refusing
  the character on the way in means nothing this command writes can be altered
  by the strip on the way out, and a foreign CRLF store still reads correctly.
  The cost is stated rather than hidden: a value holding a carriage return
  cannot be stored here at all.
* **Only ``\\n`` ends a line.** ``str.splitlines()`` also breaks on a vertical
  tab, a form feed and ``\\u2028``; those are ordinary characters inside a value
  somebody deliberately stored, and splitting on them would turn one pair into
  two unreadable lines. This reads with ``split("\\n")``.
* **A duplicate key in the file is refused, naming both lines.** Last-wins or
  first-wins would silently drop a pair somebody else wrote. This store never
  writes a duplicate, so one can only arrive from a foreign write, and that is
  exactly when a caller needs to be told.
* **An empty VALUE is stored; an empty KEY is refused.** ``k\\t`` is still a
  key, a tab and a value, and it round-trips. The contract refuses the empty key
  by name, so that one stays refused - and a line beginning with a tab would put
  the store's only structure in the first byte.
* **A write failure is a refusal, never a silent no-op.** A missing parent
  directory and an unwritable file are both named on stderr with exit 2.
* **A store this command creates gets the mode the umask would have given it.**
  The atomic write goes through a temporary file, and those are created 0600;
  without the correction ``kv`` would quietly make a more private file than the
  caller's own shell does. Measured here 2026-09-20: the first store written
  landed 0600 where a redirect gives 0644.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, NoReturn, Optional, Tuple

from aipass.canary.apps.handlers.json import json_handler

SEPARATOR = "\t"

LINE_END = "\n"

# What a key or a value may not contain: the two characters that carry the
# store's structure, plus the one that would be stripped back off on the way in.
FORBIDDEN = ((SEPARATOR, "a tab"), (LINE_END, "a newline"), ("\r", "a carriage return"))

PAIR = Tuple[str, str]


class StoreInvalid(Exception):
    """The argument, the key or the store file is not something kv will work with."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _refuse(reason: str) -> NoReturn:
    """Record the refusal on the operation trail, then raise it.

    Every refusal in this handler goes through here, so the trail carries the
    ones nobody was watching - a duplicate key on line 400 of a store written by
    something else is the interesting half of this command.

    Args:
        reason: What is wrong, named part first.

    Raises:
        StoreInvalid: Always.
    """
    json_handler.log_operation("kv_refused", {"reason": reason})
    raise StoreInvalid(reason)


def check_key(key: str) -> None:
    """Refuse a key the store cannot hold.

    Checked before the file is opened, so ``get`` with a key holding a tab is
    refused by what is actually wrong with it rather than by "no such key" -
    the store could not be holding it in the first place.

    Args:
        key: The key as the caller typed it.

    Raises:
        StoreInvalid: The key is empty or carries a separator.
    """
    if not key:
        _refuse("KEY is empty (a key is the name a value is filed under)")
    _check_separators("KEY", key)


def check_value(value: str) -> None:
    """Refuse a value the store cannot hold.

    An empty value is allowed: 'k<tab>' is still a line of this format, and it
    reads back as the empty string it was written as.

    Args:
        value: The value as the caller typed it.

    Raises:
        StoreInvalid: The value carries a separator.
    """
    _check_separators("VALUE", value)


def _check_separators(what: str, text: str) -> None:
    """Refuse text carrying a character that would break the line format.

    Args:
        what: 'KEY' or 'VALUE', named first in the refusal.
        text: The text to check.

    Raises:
        StoreInvalid: The text holds a tab, a newline or a carriage return.
    """
    for char, name in FORBIDDEN:
        if char in text:
            _refuse(f"{what} contains {name}, which separates the store's lines and fields")


def _parse_line(path: Path, number: int, line: str) -> PAIR:
    """Split one store line into its pair, or refuse it by line number.

    Args:
        path: The store file, named in the refusal.
        number: 1-based line number, named in the refusal.
        line: The line, its terminator and any trailing carriage return removed.

    Returns:
        The key and the value.

    Raises:
        StoreInvalid: The line is not exactly a key, a tab and a value.
    """
    fields = line.split(SEPARATOR)
    if len(fields) != 2:
        found = "no tab" if len(fields) == 1 else f"{len(fields) - 1} tabs"
        _refuse(f"{path}: line {number} is not a key, a tab and a value ({found})")

    key, value = fields
    if not key:
        _refuse(f"{path}: line {number} has an empty key")
    return key, value


def read_pairs(path: Path) -> List[PAIR]:
    """Parse the whole store, in file order.

    Args:
        path: The store file. It must be there: a store that does not exist is
            refused rather than read as an empty one.

    Returns:
        The pairs in the order the file holds them.

    Raises:
        StoreInvalid: The store is not there, cannot be read, is not valid
            UTF-8, holds a line that is not a key/tab/value, or repeats a key.
    """
    if not path.exists():
        _refuse(f"store not found: {path}")

    return _parse(path)


def _parse(path: Path) -> List[PAIR]:
    """Read and parse a store that is known to be on disk.

    Args:
        path: The store file.

    Returns:
        The pairs in file order; an empty list for a file with no bytes.

    Raises:
        StoreInvalid: The file cannot be read, is not valid UTF-8, holds a line
            that is not a key/tab/value, or repeats a key.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _refuse(f"cannot read {path} ({exc.strerror or exc})")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse(f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start})")

    lines = content.split(LINE_END)
    # One empty tail from the final terminator is the format, not a blank line.
    # An unterminated last line keeps its content, so a store written without a
    # final newline is read whole rather than half.
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

    ``tempfile`` creates its file 0600, so a store built through one would be
    private to its owner - measurably unlike the 0644 a caller's own ``touch``
    or shell redirect produces. Reading the umask means setting it and putting
    it straight back; this is a single-threaded CLI process, so the window is
    its own.

    Returns:
        The permission bits to give a store this call creates.
    """
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def write_pairs(path: Path, pairs: List[PAIR]) -> None:
    """Replace the store with these pairs, in one step.

    The new content is written to a temporary file in the same directory and
    then moved over the old one, so a caller reading the store during a write
    sees one whole version or the other. Same directory on purpose: a move
    across filesystems is a copy, and a copy is interruptible.

    Args:
        path: The store file. Created if it is not there.
        pairs: The pairs to write, in the order they are to be stored.

    Raises:
        StoreInvalid: The parent directory is missing, or the store cannot be
            written.
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

        # The temporary file is created 0600. An existing store keeps the mode
        # it already had, so one the caller made readable does not silently go
        # private on its next write; a new one gets what the umask would have
        # given it, so kv's file is not stricter than the caller's own.
        os.chmod(temp_name, mode)

        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        _refuse(f"cannot write {path} ({exc.strerror or exc})")


def set_value(path: Path, key: str, value: str) -> None:
    """Store one pair, replacing a key that is already there without moving it.

    Args:
        path: The store file. Created by this call if it is not there.
        key: The key to file the value under.
        value: The value, stored verbatim.

    Raises:
        StoreInvalid: The key or the value cannot be stored, the existing store
            will not parse, or the file cannot be written.
    """
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
    """Return the value filed under one key.

    Args:
        path: The store file.
        key: The key to look up.

    Returns:
        The value, exactly as it was stored.

    Raises:
        StoreInvalid: The key cannot be stored, the store will not parse, or no
            pair is filed under that key.
    """
    check_key(key)

    for existing, value in read_pairs(path):
        if existing == key:
            return value

    return _refuse(f"no such key: '{key}' in {path}")


def delete_key(path: Path, key: str) -> None:
    """Remove the pair filed under one key.

    Args:
        path: The store file.
        key: The key to remove.

    Raises:
        StoreInvalid: The key cannot be stored, the store will not parse, no
            pair is filed under that key, or the file cannot be written.
    """
    check_key(key)

    pairs = read_pairs(path)
    kept = [pair for pair in pairs if pair[0] != key]
    if len(kept) == len(pairs):
        _refuse(f"no such key: '{key}' in {path}")

    write_pairs(path, kept)


def list_pairs(path: Path) -> List[PAIR]:
    """Return every pair, sorted by key.

    Args:
        path: The store file.

    Returns:
        The pairs ordered by key, ascending by code point - the order
        ``sorted()`` gives, so 'Z' comes before 'a' and no locale or case
        folding is involved.

    Raises:
        StoreInvalid: The store is not there, or will not parse.
    """
    return sorted(read_pairs(path), key=lambda pair: pair[0])
