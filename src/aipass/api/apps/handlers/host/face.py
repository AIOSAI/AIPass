# =================== AIPass ====================
# Name: face.py
# Description: Host API Face Handler — locates the phone bundle for serving, configured or checkout
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-09-13
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
byte of fleet state stays behind `/v1/*`, which is unchanged. The bind has been
on the tailnet since 2026-08-14, so the page is reachable from that network, and
that changed nothing here: it still discloses nothing.

WHERE THE BUNDLE COMES FROM (FPLAN-0587)
---------------------------------------
Two sources, and the location says which one it used:
  * configured — the host_api config's face_dir, stored by
    `drone @api host-api set-config --face-dir <dir>` or by @aipass's installer
    (`aipass baud install`). An installed AIPass has no checkout to build in.
  * checkout — nothing configured: @baud's build output in this repo, as always.

A configured dir that no longer holds phone.html is reported AS the configured
dir, never swapped for the checkout build. Serving a bundle nobody chose would
hide the break, and the fixes differ: re-install or re-point, not npm.

KNOWN LIMIT — RESOLVED ONCE, AT create_app()
--------------------------------------------
The server calls face_location() once while it builds the app, and every face
route serves from that one answer. A running server does not see a new face_dir;
it needs a restart. Deliberate: the /assets mount is fixed when the app is built,
so resolving the entry per request could pair a new phone.html with the old
bundle's assets — an entry naming hashed files the mount does not hold.

THE CHECKOUT PATH IS @baud's
----------------------------
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

Classes:
    FaceUnavailable - The bundle is not servable; the message names the source
    FaceLocation    - One resolved answer: the bundle directory and its source

Functions:
    face_location()      - Resolve the bundle: configured face_dir, else the checkout
    face_root()          - Directory holding the phone bundle
    entry_file()         - The bundle's HTML entry point
    root_files()         - Files at the bundle root, each served by name
    assets_dir()         - The hashed-asset subdirectory, if it exists
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host.reads import repo_root

# @baud's build output — THEIR path, named once. They have undertaken to treat
# moving it as a breaking change they owe me notice on (2026-08-14). The checkout
# default since FPLAN-0587: an installed bundle is named by face_dir instead.
FACE_RELATIVE = Path("projects") / "baud" / "app" / "dist-phone"

# Not index.html: their bundle's entry is phone.html, and its manifest declares
# start_url /phone.html with scope /. The assets are referenced from the ROOT
# (/assets/..., /manifest.webmanifest), which is why this is served at / and not
# under a prefix — a prefix would break every link in the document. The name
# lives in config.py, whose set_face_dir() checks for it.
FACE_ENTRY = host_config.FACE_ENTRY

BUILD_HINT = "Build it in @baud's app directory: npm run build:phone"

# The configured source's fixes: install the bundle again, or name another one.
CONFIGURED_HINT = (
    "Re-run aipass baud install, or point the server at a built bundle: "
    "drone @api host-api set-config --face-dir <dir> (or --face-dir default for the checkout build)"
)

SOURCE_CONFIGURED = "configured"
SOURCE_CHECKOUT = "checkout"

ASSETS_DIR = "assets"


class FaceUnavailable(Exception):
    """The phone bundle is not servable. Said out loud, never served as blank."""


@dataclass(frozen=True)
class FaceLocation:
    """
    Where the phone face is served from, and which source named it.

    Attributes:
        root: The bundle directory. It may not exist, or may not be servable.
        source: SOURCE_CONFIGURED or SOURCE_CHECKOUT.
    """

    root: Path
    source: str

    def has_entry(self) -> bool:
        """
        Whether this location holds a servable entry document. Records nothing.

        Returns:
            True when the root is absolute and phone.html is a file in it. A
            relative root would resolve against the server's working directory
            and serve whatever sat there, so it never counts: set_face_dir
            refuses one, and a hand-edited store does not get one past here.
        """
        return self.root.is_absolute() and (self.root / FACE_ENTRY).is_file()

    def unavailable_message(self) -> str:
        """
        The sentence for a face that cannot be served, naming the source that failed.

        Returns:
            The configured dir and its fixes, or the checkout path and the npm build.
        """
        if self.source == SOURCE_CONFIGURED:
            return (
                f"The phone face is not at the configured face dir {self.root} "
                f"(no {FACE_ENTRY} there, or not an absolute path). {CONFIGURED_HINT}"
            )
        return f"The phone face has not been built at {self.root} (the checkout default). {BUILD_HINT}"

    def entry_file(self) -> Path:
        """
        Locate the bundle's HTML entry point.

        Returns:
            Absolute path to the entry document.

        Raises:
            FaceUnavailable: No servable entry here. The message names the source.
        """
        if not self.has_entry():
            logger.warning("[host_api] phone face requested but unavailable at %s (%s)", self.root, self.source)
            raise FaceUnavailable(self.unavailable_message())

        return self.root / FACE_ENTRY

    def assets_dir(self) -> Path:
        """
        Locate the bundle's hashed-asset subdirectory.

        Returns:
            Path to the assets directory (which may not exist).
        """
        return self.root / ASSETS_DIR

    def root_files(self) -> List[str]:
        """
        List the files sitting at the bundle root.

        Each is served under its own name — the manifest, the icons, the entry
        document. Enumerated from disk rather than hardcoded, so an icon @baud
        adds on their next build is served without a change here.

        Directories are excluded: /assets has its own mount, and nothing else
        nested should be reachable by name.

        Returns:
            Sorted file names at the bundle root. Empty if the bundle is absent,
            or its root is relative (see has_entry).
        """
        if not self.root.is_absolute() or not self.root.is_dir():
            return []

        return sorted(entry.name for entry in self.root.iterdir() if entry.is_file())

    def is_available(self) -> bool:
        """
        Whether the phone bundle can be served, recorded as a receipt.

        Returns:
            True if the entry document is servable.
        """
        available = self.has_entry()

        json_handler.log_operation(
            "host_api_face_checked",
            {"available": available, "root": str(self.root), "source": self.source},
        )

        return available


def face_location() -> FaceLocation:
    """
    Resolve where the phone face is served from: the configured dir, else the checkout.

    The server calls this ONCE, in create_app() — see KNOWN LIMIT above. The
    module-level functions below resolve afresh on every call, for callers that
    are not a running server.

    Returns:
        The configured face_dir whenever one is set, whatever state it is in;
        otherwise @baud's build output in this checkout.
    """
    configured = host_config.face_dir()

    if configured is not None:
        return FaceLocation(configured, SOURCE_CONFIGURED)

    return FaceLocation(repo_root() / FACE_RELATIVE, SOURCE_CHECKOUT)


def face_root() -> Path:
    """
    Locate the phone bundle.

    Returns:
        The bundle directory (which may not exist yet).
    """
    return face_location().root


def entry_file() -> Path:
    """
    Locate the bundle's HTML entry point.

    Returns:
        Absolute path to the entry document.

    Raises:
        FaceUnavailable: No servable entry. The message names the source.
    """
    return face_location().entry_file()


def assets_dir() -> Path:
    """
    Locate the bundle's hashed-asset subdirectory.

    Returns:
        Path to the assets directory (which may not exist).
    """
    return face_location().assets_dir()


def root_files() -> List[str]:
    """
    List the files sitting at the bundle root.

    Returns:
        Sorted file names at the bundle root. Empty if the bundle is absent.
    """
    return face_location().root_files()
