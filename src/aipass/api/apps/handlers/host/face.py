# =================== AIPass ====================
# Name: face.py
# Description: Host API Face Handler — locates the phone bundle for serving, configured or checkout
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Host API Face Handler
Reference: docs/host_surfaces.md. No catch-all at "/": it would swallow every route added after create_app()."""

from dataclasses import dataclass
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host.reads import repo_root

# @baud's path, named once: they treat moving it as a breaking change they owe notice on.
FACE_RELATIVE = Path("projects") / "baud" / "app" / "dist-phone"

# Served at /, never under a prefix: the bundle references its assets from the root.
FACE_ENTRY = host_config.FACE_ENTRY

BUILD_HINT = "Build it in @baud's app directory: npm run build:phone"

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
    """Where the phone face is served from, and which source named it."""

    root: Path
    source: str

    def has_entry(self) -> bool:
        """Whether this location holds a servable entry document. Records nothing.
        A relative root never counts: it would resolve against the server's cwd (a hand-edited store)."""
        return self.root.is_absolute() and (self.root / FACE_ENTRY).is_file()

    def unavailable_message(self) -> str:
        """The sentence for a face that cannot be served, naming the source that failed."""
        if self.source == SOURCE_CONFIGURED:
            return (
                f"The phone face is not at the configured face dir {self.root} "
                f"(no {FACE_ENTRY} there, or not an absolute path). {CONFIGURED_HINT}"
            )
        return f"The phone face has not been built at {self.root} (the checkout default). {BUILD_HINT}"

    def entry_file(self) -> Path:
        """Locate the bundle's HTML entry point."""
        if not self.has_entry():
            logger.warning("[host_api] phone face requested but unavailable at %s (%s)", self.root, self.source)
            raise FaceUnavailable(self.unavailable_message())

        return self.root / FACE_ENTRY

    def assets_dir(self) -> Path:
        """Locate the bundle's hashed-asset subdirectory."""
        return self.root / ASSETS_DIR

    def root_files(self) -> List[str]:
        """List the files sitting at the bundle root.
        Files only: /assets has its own mount, and nothing else nested should be reachable by name."""
        if not self.root.is_absolute() or not self.root.is_dir():
            return []

        return sorted(entry.name for entry in self.root.iterdir() if entry.is_file())

    def is_available(self) -> bool:
        """Whether the phone bundle can be served, recorded as a receipt."""
        available = self.has_entry()

        json_handler.log_operation(
            "host_api_face_checked",
            {"available": available, "root": str(self.root), "source": self.source},
        )

        return available


def face_location() -> FaceLocation:
    """Resolve where the phone face is served from: the configured dir, else the checkout.
    A configured dir is returned whatever its state, never swapped for the checkout: that would hide the break.
    The server calls this once, in create_app(): per request, phone.html could name assets the mount lacks."""
    configured = host_config.face_dir()

    if configured is not None:
        return FaceLocation(configured, SOURCE_CONFIGURED)

    return FaceLocation(repo_root() / FACE_RELATIVE, SOURCE_CHECKOUT)


def face_root() -> Path:
    """Locate the phone bundle."""
    return face_location().root


def entry_file() -> Path:
    """Locate the bundle's HTML entry point."""
    return face_location().entry_file()


def assets_dir() -> Path:
    """Locate the bundle's hashed-asset subdirectory."""
    return face_location().assets_dir()


def root_files() -> List[str]:
    """List the files sitting at the bundle root."""
    return face_location().root_files()
