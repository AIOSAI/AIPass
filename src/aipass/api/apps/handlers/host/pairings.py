# =================== AIPass ====================
# Name: pairings.py
# Description: Host API Pairings — one-use, five-minute codes a phone trades for its bearer
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================

"""
Host API Pairings

The owner signed his phone in by hand on 2026-10-13 and ruled on the result: the
hop of the token to the phone is the real issue, and a QR is the answer
(DPLAN-0406). A pairing code is a one-use secret with a five-minute life. The
machine mints one and shows it as a QR of the face's URL with the code in the
fragment; the phone posts the code to POST /v1/pair and receives a bearer
minted for that code's label and scope. The bearer never reaches a screen, a
file the user moves, or a mail, so "the raw value is never printed" stays
literally true.

Store: ~/.secrets/aipass/host_api/pairings.json, beside tokens.json, written
through the token store's own atomic owner-only write and under its lock. Only
a code's sha256 is stored, as with tokens.

THE ONE ANSWER. Unknown, expired and already used are refused identically: a
prober learns "no", never "that one was real". The difference goes to the log
with the caller's address, as the token refusals do.

USED BEFORE MINTED. A redeem marks the row used, releases the lock, and only
then mints through issue_token(). A failure between the two burns the code
rather than leaving it live for a second phone.

Classes:
    PairingError  - A pairing operation was refused (a TokenError)
    AttemptWindow - The in-process sliding window behind POST /v1/pair's 429

Functions:
    mint_pairing()   - Mint a one-use code, return it with its URL
    redeem_pairing() - Trade a live code for a freshly minted bearer, or None
    answer_pair()    - POST /v1/pair's whole answer, framework-free
    render_qr()      - The QR of a text as terminal block characters
    bind_address()   - The stored bind a phone would open, refused when it cannot
    store_path()     - Where the pairing store lives
    load_pairings()  - Raw store read; an unreadable store raises
"""

import hashlib
import hmac
import io
import ipaddress
import json
import secrets as secrets_lib
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import segno

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import tokens as host_tokens

PAIRING_SLUG = "pairings"
STORE_VERSION = 1

DEFAULT_TTL_SECONDS = 300
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 900

# The same randomness as a bearer: the code is a bearer for five minutes.
_CODE_BYTES = 32

# POST /v1/pair: ten attempts per client address per minute.
ATTEMPT_LIMIT = 10
ATTEMPT_WINDOW_SECONDS = 60.0

#: The one sentence for unknown, expired and used alike.
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
    """
    Attempts per client address inside a sliding window, in process.

    One per app: a restart forgets it, which costs a prober nothing it did not
    already have — a code lives five minutes and is 32 random bytes.
    """

    def __init__(self, limit: int = ATTEMPT_LIMIT, seconds: float = ATTEMPT_WINDOW_SECONDS) -> None:
        """Hold *limit* attempts per address per *seconds*."""
        self.limit = limit
        self.seconds = seconds
        self._seen: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, peer: str) -> bool:
        """
        Count one attempt from *peer*.

        Args:
            peer: The client address.

        Returns:
            False when this attempt is over the limit. It is not counted then,
            so a caller that waits out the window is let back in.
        """
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


# ==============================================
# STORE
# ==============================================


def store_path() -> Path:
    """
    Where the pairing store lives.

    Returns:
        Path to pairings.json, beside tokens.json, whether or not it exists yet.
    """
    return secrets_store.SECRETS_BASE / host_tokens.TOKEN_PROVIDER / f"{PAIRING_SLUG}.json"


def load_pairings() -> List[Dict[str, Any]]:
    """
    Read every pairing row.

    Returns:
        The rows. An absent store is no rows: nothing was ever minted.

    Raises:
        PairingError: The store exists and cannot be read or is not the store's
            shape. Never an empty list: an empty list would refuse a live code
            as unknown and hide why.
    """
    path = store_path()
    if not path.exists():
        return []

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PairingError(f"The pairing store at {path} cannot be read ({type(e).__name__})") from e

    rows = stored.get("pairings") if isinstance(stored, dict) else None
    if not isinstance(rows, list):
        raise PairingError(f"The pairing store at {path} has no 'pairings' list")
    return [row for row in rows if isinstance(row, dict)]


def _save_pairings(rows: List[Dict[str, Any]]) -> None:
    """Write the rows through the token store's atomic owner-only write."""
    try:
        host_tokens.write_private_json(store_path(), {"version": STORE_VERSION, "pairings": rows})
    except OSError as e:
        raise PairingError(f"The pairing store at {store_path()} cannot be written ({type(e).__name__})") from e


def _expires(row: Dict[str, Any]) -> Optional[datetime]:
    """
    When a row dies.

    Returns:
        The expiry as an aware datetime, or None when the row's stamp cannot be
        read. None is dead: a code nobody can date is not honoured.
    """
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


# ==============================================
# BIND
# ==============================================


def bind_address(allow_loopback: bool = True) -> Tuple[str, int]:
    """
    The stored bind, as an address a browser can open.

    Args:
        allow_loopback: False for the pair verb: a loopback bind serves a
            desktop browser on this machine and never a phone.

    Returns:
        (host, port) from the stored config.

    Raises:
        PairingError: No host is stored, it is not an address, it is a
            wildcard, or it is loopback where that was refused.
    """
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
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{port}/#pair={code}"


# ==============================================
# MINT / REDEEM
# ==============================================


def mint_pairing(label: str, scope: str = "read", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Dict[str, Any]:
    """
    Mint a one-use pairing code.

    Args:
        label: The name the paired token will carry, e.g. "phone".
        scope: 'read' or 'operate', the paired token's scope.
        ttl_seconds: The code's life, 30 to 900.

    Returns:
        {"id", "label", "scope", "code", "expires_at" (ISO 8601, UTC), "url"},
        url being http://<bind host>:<bind port>/#pair=<code>.

    Raises:
        PairingError: Empty label, unknown scope, a ttl outside 30..900, a
            stored bind with no address a phone can open, or a store that
            cannot be read or written. Nothing is stored when it raises.
    """
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

    # id, label and scope. The code never reaches a log.
    logger.info("[host_api] pairing minted: id=%s label=%s scope=%s ttl=%ss", row["id"], wanted, scope, ttl_seconds)
    json_handler.log_operation("host_api_pairing_minted", {"id": row["id"], "scope": scope, "ttl": ttl_seconds})
    return {"id": row["id"], "label": wanted, "scope": scope, "code": code, "expires_at": row["expires"], "url": url}


def redeem_pairing(raw: str, peer: str = "unknown") -> Optional[Dict[str, Any]]:
    """
    Trade a live code for a bearer minted for its label and scope.

    Args:
        raw: The code as the phone posted it.
        peer: The caller's address, for the refusal's log line.

    Returns:
        {"token", "id", "label", "scope"}: the raw bearer and its record's
        fields. None when the code is unknown, expired or already used; which
        of the three goes to the log, never to the caller. No receipt file is
        written: the phone holds the only copy.

    Raises:
        PairingError: The store cannot be read, written or locked, or the mint
            after the code was spent failed. The code is spent either way.
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
            # The sweep, keeping the row spent just now: a second try of the
            # same code is then refused as used, not unknown, in the log.
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
    """
    POST /v1/pair's whole answer, with no web framework in it.

    Args:
        payload: The parsed JSON body, whatever it turned out to be.
        peer: The caller's address.
        window: The app's attempt window.

    Returns:
        (200, {"token", "id", "label", "scope"}), or (status, {"code", "message"})
        for 429 too_many_attempts, 400 invalid_request and 401 pairing_refused.

    Raises:
        PairingError: The store failed (redeem_pairing); the route answers 503.
    """
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


# ==============================================
# QR
# ==============================================


def render_qr(text: str) -> str:
    """
    The QR of *text* as terminal block characters.

    Args:
        text: What the code encodes, a pairing URL here.

    Returns:
        segno's compact rendering with a border of 1, no trailing newline.
        Pure text: no image, no file, no colour codes.

    Raises:
        PairingError: The text is empty.
    """
    if not text or not text.strip():
        raise PairingError("Nothing to render: a QR of an empty text opens nothing")

    rendered = io.StringIO()
    segno.make(text, micro=False).terminal(out=rendered, compact=True, border=1)
    return rendered.getvalue().rstrip("\n")
