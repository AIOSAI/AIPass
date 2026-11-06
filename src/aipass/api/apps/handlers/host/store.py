# =================== AIPass ====================
# Name: store.py
# Description: Host API Store Handler — the host's tokens, pairings and config as owner-only JSON files
# Version: 1.0.0
# Created: 2026-11-06
# Modified: 2026-11-06
# =============================================

"""Host API Store Handler: 0600 files, never the login keyring, so a locked keyring cannot stop the host."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store

TOKENS = "tokens"
PAIRINGS = "pairings"
CONFIG = "config"

# Tokens first: an import with no tokens anywhere refuses before writing anything.
ENTRIES = (TOKENS, PAIRINGS, CONFIG)

IMPORTED = "imported"
KEPT = "kept"
ABSENT = "absent"


class StoreUnavailable(secrets_store.SecretsUnavailable):
    """A host store file could not be read or written. A SecretsUnavailable, so every existing refusal path holds."""


def store_dir() -> Path:
    """The host store's directory, beside the token lock and the receipts."""
    # Read per call: SECRETS_BASE is patched by tests and must never be captured at import.
    return secrets_store.SECRETS_BASE / secrets_store.HOST_STORE_DIR


def store_path(name: str) -> Path:
    """The file one host document lives in."""
    return store_dir() / f"{name}.json"


def read(name: str) -> Optional[Any]:
    """One host document, or None when its file does not exist. Never reads the keyring."""
    path = store_path(name)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise StoreUnavailable(f"The host store file {path.name} cannot be read ({type(e).__name__})") from e

    try:
        return json.loads(text)
    except ValueError as e:
        raise StoreUnavailable(f"The host store file {path.name} is not JSON ({type(e).__name__})") from e


def write(name: str, document: Any) -> Path:
    """Replace one host document in a single rename; the file is 0600 whatever it was before."""
    path = store_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(path.parent, 0o700)
        _replace(path, document)
    except OSError as e:
        raise StoreUnavailable(f"The host store file {path.name} cannot be written ({type(e).__name__})") from e
    return path


def _replace(path: Path, document: Any) -> None:
    """Stage beside the destination, then rename over it."""
    # mkstemp creates the staged file 0600, and the rename carries that mode onto the store file.
    descriptor, staged = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
        os.replace(staged, path)
    # BaseException: an interrupt mid-write leaves the same orphan.
    except BaseException:
        _discard(staged)
        raise


def _discard(staged: str) -> None:
    """Remove a staged file that never made it into place."""
    try:
        os.unlink(staged)
    except OSError as e:
        # Logged, not raised: raising would bury the write's own failure, already travelling.
        logger.warning("[host_api] a staged store file could not be removed: %s", type(e).__name__)


def import_from_keyring() -> Dict[str, str]:
    """Copy each host document from the keyring to its file once; an existing file is kept, never overwritten."""
    outcome: Dict[str, str] = {}
    for name in ENTRIES:
        if store_path(name).exists():
            outcome[name] = KEPT
            continue

        stored = secrets_store.get_secret(secrets_store.HOST_STORE_DIR, name, as_json=True)
        if stored is None:
            if name == TOKENS:
                raise StoreUnavailable(
                    "No token store in the keyring or on disk: nothing to import. "
                    "Mint the first token with `drone @api host-api issue-token`"
                )
            outcome[name] = ABSENT
            continue

        write(name, stored)
        outcome[name] = IMPORTED

    json_handler.log_operation("host_api_store_imported", outcome)
    return outcome
