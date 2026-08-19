# =================== AIPass ====================
# Name: server.py
# Description: Host API Server Handler — FastAPI app factory, auth dependency
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# pyright: reportArgumentType=false
# The suppressions above cover the optional-dependency placeholders: when the
# [host] extra is absent these names are None, and every path that touches them
# is guarded by HOST_API_AVAILABLE, which the checker cannot narrow across a
# module boundary. Same pattern as handlers/google/auth.py.

"""
Host API Server Handler

The Stage 0 skeleton (FPLAN-0411 Phase 1): app factory, bearer auth, and the two
endpoints the auth layer needs to prove itself. Everything else in the contract
is a NAMED RESERVATION below — the read lane, the verb lane and push land in
Phases 2-4, and several are held on seams other branches owe.

FastAPI and uvicorn are optional dependencies (the [host] extra). Missing libs
fail loudly with install instructions — the same guarded pattern this branch uses
for the Google stack, never a silent no-op.

Endpoints in Phase 1:
    GET /v1/ping    - 204, no auth. Tells "tunnel down" from "token rejected"
                      without leaking whether the token was close.
    GET /v1/whoami  - read scope. The auth layer proving itself end to end, and
                      the phone's enrollment check. Returns only what the caller
                      already holds.

Endpoints added in Phase 2 (read lane):
    GET /v1/feed    - read scope. Cursor-first, clamped both ends, gap flagged.
    GET /v1/roots   - read scope. Every place the file lane may stand: home,
                      every project in @baud's census, this server's own repo.
    GET /v1/files   - read scope. Names not paths, 512KB cap, cap is reported.
                      Optional root kind; absent is the branch meaning always.
    GET /v1/diff    - read scope. One patch, routed through drone, never raw:
                      a working tree, a whole repository, or one commit, and
                      optionally ONE file out of any of them.

Phase 6 grows that read lane into the phone's git surface (DPLAN-0303). Every
answer NAMES ITS OWN GRAIN, because a file list that does not say its scope is
one a client can silently read at the wrong one:
    GET /v1/git-changes - read scope. Changed files. Branch grain is @baud's
                          desktop card contract; repo grain is the app's
                          question, every changed file in the repository.
    GET /v1/git-log     - read scope. Recent commits. ALWAYS repo grain — the
                          branch names which repository, never which history.
    GET /v1/commit      - read scope. One commit's facts and per-file stats.
                          Its patch rides on /v1/diff, one file at a time, so a
                          phone never loads a whole commit at once.
    GET /v1/git-remote  - read scope. The repository's remote, so the face can
                          build link-cards out to the forge with no auth and no
                          network call. Shells NOTHING: there is no door for it
                          on drone and the fleet gate refuses both raw readers,
                          so the configuration is read as the file it is.

Phase 5 adds the phone face itself, served from this same origin (see face.py):
    GET /             - @baud's bundle. NO auth: a browser navigating to a URL
                        cannot send a bearer header, and the shell discloses
                        nothing. Every byte of data stays behind /v1/*.

Endpoints added on C1 (routed, but the exec behind them is GATED):
    GET /v1/fleet   - read scope. @baud's snapshot envelope, unchanged.
    GET /v1/rooms   - read scope. A filter over that same snapshot.
    GET /v1/roster  - read scope. Every working agent in EVERY project, from
                      @baud's own cross-project sweep. Takes no parameters:
                      a dropped filter reads as a filter that worked.

Both answer 503 with a named reason until `fleet.SNAPSHOT_READY` is flipped.
@baud's flag is verified in their tree, but the shipped release binary predates
it and would open a GUI window instead of erroring — see fleet.py. Their schema
is implemented field-for-field, so nothing here changes when the gate opens.

Phase 3 adds the verb lane — POST only, operate scope only (see verbs.py):
    POST /v1/verbs/wake            - Proxied to @ai_mail's dispatch door. The
                                     admin keyword is UNREACHABLE through it,
                                     not merely set False.
    POST /v1/verbs/kill            - Routed, validated and GATED: @baud has no
                                     headless kill, and theirs is the one door.
    POST /v1/verbs/lock            - Proxied to @skills' screen_lock. Never
                                     gated — lock must fire from anywhere.

RESERVED, NOT BUILT (FPLAN-0411; do not add without the phase that owns it):
    POST /v1/notify                - Phase 4, content-minimized through the relay
    quick-send / interrupt         - later round, CONFIRMED build (agnostic
                                     ruling). Reuses @ai_mail's verified
                                     injection path — never a raw send-keys
                                     here. @baud reproduced the bare-slash trap
                                     twice live, once landing on /remote-env.

Functions:
    is_available()  - Whether the [host] extra is installed
    create_app()    - Build the FastAPI application
    serve()         - Validate the bind, then run uvicorn
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import feed as host_feed
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import memory_config as host_memory_config
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.apps.handlers.host import settings as host_settings
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import uploads as host_uploads
from aipass.api.apps.handlers.host import verbs as host_verbs


class UnavailableHTTPException(Exception):
    """
    Stand-in for FastAPI's HTTPException when the [host] extra is absent.

    It mirrors the real signature because the name is both raised and handed to
    @app.exception_handler(), which wants a class. Learning banked on d7330b00:
    an import fallback that lands in a type position cannot be None.
    """

    def __init__(self, status_code: int = 500, detail: Any = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


try:
    from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse, Response
    from fastapi.security import HTTPBearer
    from fastapi.staticfiles import StaticFiles

    HOST_API_AVAILABLE = True
except ImportError as e:
    logger.warning("[host_api] server libraries not available: %s", e)

    Body = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    FastAPI = None  # type: ignore[assignment, misc]
    File = None  # type: ignore[assignment, misc]
    UploadFile = None  # type: ignore[assignment, misc]
    # Not None: handed to @app.exception_handler(), which wants a class. Same
    # reason HTTPException gets a stand-in rather than a None above.
    RequestValidationError = UnavailableHTTPException  # type: ignore[assignment, misc]
    # Not None: this name is raised and also handed to @app.exception_handler(),
    # both of which need a class. See UnavailableHTTPException above.
    HTTPException = UnavailableHTTPException  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    WebSocket = None  # type: ignore[assignment, misc]
    JSONResponse = None  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]
    FileResponse = None  # type: ignore[assignment, misc]
    HTTPBearer = None  # type: ignore[assignment, misc]
    StaticFiles = None  # type: ignore[assignment, misc]

    HOST_API_AVAILABLE = False

# Multipart is a SECOND optional dependency, guarded separately from the rest of
# the [host] extra because FastAPI raises at ROUTE-REGISTRATION time when a form
# route exists and this is missing — an unguarded upload route would take the
# whole server down for someone who has fastapi and uvicorn but not this. The
# route is registered either way and answers 503 with the install hint, because
# a 404 on a route that should exist reads as "wrong URL" and sends the caller
# looking in the wrong place.
try:
    # python_multipart, not multipart: the old top-level name still resolves but
    # warns, and it is a DIFFERENT package on PyPI that some environments have
    # instead. Importing the one FastAPI actually uses is the only check worth
    # making — the other name could succeed and still leave the route broken.
    import python_multipart  # noqa: F401  (imported for availability, not for use)

    MULTIPART_AVAILABLE = True
except ImportError as e:
    logger.warning("[host_api] multipart support not available — the upload route will refuse: %s", e)

    MULTIPART_AVAILABLE = False

MULTIPART_HINT = "pip install 'aipass[host]' — the upload route needs python-multipart to read a form body"

INSTALL_HINT = "pip install -e '.[host]'  (or: pip install fastapi uvicorn)"

# Auto-error off: we shape our own 401 so every failure leaves through the same
# envelope, and so a missing header cannot be told from a bad token by its shape.
_bearer = HTTPBearer(auto_error=False) if HOST_API_AVAILABLE else None


def is_available() -> bool:
    """
    Whether the [host] extra is installed.

    Returns:
        True if FastAPI imported successfully.
    """
    return HOST_API_AVAILABLE


# ==============================================
# AUTH
# ==============================================


def _deny(status: int, code: str, message: str, **extra: Any) -> Any:
    """
    Build the standard error response.

    Args:
        status: HTTP status code.
        code: Short machine-readable code.
        message: Human-readable explanation.
        **extra: Additional keys to carry INSIDE the error object. Same widening
            the validation normaliser uses for `fields` — the envelope grows,
            `code` and `message` are always there, and nothing a client had
            before is taken away.

    Returns:
        An HTTPException carrying the shared error envelope.
    """
    error: Dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return HTTPException(status_code=status, detail={"error": error})


def _peer(request: Any) -> str:
    """
    Name the caller's address for the audit trail.

    Args:
        request: The incoming request.

    Returns:
        The peer address, or 'unknown' when the transport does not expose one.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None

    # 'unknown' rather than a blank: an audit line that silently drops the field
    # reads as though nobody thought to record it.
    return str(host) if host else "unknown"


def _validation_sentence(errors: list) -> str:
    """
    Turn a validation failure into the sentence a phone can show.

    Args:
        errors: FastAPI's structured error list.

    Returns:
        One line naming each bad field and what is wrong with it. 'body' is
        dropped from the location because every field on a POST is in the body
        and repeating it says nothing — 'image: Field required' is the whole
        useful content of a 422, and it is what the operator needs to read.
    """
    parts = []
    for error in errors:
        pieces = [str(piece) for piece in error.get("loc", ()) if str(piece) != "body"]
        location = ".".join(pieces) or "body"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")

    # Never empty: a 422 whose message is a blank string is the same failure
    # this handler exists to fix, one layer further in.
    return "; ".join(parts) or "The request could not be validated"


def _declared_length(upload: Any) -> Optional[int]:
    """
    The size an upload CLAIMS to be, if it claimed one.

    Only ever used to refuse early. A body that lies about its length is caught
    by the running total while it is read, so this is a cheap first gate and
    never the one the cap depends on — trusting it alone is how a 25MB cap
    lets a 200MB body through with a small number in its header.

    Args:
        upload: The uploaded file object.

    Returns:
        The declared size, or None when the request sent no usable
        Content-Length — which is the normal case for a chunked upload.
    """
    headers = getattr(upload, "headers", None)
    raw = headers.get("content-length") if headers else None

    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        # A malformed header is not a size. Falling through to None means the
        # real check does the work, which is where the truth was anyway — but
        # it is worth a line, because a client sending garbage here is either
        # broken or probing, and neither leaves another trace.
        logger.warning("[host_api] ignoring an unreadable Content-Length on an upload: %r", raw)
        return None


def _audit_refusal(
    request: Any,
    reason: str,
    required: str,
    token_id: str = "",
    held: str = "",
) -> None:
    """
    Record a refused request in the durable audit trail.

    Security review condition C1. Before this, a refusal produced a log line with
    no peer address, so "which device has been knocking, and how often" had no
    answer. The audit distinguishes WHY; the response deliberately does not.

    THE RAW TOKEN NEVER ENTERS THIS FUNCTION. Only the id — which is safe, is
    what `revoke-token` takes, and is therefore the one identifier that makes an
    audit line actionable. Not a prefix of the value either: a prefix leaks
    entropy for free.

    Args:
        request: The incoming request, for the peer address and path.
        reason: Machine-readable refusal reason.
        required: Scope the endpoint demanded.
        token_id: Token id, when a valid token was identified.
        held: Scope the token actually holds, when known.
    """
    peer = _peer(request)
    path = str(getattr(getattr(request, "url", None), "path", "") or "")

    logger.warning("[host_api] auth refused: reason=%s peer=%s path=%s", reason, peer, path)

    json_handler.log_operation(
        "host_api_auth_refused",
        {
            "reason": reason,
            "peer": peer,
            "path": path,
            "method": str(getattr(request, "method", "") or ""),
            "required": required,
            "token_id": token_id,
            "held": held,
        },
    )


def require_scope(required: str = "read"):
    """
    Build a dependency enforcing bearer auth at *required* scope.

    Every request re-reads the token store, which is what makes revocation take
    effect on the next request with no restart.

    Args:
        required: Scope the endpoint demands ('read' or 'operate').

    Returns:
        A FastAPI dependency returning the authenticated token record.
    """

    def _dependency(request: Request, credentials: Optional[Any] = Depends(_bearer)) -> dict:
        if credentials is None or not getattr(credentials, "credentials", None):
            _audit_refusal(request, "missing_credentials", required)
            raise _deny(401, "unauthorized", "Bearer token required")

        record, status = host_tokens.resolve_token(credentials.credentials)
        # No record is no grant, whatever the status says. Belt and braces: the
        # pair is the contract, and this door refuses rather than trusts it.
        if record is None or status != host_tokens.STATUS_ACTIVE:
            # Unrecognised and REVOKED are byte-identical to the caller — a
            # revoked device learns "no", not "you were valid until 10:42". The
            # difference lives in the audit trail, never in the response.
            #
            # And the trail HAS it now. It did not on 2026-08-16, when Patrick's
            # phone was refused for nine minutes and this comment's promise came
            # up empty: both cases logged token_unrecognised, so "the phone held
            # a revoked credential" could not be ruled in or out from the log.
            revoked = status == host_tokens.STATUS_REVOKED
            _audit_refusal(
                request,
                "token_revoked" if revoked else "token_unrecognised",
                required,
                token_id=str((record or {}).get("id", "")),
            )
            raise _deny(401, "unauthorized", "Token not recognised")

        if not host_tokens.scope_allows(str(record.get("scope", "")), required):
            _audit_refusal(
                request,
                "scope_refused",
                required,
                token_id=str(record.get("id", "")),
                held=str(record.get("scope", "")),
            )
            raise _deny(403, "forbidden", f"This token's scope cannot perform a '{required}' action")

        # Only a token that BOTH verified and cleared its scope is "used". A
        # refused request means a credential was presented, which is the audit's
        # story, not this one — and stamping on a failed verify would let a
        # prober populate the store it is probing. Best-effort by contract: it
        # never raises, so it can never fail a request that already passed.
        host_tokens.touch_token(str(record.get("id", "")))

        return record

    return _dependency


def socket_bearer(websocket: Any, required: str = "operate") -> dict:
    """
    Authenticate a WebSocket from its subprotocol offer.

    A browser cannot set an Authorization header on a WebSocket. The two places
    a token could go are the query string and the `Sec-WebSocket-Protocol`
    header, and the query string is disqualified outright: URLs are written to
    access logs, proxy logs and browser history, so a token there is a
    credential copied to three places nobody chose.

    The client therefore offers two protocol values — a sentinel name and the
    bearer — and the server echoes back ONLY the sentinel. Echoing the token
    would put it in the handshake RESPONSE, undoing the whole point.

    Args:
        websocket: The incoming connection.
        required: Scope the socket demands.

    Returns:
        The authenticated token record.

    Raises:
        PermissionError: No credential offered, unrecognised, or wrong scope.
            One exception type on purpose: the caller closes the socket with a
            policy code either way, and a WebSocket handshake has no envelope to
            carry a reason without inventing one.
    """
    header = websocket.headers.get("sec-websocket-protocol", "")
    offered = [value.strip() for value in header.split(",") if value.strip()]

    if host_attach.BEARER_SUBPROTOCOL not in offered or len(offered) < 2:
        raise PermissionError("Bearer token required on the Sec-WebSocket-Protocol header")

    # The token is whatever was offered ALONGSIDE the sentinel. Taking it
    # positionally rather than by index tolerates a client reordering, which is
    # allowed by the protocol and would otherwise be an unexplainable 401.
    candidates = [value for value in offered if value != host_attach.BEARER_SUBPROTOCOL]
    record = None
    for candidate in candidates:
        record = host_tokens.verify_token(candidate)
        if record is not None:
            break

    if record is None:
        raise PermissionError("Token not recognised")

    if not host_tokens.scope_allows(str(record.get("scope", "")), required):
        raise PermissionError(f"This token's scope cannot perform a '{required}' action")

    host_tokens.touch_token(str(record.get("id", "")))

    return record


# ==============================================
# APP
# ==============================================


def _face_file_route(filename: str):
    """
    Build a route handler serving one file from the bundle root.

    The name is bound at app-creation time from a directory listing, never taken
    from the request, so there is no caller-supplied path here to fence.

    Args:
        filename: File name at the bundle root.

    Returns:
        An async route handler returning that file.
    """

    async def _serve_file() -> Any:
        return FileResponse(host_face.face_root() / filename)

    return _serve_file


# THE PUMP AND ITS CONTROL FRAMES, at module level rather than inside the app
# factory. They were nested there from the first cut and never needed to be:
# both take everything they touch as arguments, so there was no closure holding
# them in — only the factory's indentation, which was also the branch's last
# deep-nesting violation. Out here they read at their own depth.
async def _pump(websocket: Any, session: Any) -> None:
    """
    Run the bidirectional pump until either side goes away.

    The PTY read is blocking, so it lives on a thread executor rather than
    the event loop — a blocking read on the loop would freeze every other
    request this server is serving, which on a single-worker uvicorn means
    the whole phone.

    Args:
        websocket: The accepted connection.
        session: The live AttachSession.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    async def room_to_socket() -> None:
        """PTY output → client. Binary frames: the room emits escape
        sequences and partial UTF-8 across chunk boundaries, and decoding
        here would corrupt both."""
        while not stop.is_set():
            data = await loop.run_in_executor(host_attach.pump_executor(), session.read)
            if not data:
                break
            await websocket.send_bytes(data)
        stop.set()

    async def socket_to_room() -> None:
        """Client input → PTY. Bytes forwarded UNCHANGED — the key bar
        sends real control bytes, exactly as a keyboard would, so there is
        nothing here to interpret."""
        while not stop.is_set():
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                try:
                    session.write(message["bytes"])
                except host_attach.AttachRefused as e:
                    # A read-only watch was typed into. The session's own
                    # refusal (the layer that counts) ends the attach with
                    # the sentence — a client that types into a watch has
                    # broken the contract, and pretending the bytes landed
                    # would be the silent fallback this house refuses.
                    logger.warning("[host_api] input refused on %s: %s", session.room, e)
                    await websocket.close(code=1008, reason=str(e))
                    break
                continue

            text = message.get("text")
            if text:
                _handle_control(session, text)
        stop.set()

    tasks = [asyncio.ensure_future(room_to_socket()), asyncio.ensure_future(socket_to_room())]

    try:
        # FIRST_COMPLETED, not gather. Waiting for BOTH deadlocks on a quiet
        # room: the phone closes the sheet, socket_to_room ends, and
        # room_to_socket is still parked in a blocking os.read that will not
        # return until the room happens to print something. The detach — and
        # the SIGHUP with it — would wait on output that may never come, and
        # the executor thread would stay parked with it.
        #
        # Either direction ending means the attach is over, so the first one
        # to finish is the signal.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Always, and FIRST: hangup closes the descriptor, which is what
        # breaks the blocked reader out of os.read. Cancelling the task
        # alone would not — a thread sitting in a syscall does not notice
        # an asyncio cancellation.
        session.hangup()

        for task in tasks:
            task.cancel()

        # Let the unblocked reader finish rather than leaving it to be
        # collected mid-flight, which logs a 'task was destroyed but it is
        # pending' at whoever reads the server log next.
        await asyncio.gather(*tasks, return_exceptions=True)


def _handle_control(session: Any, text: str) -> None:
    """
    Handle a control frame from the client.

    Text frames are CONTROL, binary frames are KEYSTROKES. That split is
    what lets a resize travel on the same socket without a resize message
    ever being mistaken for something the operator typed.

    Args:
        session: The live AttachSession.
        text: The JSON control message.
    """
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[host_api] ignoring an unparseable control frame on %s", session.room)
        return

    if not isinstance(message, dict) or message.get("type") != "resize":
        logger.warning("[host_api] ignoring an unknown control frame on %s", session.room)
        return

    try:
        session.resize(message.get("cols"), message.get("rows"))
    except (host_attach.AttachRefused, host_attach.AttachUnavailable, OSError) as e:
        # Never fatal: a bad resize should not drop a live session the
        # operator is working in.
        logger.warning("[host_api] resize refused on %s: %s", session.room, e)


def _room_for(branch: str, project: str, external: bool, shell: bool, seated: str) -> Any:
    """
    Work out WHICH room a socket is asking for, before anything is opened.

    Pulled out of the attach route rather than left inline: the route was the
    branch's last two deep-nesting violations, and this was the whole reason —
    a three-way resolution tree sitting inside a try, inside a WebSocket
    handler, inside the app factory. Out here it reads at its own depth, and
    what it decides is now something that can be reasoned about on its own.

    Resolution ONLY. Nothing is spawned here, which keeps the route's single
    spawn site single — the property test_the_session_is_created_once_per_socket
    pins by counting that one call.

    Args:
        branch: The branch named on the socket, or empty.
        project: The project named on the socket, or empty for the seat.
        external: True when that project is not the one this server sits in.
        shell: True when the caller asked for a shell rather than an agent room.
        seated: The seat's own project name, for naming a room that omits one.

    Returns:
        (target, cwd, scope, room) — the room's human name, the directory to
        open it in, the project scope, and the room name. An empty room name
        means "the agent naming rule decides", which is what an agent room
        wants; a shell always names its own, because the agent rule would land
        it in the agent's session.

    Raises:
        AttachRefused: No branch and no shell asked for (this lane has no
            default room — key learning #22), an unknown branch in a foreign
            project, or a census that reports no root to open a shell in.
    """
    room = ""

    if branch:
        if external:
            row = host_fleet.resolve_branch(project, branch)
            if row is None:
                raise host_attach.AttachRefused(f"Project {project!r} has no branch named {branch!r}")
            target = f"@{branch} ({project})"
            cwd = Path(str(row.get("path", "")))
            scope = project.strip().lower()
        else:
            target = host_verbs.citizen_address(branch)
            cwd = host_reads.resolve_branch_root(branch)
            scope = ""

        if shell:
            room = host_attach.shell_room_name(project or seated, branch)
            target = f"shell {target}"

        return target, cwd, scope, room

    if shell:
        # The one door with no branch: a shell at the project's root.
        cwd = Path(_census_root(project)) if external else host_reads.repo_root()
        return f"shell ({project or seated})", cwd, "", host_attach.shell_room_name(project or seated)

    raise host_attach.AttachRefused("A branch name is required — this lane has no default room")


def _census_root(project: str) -> str:
    """
    The directory a foreign project's shell opens in, per @baud's census.

    Args:
        project: The foreign project's name.

    Returns:
        The project's root directory as the census reports it.

    Raises:
        AttachRefused: The census answered but named no root. Refused in words
            rather than opening a shell in whatever the process happened to be
            standing in.
    """
    root = str(host_fleet.read_snapshot(project).get("root", "")).strip()

    if not root:
        raise host_attach.AttachRefused(f"Census for {project!r} reports no root to open a shell in")

    return root


def create_app() -> Any:
    """
    Build the FastAPI application.

    Returns:
        The configured FastAPI app.

    Raises:
        RuntimeError: The [host] extra is not installed.
    """
    if not HOST_API_AVAILABLE:
        raise RuntimeError(f"Host API requires FastAPI and uvicorn. Install with: {INSTALL_HINT}")

    app = FastAPI(
        title="AIPass Host API",
        version="0.1.0",
        description="Stage 0 host API for the BAUD phone face (FPLAN-0411)",
    )

    @app.exception_handler(HTTPException)
    async def _envelope_handler(request: Request, exc: HTTPException) -> Any:
        """Send every refusal this server RAISES through the one envelope."""
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            payload = detail
        else:
            payload = {"error": {"code": "error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_envelope_handler(request: Request, exc: Any) -> Any:
        """
        The other half of the envelope, and it was missing until @baud hit it.

        Validation fires IN FRONT of every handler, so it never reached the
        envelope above — it emitted FastAPI's own `{"detail": [...]}` instead.
        A client coding to the documented shape therefore lost the sentence on
        EVERY validation error, on every route: Patrick was holding a phone
        reading "HTTP 422" while that same response body named the exact field
        and the exact problem.

        The sentence is the product here, the way it is everywhere else on this
        server. `fields` keeps the structured original so nothing a client had
        before is taken away — this widens the envelope, it does not narrow it.
        """
        errors = exc.errors() if hasattr(exc, "errors") else []
        payload = {
            "error": {
                "code": "invalid_request",
                "message": _validation_sentence(errors),
                "fields": [
                    {"loc": [str(piece) for piece in error.get("loc", ())], "msg": str(error.get("msg", ""))}
                    for error in errors
                ],
            }
        }
        logger.warning("[host_api] rejected a malformed request: %s", payload["error"]["message"])
        return JSONResponse(status_code=422, content=payload)

    # `def`, NOT `async def`, on every route whose body blocks (DPLAN-0305).
    # A handler declared async runs ON the event loop: while it shells out to
    # drone or reads a registry, the single worker answers NOTHING — a 90ms
    # snapshot froze /v1/ping for 90ms. Declared sync, FastAPI runs it in the
    # anyio threadpool and the loop stays free. Only handlers that genuinely
    # await (the socket lane) or do no blocking work at all (ping, whoami) stay
    # async, and the routes that WRITE stay async on purpose — the loop is
    # their only serialization until settings grows a lock (todo, AXIS 2).
    # Pinned structurally in test_host_perf.py: a body with no await must not
    # be async, and one slow route must not delay a fast one.

    # response_class + the Response return annotation keep FastAPI from
    # inferring a body model — 204 must not carry one.
    @app.get("/v1/ping", status_code=204, response_class=Response)
    async def ping() -> Response:
        """Liveness with no auth and no body — reachability, nothing more."""
        return Response(status_code=204)

    @app.get("/v1/whoami")
    async def whoami(record: dict = Depends(require_scope("read"))) -> dict:
        """Echo the calling token's own identity. Enrollment's proof of life."""
        return {
            "id": record.get("id"),
            "label": record.get("label"),
            "scope": record.get("scope"),
        }

    @app.get("/v1/feed")
    def feed(
        since: Optional[str] = None,
        limit: int = host_feed.DEFAULT_LIMIT,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Cursor-first notification window. See feed.py for the clamp doctrine."""
        try:
            return host_feed.read_feed(since=since, limit=limit)
        except host_feed.FeedUnavailable as e:
            raise _deny(503, "feed_unavailable", str(e)) from e

    @app.get("/v1/roots")
    def roots(record: dict = Depends(require_scope("read"))) -> dict:
        """Every place the file lane may stand. 503 rather than a short list
        when the census is gone — reads.list_roots carries the reasoning."""
        try:
            return host_reads.list_roots()
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "roots_unavailable", str(e)) from e

    @app.get("/v1/files")
    def files(
        file: str,
        branch: str = "",
        project: str = "",
        root: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Read a file by NAME under a root — no path parameter exists here.
        `branch` is the name WITHIN the kind `root` names, and is no longer
        signature-required (home and aipass name nothing), so omitting it on
        the branch lane is refused by the fence (400), not validation (422)."""
        try:
            return host_reads.read_file(branch=branch, file=file, project=project, root=root)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/dir")
    def dir_listing(
        branch: str = "",
        dir: str = "",
        project: str = "",
        root: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One directory level under a root, by NAME. The phone's file browser."""
        try:
            return host_reads.list_dir(branch=branch, dir=dir, project=project, root=root)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    if MULTIPART_AVAILABLE:

        @app.post("/v1/files/upload")
        def files_upload(
            image: UploadFile = File(...),
            record: dict = Depends(require_scope("operate")),
        ) -> dict:
            """
            Store one image from the phone and return the absolute path.

            Operate scope, because it writes to disk. The response path is the
            entire product of this route — the phone types it into the open
            attach socket, which is how the image reaches an agent.

            The client's own filename is not a parameter here. `image.filename`
            exists on the object FastAPI hands over and is deliberately never
            read: a name that arrives from a phone is attacker-controlled, and
            the only sanitiser worth trusting is not having the input at all.
            """
            try:
                return host_uploads.store_image(image.file, _declared_length(image))
            except host_uploads.UploadRefused as e:
                raise _deny(400, "upload_refused", str(e)) from e
            except host_uploads.UploadUnavailable as e:
                raise _deny(503, "upload_unavailable", str(e)) from e

    else:

        @app.post("/v1/files/upload")
        async def files_upload_unavailable(
            record: dict = Depends(require_scope("operate")),
        ) -> dict:
            """
            The same route, answering honestly when it cannot do the job.

            Registered rather than omitted: a 404 here would tell the phone the
            URL is wrong, which is the one thing it is not. 503 with the hint
            says the door exists and this host is missing a part.
            """
            raise _deny(503, "upload_unavailable", MULTIPART_HINT)

    @app.get("/v1/diff")
    def diff(
        branch: str,
        staged: bool = False,
        project: str = "",
        path: str = "",
        grain: str = "",
        ref: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One patch: a working tree, a whole repository, or one commit."""
        try:
            return host_git.read_diff(
                branch=branch,
                staged=staged,
                project=project,
                path=path,
                grain=grain,
                ref=ref,
            )
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/git-changes")
    def git_changes(
        branch: str,
        project: str = "",
        grain: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Changed files — @baud's card contract at branch grain, the repo's at repo."""
        try:
            return host_git.read_git_changes(branch=branch, project=project, grain=grain)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/git-log")
    def git_log(
        branch: str,
        project: str = "",
        limit: int = host_git.DEFAULT_LOG_COMMITS,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """The repository's recent commits. The branch names WHICH repository."""
        try:
            return host_git.read_git_log(branch=branch, project=project, limit=limit)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/git-remote")
    def git_remote(
        branch: str,
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """The repository's remote — what the face's link-cards are built from."""
        try:
            return host_git.read_git_remote(branch=branch, project=project)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/commit")
    def commit(
        branch: str,
        ref: str,
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One commit's facts and per-file stats. Its patch rides on /v1/diff."""
        try:
            return host_git.read_commit(branch=branch, ref=ref, project=project)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/fleet")
    def fleet(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@baud's fleet snapshot, passed through without an adapter."""
        try:
            return host_fleet.read_snapshot(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e

    @app.get("/v1/projects")
    def projects(
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@baud's project census — the switcher menu's rows, unchanged."""
        try:
            return host_fleet.list_projects()
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e

    @app.get("/v1/roster")
    def roster(
        request: Request,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """
        Every working agent in every project — @baud's own sweep, passed through.

        This route takes NO parameters. A `project=` would look like a filter
        and be dropped, which is worse than a refusal: the phone would render a
        wheel it believes is scoped. The binary refuses the same argument for
        the same reason, so both faces fail identically. Every parameter is
        refused, not just `project` — otherwise the next filter someone invents
        is ignored in silence under a different key.
        """
        if request.query_params:
            named = ", ".join(sorted(request.query_params.keys()))
            raise _deny(
                400,
                "roster_refused",
                f"/v1/roster takes no parameters and will not silently drop one — received: {named}. "
                "The roster spans every project by definition; there is nothing here to filter.",
            )

        try:
            return host_fleet.read_roster()
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e
        except host_fleet.FleetMisuse as e:
            # Ours, not the caller's: this server built an argv the binary
            # refuses, and no retry makes that better.
            raise _deny(500, "roster_misuse", str(e)) from e

    @app.get("/v1/rooms")
    def rooms(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Room projection of the same snapshot. A filter, never a judgment."""
        try:
            return host_fleet.read_rooms(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e

    # ── The memory-config lane (DPLAN-0302) ───────────────────────────────
    # @memory's rollover limits, read and written through @memory's own verbs.
    # Reads are read scope; every write is operate.
    #
    # Their refusals EXIT 0 — branch-wide convention on their side — so a
    # refusal is detected from the `ok` in their payload, never from the code.
    #
    # A REFUSAL IS 400 memory_config_refused HERE, wherever it was decided: an
    # argument this server rejects before routing and a sentence @memory speaks
    # after it answer identically, with their words in `message`, their remedy
    # line in `suggestion`, and their whole payload in `raw`. This lane
    # deliberately does NOT use the verb lane's {ok: false} at 200 — there, a
    # refused wake is a normal outcome of asking and the phone renders it; here,
    # a refused write to fleet configuration is a caller error. Shipping both
    # shapes at once is exactly the bug @baud found reading this file.
    #
    # 503 stays what it always was — nobody was home — and now also covers an
    # answer that did not parse. After a write that is the honest report: this
    # server cannot tell whether it happened, and a 200 would be a guess about
    # Patrick's configuration.

    @app.get("/v1/memory-config")
    def memory_config(
        branch: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Rollover limits: the fleet view, or one branch's effective set."""
        try:
            return host_memory_config.read_config(branch=branch)
        except host_memory_config.MemoryConfigRefused as e:
            raise _deny(400, "memory_config_refused", str(e), raw=e.raw, suggestion=e.suggestion) from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _deny(503, "memory_config_unavailable", str(e)) from e

    @app.post("/v1/memory-config/set")
    async def memory_config_set(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Override one branch's limit for one entry type."""
        try:
            return host_memory_config.set_branch_limit(
                branch=payload.get("branch", ""),
                entry_type=payload.get("type", ""),
                count=payload.get("count"),
            )
        except host_memory_config.MemoryConfigRefused as e:
            raise _deny(400, "memory_config_refused", str(e), raw=e.raw, suggestion=e.suggestion) from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _deny(503, "memory_config_unavailable", str(e)) from e

    @app.post("/v1/memory-config/set-default")
    async def memory_config_set_default(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """
        Change one global default.

        Answers with pushed=false always: per_branch is untouched, so every
        branch keeps reporting its old number until a push. @memory's
        semantics, surfaced rather than smoothed over here.
        """
        try:
            return host_memory_config.set_default_limit(
                entry_type=payload.get("type", ""),
                count=payload.get("count"),
            )
        except host_memory_config.MemoryConfigRefused as e:
            raise _deny(400, "memory_config_refused", str(e), raw=e.raw, suggestion=e.suggestion) from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _deny(503, "memory_config_unavailable", str(e)) from e

    @app.post("/v1/memory-config/push")
    async def memory_config_push(
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Reset EVERY branch to the defaults. Takes no body."""
        try:
            return host_memory_config.push_defaults()
        except host_memory_config.MemoryConfigRefused as e:
            raise _deny(400, "memory_config_refused", str(e), raw=e.raw, suggestion=e.suggestion) from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _deny(503, "memory_config_unavailable", str(e)) from e

    # ── The verb lane (Phase 3) ───────────────────────────────────────────
    # POST only, operate scope only. Every one of these is a proxy: the branch
    # that owns the mechanism is named in verbs.py, and this file maps its two
    # exception types onto the two honest status codes — 400 when the caller got
    # it wrong, 503 when a mechanism could not be reached at all.
    #
    # A mechanism that RAN and said no is neither: it comes back 200 with
    # {ok: false} and the door's own sentence, which @baud renders verbatim.
    #
    # Bodies are read as plain fields, never bound to a model, so an unknown key
    # is ignored rather than rejected. That is deliberate: @baud's client sends
    # no `confirmed` flag and this server would not honour one if it did — their
    # confirm dialog is pocket-safety, and pocket-safety is not authorisation.

    @app.post("/v1/verbs/wake")
    async def verb_wake(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Wake a citizen. Proxied to @ai_mail; admin is unreachable from here."""
        try:
            return host_verbs.wake_branch(
                branch=str(payload.get("branch") or ""),
                project=str(payload.get("project") or ""),
                message=str(payload.get("message") or ""),
                fresh=bool(payload.get("fresh")),
            )
        except host_verbs.VerbRefused as e:
            raise _deny(400, "verb_refused", str(e)) from e
        except host_verbs.VerbUnavailable as e:
            raise _deny(503, "verb_unavailable", str(e)) from e

    @app.post("/v1/verbs/kill")
    async def verb_kill(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """End a branch's session through @baud's door. Explicit target always."""
        try:
            return host_verbs.kill_room(
                branch=str(payload.get("branch") or ""),
                project=str(payload.get("project") or ""),
            )
        except host_verbs.VerbRefused as e:
            raise _deny(400, "verb_refused", str(e)) from e
        except host_verbs.VerbUnavailable as e:
            raise _deny(503, "verb_unavailable", str(e)) from e

    @app.post("/v1/verbs/lock")
    async def verb_lock(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Lock the machine, through @skills. Takes nothing and asks nothing."""
        return host_verbs.lock_screen()

    # ---------------------------------------------------------- settings --
    # The desktop's two gears, served (DPLAN-0300): reads ride the read scope
    # because a dial's position is observation; writes are operate because
    # they change how agents wake and compact. Both faces write the SAME
    # files through the same surgical rules — settings.py mirrors settings.rs
    # so the gears can never drift on the operator's own config. Seat-scoped
    # like the desktop's: the settings files live in THIS repo's branches.

    @app.get("/v1/agent-settings")
    def agent_settings_read(
        branch: str,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One branch's three owned claude settings — absent keys read null."""
        try:
            return host_settings.read_agent_settings(host_reads.resolve_branch_root(branch))
        except (host_reads.ReadRefused, host_settings.SettingsRefused) as e:
            raise _deny(400, "settings_refused", str(e)) from e
        except (host_reads.ReadUnavailable, host_settings.SettingsUnavailable) as e:
            raise _deny(503, "settings_unavailable", str(e)) from e

    @app.post("/v1/agent-settings")
    async def agent_settings_write(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """
        Patch one branch's claude settings. Three-state by JSON's own nature:
        an absent field touches nothing, null removes, a value sets — and
        only the three owned keys can appear, which is the surgical promise.
        """
        branch = str(payload.get("branch", ""))
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise _deny(400, "settings_refused", "the patch must be a JSON object")
        try:
            return host_settings.write_agent_settings(host_reads.resolve_branch_root(branch), patch)
        except (host_reads.ReadRefused, host_settings.SettingsRefused) as e:
            raise _deny(400, "settings_refused", str(e)) from e
        except (host_reads.ReadUnavailable, host_settings.SettingsUnavailable) as e:
            raise _deny(503, "settings_unavailable", str(e)) from e

    @app.get("/v1/baud-settings")
    def baud_settings_read(
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """BAUD's own document for the seat, whole and opaque."""
        try:
            return host_settings.read_baud_settings(host_reads.repo_root())
        except host_settings.SettingsRefused as e:
            raise _deny(400, "settings_refused", str(e)) from e
        except host_settings.SettingsUnavailable as e:
            raise _deny(503, "settings_unavailable", str(e)) from e

    @app.post("/v1/baud-settings")
    async def baud_settings_write(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Shallow-merge into BAUD's document — null removes, nested replaces."""
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise _deny(400, "settings_refused", "the patch must be a JSON object")
        try:
            return host_settings.write_baud_settings(host_reads.repo_root(), patch)
        except host_settings.SettingsRefused as e:
            raise _deny(400, "settings_refused", str(e)) from e
        except host_settings.SettingsUnavailable as e:
            raise _deny(503, "settings_unavailable", str(e)) from e

    @app.get("/v1/hooks-sound")
    def hooks_sound_read(
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@hooks' mute switch, read live — the flag file is the only truth."""
        return {"active": host_settings.hooks_sound_get()}

    @app.post("/v1/hooks-sound")
    async def hooks_sound_write(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Flip the machine-wide hook sounds — idempotent both directions."""
        active = payload.get("active")
        if not isinstance(active, bool):
            raise _deny(400, "settings_refused", "'active' must be true or false")
        try:
            return {"active": host_settings.hooks_sound_set(active)}
        except host_settings.SettingsUnavailable as e:
            raise _deny(503, "settings_unavailable", str(e)) from e

    @app.websocket("/v1/room/attach")
    async def room_attach(websocket: WebSocket, branch: str = "", project: str = "", kind: str = "") -> None:
        """
        Attach a real tmux client to a branch's room, over a WebSocket.

        Operate scope without exception: an attached room is a shell prompt, so
        there is no reading half to split off. Closing the socket detaches —
        the room and everything in it survive.

        `kind=shell` opens an EMPTY terminal instead of the agent's room — a
        plain prompt in the branch's directory, or at the project root when no
        branch is named. Same tmux discipline, separate `baud-shell-`
        namespace: a phone terminal that dies with the screen lock is useless,
        so shells persist and reattach exactly like agent rooms do.
        """
        try:
            # A watch is tier-0 OBSERVATION — live output, no keyboard, its
            # session refuses input at the layer that counts. Observation is
            # what the read scope IS; demanding operate for it would make the
            # read token a lie. Every other kind is a shell prompt with the
            # operator's credentials at it, and stays operate.
            socket_bearer(websocket, "read" if kind == "watch" else "operate")
        except PermissionError as e:
            # Refused BEFORE accept, so the handshake itself fails and no PTY is
            # ever spawned for an unauthenticated caller. A browser cannot read
            # a close code on a handshake that never completed — it reports a
            # bare connection error — and that is the right shape HERE and only
            # here: there is exactly one reason this stage refuses, so the
            # sentence the client loses is one it can already infer.
            logger.warning("[host_api] socket refused for %s: %s", branch or "<no branch>", e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=str(e))
            return

        # Accepted now that the caller is known, and deliberately BEFORE the
        # remaining checks. Everything below refuses something the operator can
        # act on — wrong branch, wrong project, no tmux — and a browser only
        # surfaces a close code and reason on an ESTABLISHED socket. Refusing
        # these pre-accept would put a fixable sentence somewhere the phone
        # cannot render it, which is a blank error screen holding an answer.
        # No PTY exists yet either way: the spawn is still below.
        #
        # Echo the SENTINEL, never the token: the accepted subprotocol appears
        # in the handshake RESPONSE, and a token there would undo the whole
        # reason it is not in the query string.
        await websocket.accept(subprotocol=host_attach.BEARER_SUBPROTOCOL)

        # WHICH project's room. The seat is the historical default; any other
        # name resolves through BAUD's own census (the same engine the desktop
        # trusts), which yields the branch's real path for the cwd and marks
        # the room with the project scope — `baud-<project>-<branch>` — so a
        # phone attach and a desktop attach always agree on which session a
        # card means. An unknown project or branch refuses with a sentence;
        # nothing ever falls back to the seat, because a fallback here attaches
        # a room nobody asked for (key learning #22).
        seated = host_reads.seated_project()
        external = bool(project) and project.strip().lower() != seated.lower()
        shell = kind == "shell"

        try:
            if kind and kind not in ("shell", "watch"):
                raise host_attach.AttachRefused(
                    f"Unknown room kind {kind!r} — this lane opens rooms, shells and watches"
                )
            if kind == "watch":
                # The desktop card's watch button (m9): `drone @prax monitor
                # run <branch>` on a read-only PTY.
                #
                # THIS USED TO REFUSE ANY PROJECT BUT THE SEAT, on the reasoning
                # that a watch is anchor tooling. Patrick ruled against it and
                # measuring settled it: `monitor run baud` answers "Live —
                # scoped to BAUD" and `monitor run vera` answers "Live — scoped
                # to VERA" plus @prax's own line, "VERA is not a known branch —
                # nothing will be shown for it". Identical from the anchor and
                # from each project's own root, so cwd was never the variable I
                # believed it was.
                #
                # @prax refuses nothing and says precisely what it can and
                # cannot show, on the screen the operator is already reading. My
                # refusal was strictly worse: it blocked the tenant case that
                # works, and would have replaced an accurate live warning with a
                # guess. So no project check here, and no allowlist of watchable
                # projects either — that would be a second model of what @prax
                # can monitor, drifting from the first time they change it.
                #
                # NO BRANCH IS A REAL ANSWER HERE, and the only lane where it
                # is. Everywhere else on this surface an absent branch is the
                # bug that killed a live session (key learning #22), which is
                # why the verb lane has no default target at all. A watch is
                # different in kind: `drone @prax monitor run` with nothing
                # after it is global mission control, the desktop's own default
                # pane, and it names no session to take over. Read-only, no
                # keyboard, nothing to seize.
                #
                # A NAMED branch still goes through the same existence gate
                # every verb uses — 'commons' is a citizen too, so the feed
                # keyword rides free.
                if branch:
                    # Existence through the same gate every verb uses, and now
                    # with the project, so a tenant's or an external project's
                    # branch is checked against ITS registry rather than the
                    # seat's — where it does not exist and never did.
                    target = f"watch {host_verbs.citizen_address(branch, project)}"
                else:
                    target = "watch (every branch)"
                session = host_attach.open_monitor(branch, cwd=host_reads.repo_root())
            else:
                target, cwd, scope, room = _room_for(branch, project, external, shell, seated)
                # ONE spawn site, whichever lane resolved it — a per-poll spawn
                # here is the leak test_the_session_is_created_once_per_socket
                # pins by counting this very call.
                session = host_attach.open_attach(branch, cwd=cwd, scope=scope, room=room)
        except (host_verbs.VerbRefused, host_attach.AttachRefused) as e:
            logger.warning("[host_api] socket refused for %s: %s", branch or "<no branch>", e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=str(e))
            return
        except host_fleet.FleetUnavailable as e:
            # The census could not answer — an unknown project name arrives
            # here too, carrying the binary's own "no project named ..."
            # sentence, which is the most actionable words this refusal has.
            logger.warning("[host_api] socket census failed for %s/%s: %s", project, branch, e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=str(e))
            return
        except (host_verbs.VerbUnavailable, host_attach.AttachUnavailable, host_reads.ReadUnavailable) as e:
            # 1011 is "server error" — ours, not the caller's, same split the
            # HTTP lanes make between 400 and 503. Logged at error rather than
            # warning for the same reason: a refusal this server caused is one
            # somebody has to go and fix, and it leaves no other trace.
            logger.error("[host_api] attach unavailable for %s: %s", branch or "<no branch>", e)
            json_handler.log_operation(
                "host_api_socket_unavailable",
                {"branch": branch, "reason": str(e), "route": "/v1/room/attach"},
            )
            await websocket.close(code=1011, reason=str(e))
            return

        logger.info("[host_api] socket attached to %s for %s", session.room, target)

        await _pump(websocket, session)

    def _audit_socket_refusal(websocket: Any, reason: str) -> None:
        """
        Record a refused socket with its peer, like the HTTP lane does.

        The structured record only — each call site logs its own sentence, so
        the log says WHICH gate turned the socket away rather than four
        identical lines that all read 'socket refused'.

        Args:
            websocket: The refused connection.
            reason: Why it was refused.
        """
        client = getattr(websocket, "client", None)
        json_handler.log_operation(
            "host_api_socket_refused",
            {"peer": getattr(client, "host", "") or "unknown", "reason": reason, "route": "/v1/room/attach"},
        )

    @app.get("/", include_in_schema=False)
    async def face_entry() -> Any:
        """
        Serve @baud's phone face.

        Unauthenticated on purpose: a browser navigating to a URL cannot send a
        bearer header, so gating this would mean inventing a second, weaker auth
        system to guard a public bundle that renders a token door and nothing
        else. The data wall is on /v1/*, where the data is.
        """
        try:
            return FileResponse(host_face.entry_file())
        except host_face.FaceUnavailable as e:
            raise _deny(503, "face_unavailable", str(e)) from e

    # NOT a catch-all. The bundle's own files get their own routes, so nothing
    # registered on this app — now or by a later caller — can be shadowed. See
    # face.py: the first cut DID mount "/" and the existing scope tests caught it.
    if host_face.is_face_available():
        if host_face.assets_dir().is_dir():
            app.mount("/assets", StaticFiles(directory=str(host_face.assets_dir())), name="face-assets")

        for filename in host_face.root_files():
            app.add_api_route(
                f"/{filename}",
                _face_file_route(filename),
                methods=["GET"],
                include_in_schema=False,
            )

        logger.info("[host_api] phone face served from %s", host_face.face_root())
    else:
        # Not fatal: the API is the product, the face is a client of it.
        logger.warning("[host_api] phone face not built — / will report it. %s", host_face.BUILD_HINT)

    # DERIVED FROM THE APP, never written down. The hand-kept list this
    # replaces named 18 doors while the app registered nearly forty — /v1/dir,
    # /v1/projects, every git route and every settings route had been missing
    # since the day they were added, and the log line kept reading as complete.
    routes = sorted({path for path in (getattr(route, "path", "") for route in app.routes) if path.startswith("/v1")})
    logger.info("[host_api] app created (read lane + verb lane: %s)", ", ".join(routes))
    json_handler.log_operation("host_api_app_created", {"phase": 3, "routes": routes})
    return app


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """
    Validate the bind address, then run the server.

    Validation happens BEFORE uvicorn is handed anything — a refused address
    must never reach a listener.

    Args:
        host: Bind address override. Defaults to the stored config.
        port: Port override. Defaults to the stored config.

    Raises:
        RuntimeError: The [host] extra is not installed.
        BindRefused: The address was refused. The server does not start.
    """
    if not HOST_API_AVAILABLE:
        raise RuntimeError(f"Host API requires FastAPI and uvicorn. Install with: {INSTALL_HINT}")

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    host_config.validate_bind(bind_host, bind_port)

    # Once, here: a long-lived server must not re-walk the filesystem for the
    # registry on every branch resolution. See config.pin_registry.
    host_config.pin_registry()

    import uvicorn

    logger.info("[host_api] serving on %s:%s", bind_host, bind_port)
    json_handler.log_operation("host_api_serve_start", {"host": bind_host, "port": bind_port})
    uvicorn.run(create_app(), host=bind_host, port=bind_port)
