# =================== AIPass ====================
# Name: tokens.py
# Description: Host API Token Handler — bearer token issue, verify, revoke
# Version: 1.3.1
# Created: 2026-08-14
# Modified: 2026-10-24
# =============================================

"""
Host API Token Handler

Reference: docs/host_api.md (two auth layers, the store, last_used).
"""

import hashlib
import hmac
import os
import secrets as secrets_lib
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store

TOKEN_PROVIDER = "host_api"
TOKEN_SLUG = "tokens"

# Version 1 records (no minted_by) keep verifying, listing and revoking.
STORE_VERSION = 2

CALLER_ENV = "AIPASS_CALLER_BRANCH"
UNKNOWN_MINTER = "unknown"

# Coalesces last_used writes: a per-request store rewrite becomes a per-minute one.
LAST_USED_GRANULARITY_SECONDS = 60

# Breaking a stale lock risks a lost timestamp; honouring it forever means no revoke ever again.
LOCK_STALE_SECONDS = 30

LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.02

# AUDIT vocabulary, never response vocabulary: revoked and unknown answer identically,
# or a prober learns which guesses were once real.
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_UNKNOWN = "unknown"

SCOPES = ("read", "operate")

_SCOPE_IMPLIES: Dict[str, Tuple[str, ...]] = {
    "read": ("read",),
    "operate": ("read", "operate"),
}

_TOKEN_BYTES = 32


class TokenError(Exception):
    """A token operation was refused."""


def load_tokens() -> List[Dict[str, Any]]:
    """Read every token record from the store."""
    stored = secrets_store.get_secret(TOKEN_PROVIDER, TOKEN_SLUG, as_json=True)

    if stored is None:
        return []

    if not isinstance(stored, dict):
        logger.error("[host_api] token store is not a JSON object — treating as empty (all requests will be denied)")
        return []

    records = stored.get("tokens")
    if not isinstance(records, list):
        logger.error("[host_api] token store has no 'tokens' list — treating as empty (all requests will be denied)")
        return []

    return [record for record in records if isinstance(record, dict)]


def prepare_receipt_dir(target: Path) -> None:
    """Make sure a receipt's directory exists and is owner-only."""
    target.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "posix":
        os.chmod(target.parent, 0o700)


def receipt_path(label: str) -> Path:
    """Where a freshly minted token's raw value belongs, given its label."""
    wanted = (label or "").strip()
    if not wanted:
        raise TokenError("Token label is required — an unlabelled token cannot be revoked with confidence")

    if wanted != Path(wanted).name or wanted in (".", ".."):
        raise TokenError(
            f"Label {label!r} cannot name a receipt file — it looks like a path. "
            f"Use a plain label, or choose the file yourself with --out FILE"
        )

    if wanted.startswith("."):
        raise TokenError(
            f"Label {label!r} would write a hidden receipt — a secret nobody can see is a secret nobody rotates"
        )

    # Gate two, not redundant: post-resolve containment holds however the escape was spelled.
    provider_dir = secrets_store.SECRETS_BASE / TOKEN_PROVIDER
    candidate = (provider_dir / f"{wanted}.token").resolve()

    if candidate.parent != provider_dir.resolve():
        raise TokenError(f"Label {label!r} resolves outside the token store — refused")

    return candidate


def lock_path() -> Path:
    """Where the store's write lock lives."""
    return secrets_store.SECRETS_BASE / TOKEN_PROVIDER / f"{TOKEN_SLUG}.lock"


def save_tokens(records: List[Dict[str, Any]]) -> str:
    """Persist token records as the keyring entry host_api/tokens; returns the entry's name."""
    envelope: Dict[str, Any] = {"version": STORE_VERSION, "tokens": records}
    return secrets_store.set_secret(TOKEN_PROVIDER, TOKEN_SLUG, envelope, as_json=True)


@contextmanager
def store_lock() -> Iterator[None]:
    """The token store's write lock, for the pairing store that shares it."""
    # Not reentrant: pairings.py must release it before issue_token(), which takes it again.
    with _store_lock():
        yield


@contextmanager
def _store_lock(wait: Optional[float] = None) -> Iterator[None]:
    """Hold an exclusive write lock on the token store."""
    # O_CREAT|O_EXCL rather than fcntl: this has to work on Windows too.
    # wait=None reads LOCK_WAIT_SECONDS at call time, not def time: the tests shorten it there.
    wait = LOCK_WAIT_SECONDS if wait is None else wait
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait
    descriptor = None

    while descriptor is None:
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_is_stale(path):
                logger.warning("[host_api] breaking a stale token store lock")
                _drop_lock(path)
                continue
            if time.monotonic() >= deadline:
                raise OSError(f"Token store lock held longer than {wait}s at {path}") from None
            time.sleep(LOCK_POLL_SECONDS)
        except PermissionError as e:
            # Windows answers a delete-pending lock with ACCESS DENIED: still held, so poll it.
            # Never a staleness check (a stale lock answers FILE EXISTS); past the wait, a real denial.
            if time.monotonic() >= deadline:
                raise OSError(f"Token store lock at {path} still denied access after {wait}s: {e}") from e
            time.sleep(LOCK_POLL_SECONDS)

    try:
        yield
    finally:
        os.close(descriptor)
        _drop_lock(path)


def _lock_is_stale(path: Path) -> bool:
    """Whether a held lock is old enough to be broken."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError as e:
        # Gone (or Windows delete-pending ACCESS DENIED) since the failed create: raced, not stale.
        logger.debug("[host_api] token store lock vanished while checking its age: %s", e)
        return False

    return age > LOCK_STALE_SECONDS


def _drop_lock(path: Path) -> None:
    """Remove a lock file, tolerating its absence."""
    try:
        os.unlink(str(path))
    except FileNotFoundError as e:
        logger.debug("[host_api] the token store lock was already gone: %s", e)
    except OSError as e:
        # Never raised: a release that throws would mask whatever the body was doing.
        logger.warning("[host_api] could not remove the token store lock: %s", e)


def issue_token(label: str, scope: str = "read") -> Tuple[Dict[str, Any], str]:
    """Mint a bearer token."""
    if not label or not label.strip():
        raise TokenError("Token label is required — an unlabelled token cannot be revoked with confidence")

    if scope not in SCOPES:
        raise TokenError(f"Unknown scope {scope!r} — expected one of: {', '.join(SCOPES)}")

    raw = secrets_lib.token_urlsafe(_TOKEN_BYTES)

    record: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "label": label.strip(),
        "scope": scope,
        "hash": _hash_token(raw),
        "created": datetime.now().isoformat(),
        "minted_by": current_minter(),
        "last_used": None,
        "revoked": False,
    }

    with _store_lock():
        records = load_tokens()
        records.append(record)
        save_tokens(records)

    # The raw value never reaches a log.
    logger.info(
        "[host_api] token issued: id=%s label=%s scope=%s by=%s",
        record["id"],
        record["label"],
        scope,
        record["minted_by"],
    )
    json_handler.log_operation(
        "host_api_token_issued",
        {"id": record["id"], "scope": scope, "minted_by": record["minted_by"]},
    )

    return record, raw


def current_minter() -> str:
    """Best-effort name for whoever is running this command."""
    # PROVENANCE, NEVER PERMISSION: it comes from the caller's own environment.
    return (os.environ.get(CALLER_ENV) or "").strip() or UNKNOWN_MINTER


def resolve_token(raw: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Resolve a raw bearer token to its record AND to what it turned out to be."""
    # A record returned alongside 'revoked' IS NOT A GRANT; the caller refuses non-active.
    # The store is re-read per call: that is what makes revocation effective next request.
    if not raw or not isinstance(raw, str):
        return None, STATUS_UNKNOWN

    candidate = _hash_token(raw)

    for record in load_tokens():
        stored_hash = record.get("hash")
        if not isinstance(stored_hash, str):
            continue

        if not hmac.compare_digest(candidate, stored_hash):
            continue

        if record.get("revoked"):
            return record, STATUS_REVOKED

        return record, STATUS_ACTIVE

    return None, STATUS_UNKNOWN


def verify_token(raw: str) -> Optional[Dict[str, Any]]:
    """Resolve a raw bearer token to its record, or None."""
    record, status = resolve_token(raw)
    return record if status == STATUS_ACTIVE else None


def touch_token(token_id: str, last_used: Any = None) -> None:
    """Record that a token was just used. Best-effort, and never fatal."""
    # The caller's stamp, still inside the window, settles it without locking: every request touches.
    if last_used is not None and not _is_due(last_used):
        return
    try:
        with _store_lock():
            # Re-read INSIDE the lock: a list read before a revoke, written back, resurrects the token.
            records = load_tokens()

            for record in records:
                if record.get("id") != token_id:
                    continue

                if not _is_due(record.get("last_used")):
                    return

                record["last_used"] = datetime.now().isoformat()
                save_tokens(records)
                return
    except (OSError, secrets_store.SecretsUnavailable) as e:
        # Swallowed: telemetry never fails a request. No id: nothing read from the store reaches a log (CodeQL).
        logger.warning("[host_api] could not record last_used for the presented token: %s", e)


def _is_due(last_used: Any) -> bool:
    """Whether a token's last_used is old enough to rewrite."""
    # An unparseable value counts as due: a stamp nobody can read is not a stamp.
    if not last_used:
        return True

    stamp: Optional[datetime] = None
    try:
        stamp = datetime.fromisoformat(str(last_used))
    except ValueError as e:
        # Type name only: ValueError's text quotes the stamp, a value read from the credential store.
        logger.warning("[host_api] unreadable last_used stamp, treating as due (%s)", type(e).__name__)

    return stamp is None or (datetime.now() - stamp).total_seconds() >= LAST_USED_GRANULARITY_SECONDS


def revoke_token(token_id: str) -> bool:
    """Revoke a token by id."""
    with _store_lock():
        records = load_tokens()
        changed = False

        for record in records:
            if record.get("id") == token_id and not record.get("revoked"):
                record["revoked"] = True
                record["revoked_at"] = datetime.now().isoformat()
                changed = True

        if not changed:
            return False

        save_tokens(records)

    logger.info("[host_api] token revoked: id=%s", token_id)
    json_handler.log_operation("host_api_token_revoked", {"id": token_id})
    return True


def list_tokens() -> List[Dict[str, Any]]:
    """Token records for display, with hashes stripped."""
    # minted_by stays None for pre-v2 records: "unknown" would claim someone was asked.
    return [
        {
            "id": record.get("id"),
            "label": record.get("label"),
            "scope": record.get("scope"),
            "created": record.get("created"),
            "minted_by": record.get("minted_by"),
            "last_used": record.get("last_used"),
            "revoked": bool(record.get("revoked")),
            "revoked_at": record.get("revoked_at"),
        }
        for record in load_tokens()
    ]


def scope_allows(record_scope: str, required: str) -> bool:
    """Check whether a token's scope satisfies a requirement."""
    return required in _SCOPE_IMPLIES.get(record_scope, ())


def _hash_token(raw: str) -> str:
    """Hash a raw token for storage and comparison."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
