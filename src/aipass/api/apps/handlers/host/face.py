# =================== AIPass ====================
# Name: face.py
# Description: Host API Face Handler — locates @baud's phone bundle for serving
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Face Handler

Locates the phone face (@baud's FPLAN-0413 `dist-phone` bundle) so this server
can serve it from the same origin as `/v1` — option A of their serving question.

WHY OPTION A (ONE ORIGIN) RATHER THAN CORS
------------------------------------------
CORS would mean this server publishing an allow-list of origins that may read
authenticated fleet data across a boundary. Same origin means there is no such
list to publish, no preflight to answer, and no header to get wrong. @baud built
the bundle with an EMPTY API base — same-origin by default — so option A needs
zero configuration from either side, while option B needs an env var at their
build time and real headers at mine. Fewer moving parts on a security boundary
wins; the option with no configuration cannot be misconfigured.

WHY THE PAGE ITSELF IS NOT BEHIND THE TOKEN
-------------------------------------------
The decisive reason is mechanical, not a judgment call: a browser performing a
top-level navigation CANNOT attach an `Authorization: Bearer` header. Gating the
HTML would therefore require cookies or a session — a SECOND auth system beside
the bearer wall, and the weaker of the two, invented purely to guard a file that
is already public code in a public repo.

What the shell discloses is nothing: it renders a token door and waits. Every
byte of fleet state stays behind `/v1/*`, which is unchanged. And in Stage 0 the
bind is loopback-only, so the page is not reachable off this machine at all.

THE BUNDLE PATH IS @baud's
--------------------------
Named once, here, as they asked: they will treat moving it as a breaking change
they owe notice on. If it is ever absent this server says so with the command
that builds it — it does not serve a blank page and let the operator wonder.

NO CATCH-ALL, AND THAT IS A CORRECTION
--------------------------------------
The first cut mounted the bundle at "/" as a catch-all, which is the ordinary way
to serve an SPA. It was wrong here, and the existing suite caught it: two scope
tests went 404 because they register a route on the app AFTER create_app()
returns, and a catch-all registered last swallows everything added after it. A
server whose API silently disappears depending on when a route was added is a
trap, and the next person to hit it would be debugging Phase 3's verb lane.

So the bundle is served precisely instead: /assets is a real subdirectory mount,
and each file at the bundle root gets its own route. Nothing is a catch-all,
nothing can be shadowed, and the exposed surface is exactly the files @baud
built rather than "whatever happens to sit in that directory".

Functions:
    face_root()          - Directory holding @baud's built phone bundle
    entry_file()         - The bundle's HTML entry point
    root_files()         - Files at the bundle root, each served by name
    assets_dir()         - The hashed-asset subdirectory, if it exists
    is_face_available()  - Whether the bundle has been built
"""

from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.reads import repo_root

# @baud's build output — THEIR path, named once. They have undertaken to treat
# moving it as a breaking change they owe me notice on (2026-08-14). A published
# install target is the better answer and is theirs to raise when packaging comes
# up; until then this constant is the whole coupling.
FACE_RELATIVE = Path("projects") / "baud" / "app" / "dist-phone"

# Not index.html: their bundle's entry is phone.html, and its manifest declares
# start_url /phone.html with scope /. The assets are referenced from the ROOT
# (/assets/..., /manifest.webmanifest), which is why this is served at / and not
# under a prefix — a prefix would break every link in the document.
FACE_ENTRY = "phone.html"

BUILD_HINT = "Build it in @baud's app directory: npm run build:phone"


class FaceUnavailable(Exception):
    """The phone bundle is not present. Said out loud, never served as blank."""


def face_root() -> Path:
    """
    Locate @baud's built phone bundle.

    Returns:
        Absolute path to the bundle directory (which may not exist yet).
    """
    return repo_root() / FACE_RELATIVE


def entry_file() -> Path:
    """
    Locate the bundle's HTML entry point.

    Returns:
        Absolute path to the entry document.

    Raises:
        FaceUnavailable: The bundle has not been built.
    """
    entry = face_root() / FACE_ENTRY

    if not entry.is_file():
        logger.warning("[host_api] phone face requested but not built at %s", entry)
        raise FaceUnavailable(f"The phone face has not been built at {face_root()}. {BUILD_HINT}")

    return entry


ASSETS_DIR = "assets"


def assets_dir() -> Path:
    """
    Locate the bundle's hashed-asset subdirectory.

    Returns:
        Absolute path to the assets directory (which may not exist).
    """
    return face_root() / ASSETS_DIR


def root_files() -> List[str]:
    """
    List the files sitting at the bundle root.

    Each is served under its own name — the manifest, the icons, the entry
    document. Enumerated from disk rather than hardcoded, so an icon @baud adds
    on their next build is served without a change here.

    Directories are excluded: /assets has its own mount, and nothing else nested
    should be reachable by name.

    Returns:
        Sorted file names at the bundle root. Empty if the bundle is unbuilt.
    """
    root = face_root()

    if not root.is_dir():
        return []

    return sorted(entry.name for entry in root.iterdir() if entry.is_file())


def is_face_available() -> bool:
    """
    Whether the phone bundle has been built.

    Returns:
        True if the entry document exists.
    """
    available = (face_root() / FACE_ENTRY).is_file()

    json_handler.log_operation("host_api_face_checked", {"available": available, "root": str(face_root())})

    return available
