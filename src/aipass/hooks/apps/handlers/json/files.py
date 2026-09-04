# =================== AIPass ====================
# Name: files.py
# Description: Atomic read/write for hooks arbitrary-path JSON documents
# Version: 1.1.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Arbitrary-path JSON documents hooks owns outside the branch json directory.

The fleet's one json service (``aipass.prax.json_handler``, DPLAN-0325) covers
the nine standard names, bound into this branch by
``apps/handlers/json/json_handler.py``. Two names this branch used are NOT in
that set and never enter the shim: the trust registry
(``~/.aipass/trusted_projects.json``) and a project's ``.aipass/alerts.json``
live outside ``hooks_json/`` and are addressed by path, not by module and type.

They keep their own module because they keep their own contract. The service's
``read_json`` answers ``None`` for a document that is missing OR unparseable,
and its ``write_json`` answers ``False`` for a write that did not land. Both
failures are silent by design there and unsafe here: a trust registry that
reads as an empty dict revokes every enrolled project, and a dismissal that
reports success while the alerts file is unchanged tells a caller a lie. So
these two raise, and both call sites already catch — ``read_json_file`` raises
``JSONDecodeError``/``OSError``, ``write_json_file`` raises ``OSError``.

The write is atomic for the same reason it is atomic in the service: a torn
trust registry is not a lost log entry, it is every hook in the project going
dark. The on-disk form matches the fleet service exactly — ``indent=2``,
``ensure_ascii=False``. It used to escape non-ASCII, and that was this branch's
historical form, but the trust registry has had a second writer since @aipass
re-pointed to its own shim (DPLAN-0325): one document written two ways would
flip its escaping depending on which branch touched it last, so the service's
choice is the one with standing.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

# os.replace on Windows raises PermissionError while ANY reader holds the
# target open (no FILE_SHARE_DELETE on Python's open). Readers hold handles
# for microseconds, so a short bounded retry converges; after the bound the
# error raises honestly. POSIX never takes this path for open files, so a
# genuine permission problem still surfaces — just ~200ms later.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """
    os.replace that tolerates Windows sharing violations, bounded.

    Args:
        source: Staged file to move into place.
        destination: The live document being replaced.

    Raises:
        PermissionError: Still blocked after every attempt.
        OSError: Any non-sharing failure, immediately.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write a JSON document so a reader sees the old one or the new one, never a torn one.

    Args:
        target_path: The document to replace.
        data: What to write.

    Raises:
        OSError: The staged file could not be written or moved into place.

    Note:
        write_text opens the target with "w", which truncates it BEFORE the new
        content lands — every concurrent reader in that window gets an empty
        file. Measured on the handler this module was carved out of: 587 of 1023
        concurrent reads unusable (57.4%), three runs 56.7-57.5%. The staged
        file is created in the TARGET's directory so os.replace stays a
        same-filesystem rename, which is atomic on POSIX and on Windows. On
        Windows it can still raise PermissionError while a reader holds the
        target open, so the move goes through _replace_with_retry — bounded,
        then raises (proven by the Windows CI hang of 2026-08-18).
    """
    descriptor, temporary = tempfile.mkstemp(dir=str(target_path.parent), prefix=target_path.stem, suffix=".tmp")
    succeeded = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        _replace_with_retry(temporary, str(target_path))
        succeeded = True
    finally:
        if not succeeded and Path(temporary).exists():
            # A failed write must not leave a partial document beside the real one
            os.unlink(temporary)


def read_json_file(path: Path) -> Any:
    """Read and parse a JSON file at an arbitrary path.

    Args:
        path: The document to read.

    Returns:
        The parsed document.

    Raises:
        OSError: The file could not be read.
        json.JSONDecodeError: The file is not valid JSON.

    Note:
        Raises where the fleet service answers None: an unreadable trust
        registry must never be mistaken for an empty one.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: Any) -> None:
    """Write data as JSON to an arbitrary path, atomically.

    Args:
        path: The document to write.
        data: The payload.

    Raises:
        OSError: The document could not be written.

    Note:
        Writes the TRUST REGISTRY (trust_registry.py) and a project's persistent
        alerts file (alert_dismiss.py). A torn registry read is not a lost log
        entry: it is every hook in the project going dark.
    """
    _atomic_write_json(path, data)
