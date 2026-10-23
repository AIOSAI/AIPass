# =================== AIPass ====================
# Name: pairings.py
# Description: Host API Pairings — one-use, five-minute codes a phone trades for its bearer
# Version: 1.2.0
# Created: 2026-10-13
# Modified: 2026-10-22
# =============================================

"""
Host API Pairings

Reference: docs/host_api.md (Pairing).
"""

import hashlib
import hmac
import io
import ipaddress
import secrets as secrets_lib
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

import segno

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import tokens as host_tokens

PAIRING_SLUG = "pairings"
_ENTRY = f"{host_tokens.TOKEN_PROVIDER}/{PAIRING_SLUG}"
STORE_VERSION = 1

DEFAULT_TTL_SECONDS = 300
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 900

PROBE_TIMEOUT_SECONDS = 3.0

# The same randomness as a bearer: the code is a bearer for five minutes.
_CODE_BYTES = 32

ATTEMPT_LIMIT = 10
ATTEMPT_WINDOW_SECONDS = 60.0

# One sentence for unknown, expired and used alike: a prober never learns a code was real.
REFUSED = "pairing code unknown, expired or already used"
TOO_MANY = "Too many pairing attempts from this address; wait a minute and scan a fresh code"
NO_CODE = 'A pairing code is required: {"code": "<the code>"}'

# Audit vocabulary, never response vocabulary (tokens.py's STATUS_* rule).
REASON_UNKNOWN = "unknown"
REASON_EXPIRED = "expired"
REASON_USED = "used"


class PairingError(host_tokens.TokenError):
    """A pairing operation was refused."""


class AttemptWindow:
    """Attempts per client address inside a sliding window, in process."""

    def __init__(self, limit: int = ATTEMPT_LIMIT, seconds: float = ATTEMPT_WINDOW_SECONDS) -> None:
        """Hold *limit* attempts per address per *seconds*."""
        self.limit = limit
        self.seconds = seconds
        self._seen: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, peer: str) -> bool:
        """Count one attempt from *peer*."""
        # A refused attempt is not counted, so a caller that waits out the window gets back in.
        now = time.monotonic()
        with self._lock:
            for address in [key for key, stamps in self._seen.items() if stamps[-1] <= now - self.seconds]:
                del self._seen[address]

            stamps = self._seen.setdefault(peer, deque())
            while stamps and stamps[0] <= now - self.seconds:
                stamps.popleft()
            if len(stamps) >= self.limit:
                return False
            stamps.append(now)
            return True


def load_pairings() -> List[Dict[str, Any]]:
    """
    Read every pairing row from the keyring entry host_api/pairings.

    A broken store raises, never []: an empty list would refuse a live code as unknown and hide why.
    """
    try:
        stored = secrets_store.get_secret(host_tokens.TOKEN_PROVIDER, PAIRING_SLUG, as_json=True)
    except secrets_store.SecretsUnavailable as e:
        raise PairingError(f"The pairing store {_ENTRY} cannot be read ({e})") from None
    if stored is None:
        return []

    rows = stored.get("pairings") if isinstance(stored, dict) else None
    if not isinstance(rows, list):
        raise PairingError(f"The pairing store {_ENTRY} has no 'pairings' list")
    return [row for row in rows if isinstance(row, dict)]


def _save_pairings(rows: List[Dict[str, Any]]) -> None:
    """Write the rows to the keyring entry host_api/pairings."""
    document = {"version": STORE_VERSION, "pairings": rows}
    try:
        secrets_store.set_secret(host_tokens.TOKEN_PROVIDER, PAIRING_SLUG, document, as_json=True)
    except secrets_store.SecretsUnavailable as e:
        raise PairingError(f"The pairing store {_ENTRY} cannot be written ({e})") from None


def _expires(row: Dict[str, Any]) -> Optional[datetime]:
    """When a row dies; None (unreadable stamp) is dead: a code nobody can date is not honoured."""
    try:
        expires = datetime.fromisoformat(str(row.get("expires")))
    except ValueError as e:
        logger.warning("[host_api] a pairing row has an unreadable expiry; treated as expired (%s)", type(e).__name__)
        return None
    return expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)


def _status(row: Dict[str, Any], now: datetime) -> Optional[str]:
    """None for a live row, else why it is dead: REASON_USED or REASON_EXPIRED."""
    if row.get("used_at"):
        return REASON_USED
    expires = _expires(row)
    if expires is None or now >= expires:
        return REASON_EXPIRED
    return None


def _hash_code(raw: str) -> str:
    """sha256 of a raw code, the only form of it the store keeps."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def bind_address(allow_loopback: bool = True) -> Tuple[str, int]:
    """The stored bind, as an address a browser can open."""
    config = host_config.load_config()
    host = str(config.get("host") or "").strip()
    port = config.get("port")

    if not host or not isinstance(port, int) or isinstance(port, bool):
        raise PairingError("No bind is stored, so there is no address a phone can open. Set one first")

    try:
        address = ipaddress.ip_address(host)
    except ValueError as e:
        raise PairingError(f"The stored host {host!r} is not an address a phone can open") from e

    if address.is_unspecified:
        raise PairingError(f"The stored host {host} is a wildcard, so there is no one address a phone can open")

    if address.is_loopback and not allow_loopback:
        raise PairingError(
            f"The face listens on {host} only; a phone cannot reach it. Run the install's phone step or "
            f"drone @api host-api set-config --host <tailnet ip> --port {port} first"
        )
    return host, port


def _pairing_url(code: str) -> str:
    """The face's URL with the code in the fragment, which a browser never sends."""
    host, port = bind_address()
    return f"{_origin(host, port)}/#pair={code}"


def _origin(host: str, port: int) -> str:
    """http://<host>:<port>, an IPv6 host in brackets."""
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{port}"


def _require_listener(label: str, scope: str) -> None:
    """
    Refuse a code no server is there to redeem: one GET on the bind's face.

    A serve record is not the check (it can name a dead pid); an HTTP answer is.
    """
    host, port = bind_address()
    try:
        with urllib_request.urlopen(f"{_origin(host, port)}/", timeout=PROBE_TIMEOUT_SECONDS):
            return
    except urllib_error.HTTPError as e:
        logger.warning("[host_api] pairing refused: the server on %s:%s answered %s", host, port, e.code)
        raise PairingError(
            f"The server on {host}:{port} answers {e.code}, not the phone face, so a code would open nothing. "
            f"See what it is serving:\n  drone @api host-api status"
        ) from e
    except (urllib_error.URLError, OSError) as e:
        logger.warning("[host_api] pairing refused: no server answers on %s:%s (%s)", host, port, type(e).__name__)
        raise PairingError(
            f"No server answers on {host}:{port}, so a code would open nothing. Start it, then mint again:\n"
            f"  drone @api host-api serve --detach\n"
            f"  drone @api host-api pair {label} --scope {scope}"
        ) from e


def mint_pairing(label: str, scope: str = "read", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Dict[str, Any]:
    """Mint a one-use pairing code."""
    wanted = (label or "").strip()
    if not wanted:
        raise PairingError("A pairing needs a label: the token it mints is revoked by that name")
    if scope not in host_tokens.SCOPES:
        raise PairingError(f"Unknown scope {scope!r} — expected one of: {', '.join(host_tokens.SCOPES)}")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise PairingError(f"The pairing ttl must be whole seconds, got {ttl_seconds!r}")
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PairingError(f"The pairing ttl must be {MIN_TTL_SECONDS} to {MAX_TTL_SECONDS} seconds, got {ttl_seconds}")

    code = secrets_lib.token_urlsafe(_CODE_BYTES)
    url = _pairing_url(code)
    _require_listener(wanted, scope)
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid.uuid4().hex[:12],
        "label": wanted,
        "scope": scope,
        "sha256": _hash_code(code),
        "created": now.isoformat(),
        "expires": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "used_at": None,
    }

    try:
        with host_tokens.store_lock():
            rows = [kept for kept in load_pairings() if _status(kept, now) is None]
            rows.append(row)
            _save_pairings(rows)
    except OSError as e:
        raise PairingError(f"The pairing store's lock could not be taken ({type(e).__name__})") from e

    # The code never reaches a log.
    logger.info("[host_api] pairing minted: id=%s label=%s scope=%s ttl=%ss", row["id"], wanted, scope, ttl_seconds)
    json_handler.log_operation("host_api_pairing_minted", {"id": row["id"], "scope": scope, "ttl": ttl_seconds})
    return {"id": row["id"], "label": wanted, "scope": scope, "code": code, "expires_at": row["expires"], "url": url}


def redeem_pairing(raw: str, peer: str = "unknown") -> Optional[Dict[str, Any]]:
    """
    Trade a live code for a bearer minted for its label and scope.

    Marked used before the mint: a failure between the two burns the code, never leaves it live.
    """
    hashed = _hash_code(raw)
    now = datetime.now(timezone.utc)

    try:
        with host_tokens.store_lock():
            rows = load_pairings()
            found = next((row for row in rows if hmac.compare_digest(str(row.get("sha256", "")), hashed)), None)
            reason = REASON_UNKNOWN if found is None else _status(found, now)
            if reason is None and found is not None:
                found["used_at"] = now.isoformat()
            # Keep the row spent just now: a second try then logs as used, not unknown.
            _save_pairings([row for row in rows if (row is found and reason is None) or _status(row, now) is None])
    except OSError as e:
        raise PairingError(f"The pairing store's lock could not be taken ({type(e).__name__})") from e

    if reason is not None or found is None:
        logger.warning("[host_api] pairing refused: %s, from %s", reason, peer)
        json_handler.log_operation("host_api_pair_refused", {"reason": reason, "peer": peer})
        return None

    try:
        record, token = host_tokens.issue_token(str(found["label"]), str(found["scope"]))
    except (host_tokens.TokenError, OSError) as e:
        raise PairingError(f"Pairing {found['id']} was spent but no token could be minted; mint a new code") from e

    logger.info("[host_api] pairing %s redeemed from %s: token id=%s", found["id"], peer, record["id"])
    json_handler.log_operation("host_api_pair_redeemed", {"pairing": found["id"], "token": record["id"], "peer": peer})
    return {"token": token, "id": record["id"], "label": record["label"], "scope": record["scope"]}


def answer_pair(payload: Any, peer: str, window: AttemptWindow) -> Tuple[int, Dict[str, Any]]:
    """POST /v1/pair's whole answer, with no web framework in it."""
    if not window.allow(peer):
        logger.warning("[host_api] pairing refused: rate limited, from %s", peer)
        json_handler.log_operation("host_api_pair_refused", {"reason": "rate_limited", "peer": peer})
        return 429, {"code": "too_many_attempts", "message": TOO_MANY}

    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not code.strip():
        return 400, {"code": "invalid_request", "message": NO_CODE}

    redeemed = redeem_pairing(code.strip(), peer)
    if redeemed is None:
        return 401, {"code": "pairing_refused", "message": REFUSED}
    return 200, redeemed


def render_qr(text: str) -> str:
    """The QR of *text* as terminal block characters."""
    if not text or not text.strip():
        raise PairingError("Nothing to render: a QR of an empty text opens nothing")

    rendered = io.StringIO()
    segno.make(text, micro=False).terminal(out=rendered, compact=True, border=1)
    return rendered.getvalue().rstrip("\n")
