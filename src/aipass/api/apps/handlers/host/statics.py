# =================== AIPass ====================
# Name: statics.py
# Description: Host API Statics Handler — how @baud's bundle files reach a browser
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""
Host API Statics Handler

Cache policy for @baud's phone bundle, and the conditional-request machinery the
entry document never had.

THE DEFECT THIS EXISTS FOR
--------------------------
`GET /` answered 200 with `etag` and `last-modified` and NO `cache-control`.
That is not "no caching" — RFC 9111 4.2.2 says a response with no explicit
freshness information MAY be assigned a heuristic lifetime, and the common one
is ~10% of the age since `last-modified`. So the browser is free to serve
`location.reload()` wholly from its own cache without asking this server
anything.

For a normal document that is a stale page. For THIS document it is worse: the
entry is un-hashed and it NAMES the content-hashed bundles. A stale entry
therefore fetches OLD assets, correctly and quietly, and the app looks like it
simply did not deploy. Patrick hit it live on 2026-08-19 — his first reload
served a round-3 bundle and an acceptance round recorded a false FAIL. @baud
measured the missing header; the cost landed on someone else.

THE RULE, STATED ONCE
---------------------
A file whose NAME changes when its content changes may be cached. A file served
under a STABLE name must revalidate.

Every file at the bundle root is stable-named — `phone.html`, the manifest, the
icons — and a build replaces each in place. They all revalidate. `/assets` is
the hashed lane and is deliberately NOT routed through here: a stale hashed file
is impossible by construction, because a new build writes a new name that the
(now-revalidating) entry points at. Spending a round trip per asset to prevent
nothing is not caution, it is cost.

WHY no-cache AND NOT no-store
-----------------------------
`no-cache` does not mean "do not cache" — it means "do not reuse without asking
me first". The copy stays in the browser and a matching `etag` comes back 304
with an empty body. `no-store` would forbid keeping it at all and re-download
every byte on every load.

That distinction is only true if this server ANSWERS conditional requests, and
it did not. Starlette's `FileResponse` sets an `etag` but never reads
`If-None-Match` — only `StaticFiles` does, which is why `/assets` already
revalidated properly and the entry never has. Measured before the fix: a second
`GET /` carrying the first response's own etag came back 200 with the full body.

So `no-cache` on its own would have turned a stale-bundle bug into a
re-download-everything bug. The check below closes that, and it is starlette's
OWN comparison rather than a copy of it, so this lane and the `/assets` lane
cannot drift apart on what "not modified" means.

Functions:
    bundle_response()  - Serve one bundle-root file, revalidating not caching blind
    face_file_route()  - Build the route handler for one bundle-root file
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# Request is only ever an ANNOTATION — FastAPI reads it to decide what to
# inject — so the checker needs a CLASS here, not a name that might be None.
# Split from the guard below for exactly that reason: at runtime only the else
# branch executes, and it binds the real class whenever the extra is installed.
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


# "do not reuse this without asking me first", NOT "do not keep it". See the
# module docstring — the difference is a 304 with no body versus a full
# download on every single page load.
REVALIDATE = "no-cache"

# Starlette's own If-None-Match / If-Modified-Since comparison, borrowed rather
# than reimplemented. It reads nothing from the instance — only its two
# arguments — so a directory-less instance is the whole cost of not having a
# second, subtly different definition of "not modified" living in this branch.
_CONDITIONAL: Any = StaticFiles() if STATICS_AVAILABLE else None


def bundle_response(path: Path, request_headers: Any) -> Any:
    """
    Serve one file from @baud's bundle root.

    Args:
        path: The file to serve. Bound at app-creation time from a directory
            listing, never taken from a request — there is no caller-supplied
            path here to fence.
        request_headers: The incoming request's headers, read for the
            conditional-request validators.

    Returns:
        A 304 with no body when the caller's copy is current, otherwise the
        file. Either way carrying `cache-control: no-cache`, so the next load
        asks again instead of guessing.

    Note:
        The 304 keeps `cache-control` — starlette's NotModifiedResponse carries
        it through deliberately. Dropping it would leave the browser with a
        fresh copy and no instruction, back in heuristic-caching territory one
        revalidation later.
    """
    response = FileResponse(path, stat_result=os.stat(path), headers={"cache-control": REVALIDATE})

    if _CONDITIONAL.is_not_modified(response.headers, Headers(scope={"headers": request_headers.raw})):
        return NotModifiedResponse(response.headers)

    # RECORDED ONLY ON A FULL SEND, never on a 304. That is what makes this
    # cheap enough to keep: after the first load a phone's reloads are all
    # revalidations, so this writes roughly once per file per DEPLOY — which is
    # exactly the question that could not be answered on 2026-08-19, when a
    # day of access history lived only in a tmux scrollback and the restart
    # churn ate it. "Which bundle did that phone pull" now has an answer that
    # does not depend on a pane still being open.
    json_handler.log_operation(
        "host_api_face_served",
        {"file": path.name, "etag": response.headers.get("etag", "")},
    )

    return response


def face_file_route(filename: str) -> Any:
    """
    Build a route handler serving one file from the bundle root.

    The name is bound at app-creation time from a directory listing, never
    taken from the request, so there is no caller-supplied path here to fence.

    Lives here rather than in server.py because the two are the same decision:
    what this returns is entirely a question of cache policy, and the file that
    owns the policy should own the handler that applies it.

    Args:
        filename: File name at the bundle root.

    Returns:
        An async route handler returning that file, revalidating rather than
        letting a browser guess a freshness lifetime. Every name here is STABLE
        across builds, which is the whole reason.
    """
    from aipass.api.apps.handlers.host import face as host_face

    async def _serve_file(request: Request) -> Any:
        return bundle_response(host_face.face_root() / filename, request.headers)

    return _serve_file
