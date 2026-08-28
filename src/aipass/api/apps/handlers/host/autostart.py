# =================== AIPass ====================
# Name: autostart.py
# Description: Host API Autostart Handler — the supervisor seam, so the server survives a reboot
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""
Host API Autostart Handler

What it takes for the tailnet server to come back on its own, and how this
branch finds out that something else is holding it.

WHY THIS EXISTS
---------------
On 2026-08-27 @baud's phone face went dark. `host_api_serve.log` showed normal
traffic, then silence — no traceback, no shutdown line. A detached server dies
with the machine, and nothing brought it back; Patrick ruled that a face which
waits for a human after every reboot is wrong.

WHY SYSTEMD AND NOT A LOOP OF MY OWN
------------------------------------
`lifetime.py` refuses on principle to restart anything, and that refusal is
still right: the fourteen death-and-restart cycles @baud read out of a pane on
2026-08-19 came FROM a supervisor — a shell loop somebody typed. Answering a
missing supervisor with a second home-grown one repeats the mistake with better
manners. systemd is already running on this host, already owns boot ordering,
and already knows how to not restart something an operator deliberately stopped.

So this handler supervises nothing. It RENDERS a unit, ANSWERS whether the
supervisor currently holds the server, and ASKS it to stop. Every actual
decision about starting, restarting and boot ordering belongs to systemd.

THE TWO THINGS THAT MAKE THIS SAFE RATHER THAN MERELY AUTOMATIC
---------------------------------------------------------------
`status` must not lie. Today it reads a record file written by `serve_detached`,
and a unit-managed server writes no such record — so a perfectly healthy server
would be reported as absent, which is the exact failure that costs an operator
an hour at 3am. `supervised_pid()` is what closes that.

`stop` must not become a trap. Signalling the pid directly while a restart
policy watches it is how you get a command that appears to work and undoes
itself seconds later. When the supervisor owns the process, stop goes THROUGH
the supervisor, which suppresses the restart policy by definition.

Functions:
    is_supported()      - Whether this platform has a user-level systemd
    unit_name()         - The unit's name
    unit_text()         - Render the unit file from argv, workdir and log path
    supervised_pid()    - The unit's live main pid, or 0
    supervised_bind()   - The address the supervised server was actually started on
    stop_unit()         - Ask the supervisor to stop the unit
    linger_enabled()    - Whether this account's units survive logout
    install_commands()  - The exact host-side steps, in order
    installation_report() - Everything the autostart command has to show
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# The unit's name is part of the contract with whoever installs it: the reply
# that carries the install commands and the code that asks "are you holding
# it?" have to mean the same unit, so it is spelled once.
UNIT_NAME = "aipass-host-api.service"

# Where a user unit lives. Rendered into install instructions only — nothing
# here ever writes outside this tree.
USER_UNIT_DIR = "~/.config/systemd/user"

# How long any systemctl question may take. A supervisor probe that hangs turns
# `status` — the command an operator runs precisely when things are strange —
# into another thing that is not answering.
PROBE_TIMEOUT_SECONDS = 5.0

# How long to wait for the supervisor to bring the unit down. Longer than
# lifetime's own stop wait, because systemd runs the graceful shutdown AND the
# bookkeeping after it.
STOP_TIMEOUT_SECONDS = 20.0

# Restart policy, and the reasoning is the tailnet address. At boot this server
# may come up before tailscaled has assigned the address it is configured to
# bind, and that failure looks exactly like a fatal misconfiguration: it exits
# non-zero immediately. So the retry window is generous enough to outlast a slow
# network (60 attempts, 5s apart, inside 10 minutes) and still FINITE, because a
# genuinely impossible bind should end as a unit in `failed` that says so, not
# as a process quietly retrying forever into a growing log.
RESTART_SECONDS = 5
START_LIMIT_INTERVAL_SECONDS = 600
START_LIMIT_BURST = 60

# systemd's own graceful-stop budget. Above lifetime's ten seconds so the
# supervisor is never the thing that cuts a shutdown short.
TIMEOUT_STOP_SECONDS = 15


class AutostartUnsupported(Exception):
    """This platform has no user-level systemd to hand the server to."""


class SupervisorUnreachable(Exception):
    """
    There IS a supervisor here and it did not answer.

    Deliberately separate from AutostartUnsupported, because the two look
    identical at the call site and mean opposite things. No systemd at all is a
    MEASUREMENT — there is no unit and there cannot be one, so zero is the
    truth. A systemctl that hangs, times out or cannot be executed on a machine
    that has one is an ABSENCE of measurement, and reporting that as "no unit is
    running" is the same defect the status lane was just fixed for: answering
    absence when the honest answer is I could not ask.
    """


def is_supported() -> bool:
    """
    Whether the supervisor lane can work on this platform at all.

    Returns:
        True when this is Linux and systemctl is on PATH.

    Note:
        Asked before every probe rather than once at import. A branch that
        answers "no autostart here" honestly on Windows or macOS is worth more
        than one that raises FileNotFoundError out of a status command — and
        seedgo's Windows check exists because `--detach` already shipped one
        POSIX-only assumption that reported success while doing nothing.
    """
    if not sys.platform.startswith("linux"):
        return False

    return shutil.which("systemctl") is not None


def unit_name() -> str:
    """
    The unit this branch installs and asks about.

    Returns:
        The unit name, including the .service suffix.
    """
    return UNIT_NAME


def unit_text(argv: List[str], workdir: Path, log: Path) -> str:
    """
    Render the unit file.

    Args:
        argv: The exact command that starts the server, already built by the
            lifetime lane — so the supervised server and a detached one are
            started by one spelling and cannot drift apart.
        workdir: The branch root the server runs from.
        log: The file its output appends to.

    Returns:
        The unit file's full text.

    Note:
        StandardOutput=append: is what keeps requirement three — the SAME
        `host_api_serve.log`, appended, across reboots and restarts. It is the
        continuity that made this morning's outage diagnosable at all: a log
        that starts fresh on every restart cannot tell you that traffic stopped
        rather than that the file is new.

        StartLimit* sit under [Unit] and not [Service]. systemd moved them in
        v230 and accepts the old spelling by IGNORING it — a rate limit written
        in the wrong section is not an error, it is an absence, which is the
        kind of silent no-op this branch has been bitten by before.
    """
    command = " ".join(argv)

    return f"""[Unit]
Description=AIPass host API — the tailnet server behind BAUD's phone face
Documentation=file://{workdir}/README.md
StartLimitIntervalSec={START_LIMIT_INTERVAL_SECONDS}
StartLimitBurst={START_LIMIT_BURST}

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={command}
StandardOutput=append:{log}
StandardError=append:{log}
Restart=on-failure
RestartSec={RESTART_SECONDS}
KillSignal=SIGTERM
TimeoutStopSec={TIMEOUT_STOP_SECONDS}

[Install]
WantedBy=default.target
"""


def _systemctl(arguments: List[str], timeout: float) -> Optional[subprocess.CompletedProcess]:
    """
    Run a `systemctl --user` command.

    Args:
        arguments: Everything after `--user`.
        timeout: Seconds to allow.

    Returns:
        The completed process, or None when systemctl could not be run at all.
    """
    if not is_supported():
        return None

    try:
        return subprocess.run(
            ["systemctl", "--user", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        # RAISED, not swallowed into None. This machine HAS a systemctl and it
        # did not answer — folding that into the same None the no-systemd
        # platform returns is what turned "I could not ask" into "nothing is
        # running" one layer up.
        logger.warning("[host_api] the supervisor could not be reached: %s", e)
        raise SupervisorUnreachable(f"systemctl is here but did not answer: {e}") from e


def supervised_pid() -> int:
    """
    The unit's live main process id.

    Returns:
        The pid, or 0 when no unit is holding the server — including on a
        platform that has no systemd at all.

    Raises:
        SupervisorUnreachable: There is a systemctl here and it did not answer.

    Note:
        THE RULING, asked for by @devpulse 2026-08-27 and split in two because
        the question has two answers.

        NO SYSTEMD ON THIS PLATFORM ANSWERS ZERO, and that is not a refusal
        dodged. Zero means "no unit is holding the server", and on a machine
        that cannot have a unit that is a fact with no uncertainty in it — the
        strongest answer this probe can give. running() then falls through to
        the detached record, which is the only kind of server that can exist
        there, so the caller gets the truth rather than an exception it would
        have to translate back into the same truth.

        A PROBE THAT FAILED ON A CAPABLE MACHINE DOES NOT ANSWER ZERO. That one
        does deserve refuse-dont-zero: on the tailnet host the unit is live and
        writes NO record file, so a swallowed probe would send running() to a
        record that does not exist and status would print "No server is
        running" while the server was answering requests. That is the exact
        defect this lane was built to close, one layer down from where it was
        found.

        `show -p MainPID` rather than `is-active`. is-active EXITS NON-ZERO for
        an unknown or inactive unit, so a caller has to read an exit code to
        tell "no" from "could not ask"; show answers 0 with MainPID=0 in both
        of those cases and reserves a non-zero exit for a real failure to run.
        A probe whose absence-answer and error-answer look different is worth
        the extra parsing.
        `show -p MainPID` rather than `is-active`. is-active EXITS NON-ZERO for
        an unknown or inactive unit, so a caller has to read an exit code to
        tell "no" from "could not ask"; show answers 0 with MainPID=0 in both
        of those cases and reserves a non-zero exit for a real failure to run.
        A probe whose absence-answer and error-answer look different is worth
        the extra parsing.
    """
    result = _systemctl(["show", UNIT_NAME, "-p", "MainPID", "--value"], PROBE_TIMEOUT_SECONDS)

    if result is None or result.returncode != 0:
        return 0

    raw = (result.stdout or "").strip()

    try:
        pid = int(raw)
    except ValueError:
        logger.warning("[host_api] the supervisor reported an unreadable MainPID: %r", raw)
        return 0

    return pid if pid > 0 else 0


def supervised_bind() -> Tuple[Optional[str], Optional[int]]:
    """
    The address the supervised server was actually started on.

    Returns:
        A (host, port) pair read from the unit's own ExecStart, or (None, None)
        when it could not be read.

    Raises:
        Nothing. An unreadable bind is reported as unknown, never guessed.

    Note:
        READ FROM THE UNIT, NOT FROM THE STORED CONFIG. The unit pins its bind
        at install time; `set-config` afterwards changes what the NEXT install
        would use and nothing about the process currently listening. Reporting
        the config here would produce a status line that is confidently wrong
        exactly once — after somebody changes the port and before they reinstall
        — which is the worst possible time for it.
    """
    # Tolerant on purpose, and it is not the same call as the pid probe: this
    # only decorates a status line that has ALREADY established a live unit, so
    # an unreachable supervisor here cannot produce a wrong verdict — only a
    # missing bind, which prints as "unknown".
    try:
        result = _systemctl(["show", UNIT_NAME, "-p", "ExecStart", "--value"], PROBE_TIMEOUT_SECONDS)
    except SupervisorUnreachable as e:
        # Swallowed HERE and nowhere else, and it leaves a record saying so. The
        # verdict was already established by the pid probe; losing the bind only
        # costs a status line its address, which prints as "unknown".
        logger.warning("[host_api] the unit's bind could not be read: %s", e)
        return (None, None)

    if result is None or result.returncode != 0:
        return (None, None)

    line = (result.stdout or "").strip()

    if not line:
        return (None, None)

    words = line.replace(";", " ").split()

    return (_flag_in(words, "--host"), _port_in(words))


def _flag_in(words: Sequence[str], flag: str) -> Optional[str]:
    """
    The value following *flag* in a systemd argv line.

    Args:
        words: The ExecStart line, already split. A Sequence rather than a List
            because this only reads it — List is invariant, so a list of string
            literals is not assignable to List[str] and the checker was right
            to say so.
        flag: The flag to find.

    Returns:
        The value, or None when the flag is absent or ends the line.
    """
    for name, value in zip(words, words[1:]):
        if name == flag:
            return value

    return None


def _port_in(words: Sequence[str]) -> Optional[int]:
    """
    The port the unit was started on.

    Args:
        words: The ExecStart line, already split.

    Returns:
        The port, or None when it is absent or unreadable. Never a guess — a
        status line that invents a port is worse than one saying unknown.
    """
    raw = _flag_in(words, "--port")

    if raw is None:
        return None

    try:
        return int(raw)
    except ValueError:
        logger.warning("[host_api] the unit names an unreadable port: %r", raw)
        return None


def stop_unit() -> bool:
    """
    Ask the supervisor to stop the unit.

    Returns:
        True when systemd accepted the stop.

    Raises:
        AutostartUnsupported: There is no user-level systemd here.

    Note:
        THIS IS THE WHOLE REASON `stop` STAYS HONEST. A SIGTERM sent straight to
        a supervised pid is a stop the restart policy is entitled to undo, and a
        command that visibly works and reverses itself a few seconds later is
        worse than one that refuses. `systemctl stop` outranks Restart= by
        definition, so the server stays down until somebody starts it.
    """
    if not is_supported():
        raise AutostartUnsupported("There is no user-level systemd on this platform")

    result = _systemctl(["stop", UNIT_NAME], STOP_TIMEOUT_SECONDS)

    if result is None:
        return False

    if result.returncode != 0:
        logger.warning("[host_api] the supervisor refused the stop: %s", (result.stderr or "").strip())
        return False

    logger.info("[host_api] the supervisor stopped %s", UNIT_NAME)
    json_handler.log_operation("host_api_supervisor_stopped", {"unit": UNIT_NAME})
    return True


def linger_enabled() -> Optional[bool]:
    """
    Whether this account's user units run without a login session.

    Returns:
        True or False, or None when the question could not be asked.

    Note:
        Without lingering a user unit starts when the user logs IN, which for a
        headless host that reboots unattended means it does not start at all —
        the exact failure this build exists to end. It is reported rather than
        assumed, because it is set outside this tree and can be turned off again
        by somebody who never reads this file.
    """
    if not sys.platform.startswith("linux") or shutil.which("loginctl") is None:
        return None

    try:
        result = subprocess.run(
            ["loginctl", "show-user", str(Path.home().name), "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[host_api] lingering could not be read: %s", e)
        return None

    if result.returncode != 0:
        return None

    return (result.stdout or "").strip().lower() == "yes"


def install_commands(unit_file: Path) -> List[str]:
    """
    The exact host-side steps, in the order they must run.

    Args:
        unit_file: The rendered unit inside this branch.

    Returns:
        The commands. NOT run from here — installing a unit means writing under
        the operator's home and enabling something that outlives every session,
        which is outside this tree and is theirs to run.

    Note:
        `enable --now` rather than enable-then-start, so a half-installed unit —
        enabled for the next boot but not running today — cannot be the state
        somebody walks away from.
    """
    return [
        f"mkdir -p {USER_UNIT_DIR}",
        f"cp {unit_file} {USER_UNIT_DIR}/{UNIT_NAME}",
        "systemctl --user daemon-reload",
        f"systemctl --user enable --now {UNIT_NAME}",
        "loginctl enable-linger $USER",
    ]


def installation_report(unit_file: Path) -> dict:
    """
    Everything the autostart command has to show, gathered in one place.

    Args:
        unit_file: The rendered unit inside this branch.

    Returns:
        The unit path, the ordered steps, and whether lingering is on — with
        None meaning the question could not be asked, which is a third answer
        and not a no.

    Note:
        The MODULE above this only prints. Gathering the steps and probing
        lingering are decisions about what is true on this host, which is
        handler work — seedgo refused the first cut for exactly that, and it was
        right: the same report is what a future `autostart --check` would need,
        and it would have had to reach into a CLI function to get it.
    """
    return {
        "unit": unit_file,
        "steps": install_commands(unit_file),
        "linger": linger_enabled(),
    }
