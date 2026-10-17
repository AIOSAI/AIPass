# =================== AIPass ====================
# Name: server.py
# Description: Host API Server Handler — FastAPI app factory, auth dependency
# Version: 1.1.5
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# pyright: reportArgumentType=false
# The suppressions above cover the optional-dependency placeholders: when the
# [host] extra is absent these names are None, and every path that touches them
# is guarded by HOST_API_AVAILABLE, which the checker cannot narrow across a
# module boundary. Same pattern as handlers/google/auth.py.

"""
Host API Server Handler
Reference: docs/host_api.md. Routes that would push this file past its 1500-line cap live in *_route.py.
Reserved, not built: POST /v1/notify; quick-send must reuse @ai_mail's injection path, never a raw send-keys."""

import time
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import backup_route as host_backup_route
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import feed as host_feed
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import lock as host_lock
from aipass.api.apps.handlers.host import machine as host_machine
from aipass.api.apps.handlers.host import machine_route as host_machine_route
from aipass.api.apps.handlers.host import memory_config as host_memory_config
from aipass.api.apps.handlers.host import new_project_route as host_new_project_route
from aipass.api.apps.handlers.host import pair_route as host_pair_route
from aipass.api.apps.handlers.host import pump as host_pump
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import statics as host_statics
from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.apps.handlers.host import settings as host_settings
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import uploads as host_uploads
from aipass.api.apps.handlers.host import verbs as host_verbs
from aipass.api.apps.handlers.host.denials import UnavailableHTTPException

try:
    from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, Response
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
    # Not None: these two are handed to @app.exception_handler() (and HTTPException raised), which need a class.
    RequestValidationError = UnavailableHTTPException  # type: ignore[assignment, misc]
    HTTPException = UnavailableHTTPException  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    WebSocket = None  # type: ignore[assignment, misc]
    JSONResponse = None  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]
    HTTPBearer = None  # type: ignore[assignment, misc]
    StaticFiles = None  # type: ignore[assignment, misc]

    HOST_API_AVAILABLE = False

# Guarded apart from the [host] extra: FastAPI raises at route registration when a form route lacks it.
try:
    # python_multipart, not multipart: that name is a different PyPI package and can import with the route broken.
    import python_multipart  # noqa: F401  (imported for availability, not for use)

    MULTIPART_AVAILABLE = True
except ImportError as e:
    logger.warning("[host_api] multipart support not available — the upload route will refuse: %s", e)

    MULTIPART_AVAILABLE = False

MULTIPART_HINT = "pip install 'aipass[host]' — the upload route needs python-multipart to read a form body"

INSTALL_HINT = "pip install -e '.[host]'  (or: pip install fastapi uvicorn)"

# Auto-error off: our own 401 keeps one envelope, so a missing header looks like a bad token.
_bearer = HTTPBearer(auto_error=False) if HOST_API_AVAILABLE else None


def is_available() -> bool:
    """Whether the [host] extra is installed."""
    return HOST_API_AVAILABLE


def _deny(status: int, code: str, message: str, **extra: Any) -> Any:
    """Build the standard error response."""
    error: Dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return HTTPException(status_code=status, detail={"error": error})


def _logged_denial(error: Exception, status: int, code: str, **extra: Any) -> Any:
    """`_deny` for a caught exception: its words go to the host log under `ref`, the client gets the code's sentence."""
    ref = host_denials.logged(error, status, code)
    return _deny(status, code, host_denials.SENTENCES[code], ref=ref, **extra)


def _peer(request: Any) -> str:
    """Name the caller's address for the audit trail."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None

    return str(host) if host else "unknown"


def _validation_sentence(errors: list) -> str:
    """Turn a validation failure into the sentence a phone can show."""
    parts = []
    for error in errors:
        pieces = [str(piece) for piece in error.get("loc", ()) if str(piece) != "body"]
        location = ".".join(pieces) or "body"
        parts.append(f"{location}: {error.get('msg', 'invalid')}")

    # Never empty: a blank 422 message is the very failure this handler exists to fix.
    return "; ".join(parts) or "The request could not be validated"


def _declared_length(upload: Any) -> Optional[int]:
    """
    The size an upload CLAIMS to be, if it claimed one.
    Only a cheap early refusal: the cap rests on the running total while reading, never on this header.
    """
    headers = getattr(upload, "headers", None)
    raw = headers.get("content-length") if headers else None

    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
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
    The audit says WHY; the response does not. Never pass the raw token or a prefix of it: only its id.
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
    Every request re-reads the token store, so a revocation takes effect on the next request.
    """

    def _dependency(request: Request, credentials: Optional[Any] = Depends(_bearer)) -> dict:
        if credentials is None or not getattr(credentials, "credentials", None):
            _audit_refusal(request, "missing_credentials", required)
            raise _deny(401, "unauthorized", "Bearer token required")

        record, status = host_tokens.resolve_token(credentials.credentials)
        if record is None or status != host_tokens.STATUS_ACTIVE:
            # Unrecognised and revoked are byte-identical to the caller; only the audit tells them apart.
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

        # Stamp only after verify and scope pass: else a prober writes the store it probes. Never raises.
        host_tokens.touch_token(str(record.get("id", "")))

        return record

    return _dependency


def socket_bearer(websocket: Any, required: str = "operate") -> dict:
    """
    Authenticate a WebSocket from its subprotocol offer.
    Echo back ONLY the sentinel: echoing the token would put it in the handshake response.
    """
    header = websocket.headers.get("sec-websocket-protocol", "")
    offered = [value.strip() for value in header.split(",") if value.strip()]

    if host_attach.BEARER_SUBPROTOCOL not in offered or len(offered) < 2:
        raise PermissionError("Bearer token required on the Sec-WebSocket-Protocol header")

    # Not by index: a client may reorder the offer, and that must not be a 401.
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


def _room_for(branch: str, project: str, external: bool, shell: bool, seated: str) -> Any:
    """
    Work out WHICH room a socket is asking for, before anything is opened.
    Resolution only, never a spawn: test_the_session_is_created_once_per_socket counts the route's one spawn.
    An empty room means the agent naming rule decides; a shell names its own or would land in the agent's session.
    """
    room = ""
    row = None

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
            return target, cwd, scope, room, False

        # The external lane's row is handed over: one socket must not cost two snapshots.
        outside = _outside_room_for(project, branch, row)
        if outside:
            return target, cwd, scope, outside, True

        return target, cwd, scope, room, False

    if shell:
        cwd = Path(_census_root(project)) if external else host_reads.repo_root()
        return f"shell ({project or seated})", cwd, "", host_attach.shell_room_name(project or seated), False

    raise host_attach.AttachRefused("A branch name is required — this lane has no default room")


def _outside_room_for(project: str, branch: str, row: Optional[Dict[str, Any]] = None) -> str:
    """
    The session an agent is ALREADY seated in, when it is not a room BAUD made.
    `has_room` is the only guard: true keeps the branch in its own room. It says nothing about occupancy.
    A CENSUS THAT CANNOT ANSWER IS NOT AN ANSWER OF 'NO': "" leaves the attach on the naming rule, never refused.
    """
    if row is None:
        try:
            row = host_fleet.resolve_branch(project, branch)
        except host_fleet.FleetUnavailable as e:
            logger.info("[host_api] no census for the outside-room check on %s: %s", branch, e)
            return ""

    if row is None or row.get("has_room"):
        return ""

    return str(row.get("outside_room") or "").strip()


def _census_root(project: str) -> str:
    """The directory a foreign project's shell opens in, per @baud's census."""
    root = str(host_fleet.read_snapshot(project).get("root", "")).strip()

    if not root:
        raise host_attach.AttachRefused(f"Census for {project!r} reports no root to open a shell in")

    return root


def create_app() -> Any:
    """Build the FastAPI application."""
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
        Validation fires in front of every handler, so it never reaches the handler above; `fields` keeps the original.
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

    # `def`, not `async def`, on every route whose body blocks: async runs on the single worker's loop.
    # Routes that WRITE stay async on purpose: the loop is their only serialization. test_host_perf.py pins both.

    # response_class + the Response annotation keep FastAPI from inferring a body model; 204 must carry none.
    @app.get("/v1/ping", status_code=204, response_class=Response)
    async def ping() -> Response:
        """Liveness with no auth and no body — reachability, nothing more."""
        return Response(status_code=204)

    host_pair_route.register(app, _deny, _peer)

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
            raise _logged_denial(e, 503, "feed_unavailable") from e

    @app.get("/v1/roots")
    def roots(record: dict = Depends(require_scope("read"))) -> dict:
        """Every place the file lane may stand. 503 rather than a short list
        when the census is gone — reads.list_roots carries the reasoning."""
        try:
            return host_reads.list_roots()
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "roots_unavailable") from e

    @app.get("/v1/files")
    def files(
        file: str,
        branch: str = "",
        project: str = "",
        root: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Read a file by NAME under a root — no path parameter exists here."""
        try:
            return host_reads.read_file(branch=branch, file=file, project=project, root=root)
        except host_reads.ReadRefused as e:
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

    if MULTIPART_AVAILABLE:

        @app.post("/v1/files/upload")
        def files_upload(
            image: UploadFile = File(...),
            record: dict = Depends(require_scope("operate")),
        ) -> dict:
            """
            Store one image from the phone and return the absolute path.
            Never read `image.filename`: a name from a phone is attacker-controlled.
            """
            try:
                return host_uploads.store_image(image.file, _declared_length(image))
            except host_uploads.UploadRefused as e:
                raise _deny(400, "upload_refused", str(e)) from e
            except host_uploads.UploadUnavailable as e:
                raise _logged_denial(e, 503, "upload_unavailable") from e

    else:

        @app.post("/v1/files/upload")
        async def files_upload_unavailable(
            record: dict = Depends(require_scope("operate")),
        ) -> dict:
            """
            The same route, answering honestly when it cannot do the job.
            Registered rather than omitted: a 404 would tell the phone the URL is wrong.
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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

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
            raise _logged_denial(e, 400, "read_refused") from e
        except host_reads.ReadUnavailable as e:
            raise _logged_denial(e, 503, "read_unavailable") from e

    @app.get("/v1/fleet")
    def fleet(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@baud's fleet snapshot, passed through without an adapter."""
        try:
            return host_fleet.read_snapshot(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _logged_denial(e, 503, "fleet_unavailable") from e

    @app.get("/v1/projects")
    def projects(
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@baud's project census — the switcher menu's rows, unchanged."""
        try:
            return host_fleet.list_projects()
        except host_fleet.FleetUnavailable as e:
            raise _logged_denial(e, 503, "fleet_unavailable") from e

    @app.get("/v1/roster")
    def roster(
        request: Request,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """
        Every working agent in every project — @baud's own sweep, passed through.
        Every parameter is refused: a dropped filter would render a wheel the phone believes is scoped.
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
            raise _logged_denial(e, 503, "fleet_unavailable") from e
        except host_fleet.FleetMisuse as e:
            # Ours, not the caller's: this server built an argv the binary refuses.
            raise _logged_denial(e, 500, "roster_misuse") from e

    @app.get("/v1/machine")
    def machine(
        request: Request,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """The machine's vitals — @skills' machine_vitals(), relayed verbatim."""
        if request.query_params:
            named = ", ".join(sorted(request.query_params.keys()))
            raise _deny(
                400,
                "machine_parameters_refused",
                f"/v1/machine takes no parameters and will not silently drop one — received: {named}.",
            )

        try:
            return host_machine.read_machine()
        except host_machine.MachineRefused as e:
            raise _logged_denial(e, 503, "machine_refused", reason=e.reason) from e
        except host_machine.MachineDoorFailed as e:
            raise _deny(503, "machine_door_failed", str(e)) from e

    @app.get("/v1/lock")
    def lock_state(
        request: Request,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Whether the screen is locked: @skills' lock_state(), verbatim. lock.py carries the argument."""
        if request.query_params:
            named = ", ".join(sorted(request.query_params.keys()))
            raise _deny(
                400,
                "lock_parameters_refused",
                f"/v1/lock takes no parameters and will not silently drop one — received: {named}.",
            )

        try:
            return host_lock.read_lock()
        except host_lock.LockDoorFailed as e:
            raise _logged_denial(e, 503, "lock_door_failed") from e

    @app.get("/v1/rooms")
    def rooms(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Room projection of the same snapshot. A filter, never a judgment."""
        try:
            return host_fleet.read_rooms(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _logged_denial(e, 503, "fleet_unavailable") from e

    # A memory-config refusal is 400, never the verb lane's 200 {ok: false}: a refused config write is a caller error.

    @app.get("/v1/memory-config")
    def memory_config(
        branch: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Rollover limits: the fleet view, or one branch's effective set."""
        try:
            return host_memory_config.read_config(branch=branch)
        except host_memory_config.MemoryConfigRefused as e:
            raise _logged_denial(e, 400, "memory_config_refused") from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _logged_denial(e, 503, "memory_config_unavailable") from e

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
            raise _logged_denial(e, 400, "memory_config_refused") from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _logged_denial(e, 503, "memory_config_unavailable") from e

    @app.post("/v1/memory-config/set-default")
    async def memory_config_set_default(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """
        Change one global default.
        Answers pushed=false always: every branch keeps its old number until a push, by @memory's semantics.
        """
        try:
            return host_memory_config.set_default_limit(
                entry_type=payload.get("type", ""),
                count=payload.get("count"),
            )
        except host_memory_config.MemoryConfigRefused as e:
            raise _logged_denial(e, 400, "memory_config_refused") from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _logged_denial(e, 503, "memory_config_unavailable") from e

    @app.post("/v1/memory-config/push")
    async def memory_config_push(
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Reset EVERY branch to the defaults. Takes no body."""
        try:
            return host_memory_config.push_defaults()
        except host_memory_config.MemoryConfigRefused as e:
            raise _logged_denial(e, 400, "memory_config_refused") from e
        except host_memory_config.MemoryConfigUnavailable as e:
            raise _logged_denial(e, 503, "memory_config_unavailable") from e

    # Verb bodies are plain fields, never a model; a client `confirmed` flag is never authorisation.

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
            raise _logged_denial(e, 503, "verb_unavailable") from e

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
            raise _logged_denial(e, 503, "verb_unavailable") from e

    @app.post("/v1/verbs/lock")
    async def verb_lock(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """Lock the machine, through @skills. Takes nothing and asks nothing."""
        return host_verbs.lock_screen()

    host_backup_route.register(app, _deny, require_scope)
    host_machine_route.register(app, _deny, _logged_denial, require_scope)
    host_new_project_route.register(app, _deny, _logged_denial, require_scope)
    # settings.py mirrors @baud's settings.rs: both faces write the same files by the same rules.

    @app.get("/v1/agent-settings")
    def agent_settings_read(
        branch: str,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """One branch's three owned claude settings — absent keys read null."""
        try:
            return host_settings.read_agent_settings(host_reads.resolve_branch_root(branch))
        except (host_reads.ReadRefused, host_settings.SettingsRefused) as e:
            raise _logged_denial(e, 400, "settings_refused") from e
        except (host_reads.ReadUnavailable, host_settings.SettingsUnavailable) as e:
            raise _logged_denial(e, 503, "settings_unavailable") from e

    @app.post("/v1/agent-settings")
    async def agent_settings_write(
        payload: dict = Body(default={}),
        record: dict = Depends(require_scope("operate")),
    ) -> dict:
        """
        Patch one branch's claude settings. Three-state by JSON's own nature:
        an absent field touches nothing, null removes, a value sets.
        """
        branch = str(payload.get("branch", ""))
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            raise _deny(400, "settings_refused", "the patch must be a JSON object")
        try:
            return host_settings.write_agent_settings(host_reads.resolve_branch_root(branch), patch)
        except (host_reads.ReadRefused, host_settings.SettingsRefused) as e:
            raise _logged_denial(e, 400, "settings_refused") from e
        except (host_reads.ReadUnavailable, host_settings.SettingsUnavailable) as e:
            raise _logged_denial(e, 503, "settings_unavailable") from e

    @app.get("/v1/baud-settings")
    def baud_settings_read(
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """BAUD's own document for the seat, whole and opaque."""
        try:
            return host_settings.read_baud_settings(host_reads.repo_root())
        except host_settings.SettingsRefused as e:
            raise _logged_denial(e, 400, "settings_refused") from e
        except host_settings.SettingsUnavailable as e:
            raise _logged_denial(e, 503, "settings_unavailable") from e

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
            raise _logged_denial(e, 400, "settings_refused") from e
        except host_settings.SettingsUnavailable as e:
            raise _logged_denial(e, 503, "settings_unavailable") from e

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
            raise _logged_denial(e, 503, "settings_unavailable") from e

    @app.websocket("/v1/room/attach")
    async def room_attach(websocket: WebSocket, branch: str = "", project: str = "", kind: str = "") -> None:
        """Attach a real tmux client to a branch's room, over a WebSocket."""
        try:
            # A watch has no keyboard: observation is read scope. Every other kind is a shell prompt.
            socket_bearer(websocket, "read" if kind == "watch" else "operate")
        except PermissionError as e:
            # Refused BEFORE accept: no PTY is ever spawned for an unauthenticated caller.
            logger.warning("[host_api] socket refused for %s: %s", branch or "<no branch>", e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=str(e))
            return

        # Accepted BEFORE the remaining checks: a browser shows a close reason only on an established socket.
        # Echo the SENTINEL, never the token: the accepted subprotocol appears in the handshake response.
        await websocket.accept(subprotocol=host_attach.BEARER_SUBPROTOCOL)

        # An unknown project or branch refuses; never fall back to the seat, which attaches a room nobody asked for.
        seated = host_reads.seated_project()
        external = bool(project) and project.strip().lower() != seated.lower()
        shell = kind == "shell"

        try:
            if kind and kind not in ("shell", "watch"):
                raise host_attach.AttachRefused(
                    f"Unknown room kind {kind!r} — this lane opens rooms, shells and watches"
                )
            if kind == "watch":
                # No project check and no allowlist: @prax says itself what it can show for any project.
                # No branch is a real answer only here: global mission control, read-only, nothing to seize.
                if branch:
                    # With the project, so a tenant's branch is checked against ITS registry, not the seat's.
                    target = f"watch {host_verbs.citizen_address(branch, project)}"
                else:
                    target = "watch (every branch)"
                session = host_attach.open_monitor(branch, cwd=host_reads.repo_root())
            else:
                target, cwd, scope, room, attach_only = _room_for(branch, project, external, shell, seated)
                # ONE spawn site: test_the_session_is_created_once_per_socket counts this call.
                session = host_attach.open_attach(branch, cwd=cwd, scope=scope, room=room, attach_only=attach_only)
        except (host_verbs.VerbRefused, host_attach.AttachRefused) as e:
            logger.warning("[host_api] socket refused for %s: %s", branch or "<no branch>", e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=str(e))
            return
        except host_fleet.FleetUnavailable as e:
            # @baud's words can carry a host path: they stay in the log and audit; the close reason is fixed.
            logger.warning("[host_api] socket census failed for %s/%s: %s", project, branch, e)
            _audit_socket_refusal(websocket, str(e))
            await websocket.close(code=1008, reason=host_denials.SOCKET_CENSUS_FAILED)
            return
        except (host_verbs.VerbUnavailable, host_attach.AttachUnavailable, host_reads.ReadUnavailable) as e:
            logger.error("[host_api] attach unavailable for %s: %s", branch or "<no branch>", e)
            json_handler.log_operation(
                "host_api_socket_unavailable",
                {"branch": branch, "reason": str(e), "route": "/v1/room/attach"},
            )
            await websocket.close(code=1011, reason=host_denials.SOCKET_UNAVAILABLE)
            return

        logger.info("[host_api] socket attached to %s for %s", session.room, target)

        # Duration and close code tell a reconnect loop (short, 1006) from an operator opening sheets.
        opened = time.monotonic()
        close_code = await host_pump.run_pump(websocket, session)
        logger.info(
            "[host_api] socket detached from %s after %.1fs (close %s)",
            session.room,
            time.monotonic() - opened,
            "room ended" if close_code is None else close_code,
        )

    def _audit_socket_refusal(websocket: Any, reason: str) -> None:
        """Record a refused socket with its peer, like the HTTP lane does."""
        client = getattr(websocket, "client", None)
        json_handler.log_operation(
            "host_api_socket_refused",
            {"peer": getattr(client, "host", "") or "unknown", "reason": reason, "route": "/v1/room/attach"},
        )

    # Resolved ONCE: a running server serves this bundle until restarted (face.py, KNOWN LIMIT).
    face = host_face.face_location()

    @app.get("/", include_in_schema=False)
    async def face_entry(request: Request) -> Any:
        """
        Serve @baud's phone face.
        Unauthenticated on purpose: a browser navigating to a URL cannot send a bearer. The data wall is /v1/*.
        """
        try:
            return host_statics.bundle_response(face.entry_file(), request.headers)
        except host_face.FaceUnavailable as e:
            raise _logged_denial(e, 503, "face_unavailable") from e

    # NOT a catch-all mount on "/": that would shadow every route registered on this app.
    if face.is_available():
        if face.assets_dir().is_dir():
            app.mount("/assets", StaticFiles(directory=str(face.assets_dir())), name="face-assets")

        for filename in face.root_files():
            app.add_api_route(
                f"/{filename}",
                host_statics.face_file_route(face.root / filename),
                methods=["GET"],
                include_in_schema=False,
            )

        logger.info("[host_api] phone face served from %s (%s)", face.root, face.source)
    else:
        # Not fatal: the API is the product, the face is a client of it.
        logger.warning("[host_api] phone face unavailable — / will report it. %s", face.unavailable_message())

    # Derived from the app, never a hand-kept list: a written list drifts from what is registered.
    routes = sorted({path for path in (getattr(route, "path", "") for route in app.routes) if path.startswith("/v1")})
    logger.info("[host_api] app created (read lane + verb lane: %s)", ", ".join(routes))
    json_handler.log_operation("host_api_app_created", {"phase": 3, "routes": routes})
    return app


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """
    Validate the bind address, then run the server.
    Validation happens BEFORE uvicorn is handed anything: a refused address must never reach a listener.
    """
    if not HOST_API_AVAILABLE:
        raise RuntimeError(f"Host API requires FastAPI and uvicorn. Install with: {INSTALL_HINT}")

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    host_config.validate_bind(bind_host, bind_port)

    # Once, here: a long-lived server must not re-walk the filesystem on every branch resolution.
    host_config.pin_registry()

    import uvicorn

    logger.info("[host_api] serving on %s:%s", bind_host, bind_port)
    json_handler.log_operation("host_api_serve_start", {"host": bind_host, "port": bind_port})
    uvicorn.run(create_app(), host=bind_host, port=bind_port, access_log=False)
