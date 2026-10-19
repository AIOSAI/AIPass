# =================== AIPass ====================
# Name: attach.py
# Description: Host API Attach Handler — a real PTY running a tmux client, for the phone
# Version: 1.0.2
# Created: 2026-08-14
# Modified: 2026-10-19
# =============================================
# pyright: reportOptionalMemberAccess=false
# fcntl/pty/termios are None off POSIX; every use sits behind PTY_AVAILABLE, which the checker cannot narrow.

"""Host API Attach Handler
Reference: docs/host_surfaces.md. Detach is SIGHUP and the room survives: nothing here may kill a session."""

import os
import re
import shutil
import signal
import struct
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

try:
    import fcntl
    import pty
    import termios

    PTY_AVAILABLE = True
except ImportError as e:  # pragma: no cover - Windows only
    logger.warning("[host_api] PTY support unavailable on this platform: %s", e)

    fcntl = None  # type: ignore[assignment]
    pty = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]

    PTY_AVAILABLE = False

# @baud's convention, mirrored: an invented name would be a second room beside the real one.
ROOM_PREFIX = "baud-"

TMUX_BINARY = "tmux"

# A lone ';' is tmux's command separator, '-' opens an option, '.' and ':' are target syntax.
ROOM_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")

MONITOR_TARGET = re.compile(r"[a-z0-9_,-]+")

MONITOR_BINARY = "drone"

GLOBAL_WATCH_LABEL = "watch-all"

BEARER_SUBPROTOCOL = "aipass.bearer"

DEFAULT_COLS = 80
DEFAULT_ROWS = 24

MAX_DIMENSION = 1000

READ_CHUNK_BYTES = 65536

# Each socket parks a thread in os.read for life: its own pool, never asyncio's shared default, capped in words.
PUMP_WORKERS = 16

# Bounded: an over-release raises instead of inventing capacity, which would return as a silent hang.
_PUMP_SLOTS = threading.BoundedSemaphore(PUMP_WORKERS)
_PUMP_EXECUTOR: Any = None
_EXECUTOR_GUARD = threading.Lock()


class AttachRefused(Exception):
    """The caller asked for something invalid. Their fault, and they may know."""


class AttachUnavailable(Exception):
    """The attach could not happen for a reason that is not the caller's."""


def pump_executor() -> Any:
    """The thread pool the socket pump reads on. One pool, built once."""
    global _PUMP_EXECUTOR
    with _EXECUTOR_GUARD:
        if _PUMP_EXECUTOR is None:
            _PUMP_EXECUTOR = ThreadPoolExecutor(max_workers=PUMP_WORKERS, thread_name_prefix="host-attach")
        return _PUMP_EXECUTOR


def _reserve_session(room: str) -> None:
    """Take one of the pump's threads, or refuse in words.
    Non-blocking (waiting is the silent hang) and before the spawn, so two sockets cannot share one slot."""
    if not _PUMP_SLOTS.acquire(blocking=False):
        raise AttachUnavailable(
            f"This server is already pumping {PUMP_WORKERS} terminals, which is its cap — "
            f"close one before opening {room}"
        )


def _release_session() -> None:
    """Give a pump thread back."""
    _PUMP_SLOTS.release()


def is_available() -> bool:
    """Whether this platform can host a PTY at all."""
    return PTY_AVAILABLE


def _tmux_safe(text: str) -> str:
    """Flatten anything outside [A-Za-z0-9_-] to '-', mirroring @baud's sanitize.
    '.' and ':' are tmux target syntax; pinned to @baud's lib.rs `room_name` by shared test vectors."""
    return "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "_-" else "-" for ch in text)


def room_name(branch: str, scope: str = "") -> str:
    """The tmux session name for a branch, in @baud's convention.
    Mirrors the desktop's lib.rs `room_name`; `scope` is the non-anchor project, lowercased by the caller."""
    plain = _tmux_safe(branch.strip().lstrip("@"))
    if scope:
        return ROOM_PREFIX + _tmux_safe(scope) + "-" + plain
    return ROOM_PREFIX + plain


def shell_room_name(project: str, branch: str = "") -> str:
    """The tmux session name for an EMPTY shell — no claude, just a prompt.
    Own namespace, which the fleet scan skips, so a shell is never taken for an agent's room."""
    room = ROOM_PREFIX + "shell-" + _tmux_safe(project.strip().lower())
    if branch and branch.strip():
        room += "-" + _tmux_safe(branch.strip().lstrip("@"))
    return room


def valid_monitor_target(target: str) -> bool:
    """Charset fence for a watch target — MIRRORED from `valid_monitor_target` in @baud's pty.rs, exactly."""
    return MONITOR_TARGET.fullmatch(target) is not None


def _option_shaped(target: str) -> bool:
    """A leading '-' reaches drone as a flag, not a branch: `--relay` would start the Telegram relay."""
    return target.startswith("-")


def monitor_command(target: str = "") -> List[str]:
    """
    The watch argv: `drone @prax monitor run <target>` — the exact command the
    desktop's monitor pane runs, minus its login shell; empty target means every branch, never `run all`."""
    command = ["drone", "@prax", "monitor", "run"]
    if target:
        if not MONITOR_TARGET.fullmatch(target) or _option_shaped(target):
            raise AttachRefused(f"Not a monitor target: {target!r}")
        command.append(target)
    return command


def attach_command(branch: str, scope: str = "") -> List[str]:
    """The exact argv the desktop runs, mirrored — including its room options."""
    return client_command(room_name(branch, scope))


def client_command(room: str) -> List[str]:
    """The tmux client argv for a NAMED room — the shared tail of every attach.
    Every chained command carries its own -t: without one, set-option hits tmux's current session and exits 0."""
    if not ROOM_NAME.fullmatch(room):
        raise AttachRefused(f"Not a room name: {room!r}")
    return [
        TMUX_BINARY,
        "new-session",
        "-A",
        "-s",
        room,
        ";",
        "set-option",
        "-t",
        room,
        "mouse",
        "on",
        ";",
        "set-option",
        "-w",
        "-t",
        room,
        "window-size",
        "smallest",
    ]


def attach_only_command(room: str) -> List[str]:
    """The tmux client argv for a room this server must NOT create (DPLAN-0327).
    For `outside_room`: creating a name someone else chose mints an empty session the desktop owns."""
    if not ROOM_NAME.fullmatch(room):
        raise AttachRefused(f"Not a room name: {room!r}")
    return [
        TMUX_BINARY,
        "attach-session",
        "-t",
        room,
        ";",
        "set-option",
        "-t",
        room,
        "mouse",
        "on",
        ";",
        "set-option",
        "-w",
        "-t",
        room,
        "window-size",
        "smallest",
    ]


def set_winsize(descriptor: int, cols: int, rows: int) -> None:
    """Stamp a terminal size into the kernel for a PTY."""
    if not PTY_AVAILABLE:
        raise AttachUnavailable("Setting a terminal size needs a PTY, which this platform does not have")

    # struct winsize is (rows, cols, ...): backwards renders a plausible wrong shape, not an error.
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)


class AttachSession:
    """One live PTY running one tmux client."""

    def __init__(self, process: Any, descriptor: int, branch: str, room: str, read_only: bool = False) -> None:
        self.process = process
        self.descriptor = descriptor
        self.branch = branch
        self.room = room
        self.read_only = read_only
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether this session has already been hung up."""
        return self._closed

    def read(self, size: int = READ_CHUNK_BYTES) -> bytes:
        """Read whatever the room has produced."""
        try:
            return os.read(self.descriptor, size)
        except OSError as e:
            # How a PTY reports end of life; logged since the errno is the only clue to an unexpected death.
            logger.debug("[host_api] PTY for %s reached end of life: %s", self.room, e)
            return b""

    def write(self, data: bytes) -> None:
        """Type into the room."""
        if self.read_only:
            raise AttachRefused(f"{self.room} is a read-only watch — nothing types into it")
        os.write(self.descriptor, data)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY, so the room draws at the client's geometry."""
        if not PTY_AVAILABLE:
            raise AttachUnavailable("Resizing needs a PTY, which this platform does not have")

        set_winsize(
            self.descriptor,
            _require_dimension(cols, "cols"),
            _require_dimension(rows, "rows"),
        )

    def hangup(self) -> None:
        """Detach: SIGHUP the tmux CLIENT and let the room live on."""
        if self._closed:
            return

        self._closed = True
        # Released here, not in the socket handler: hangup is the one path every lane ends through.
        _release_session()

        try:
            # SIGHUP, never SIGKILL: tmux clients take a hangup as a clean detach.
            self.process.send_signal(signal.SIGHUP)
        except (ProcessLookupError, OSError) as e:
            logger.debug("[host_api] attach client for %s was already gone: %s", self.room, e)

        try:
            os.close(self.descriptor)
        except OSError as e:
            logger.debug("[host_api] attach descriptor for %s was already closed: %s", self.room, e)

        json_handler.log_operation("host_api_attach_closed", {"branch": self.branch, "room": self.room})
        logger.info("[host_api] detached from %s — the room survives", self.room)


def open_attach(
    branch: str,
    cwd: Optional[Path] = None,
    scope: str = "",
    room: str = "",
    attach_only: bool = False,
) -> AttachSession:
    """Spawn a PTY running a tmux client into a branch's room."""
    if not PTY_AVAILABLE:
        raise AttachUnavailable("This host cannot attach: a PTY is a POSIX object and this platform has none")

    if not (room and room.strip()) and (not branch or not branch.strip()):
        raise AttachRefused("A branch name is required — this lane has no default room")

    if not shutil.which(TMUX_BINARY):
        raise AttachUnavailable(f"{TMUX_BINARY} is not installed on this host — the attach lane runs a tmux client")

    if room and room.strip():
        room = room.strip()
        command = attach_only_command(room) if attach_only else client_command(room)
    else:
        room = room_name(branch, scope)
        command = attach_command(branch, scope)

    process, master = _spawn_pty(command, cwd, room)

    json_handler.log_operation("host_api_attach_opened", {"branch": branch, "room": room, "pid": process.pid})
    logger.info("[host_api] attached to %s (pid %s)", room, process.pid)

    return AttachSession(process, master, branch.strip().lstrip("@") or room, room)


def open_monitor(target: str = "", cwd: Optional[Path] = None) -> AttachSession:
    """Spawn a tier-0 watch: `drone @prax monitor run <target>` on its own PTY.
    Not tmux-backed: a watch holds no work, so it dies with its socket."""
    if not PTY_AVAILABLE:
        raise AttachUnavailable("This host cannot attach: a PTY is a POSIX object and this platform has none")

    cleaned = target.strip().lstrip("@")

    # Absence is asked here, before the fence: folding "" into the mirrored fence would break the mirror.
    if cleaned and (not valid_monitor_target(cleaned) or _option_shaped(cleaned)):
        raise AttachRefused(f"Not a monitor target: {target!r}")

    if not shutil.which(MONITOR_BINARY):
        raise AttachUnavailable(f"{MONITOR_BINARY} is not on this host's PATH — the watch lane runs it")

    label = f"watch-{cleaned}" if cleaned else GLOBAL_WATCH_LABEL
    process, master = _spawn_pty(monitor_command(cleaned), cwd, label)

    json_handler.log_operation("host_api_watch_opened", {"target": cleaned, "pid": process.pid})
    logger.info("[host_api] watching %s (pid %s)", cleaned or "every branch", process.pid)

    return AttachSession(process, master, cleaned or GLOBAL_WATCH_LABEL, label, read_only=True)


def _spawn_pty(command: List[str], cwd: Optional[Path], room: str, close_fd: Any = None) -> tuple:
    """
    Spawn `command` as the child of a fresh PTY. The shared mechanics of every
    lane that ends in a live terminal. `close_fd` is a test seam; None means os.close."""
    closer = close_fd if close_fd is not None else os.close

    _reserve_session(room)

    master, slave = pty.openpty()

    # openpty gives 0x0, which tmux reads at startup: stamped before the child exists.
    set_winsize(master, DEFAULT_COLS, DEFAULT_ROWS)

    try:
        process = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(cwd) if cwd else None,
            # Not start_new_session: with no controlling tty every resize is deaf (see that function).
            preexec_fn=_acquire_controlling_tty,  # see the note in that function
            close_fds=True,
            env=_child_env(),
        )
    except OSError as e:
        closer(master)
        # No session will own this slot: without the release, failed spawns use up the cap.
        _release_session()
        logger.error("[host_api] could not start a client for %s: %s", room, e)
        raise AttachUnavailable(f"Could not start a client for {room}: {e}") from e
    finally:
        # Ours open means the master never reports EOF. Closed here alone: a second close
        # can land on a descriptor number another thread was just handed.
        closer(slave)

    return process, master


def _acquire_controlling_tty(
    _setsid: Any = getattr(os, "setsid", None),
    _login_tty: Any = getattr(os, "login_tty", None),
    _ioctl: Any = getattr(fcntl, "ioctl", None),
    _tiocsctty: Any = getattr(termios, "TIOCSCTTY", None),
) -> None:
    """Run in the CHILD, between fork and exec: take the slave as our controlling tty.
    SIGWINCH reaches only a controlling tty's group, and inheriting a descriptor never acquires one.
    Callables are default args so the forked child does no lookup or allocation before exec;
    each is a getattr, os.setsid included, because a bare name raises at import on Windows."""
    if _login_tty is not None:
        _login_tty(0)
        return

    if _setsid is None or _ioctl is None or _tiocsctty is None:
        raise AttachUnavailable("This platform cannot acquire a controlling tty")

    _setsid()
    _ioctl(0, _tiocsctty, 0)


def _child_env() -> Dict[str, str]:
    """The environment the tmux client runs in.
    TERM pinned to the phone's xterm.js: an inherited TERM renders the wrong capability set."""
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    return env


def _require_dimension(value: Any, name: str) -> int:
    """Validate one terminal dimension. Refused, never clamped: the client would render against the wrong size."""
    try:
        size = int(value)
    except (TypeError, ValueError) as e:
        raise AttachRefused(f"{name} must be a whole number, got {value!r}") from e

    if size <= 0:
        raise AttachRefused(f"{name} must be positive, got {size}")

    if size > MAX_DIMENSION:
        raise AttachRefused(f"{name} is {size}, over the {MAX_DIMENSION} cap")

    return size
