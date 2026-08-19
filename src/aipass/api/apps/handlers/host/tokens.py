# =================== AIPass ====================
# Name: tokens.py
# Description: Host API Token Handler — bearer token issue, verify, revoke
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Token Handler

The app-layer half of FPLAN-0411's two-layer auth (design call D2). The network
boundary is the other half; neither is trusted alone — Tailscale's own docs say
identity headers are spoofable, so a token sits behind the tunnel.

Store: ~/.secrets/aipass/host_api/tokens.json, through this branch's existing
secrets door (0o700 dir, 0o600 file, already proven).

THREE PROPERTIES THIS FILE OWES THE PHONE:

1. The raw token is returned ONCE, at issue, and never stored. Records carry a
   sha256 hash, so a reader of the store cannot authenticate with it.
2. Verification is constant-time (hmac.compare_digest) — a hash comparison that
   short-circuits leaks the hash one byte at a time.
3. Revocation is server-side and effective on the NEXT REQUEST. The store is
   re-read per verification, so revoking needs no restart and no cooperation
   from the phone. This is the answer to the iOS keychain surviving an app
   uninstall: a token the phone keeps forever is inert once the host stops
   honouring it.

Scopes: 'read' and 'operate'. operate implies read. Destructive verbs (Phase 3)
require operate; the client is expected to gate those behind biometrics too, but
the server never relies on that — scope is enforced here.

THREE ACCOUNTABILITY FIELDS (devpulse's ruling, 2026-08-14)
------------------------------------------------------------------------
Added after an operate-scoped token appeared on this machine and the store could
not say who minted it. The C1 audit knew exactly who FAILED auth; nothing knew
who ISSUED.

    minted_by   - best-effort provenance, from the caller identity drone sets.
                  PROVENANCE, NEVER PERMISSION: the value comes from the
                  caller's own environment, so trusting it to authorise
                  anything would be trusting the caller about the caller.
    revoked_at  - written since Phase 1; it was the LISTING that never showed
                  it. My own correction — I read the projection and called it
                  the store.
    last_used   - whether a live token is actually live, or merely un-revoked.

THE DANGER IN `last_used`, WHICH IS WHY PHASE 1 RESERVED IT
------------------------------------------------------------------------
It means a write on every authenticated request, to the same file issue and
revoke write. The obvious risk is a lost update. The real risk is worse: a
telemetry write holding a record list read BEFORE a revoke landed would write
that stale list back and UN-REVOKE the token. A revoked device starts working
again because something looked at a timestamp.

So every read-modify-write here happens under a lock and re-reads inside it, the
store is written atomically (a truncated store reads as empty, and an empty
store denies every request), and a touch that cannot take the lock is DROPPED
rather than raised — telemetry never fails an authenticated request.

Writes coalesce inside a window, because the question is "is this credential
still in use", not "at which second". A phone polling the feed would otherwise
rewrite the whole store every few seconds.

Functions:
    issue_token()  - Mint a token, return (record, raw_value)
    verify_token() - Resolve a raw token to its record, or None
    touch_token()  - Best-effort 'this token was used just now'
    revoke_token() - Revoke by id
    list_tokens()  - Records for display, hashes stripped
    load_tokens()  - Raw store read
    lock_path()    - Where the store's write lock lives
"""

import hashlib
import hmac
import json
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

# Bumped when the stored record shape changes in a way a reader must notice.
# 2 adds minted_by. Version 1 records keep verifying, listing and revoking.
STORE_VERSION = 2

# Drone names the calling branch in the child environment. Absent when this
# module is driven in-process or from a bare shell.
CALLER_ENV = "AIPASS_CALLER_BRANCH"
UNKNOWN_MINTER = "unknown"

# How coarse `last_used` is allowed to be. A minute answers live-or-dormant and
# turns a per-request store rewrite into a per-minute one.
LAST_USED_GRANULARITY_SECONDS = 60

# How long before a lock left behind by a dead process is broken. Bounded
# staleness beats a permanent outage: the worst case for breaking a stale lock
# is a lost timestamp; the worst case for honouring one forever is a server that
# can never issue or revoke again.
LOCK_STALE_SECONDS = 30

# How long a writer waits for the lock. Callers that must not be lost (issue,
# revoke) surface a failure; callers that must not delay a request (touch) skip.
LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.02

# What a presented token turned out to be. THESE ARE AUDIT VOCABULARY, NEVER
# RESPONSE VOCABULARY — revoked and unknown are refused identically at the door,
# and the difference exists so the trail can answer 'was that device ever ours?'
# after the fact. Answering it in the response would hand a prober an oracle.
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_UNKNOWN = "unknown"

SCOPES = ("read", "operate")

# operate implies read; read implies nothing else.
_SCOPE_IMPLIES: Dict[str, Tuple[str, ...]] = {
    "read": ("read",),
    "operate": ("read", "operate"),
}

# 32 bytes of urlsafe randomness. Long enough that the tunnel is the slow lane.
_TOKEN_BYTES = 32


class TokenError(Exception):
    """A token operation was refused."""


# ==============================================
# STORE
# ==============================================


def load_tokens() -> List[Dict[str, Any]]:
    """
    Read every token record from the store.

    Returns:
        List of records. Missing or malformed store reads as empty — which
        denies every request rather than admitting one.
    """
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


def store_path() -> Path:
    """
    Where the token store lives.

    Returns:
        Path to tokens.json, whether or not it exists yet.
    """
    return secrets_store.SECRETS_BASE / TOKEN_PROVIDER / f"{TOKEN_SLUG}.json"


def lock_path() -> Path:
    """
    Where the store's write lock lives.

    Returns:
        Path to the lock file, whether or not it is held.
    """
    return secrets_store.SECRETS_BASE / TOKEN_PROVIDER / f"{TOKEN_SLUG}.lock"


def save_tokens(records: List[Dict[str, Any]]) -> str:
    """
    Persist token records ATOMICALLY.

    Wrapped in a versioned envelope so the store can gain fields later without a
    reader having to guess which shape it is holding.

    Written to a temporary file in the same directory and renamed into place, so
    a concurrent reader sees the old file or the new one and never part of
    either. That matters more than it looks: load_tokens() treats an unparseable
    store as EMPTY, and an empty store denies every request. Before `last_used`
    the truncation window opened only when an operator ran a command; now it
    would open on every authenticated request.

    Args:
        records: Full record list to write.

    Returns:
        Path to the written file, as a string.
    """
    envelope: Dict[str, Any] = {"version": STORE_VERSION, "tokens": records}
    target = store_path()

    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)

    # Same directory, so the rename cannot cross a filesystem boundary — and
    # 0o600 is set at creation rather than chmod'd after, so the content is
    # never briefly world-readable.
    temporary = target.parent / f".{TOKEN_SLUG}.{os.getpid()}.tmp"
    content = json.dumps(envelope, indent=2).encode("utf-8")

    # The low-level descriptor call rather than the builtin, because the mode
    # argument is the point: creating with 0o600 means the bytes are never
    # briefly readable by anyone else, which a chmod-after cannot promise.
    # Content is already UTF-8 encoded above.
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # encoding=utf-8 done above
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    try:
        os.replace(str(temporary), str(target))
    except OSError:
        # Leave nothing behind for the next writer to trip over. A failure to
        # clean up is not the story here — the failed rename is, and it is
        # re-raised below — but it is still worth a line, because a temp file
        # nobody can unlink is how a full or read-only secrets dir announces
        # itself before the next writer trips over it.
        try:
            os.unlink(str(temporary))
        except OSError as cleanup_error:
            logger.warning("[host_api] could not remove the temp store at %s: %s", temporary, cleanup_error)
        raise

    return str(target)


@contextmanager
def _store_lock(wait: float = LOCK_WAIT_SECONDS) -> Iterator[None]:
    """
    Hold an exclusive write lock on the token store.

    O_CREAT|O_EXCL rather than fcntl, because this has to work on Windows too.
    A lock older than LOCK_STALE_SECONDS is broken: a process that died holding
    it must not lock out every future issue and revoke. The worst case for
    breaking a stale lock is a lost timestamp; the worst case for honouring one
    forever is a server that can never revoke a credential again.

    Args:
        wait: Seconds to keep trying before giving up.

    Yields:
        None, with the lock held.

    Raises:
        OSError: The lock could not be taken within *wait*.
    """
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait
    descriptor = None

    while descriptor is None:
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lock_is_stale(path):
                logger.warning("[host_api] breaking a stale token store lock at %s", path)
                _drop_lock(path)
                continue
            if time.monotonic() >= deadline:
                raise OSError(f"Token store lock held longer than {wait}s at {path}") from None
            time.sleep(LOCK_POLL_SECONDS)

    try:
        yield
    finally:
        # Released even when the body raised — a lock left behind by a failed
        # write wedges every write after it until the staleness timeout.
        os.close(descriptor)
        _drop_lock(path)


def _lock_is_stale(path: Path) -> bool:
    """
    Whether a held lock is old enough to be broken.

    Args:
        path: The lock file.

    Returns:
        True if the lock is older than LOCK_STALE_SECONDS, or has vanished.
    """
    try:
        age = time.time() - path.stat().st_mtime
    except OSError as e:
        # Gone between the failed create and this stat — not stale, just raced.
        # Logged rather than passed over: this is the ordinary outcome of two
        # writers meeting, but if it ever repeats in a burst it is the trace
        # that says so.
        logger.debug("[host_api] token store lock vanished while checking its age: %s", e)
        return False

    return age > LOCK_STALE_SECONDS


def _drop_lock(path: Path) -> None:
    """
    Remove a lock file, tolerating its absence.

    Args:
        path: The lock file.
    """
    try:
        os.unlink(str(path))
    except OSError as e:
        # Tolerated: a stale-lock break may have removed it already. Never
        # raised — a release that throws would mask whatever the body was
        # doing — but never silent either, because a lock that cannot be
        # removed wedges every write until the staleness timeout expires.
        logger.debug("[host_api] token store lock at %s was already gone: %s", path, e)


# ==============================================
# ISSUE / VERIFY / REVOKE
# ==============================================


def issue_token(label: str, scope: str = "read") -> Tuple[Dict[str, Any], str]:
    """
    Mint a bearer token.

    The raw value is returned to the caller and NOT stored — this is the only
    moment it exists outside the phone.

    Args:
        label: Human name for the device, e.g. "pixel-8".
        scope: 'read' or 'operate'.

    Returns:
        Tuple of (stored record, raw token value).

    Raises:
        TokenError: Empty label or unknown scope.
    """
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

    # id, label and minter only. The raw value never reaches a log.
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
    """
    Best-effort name for whoever is running this command.

    drone names the calling branch in the child environment. Absent when this
    module is driven in-process or from a bare shell, and 'unknown' is the
    honest answer then — a field that vanishes when it has nothing to say reads
    as though nobody thought to record it.

    THIS IS PROVENANCE, NEVER PERMISSION. The value comes from the caller's own
    environment, so treating it as authorisation would be trusting the caller
    about the caller. It records what happened; it decides nothing.

    Returns:
        The calling branch name, or 'unknown'.
    """
    return (os.environ.get(CALLER_ENV) or "").strip() or UNKNOWN_MINTER


def resolve_token(raw: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Resolve a raw bearer token to its record AND to what it turned out to be.

    Re-reads the store on every call, which is what makes revocation effective
    on the next request.

    WHY THIS EXISTS SEPARATELY FROM verify_token: on 2026-08-16 Patrick's phone
    was refused for nine minutes and the trail said only token_unrecognised.
    The store was provably intact, so the one thing that would have closed the
    investigation — did that device present a credential we once issued, or
    garbage? — was exactly what the log could not say. A revoked record was
    skipped silently and became indistinguishable from a token nobody had ever
    minted.

    So the revoked match is now FOUND, not skipped. The caller gets the record
    for the trail and the status for the decision, and it is the caller's job to
    refuse anything that is not active — which is why the record comes back
    paired with a status rather than alone.

    Args:
        raw: The bearer value presented by the client.

    Returns:
        (record, status). Status is active, revoked, or unknown. The record is
        present for active and revoked, and None for unknown. A record returned
        alongside 'revoked' IS NOT A GRANT.
    """
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
    """
    Resolve a raw bearer token to its record, or None.

    The narrow door: a record comes back only when the token is usable RIGHT
    NOW. Callers that want to know why a refusal happened use resolve_token;
    callers that only want the yes-or-no keep this one and cannot accidentally
    honour a revoked record, because a revoked token never leaves here as a
    truthy value.

    Args:
        raw: The bearer value presented by the client.

    Returns:
        The matching, non-revoked record, or None.
    """
    record, status = resolve_token(raw)
    return record if status == STATUS_ACTIVE else None


def touch_token(token_id: str) -> None:
    """
    Record that a token was just used. Best-effort, and never fatal.

    THE RULE THIS FUNCTION OBEYS: telemetry never undoes security, and telemetry
    never fails a request.

    So the record list is re-read INSIDE the lock. A list read before a revoke
    landed, written back afterwards, would resurrect a revoked device — a
    security property destroyed by a timestamp. And if the lock cannot be taken,
    the write is dropped with a log line rather than raised: a missing timestamp
    is a small loss, a 500 on a properly authenticated request is not.

    Writes coalesce inside LAST_USED_GRANULARITY_SECONDS, because the question
    this field answers is "is this credential still in use", not "at which
    second". A phone polling the feed would otherwise rewrite the whole store
    every few seconds.

    Args:
        token_id: The record id to stamp.
    """
    try:
        with _store_lock():
            records = load_tokens()

            for record in records:
                if record.get("id") != token_id:
                    continue

                if not _is_due(record.get("last_used")):
                    return

                record["last_used"] = datetime.now().isoformat()
                save_tokens(records)
                return
    except OSError as e:
        # Deliberately swallowed. See the rule above.
        logger.warning("[host_api] could not record last_used for %s: %s", token_id, e)


def _is_due(last_used: Any) -> bool:
    """
    Whether a token's last_used is old enough to rewrite.

    Args:
        last_used: The stored timestamp, or None.

    Returns:
        True if the store should be rewritten. An unparseable value counts as
        due — a stamp nobody can read is not a stamp.
    """
    if not last_used:
        return True

    try:
        age = (datetime.now() - datetime.fromisoformat(str(last_used))).total_seconds()
    except ValueError as e:
        # Due, not fatal: an unreadable stamp gets overwritten with a readable
        # one on this request. Logged because the only way this fires is a
        # hand-edited store or a shape change nobody migrated, and both are
        # things an operator should see once rather than never.
        logger.warning("[host_api] unreadable last_used %r, treating as due: %s", last_used, e)
        return True

    return age >= LAST_USED_GRANULARITY_SECONDS


def revoke_token(token_id: str) -> bool:
    """
    Revoke a token by id.

    Args:
        token_id: The record id.

    Returns:
        True if a record was revoked, False if the id was unknown or already
        revoked.
    """
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
    """
    Token records for display, with hashes stripped.

    Every accountability field is projected here. `revoked_at` was written from
    Phase 1 onward and simply never surfaced, which is how I came to report it
    as a missing field — I read the projection and called it the store.

    `minted_by` is None rather than 'unknown' for a record written before the
    field existed: nobody was ever asked, and "unknown" would claim they were.

    Returns:
        List of records carrying id, label, scope, created, minted_by,
        last_used, revoked and revoked_at.
    """
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
    """
    Check whether a token's scope satisfies a requirement.

    Args:
        record_scope: Scope carried by the token.
        required: Scope the endpoint demands.

    Returns:
        True if allowed. An unknown scope allows nothing.
    """
    return required in _SCOPE_IMPLIES.get(record_scope, ())


# ==============================================
# PRIVATE HELPERS
# ==============================================


def _hash_token(raw: str) -> str:
    """
    Hash a raw token for storage and comparison.

    Args:
        raw: Raw token value.

    Returns:
        Hex sha256 digest.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
