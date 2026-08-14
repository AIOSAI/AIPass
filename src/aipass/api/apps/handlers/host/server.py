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
    GET /v1/files   - read scope. Names not paths, 512KB cap, cap is reported.
    GET /v1/diff    - read scope. Routed through drone's git lane, never raw git.

Endpoints added on C1 (routed, but the exec behind them is GATED):
    GET /v1/fleet   - read scope. @baud's snapshot envelope, unchanged.
    GET /v1/rooms   - read scope. A filter over that same snapshot.

Both answer 503 with a named reason until `fleet.SNAPSHOT_READY` is flipped.
@baud's flag is verified in their tree, but the shipped release binary predates
it and would open a GUI window instead of erroring — see fleet.py. Their schema
is implemented field-for-field, so nothing here changes when the gate opens.

RESERVED, NOT BUILT (FPLAN-0411; do not add without the phase that owns it):
    POST /v1/verbs/wake            - Phase 3, admin=False pinned by test
    POST /v1/verbs/kill            - Phase 3, explicit target + room's own
                                     project. Also held on @baud's rebuild.
    POST /v1/verbs/lock            - Phase 3, held on C2 (@skills extraction)
    POST /v1/notify                - Phase 4, content-minimized through the relay
    quick-send / interrupt         - later round, CONFIRMED build (agnostic
                                     ruling). Reuses @ai_mail's verified
                                     injection path — never a raw send-keys
                                     here. @baud reproduced the bare-slash trap
                                     twice live, once landing on /remote-env.
    photo upload                   - later round, the one row that WIDENS this
                                     surface: size cap enforced before the body
                                     is read, content-type allowlist, and no
                                     client-chosen filename or path
    websocket                      - explicitly out of Stage 0

Functions:
    is_available()  - Whether the [host] extra is installed
    create_app()    - Build the FastAPI application
    serve()         - Validate the bind, then run uvicorn
"""

from typing import Any, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import feed as host_feed
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import tokens as host_tokens


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
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse, Response
    from fastapi.security import HTTPBearer

    HOST_API_AVAILABLE = True
except ImportError as e:
    logger.warning("[host_api] server libraries not available: %s", e)

    Depends = None  # type: ignore[assignment, misc]
    FastAPI = None  # type: ignore[assignment, misc]
    # Not None: this name is raised and also handed to @app.exception_handler(),
    # both of which need a class. See UnavailableHTTPException above.
    HTTPException = UnavailableHTTPException  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    JSONResponse = None  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]
    HTTPBearer = None  # type: ignore[assignment, misc]

    HOST_API_AVAILABLE = False

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


def _deny(status: int, code: str, message: str) -> Any:
    """
    Build the standard error response.

    Args:
        status: HTTP status code.
        code: Short machine-readable code.
        message: Human-readable explanation.

    Returns:
        An HTTPException carrying the shared error envelope.
    """
    return HTTPException(status_code=status, detail={"error": {"code": code, "message": message}})


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

    def _dependency(credentials: Optional[Any] = Depends(_bearer)) -> dict:
        if credentials is None or not getattr(credentials, "credentials", None):
            raise _deny(401, "unauthorized", "Bearer token required")

        record = host_tokens.verify_token(credentials.credentials)
        if record is None:
            # Rejected and revoked are deliberately indistinguishable to the
            # caller — a revoked device learns "no", not "you were valid until
            # 10:42". The reason is in our log, not the response.
            logger.warning("[host_api] auth rejected: token not recognised or revoked")
            raise _deny(401, "unauthorized", "Token not recognised")

        if not host_tokens.scope_allows(str(record.get("scope", "")), required):
            logger.warning(
                "[host_api] scope refused: id=%s has %s, needs %s",
                record.get("id"),
                record.get("scope"),
                required,
            )
            raise _deny(403, "forbidden", f"This token's scope cannot perform a '{required}' action")

        return record

    return _dependency


# ==============================================
# APP
# ==============================================


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
        """Send every error through the one envelope shape the client parses."""
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            payload = detail
        else:
            payload = {"error": {"code": "error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=payload)

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
    async def feed(
        since: Optional[str] = None,
        limit: int = host_feed.DEFAULT_LIMIT,
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Cursor-first notification window. See feed.py for the clamp doctrine."""
        try:
            return host_feed.read_feed(since=since, limit=limit)
        except host_feed.FeedUnavailable as e:
            raise _deny(503, "feed_unavailable", str(e)) from e

    @app.get("/v1/files")
    async def files(
        branch: str,
        file: str,
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Read a file by NAME under a branch. No path parameter exists here."""
        try:
            return host_reads.read_file(branch=branch, file=file, project=project)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/diff")
    async def diff(
        branch: str,
        staged: bool = False,
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """A branch's diff, routed through drone's git lane."""
        try:
            return host_reads.read_diff(branch=branch, staged=staged, project=project)
        except host_reads.ReadRefused as e:
            raise _deny(400, "read_refused", str(e)) from e
        except host_reads.ReadUnavailable as e:
            raise _deny(503, "read_unavailable", str(e)) from e

    @app.get("/v1/fleet")
    async def fleet(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """@baud's fleet snapshot, passed through without an adapter."""
        try:
            return host_fleet.read_snapshot(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e

    @app.get("/v1/rooms")
    async def rooms(
        project: str = "",
        record: dict = Depends(require_scope("read")),
    ) -> dict:
        """Room projection of the same snapshot. A filter, never a judgment."""
        try:
            return host_fleet.read_rooms(project=project)
        except host_fleet.FleetUnavailable as e:
            raise _deny(503, "fleet_unavailable", str(e)) from e

    routes = ["/v1/ping", "/v1/whoami", "/v1/feed", "/v1/files", "/v1/diff", "/v1/fleet", "/v1/rooms"]
    logger.info("[host_api] app created (Phase 2 read lane: %s)", ", ".join(routes))
    json_handler.log_operation("host_api_app_created", {"phase": 2, "routes": routes})
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

    import uvicorn

    logger.info("[host_api] serving on %s:%s", bind_host, bind_port)
    json_handler.log_operation("host_api_serve_start", {"host": bind_host, "port": bind_port})
    uvicorn.run(create_app(), host=bind_host, port=bind_port)
