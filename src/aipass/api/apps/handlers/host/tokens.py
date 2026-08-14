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

Functions:
    issue_token()  - Mint a token, return (record, raw_value)
    verify_token() - Resolve a raw token to its record, or None
    revoke_token() - Revoke by id
    list_tokens()  - Records for display, hashes stripped
    load_tokens()  - Raw store read
"""

import hashlib
import hmac
import secrets as secrets_lib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store

TOKEN_PROVIDER = "host_api"
TOKEN_SLUG = "tokens"

# Bumped when the stored record shape changes in a way a reader must notice.
STORE_VERSION = 1

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


def save_tokens(records: List[Dict[str, Any]]) -> str:
    """
    Persist token records.

    Wrapped in a versioned envelope so the store can gain fields later without
    a reader having to guess which shape it is holding.

    Args:
        records: Full record list to write.

    Returns:
        Path to the written file, as a string.
    """
    envelope: Dict[str, Any] = {"version": STORE_VERSION, "tokens": records}
    path = secrets_store.set_secret(TOKEN_PROVIDER, TOKEN_SLUG, envelope, as_json=True)
    return str(path)


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
        # RESERVATION: last_used is in the schema but never written in Phase 1.
        # A write per request on a shared JSON file needs the locking that
        # Phase 5 brings; a half-built version would corrupt the store under
        # concurrent requests, which is worse than an honest null.
        "last_used": None,
        "revoked": False,
    }

    records = load_tokens()
    records.append(record)
    save_tokens(records)

    # id and label only. The raw value never reaches a log.
    logger.info("[host_api] token issued: id=%s label=%s scope=%s", record["id"], record["label"], scope)
    json_handler.log_operation("host_api_token_issued", {"id": record["id"], "scope": scope})

    return record, raw


def verify_token(raw: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a raw bearer token to its record.

    Re-reads the store on every call, which is what makes revocation effective
    on the next request.

    Args:
        raw: The bearer value presented by the client.

    Returns:
        The matching, non-revoked record, or None.
    """
    if not raw or not isinstance(raw, str):
        return None

    candidate = _hash_token(raw)

    for record in load_tokens():
        if record.get("revoked"):
            continue

        stored_hash = record.get("hash")
        if not isinstance(stored_hash, str):
            continue

        if hmac.compare_digest(candidate, stored_hash):
            return record

    return None


def revoke_token(token_id: str) -> bool:
    """
    Revoke a token by id.

    Args:
        token_id: The record id.

    Returns:
        True if a record was revoked, False if the id was unknown or already
        revoked.
    """
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

    Returns:
        List of records carrying id, label, scope, created, last_used, revoked.
    """
    return [
        {
            "id": record.get("id"),
            "label": record.get("label"),
            "scope": record.get("scope"),
            "created": record.get("created"),
            "last_used": record.get("last_used"),
            "revoked": bool(record.get("revoked")),
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
