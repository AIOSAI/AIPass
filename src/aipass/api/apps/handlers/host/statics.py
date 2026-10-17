# =================== AIPass ====================
# Name: statics.py
# Description: Host API Statics Handler — how @baud's bundle files reach a browser
# Version: 1.1.0
# Created: 2026-08-19
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false
# The [host] extra's imports are guarded, and CI installs `.[dev,memory]`, never `[host]`.

"""Host API Statics Handler"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# Request is only an annotation FastAPI reads, so the checker needs a class, never a maybe-None name.
if TYPE_CHECKING:
    from fastapi import Request
else:
    try:
        from fastapi import Request
    except ImportError as e:
        logger.debug("[host_api] Request unavailable, no route will be built: %s", e)
        Request = None

try:
    from fastapi.responses import FileResponse
    from starlette.datastructures import Headers
    from starlette.staticfiles import NotModifiedResponse, StaticFiles

    STATICS_AVAILABLE = True
except ImportError as e:
    logger.warning("[host_api] static-serving libraries not available: %s", e)

    FileResponse: Any = None

    Headers: Any = None
    NotModifiedResponse: Any = None
    StaticFiles: Any = None

    STATICS_AVAILABLE = False


REVALIDATE = "no-cache"

# Starlette's own comparison (it reads only its arguments), so this lane and /assets agree on "not modified".
_CONDITIONAL: Any = StaticFiles() if STATICS_AVAILABLE else None


def bundle_response(path: Path, request_headers: Any) -> Any:
    """Serve one file from @baud's bundle root.
    The 304 keeps cache-control: without it the browser is back to heuristic caching."""
    response = FileResponse(path, stat_result=os.stat(path), headers={"cache-control": REVALIDATE})

    if _CONDITIONAL.is_not_modified(response.headers, Headers(scope={"headers": request_headers.raw})):
        return NotModifiedResponse(response.headers)

    json_handler.log_operation(
        "host_api_face_served",
        {"file": path.name, "etag": response.headers.get("etag", "")},
    )

    return response


def face_file_route(path: Path) -> Any:
    """Build a route handler serving one file from the bundle root.
    The path is bound once at app creation, never per request: it must match the /assets mount's bundle."""

    async def _serve_file(request: Request) -> Any:
        return bundle_response(path, request.headers)

    return _serve_file
