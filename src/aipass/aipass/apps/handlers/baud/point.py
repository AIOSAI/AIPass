# =================== AIPass ====================
# Name: point.py
# Description: Point @api's host server at the installed phone face, and read back where it points
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
Point @api's host server at the installed bundle (FPLAN-0587 row 2).

@api owns the face_dir setting and its validation (row 1): ``set_face_dir(path)``
refuses a relative path, a missing directory, or one without phone.html, at write
time. This file calls it in-process and never writes api's config file itself.

The module layer imports @api's host config and hands it in as ``host_config``
(None when @api is not importable here), so the one cross-branch edge lives in
modules/baud.py and this handler stays inside its branch. When @api does not
publish the function on this install, the result says so and names the CLI door
(``drone @api host-api set-config --face-dir <dir>``).

A server already running resolved its face root at start, so every successful
point is followed by the restart line.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

RESTART_HINT = (
    "Restart the host api to serve it: drone @api host-api stop, then drone @api host-api serve "
    "(or restart the autostart unit, see drone @api host-api autostart)."
)


@dataclass(frozen=True)
class PointResult:
    """Whether @api now points at the bundle, and the line that says so."""

    ok: bool
    message: str


def point_api_at(dest: Path, host_config: Any) -> PointResult:
    """Ask @api to serve the phone face from `dest`.

    Args:
        dest: An absolute directory holding phone.html.
        host_config: @api's host config module, or None when it is not importable.

    Returns:
        ok=True with the directory @api stored, or ok=False with the refusal
        and the manual command.
    """
    set_face_dir = getattr(host_config, "set_face_dir", None)
    if set_face_dir is None:
        logger.warning("[baud] @api set_face_dir unavailable (host config: %s)", type(host_config).__name__)
        return PointResult(
            False,
            "@api's face-dir setting is not available on this install. "
            f"Run: drone @api host-api set-config --face-dir {dest}",
        )
    try:
        stored = set_face_dir(dest)
    except Exception as exc:  # @api owns the validation; its refusal IS the message
        logger.warning("[baud] @api refused face dir %s: %s", dest, exc)
        return PointResult(False, f"@api refused the face dir: {exc}")
    json_handler.log_operation("baud_face_pointed", {"dest": str(stored or dest)}, module_name="baud")
    return PointResult(True, f"@api serves the phone face from {stored or dest}")


def api_face_dir_state(dest: Path, host_config: Any) -> str:
    """One line: where @api's face_dir points, relative to `dest`."""
    face_dir = getattr(host_config, "face_dir", None)
    if face_dir is None:
        return "unknown (@api's face_dir is not available on this install)"
    try:
        configured = face_dir()
    except OSError as exc:
        logger.warning("[baud] @api face_dir unreadable: %s", exc)
        return f"unreadable ({exc})"
    if configured is None:
        return "not set (@api serves the source-checkout bundle)"
    if Path(configured) == dest:
        return f"points here ({dest})"
    return f"points elsewhere: {configured}"


def phone_url(host_config: Any) -> str:
    """The phone face URL from @api's effective host config."""
    unknown = "http://<host>:<port>/phone.html (see: drone @api host-api config)"
    load_config = getattr(host_config, "load_config", None)
    if load_config is None:
        return unknown
    try:
        config = load_config()
        host = str(config["host"])
        port = int(config["port"])
    except (KeyError, TypeError, ValueError, OSError) as exc:
        logger.info("[baud] host api config unusable for the url: %s", exc)
        return unknown
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}/phone.html"
