# =================== AIPass ====================
# Name: attach.py
# Description: Host API Attach Handler — a real PTY running a tmux client, for the phone
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================
# pyright: reportOptionalMemberAccess=false
# The suppression covers the POSIX-only placeholders: on Windows fcntl/pty/
# termios are None, and every path that touches them is guarded by
# PTY_AVAILABLE, which the checker cannot narrow across a module boundary.
# Same pattern as server.py's [host] extra and handlers/google/auth.py.

"""
Host API Attach Handler

The terminal lane (DPLAN-0300 Round 18b/18c). A WebSocket carrying a real PTY
that runs a tmux CLIENT into a branch's persistent room — the same window the
desktop has, over a different wire.

WHY THIS IS NOT THE POLL/CAPTURE LANE THAT WAS BRIEFED FIRST
------------------------------------------------------------------------
Round 18 briefed a capture-and-repaint design: poll `tmux capture-pane`, render
the text, send keys back. Patrick corrected it four minutes later, and the
sentence is worth keeping because it is the whole difference:

    repaint-polling shows a PICTURE of the room that updates.
    attach gives you THE ROOM.

A picture has to be re-fetched, drifts between frames, and cannot carry a
program that draws its own cursor. Attaching makes the phone a real tmux client,
so scrollback, colour, cursor position and full-screen programs all work because
nobody is reimplementing them.

MIRROR THE DESKTOP, DO NOT REDESIGN IT
------------------------------------------------------------------------
`pty.rs` on the desktop spawns a PTY running `tmux new-session -A -t <room>`.
This runs the SAME command. Attach-or-create, identical semantics, so a phone
and a desktop attaching to one branch land in one room rather than two.

A launch IS an attach (their `Terminal.tsx`, since m6). There is no third mode
here and no launch endpoint: the client attaches, then writes the command bytes
into the socket exactly as their terminal types into the pty after `ptyCreate`.
`resume_id` and `has_history` already ride the fleet card, so this lane needs no
read route to support fresh/resume — the decision is made where the card is
rendered, which is where the desktop makes it too.

WHY A SECOND PTY IS NOT A SECOND DOOR
------------------------------------------------------------------------
The one-door rule governs ENDING a session — `room_kill`, reached here only
through `--end-room`, untouched by this module. Attaching a tmux client is
ordinary tmux usage, and tmux itself stays the single source of truth for the
room. The desktop's PTY is Rust and this one is Python because they run in
different processes on different platforms; that is a parallel implementation of
a client, not a competing implementation of a mechanism.

D0 STILL HOLDS WHERE IT MATTERS. `verbs.py` imports no subprocess machinery and
cannot run a program. This module can — it is the exec lane, like `fleet.py`,
and the rule was always that the exec lives in ONE named place per mechanism
rather than leaking into the lane that validates.

DETACH IS A HANGUP, AND THE ROOM SURVIVES IT
------------------------------------------------------------------------
Closing the socket sends SIGHUP to the tmux CLIENT, which detaches. The session,
the agent inside it, and its scrollback all live on — that is the desktop's exact
lifecycle and the reason a phone can close a sheet without consequence. What must
never happen is this module killing a session: it never calls kill-session, never
sends `tmux kill-*` anything, and a test reads this file to prove it.

AUTH ON A WEBSOCKET, AND WHY NOT THE QUERY STRING
------------------------------------------------------------------------
A browser cannot set an `Authorization` header on a WebSocket. The two options
are a query parameter or the `Sec-WebSocket-Protocol` subprotocol, and the query
string is disqualified: URLs land in access logs, proxy logs and browser history,
so a token there is a credential written to disk in three places nobody chose.

The subprotocol header is used instead. The server MUST echo back exactly one of
the offered protocols or the browser fails the handshake, so the accepted value
is the sentinel name and never the token itself.

Scope is `operate`, without exception: an attached room is a shell prompt on
Patrick's machine, and there is no reading half to split off.

Functions:
    is_available()   - Whether this platform can host a PTY
    room_name()      - The tmux session name for a branch
    attach_command() - The exact argv the desktop runs
    open_attach()    - Spawn the PTY and return a live session
"""

import os
import shutil
import signal
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# POSIX-only, and that is a platform truth rather than a missing feature: a PTY
# is a Unix object and tmux does not run on Windows either. Guarded exactly like
# the [host] extra so the import cannot take the whole server down on a machine
# that will never use this route.
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

# @baud's naming convention for a branch's room. Mirrored, not invented — this
# is the string their desktop uses, and a room name this server made up would be
# a SECOND room sitting beside the real one with the same agent's name on it.
ROOM_PREFIX = "baud-"

TMUX_BINARY = "tmux"

# The watch lane's binary — the same drone that started this server, so it
# resolves from the server's own PATH with no login shell in between.
MONITOR_BINARY = "drone"

# What a targetless watch calls itself in labels and logs. A watch with no
# target is global mission control, and "watch-" with nothing after it would
# read as a truncated name rather than a deliberate one.
GLOBAL_WATCH_LABEL = "watch-all"

# The subprotocol the client offers, carrying the bearer as a second value. The
# server echoes THIS name back, never the token — the accepted protocol is
# visible in the handshake response.
BEARER_SUBPROTOCOL = "aipass.bearer"

# A terminal that opens at 0x0 renders nothing, and the client resizes on its
# first frame anyway. These are only what the room sees for the few milliseconds
# before that arrives.
DEFAULT_COLS = 80
DEFAULT_ROWS = 24

# tmux itself caps at 65535 and a client asking for more has lost track of what
# it is doing. Refused rather than clamped, because a geometry silently changed
# is a geometry the client will render against wrongly.
MAX_DIMENSION = 1000

# Read size for one pump iteration. Large enough that a full-screen repaint
# arrives in a few frames, small enough that a chatty room cannot starve the
# socket writer.
READ_CHUNK_BYTES = 65536


class AttachRefused(Exception):
    """The caller asked for something invalid. Their fault, and they may know."""


class AttachUnavailable(Exception):
    """The attach could not happen for a reason that is not the caller's."""


def is_available() -> bool:
    """
    Whether this platform can host a PTY at all.

    Returns:
        True on POSIX with the pty module importable.
    """
    return PTY_AVAILABLE


def _tmux_safe(text: str) -> str:
    """
    Flatten anything outside [A-Za-z0-9_-] to '-', mirroring @baud's sanitize.

    '.' and ':' carry tmux target syntax; a name containing them would glob or
    address another session. Same charset as `room_name` in @baud's lib.rs —
    the two implementations are pinned to the same test vectors.

    Args:
        text: Raw name component.

    Returns:
        The tmux-safe form.
    """
    return "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "_-" else "-" for ch in text)


def room_name(branch: str, scope: str = "") -> str:
    """
    The tmux session name for a branch, in @baud's convention.

    Anchor rooms keep their historical plain names ('baud-memory'); a branch
    in another project carries that project as a scope
    ('baud-vera-studio-vera'), so two projects' same-named branches can never
    land in each other's sessions. The rule is the desktop's `room_name` in
    lib.rs, mirrored — a phone attach and a desktop attach must always agree
    on which room a card means.

    Args:
        branch: Branch name, with or without a leading '@'.
        scope: The branch's project, LOWERCASED by the caller, for non-anchor
            projects. Empty for the anchor.

    Returns:
        The session name, e.g. 'baud-memory' or 'baud-vera-studio-vera'.
    """
    plain = _tmux_safe(branch.strip().lstrip("@"))
    if scope:
        return ROOM_PREFIX + _tmux_safe(scope) + "-" + plain
    return ROOM_PREFIX + plain


def shell_room_name(project: str, branch: str = "") -> str:
    """
    The tmux session name for an EMPTY shell — no claude, just a prompt.

    A separate `baud-shell-` namespace, deliberately: the fleet scan matches
    agent rooms by exact name and skips everything else under 'baud-', so a
    shell can never be mistaken for a branch's live session or dressed up as
    an outside room. The project is ALWAYS in the name — including the
    anchor's — because a shell is a place, and 'baud-shell-devpulse' does not
    say which devpulse when two projects have one.

    Args:
        project: The project the shell stands in, lowercased by the caller
            (census name for external projects, seated name for the anchor).
        branch: Branch whose directory the shell opens in; empty for a shell
            at the project root.

    Returns:
        'baud-shell-aipass', 'baud-shell-aipass-devpulse',
        'baud-shell-testing-testing' — that shape.
    """
    room = ROOM_PREFIX + "shell-" + _tmux_safe(project.strip().lower())
    if branch and branch.strip():
        room += "-" + _tmux_safe(branch.strip().lstrip("@"))
    return room


def valid_monitor_target(target: str) -> bool:
    """
    Charset fence for a watch target — MIRRORED from `valid_monitor_target`
    in @baud's pty.rs, character for character.

    A branch list ('seedgo,cli') or the 'commons' feed keyword. Anything
    outside it is refused: the phone picks targets off the fleet snapshot, it
    never composes command lines — and the fence is what makes that a fact
    about the system rather than a fact about today's client.
    """
    return bool(target) and all(
        ch.islower() and ch.isascii() or ch.isdigit() and ch.isascii() or ch in "_-," for ch in target
    )


def monitor_command(target: str = "") -> List[str]:
    """
    The watch argv: `drone @prax monitor run <target>` — the exact command the
    desktop's monitor pane runs (pty.rs `monitor_create`), minus its login
    shell: this server was itself started by drone, so drone resolves from the
    server's own PATH and there is no shell for a target to be interpreted by.

    AN EMPTY TARGET DROPS THE ARGUMENT ENTIRELY, and that is the whole point of
    the default. `drone @prax monitor run` with nothing after it is global
    mission control — every branch at once — and it is what the desktop runs.
    @prax also documents `run all` for the same thing, and this lane deliberately
    does NOT use it: the desktop's argv is the one being mirrored, and if those
    two paths ever diverge on @prax's side the phone must diverge with the desk,
    not with the synonym.

    Before this, the no-target form was unreachable: the charset fence refused
    an empty string and this function always appended one. @baud measured it and
    shipped the phone's door DISABLED rather than pointing it at a single
    branch's monitor, which would have rendered perfectly and been a lie.

    Args:
        target: A branch list or 'commons'. Empty means every branch.

    Returns:
        The argv, with no trailing argument when target is empty.
    """
    command = ["drone", "@prax", "monitor", "run"]
    if target:
        command.append(target)
    return command


def attach_command(branch: str, scope: str = "") -> List[str]:
    """
    The exact argv the desktop runs, mirrored — including its room options.

    `new-session -A` is attach-or-create: it attaches to the room if it exists
    and creates it if it does not, which is why the phone and the desktop cannot
    end up in two different rooms for one branch. The two options that follow
    are what make a room born HERE identical to one born at the desk: without
    them a phone-created room comes up with no scroll lane and the wrong sizing
    policy, so the phone-only path would get the worst geometry of the two.

    EVERY CHAINED COMMAND CARRIES ITS OWN -t, AND THAT IS THE WHOLE POINT.
    @baud's `pty.rs` chained `set-option mouse on` with no target. A chained
    set-option without one writes to whatever tmux considers the CURRENT
    session — never the room being opened. It parses, it exits 0, it does
    nothing, and no BAUD room had mouse on from the day rooms were born. The
    code read correctly; only `show-options` against a live room could tell.

    Args:
        branch: Branch whose room to attach to.
        scope: The branch's project scope for non-anchor projects — see
            `room_name`.

    Returns:
        The tmux client command as a list — a list, never a string, because a
        list never reaches a shell and a branch name therefore cannot be one.
        `;` is its own argument: that is how tmux separates commands in an argv,
        and it is why no shell escaping is involved anywhere here.
    """
    return client_command(room_name(branch, scope))


def client_command(room: str) -> List[str]:
    """
    The tmux client argv for a NAMED room — the shared tail of every attach.

    Agent rooms and empty shells differ only in what runs inside and where the
    room is born; the client that carries the bytes is identical. One builder,
    so the mouse and window-size lessons in `attach_command`'s docstring are
    learned once and hold for both.
    """
    return [
        TMUX_BINARY,
        "new-session",
        "-A",
        "-s",
        room,
        # Session option: the scroll lane. -t names the room explicitly.
        ";",
        "set-option",
        "-t",
        room,
        "mouse",
        "on",
        # Window option, hence -w. `smallest` measured by @baud against two real
        # clients: it holds the phone through a desk resize and self-heals on
        # detach, which `latest` and `largest` do not.
        ";",
        "set-option",
        "-w",
        "-t",
        room,
        "window-size",
        "smallest",
    ]


def set_winsize(descriptor: int, cols: int, rows: int) -> None:
    """
    Stamp a terminal size into the kernel for a PTY.

    Published rather than private because two callers need it and they must not
    disagree: the initial size set the moment the PTY is created, and every
    resize the client sends afterwards. Two copies of a struct-packing call is
    how a startup geometry and a live geometry end up transposed relative to
    each other.

    Args:
        descriptor: The PTY master.
        cols: Column count, already validated.
        rows: Row count, already validated.

    Raises:
        AttachUnavailable: This platform has no TIOCSWINSZ.
    """
    if not PTY_AVAILABLE:
        raise AttachUnavailable("Setting a terminal size needs a PTY, which this platform does not have")

    # struct winsize is (rows, cols, xpixel, ypixel) — rows FIRST. Getting that
    # pair backwards produces a room that renders at a plausible but wrong
    # shape, which reads as a rendering bug rather than a bad ioctl.
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, packed)


class AttachSession:
    """
    One live PTY running one tmux client.

    Owns the file descriptor and the child process, and knows how to hang up.
    Deliberately not a context manager: the socket handler's lifecycle is the
    session's lifecycle, and hiding that in a `with` would make the close path
    harder to see than it deserves to be.
    """

    def __init__(self, process: Any, descriptor: int, branch: str, room: str, read_only: bool = False) -> None:
        """
        Args:
            process: The spawned tmux client.
            descriptor: Master side of the PTY.
            branch: Branch this room belongs to.
            room: The tmux session name.
            read_only: A tier-0 watch — output streams, input refuses. The
                refusal lives HERE, at the layer that counts, exactly where the
                desktop puts it (`pty_write` refuses monitor panes): a client
                that never sends bytes is politeness, a session that refuses
                them is the contract.
        """
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
        """
        Read whatever the room has produced.

        Args:
            size: Maximum bytes to take.

        Returns:
            Raw bytes, or empty when the PTY has closed. Bytes, never str: the
            room emits escape sequences and partial UTF-8 across chunk
            boundaries, and decoding here would corrupt both.
        """
        try:
            return os.read(self.descriptor, size)
        except OSError as e:
            # The child exited and the master went away. Not an error — it is
            # how a PTY reports end-of-life, and the caller closes the socket.
            # Logged at debug rather than swallowed: this fires exactly once per
            # session, and when a room dies for a reason nobody expected, the
            # errno is the only thing that says which.
            logger.debug("[host_api] PTY for %s reached end of life: %s", self.room, e)
            return b""

    def write(self, data: bytes) -> None:
        """
        Type into the room.

        Args:
            data: Raw bytes from the client, forwarded UNCHANGED. Key bar
                buttons send real control bytes (\\x03 for Ctrl+C), exactly as a
                keyboard would, so there is nothing here to interpret and no
                allowlist to keep in step with somebody else's.

        Raises:
            AttachRefused: This is a read-only watch — nothing types into it.
        """
        if self.read_only:
            raise AttachRefused(f"{self.room} is a read-only watch — nothing types into it")
        os.write(self.descriptor, data)

    def resize(self, cols: int, rows: int) -> None:
        """
        Resize the PTY, so the room draws at the client's geometry.

        Args:
            cols: Column count.
            rows: Row count.

        Raises:
            AttachRefused: A dimension that is not a usable terminal size.
            AttachUnavailable: This platform has no TIOCSWINSZ.
        """
        if not PTY_AVAILABLE:
            raise AttachUnavailable("Resizing needs a PTY, which this platform does not have")

        set_winsize(
            self.descriptor,
            _require_dimension(cols, "cols"),
            _require_dimension(rows, "rows"),
        )

    def hangup(self) -> None:
        """
        Detach: SIGHUP the tmux CLIENT and let the room live on.

        This is the whole lifecycle promise. The client process dies, the
        session it was attached to does not, and everything running inside it
        keeps running — which is why closing a sheet on a phone is free.

        Idempotent: a socket that errors and then closes calls this twice.
        """
        if self._closed:
            return

        self._closed = True

        try:
            # SIGHUP, not SIGKILL: a hangup is what a detaching terminal sends,
            # and tmux clients handle it as a clean detach.
            self.process.send_signal(signal.SIGHUP)
        except (ProcessLookupError, OSError) as e:
            logger.debug("[host_api] attach client for %s was already gone: %s", self.room, e)

        try:
            os.close(self.descriptor)
        except OSError as e:
            logger.debug("[host_api] attach descriptor for %s was already closed: %s", self.room, e)

        json_handler.log_operation("host_api_attach_closed", {"branch": self.branch, "room": self.room})
        logger.info("[host_api] detached from %s — the room survives", self.room)


def open_attach(branch: str, cwd: Optional[Path] = None, scope: str = "", room: str = "") -> AttachSession:
    """
    Spawn a PTY running a tmux client into a branch's room.

    Args:
        branch: Branch whose room to attach to. Required unless `room` names
            the room directly (an empty shell has no branch to be named after).
        cwd: Directory the room is created in when it does not exist yet — the
            branch's own directory, so an attach-or-create lands somewhere that
            makes sense rather than wherever this server was started.
        scope: The branch's project scope for non-anchor projects — decides
            the room NAME, exactly as the desktop decides it (see `room_name`).
        room: Explicit room name override — the shell lane's door. When set,
            `branch`/`scope` no longer decide the name (use `shell_room_name`
            to build it) and `branch` may be empty.

    Returns:
        A live AttachSession.

    Raises:
        AttachRefused: No branch named and no room override.
        AttachUnavailable: No PTY on this platform, or tmux is not installed.
    """
    if not PTY_AVAILABLE:
        raise AttachUnavailable("This host cannot attach: a PTY is a POSIX object and this platform has none")

    if not (room and room.strip()) and (not branch or not branch.strip()):
        raise AttachRefused("A branch name is required — this lane has no default room")

    if not shutil.which(TMUX_BINARY):
        # Named rather than shrugged at: tmux missing is a real, fixable state,
        # and "attach failed" with no subject is a support ticket.
        raise AttachUnavailable(f"{TMUX_BINARY} is not installed on this host — the attach lane runs a tmux client")

    if room and room.strip():
        room = room.strip()
        command = client_command(room)
    else:
        room = room_name(branch, scope)
        command = attach_command(branch, scope)

    process, master = _spawn_pty(command, cwd, room)

    json_handler.log_operation("host_api_attach_opened", {"branch": branch, "room": room, "pid": process.pid})
    logger.info("[host_api] attached to %s (pid %s)", room, process.pid)

    # A shell has no branch; its room name is the truest label it owns.
    return AttachSession(process, master, branch.strip().lstrip("@") or room, room)


def open_monitor(target: str = "", cwd: Optional[Path] = None) -> AttachSession:
    """
    Spawn a tier-0 watch: `drone @prax monitor run <target>` on its own PTY.

    The phone twin of the desktop's monitor pane (m9): live output, no
    keyboard. Deliberately NOT tmux-backed — the opposite call from the shell
    lane, for the opposite reason. A shell holds work, so it must survive its
    client; a watch holds nothing, so when the socket closes the observer
    dies and nothing was lost. A persistent watcher would just be a process
    printing into a room nobody is in.

    Args:
        target: What to watch — a branch name off the fleet snapshot, or
            'commons' for the feed. EMPTY means global mission control, every
            branch at once, which is the desktop's own default form. A non-empty
            target is fenced by `valid_monitor_target`.
        cwd: Where the monitor runs — the repo root, where drone expects to
            stand.

    Returns:
        A live AttachSession with `read_only=True` — its `write` refuses.

    Raises:
        AttachRefused: A named target fails the charset fence.
        AttachUnavailable: No PTY on this platform, or drone is not on PATH.
    """
    if not PTY_AVAILABLE:
        raise AttachUnavailable("This host cannot attach: a PTY is a POSIX object and this platform has none")

    cleaned = target.strip().lstrip("@")

    # ABSENCE IS NOT A BAD VALUE, and the two questions are kept apart on
    # purpose. `valid_monitor_target` is mirrored from @baud's pty.rs character
    # for character and answers "is this string a legal target" — so it still
    # refuses the empty string and stays a faithful mirror. Whether a target was
    # NAMED AT ALL is asked here, once, before the fence is consulted. Folding
    # "" into the fence would have been the shorter diff and would have quietly
    # broken the mirror this lane's safety rests on.
    if cleaned and not valid_monitor_target(cleaned):
        raise AttachRefused(f"Not a monitor target: {target!r}")

    if not shutil.which(MONITOR_BINARY):
        raise AttachUnavailable(f"{MONITOR_BINARY} is not on this host's PATH — the watch lane runs it")

    label = f"watch-{cleaned}" if cleaned else GLOBAL_WATCH_LABEL
    process, master = _spawn_pty(monitor_command(cleaned), cwd, label)

    json_handler.log_operation("host_api_watch_opened", {"target": cleaned, "pid": process.pid})
    logger.info("[host_api] watching %s (pid %s)", cleaned or "every branch", process.pid)

    return AttachSession(process, master, cleaned or GLOBAL_WATCH_LABEL, label, read_only=True)


def _spawn_pty(command: List[str], cwd: Optional[Path], room: str) -> tuple:
    """
    Spawn `command` as the child of a fresh PTY. The shared mechanics of every
    lane that ends in a live terminal — attach, shell, and watch differ only
    in what runs and whether it listens.

    Args:
        command: The argv to run.
        cwd: Directory the child starts in; None inherits the server's.
        room: What to call this session in logs and error sentences.

    Returns:
        (process, master descriptor).

    Raises:
        AttachUnavailable: The spawn itself failed; both descriptors are
            closed before the error leaves.
    """
    # openpty rather than fork: the child is a normal subprocess with the slave
    # as its three standard descriptors, so it can be signalled and waited on
    # like anything else. forkpty would hand back a bare pid and a fork this
    # process has no other reason to own.
    # Not a file open: a PTY is a byte pipe with no encoding='utf-8' to give it.
    # Decoding happens nowhere in this module — see AttachSession.read().
    master, slave = pty.openpty()

    # openpty hands back a 0x0 terminal, and a tmux client reads that at startup,
    # decides it is not a real size, and falls back to its OWN 80x24. The
    # contract has always PROMISED 80x24 and until the stamp it was true only by
    # that accident. Stamped for real, before the child exists, so the contract
    # and the kernel agree from the first byte.
    set_winsize(master, DEFAULT_COLS, DEFAULT_ROWS)

    try:
        process = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=str(cwd) if cwd else None,
            # NOT start_new_session: that gives the child its own session and no
            # CONTROLLING TERMINAL, and a pty with no controlling terminal is
            # DEAF. TIOCSWINSZ delivers SIGWINCH to the foreground process group
            # of the controlling tty; with none, the signal has no destination.
            # The resize reached the kernel and the client never heard it — every
            # resize, forever. _acquire_controlling_tty does the setsid itself,
            # so the signal isolation start_new_session bought is kept.
            preexec_fn=_acquire_controlling_tty,  # noqa: PLW1509 - see the note in that function
            close_fds=True,
            env=_child_env(),
        )
    except OSError as e:
        os.close(master)
        os.close(slave)
        logger.error("[host_api] could not start a client for %s: %s", room, e)
        raise AttachUnavailable(f"Could not start a client for {room}: {e}") from e
    finally:
        # The child holds its own copy; keeping ours open would mean the master
        # never reports EOF when the client exits, and the pump would hang
        # forever on a room that is already gone.
        try:
            os.close(slave)
        except OSError as e:
            logger.debug("[host_api] slave descriptor for %s was already closed: %s", room, e)

    return process, master


# ==============================================
# INTERNALS
# ==============================================


def _acquire_controlling_tty(
    _setsid: Any = getattr(os, "setsid", None),
    _login_tty: Any = getattr(os, "login_tty", None),
    _ioctl: Any = getattr(fcntl, "ioctl", None),
    _tiocsctty: Any = getattr(termios, "TIOCSCTTY", None),
) -> None:
    """
    Run in the CHILD, between fork and exec: take the slave as our controlling tty.

    This is the whole reason resizes work. A PTY only delivers SIGWINCH to the
    foreground process group of its CONTROLLING terminal, and a controlling
    terminal is never acquired by INHERITING an already-open descriptor — only
    by a session leader opening a tty, or by TIOCSCTTY. `start_new_session=True`
    gave the child a fresh session and therefore no controlling terminal at all,
    so every TIOCSWINSZ landed in the kernel and reached nobody. The room was
    deaf to every resize any client would ever send.

    By the time this runs, subprocess has already dup'd the slave onto fds 0, 1
    and 2, so fd 0 IS the terminal to claim.

    THE preexec_fn CAVEAT, stated rather than hidden: this runs after fork in a
    process that has threads (uvicorn's executor, among others), where only
    async-signal-safe work is really allowed. Both operations here are single
    syscalls, and every callable and constant they need is bound as a DEFAULT
    ARGUMENT so the child performs no attribute lookup, no import and no
    allocation before exec — which is the standard mitigation, and the reason
    this function takes arguments nobody ever passes.

    EVERY DEFAULT IS A getattr, INCLUDING os.setsid — that is not style. A bare
    `os.setsid` in this signature is evaluated when the module is IMPORTED, and
    the attribute does not exist on Windows, so it raised AttributeError before
    any platform guard could run and took `attach` down, then `server`, then
    `host_api`, then every test file that imports them. One line cost 22
    collection errors on the Windows lane (2026-08-18). The POSIX-only names
    are already fetched this way; this one was the exception and the exception
    was the bug.

    Args:
        _setsid: Bound at definition time. Never passed. None off POSIX.
        _login_tty: Bound at definition time. Never passed. None before 3.11.
        _ioctl: Bound at definition time. Never passed. None off POSIX.
        _tiocsctty: Bound at definition time. Never passed. None off POSIX.

    Raises:
        AttachUnavailable: This platform has no way to acquire a controlling
            tty. No caller can reach it — every one of them is behind
            PTY_AVAILABLE — so this refuses rather than pretending, and it
            refuses in the CHILD, which subprocess reports to the parent.
    """
    if _login_tty is not None:
        # One C call doing setsid + TIOCSCTTY + the dup2s. Less Python running
        # in a forked child is strictly better here. Python 3.11+.
        _login_tty(0)
        return

    if _setsid is None or _ioctl is None or _tiocsctty is None:
        # Three identity comparisons: async-signal-safe, and nothing is
        # allocated until the platform has already lost.
        raise AttachUnavailable("This platform cannot acquire a controlling tty")

    _setsid()
    _ioctl(0, _tiocsctty, 0)


def _child_env() -> Dict[str, str]:
    """
    The environment the tmux client runs in.

    Returns:
        A copy of this process's environment with TERM pinned. The phone's
        xterm.js is xterm-256color, and a client inheriting a server's bare or
        missing TERM renders a room in the wrong capability set — which looks
        like an application bug rather than an environment one.
    """
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    return env


def _require_dimension(value: Any, name: str) -> int:
    """
    Validate one terminal dimension.

    Args:
        value: Caller-supplied size.
        name: Which dimension, for the message.

    Returns:
        The value as an int.

    Raises:
        AttachRefused: Not a whole number, not positive, or over the cap.
    """
    try:
        size = int(value)
    except (TypeError, ValueError) as e:
        raise AttachRefused(f"{name} must be a whole number, got {value!r}") from e

    if size <= 0:
        raise AttachRefused(f"{name} must be positive, got {size}")

    if size > MAX_DIMENSION:
        raise AttachRefused(f"{name} is {size}, over the {MAX_DIMENSION} cap")

    return size
