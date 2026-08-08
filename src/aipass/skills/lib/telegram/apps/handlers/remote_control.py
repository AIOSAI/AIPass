# =================== AIPass ====================
# Name: remote_control.py
# Description: /rc verb — recover Claude Code Remote Control for a tmux-hosted agent
# Version: 1.0.0
# Created: 2026-08-07
# Modified: 2026-08-07
# =============================================

"""
Remote Control recovery for tmux-hosted Claude Code agents.

Backs the Telegram `/rc <target>` verb: resolve an agent name to its tmux
session, type the built-in `/remote-control` command into that session, and
report the honest outcome from what the pane actually shows.

Everything here is a pure pane-parsing or resolution seam except the four
subprocess wrappers at the bottom — that split is what makes the behaviour
unit-testable against real captured pane fixtures.

Live-verified against Claude Code v2.1.224 (2026-08-07), which is where every
marker below comes from:

- Typing `/rc` opens the fuzzy palette; the top entry renders as
  `/remote-control (rc)`. Its trailing description differs by state
  ("Disconnect Remote Control" when connected, "Control this session from
  your phone or claude.ai/code" when not) — the description is NOT used as a
  signal, only the command token is.
- Enter while DISCONNECTED reconnects in one step and prints
  `/remote-control is active · ... https://claude.ai/code/session_<id>`.
- Enter while ALREADY CONNECTED opens a status panel instead
  (Disconnect this session / Show QR code / Continue). That panel is modal —
  it must be dismissed with Escape or the target's composer stays wedged.
- The footer indicator is the bare token `/rc` on the status line, present
  only while connected. The published docs describe it as `/rc active`;
  this version renders `/rc`, so both spellings are accepted.
"""

import re
import subprocess
from typing import Optional

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

CONTROL_SESSION_PREFIX = "aipass-"  # same prefix the /start /kill verbs use

RC_COMMAND_TEXT = "/rc"  # the ONLY content this verb ever types into a target
RC_PALETTE_TOKEN = "/remote-control"  # top-entry token verified before Enter

# Footer indicator. Docs say "/rc active"; v2.1.224 renders "/rc" — accept both.
RC_INDICATOR_TOKENS = ("/rc active", "/rc")
FOOTER_SCAN_LINES = 3  # status lines live at the very bottom, below the composer

# Status-panel markers (the already-connected, two-step path)
PANEL_MARKERS = ("Disconnect this session", "Show QR code")

# Busy markers. A running turn renders a spinner glyph plus a gerund ending in
# an ellipsis ("✶ Thinking…", "✽ Scampering… (21s)"); a finished one renders the
# same glyph with past tense and no ellipsis ("✻ Sautéed for 3s"). The ellipsis
# is the discriminator — the elapsed "(21s)" only appears a few seconds in, so
# keying on it alone reads the first seconds of a turn as idle.
BUSY_SPINNER_RE = re.compile(r"^\s*[^\w\s]\s+\S.*…")
BUSY_INTERRUPT_TOKEN = "esc to interrupt"
BUSY_SCAN_LINES = 3  # spinner sits within a line or two of the composer

# Line prefixes that look like a spinner to the regex but never are: tool-result
# continuations and echoed user input. A finished "⎿ Read 200 lines…" sitting
# above an idle composer would otherwise pin the target as permanently busy.
NON_SPINNER_PREFIXES = ("⎿", "❯")

SESSION_URL_RE = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")

PALETTE_SETTLE_SECONDS = 1.5  # let the fuzzy palette render before verifying
CONNECT_SETTLE_SECONDS = 5.0  # let the connection attempt resolve before reading
IDLE_WAIT_SECONDS = 8.0  # how long to wait out a mid-turn target
IDLE_POLL_SECONDS = 1.0


# =============================================
# RESOLUTION
# =============================================


def resolve_agent_session(target: str, sessions: list[str]) -> Optional[str]:
    """
    Resolve an agent name to its tmux session name, or None.

    Session names on this box are not uniform: some agents own a bare session
    named after themselves (``vera``, ``devpulse``) while control-verb
    sessions carry the ``aipass-`` prefix (``aipass-aipass``). Exact match
    wins first so a bare session is never shadowed by a prefixed one.

    Args:
        target: Agent name as typed by the user (``@`` and case are ignored).
        sessions: tmux session names, as returned by list_tmux_sessions().

    Returns:
        The matching session name, or None when nothing matches.
    """
    name = normalize_target(target)
    if not name:
        return None

    by_lower = {s.lower(): s for s in sessions}

    if name in by_lower:
        return by_lower[name]

    prefixed = f"{CONTROL_SESSION_PREFIX}{name}"
    if prefixed in by_lower:
        return by_lower[prefixed]

    return None


def normalize_target(target: str) -> str:
    """Strip the ``@`` sigil, surrounding whitespace, and case from a target name."""
    return target.strip().lstrip("@").strip().lower()


# =============================================
# PANE PARSING
# =============================================


def _non_empty_lines(pane_text: str) -> list[str]:
    """Return the pane's non-blank lines, order preserved."""
    return [line for line in pane_text.splitlines() if line.strip()]


def _status_block(pane_text: str, count: int) -> list[str]:
    """
    The last *count* non-blank lines directly above the composer box.

    This is where the TUI draws transient status — the spinner, the current
    tool line — as opposed to the footer (below the box) or the transcript
    (further up). Falls back to the pane tail when the composer box cannot be
    located, so a narrow or unusual render degrades instead of failing.
    """
    lines = pane_text.splitlines()
    dividers = [idx for idx, line in enumerate(lines) if _is_divider(line)]
    region = lines[: dividers[-2]] if len(dividers) >= 2 else lines
    return [line for line in region if line.strip()][-count:]


def pane_is_busy(pane_text: str) -> bool:
    """
    True when the target session is mid-turn.

    A queued command is a command we cannot verify, so the caller refuses to
    inject while this holds — see _handle_control_rc for why that matters
    more than it looks (an unopened palette would turn Enter into arbitrary
    text sent to another agent's chat).

    Scanning is bounded to the block directly above the composer, where the
    spinner lives. A wider window reaches into transcript scrollback, where an
    unrelated line ending in an ellipsis would pin the target as permanently
    busy and make the verb refuse to run at all.
    """
    for line in _status_block(pane_text, BUSY_SCAN_LINES):
        if BUSY_INTERRUPT_TOKEN in line.lower():
            return True
        if line.lstrip().startswith(NON_SPINNER_PREFIXES):
            continue
        if BUSY_SPINNER_RE.search(line):
            return True
    return False


def rc_indicator_present(pane_text: str) -> bool:
    """
    True when the footer carries the Remote Control indicator.

    Scanning is bounded to the last few lines on purpose: the token ``/rc``
    also appears in scrollback (the echoed command, anything the user typed
    earlier), and matching that would report a dead connection as recovered.
    """
    footer = _non_empty_lines(pane_text)[-FOOTER_SCAN_LINES:]
    blob = "\n".join(footer)
    return any(token in blob for token in RC_INDICATOR_TOKENS)


def palette_top_entry_is_rc(pane_text: str) -> bool:
    """
    True when the fuzzy palette's highlighted top entry is /remote-control.

    The TUI palette fuzzy-matches and will happily surface an unrelated
    registered command; sending Enter without this check is how you run
    something you never asked for (2026-07-31 live incident, learning #95).
    The first palette row above the composer divider is the one Enter takes.
    """
    for line in _palette_rows(pane_text):
        return line.lstrip().startswith(RC_PALETTE_TOKEN)
    return False


def _palette_rows(pane_text: str) -> list[str]:
    """
    Rows of the palette, top entry first.

    The composer is drawn as a box between the pane's last two dividers, and
    the palette renders in the block directly above that box — so the anchor
    is the SECOND-to-last divider, not the last one. Anchoring on the last
    divider finds the composer itself and never sees the palette at all.
    Returns [] when no palette is showing.
    """
    lines = pane_text.splitlines()
    dividers = [idx for idx, line in enumerate(lines) if _is_divider(line)]
    if len(dividers) < 2:
        return []
    composer_top = dividers[-2]

    rows: list[str] = []
    for line in reversed(lines[:composer_top]):
        if not line.strip():
            break
        if _is_divider(line):
            break
        rows.append(line)
    rows.reverse()

    # Continuation lines of a wrapped description are indented further than the
    # command token itself; only rows that start a command matter here.
    return [r for r in rows if r.lstrip().startswith("/")]


def _is_divider(line: str) -> bool:
    """True for the box-drawing rule the TUI draws around the composer."""
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"─", "▔", "━"}


def status_panel_showing(pane_text: str) -> bool:
    """True when the Remote Control status panel (already-connected path) is showing."""
    return all(marker in pane_text for marker in PANEL_MARKERS)


def extract_session_url(pane_text: str) -> Optional[str]:
    """Return the most recent claude.ai session URL in the pane, or None."""
    matches = SESSION_URL_RE.findall(pane_text)
    return matches[-1] if matches else None


def pane_tail(pane_text: str, lines: int = 6) -> str:
    """Last few non-blank pane lines — what an honest failure report quotes."""
    return "\n".join(_non_empty_lines(pane_text)[-lines:])


# =============================================
# TMUX I/O
# =============================================


def list_tmux_sessions() -> list[str]:
    """List every tmux session name, or [] when tmux is absent or has no server."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.warning("tmux not found — is it installed?")
        return []

    if result.returncode != 0:
        return []  # no server running — honestly, zero sessions

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def capture_pane(session: str) -> Optional[str]:
    """Capture a session's visible pane text, or None when the capture fails."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.warning("tmux not found — cannot capture pane for '%s'", session)
        return None

    if result.returncode != 0:
        logger.warning("capture-pane failed for '%s': %s", session, result.stderr.strip())
        return None

    return result.stdout


def send_literal(session: str, text: str) -> bool:
    """
    Type *text* into a session verbatim (send-keys -l), never interpreted as a key name.

    Every injection is logged. This verb is only ever allowed to type
    RC_COMMAND_TEXT into another agent's composer, and the operation log is
    what makes that claim auditable after the fact rather than merely asserted.
    """
    json_handler.log_operation("rc_inject", {"session": session, "text": text})
    return _send_keys(session, ["-l", text])


def send_key(session: str, key: str) -> bool:
    """Send a named key (Enter, Escape, C-u) to a session."""
    return _send_keys(session, [key])


def _send_keys(session: str, args: list[str]) -> bool:
    """Run tmux send-keys against *session*, returning success."""
    try:
        result = subprocess.run(
            ["tmux", "send-keys", "-t", session, *args],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        logger.error("tmux not found — cannot send keys to '%s'", session)
        return False

    if result.returncode != 0:
        logger.error("send-keys failed for '%s': %s", session, result.stderr.strip())
        return False

    return True


def clear_composer(session: str) -> None:
    """
    Clear a target's composer with C-u after an aborted injection.

    Called on every abort path so a half-typed ``/rc`` is never left sitting
    in another agent's input box waiting for a stray Enter.
    """
    send_key(session, "C-u")
