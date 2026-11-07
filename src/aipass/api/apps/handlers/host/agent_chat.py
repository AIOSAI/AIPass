# =================== AIPass ====================
# Name: agent_chat.py
# Description: Host API Agent Chat — a live agent's lookup, state, feed, and typing into its BAUD room
# Version: 1.0.0
# Created: 2026-11-04
# Modified: 2026-11-05
# =============================================

"""
Host API Agent Chat
Reference: docs/host_agent_chat.md. Ported from Seed Dev's deck (ui/agents.py). An agent is (project, name) in
@baud's roster; a send types into its room through @baud's `--send-room` door.
shortcut: keystrokes into the room; swap for @ai_mail's injection path once it has one.
"""

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import aipass

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.module_root import module_file
from aipass.api.apps.handlers.host import agent_transcript as transcript
from aipass.api.apps.handlers.host import fleet as host_fleet

WORKING_SECONDS = 10  # a transcript written this recently means the agent is mid-turn
ENGINE_LOG_BYTES = 256 * 1024  # the hooks engine logs every seat; this tail holds the last hour or so of the fleet
# Unframed, a typed burst swallows the Enter after it (Codex and Claude Code); one bracketed paste submits.
PASTE_START, PASTE_END = "\x1b[200~", "\x1b[201~"
BAUD_TEXT_LIMIT = 2000  # @baud's --send-room refuses a longer --text rather than trimming it
TEXT_CAP = 20000
CONTROL = re.compile(r"[\x00-\x1f\x7f]")  # typed as keys, a CR presses Enter and an ESC interrupts the turn
SEND_TIMEOUT_SECONDS = 30
KEYS = {"interrupt": "Escape", "allow": "Enter", "deny": "Escape"}
STATE_WORKING, STATE_WAITING, STATE_IDLE = "working", "waiting", "idle"


class AgentUnknown(Exception):
    """The roster does not list (project, name): the agent is not live, or never existed."""


class TranscriptUnavailable(Exception):
    """The agent is live but its transcript cannot be read; `code` says which way."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AgentNoRoom(Exception):
    """The agent has no live BAUD room of its own to type into (a dispatched seat, or its room closed)."""


class SendFailed(Exception):
    """@baud's door refused or failed a keystroke send; the words are for the host log only."""


def roster_rows() -> List[Dict[str, Any]]:
    """@baud's roster rows (`--roster`, as /v1/roster relays it), cached briefly; FleetUnavailable when unread."""
    return host_fleet.read_roster_cached().get("branches") or []


def find_agent(project: str, name: str) -> Dict[str, Any]:
    """One live agent's roster row; AgentUnknown when the roster does not list it."""
    row = next((r for r in roster_rows() if r.get("project") == project and r.get("name") == name), None)
    if row is None:
        raise AgentUnknown(f"{name} in {project}")
    return row


def engine_log() -> Path:
    """The hooks engine's event log: one row per hook per Claude Code or Codex event, stamped with the session id."""
    return module_file(aipass.__file__).parent / "hooks" / "logs" / "engine.jsonl"


def engine_rows() -> Optional[List[Dict[str, Any]]]:
    """The rows in the engine log's tail, a bad line logged and skipped; None when there is no log to read."""
    path = engine_log()
    try:
        chunks = transcript.tail_rows(path, ENGINE_LOG_BYTES)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("[host_api] the hooks engine log could not be read, state falls back to transcripts: %s", exc)
        return None
    rows = []
    for _, chunk in chunks:
        if not chunk.strip():
            continue
        try:
            row = json.loads(chunk)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("[host_api] skipped a bad engine log line: %s", exc)
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def delegating(rows: List[Dict[str, Any]]) -> Set[str]:
    """Session ids running a sub-agent: a Task or Agent PreToolUse opens one; SubagentStop, Stop or SessionEnd closes.

    shortcut: one close ends parallel sub-agents together.
    """
    opened: Dict[str, float] = {}
    closed: Dict[str, float] = {}
    for row in rows:
        session, at, event = row.get("session_id"), row.get("ts"), row.get("event")
        if not session or not isinstance(at, (int, float)):
            continue
        if event == "PreToolUse" and row.get("tool_name") in ("Task", "Agent") and not row.get("agent_id"):
            opened[session] = at
        elif event in ("SubagentStop", "Stop", "SessionEnd"):
            closed[session] = at
    return {s for s, at in opened.items() if at > closed.get(s, -1.0)}


def hook_state(session: str, rows: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """(state, tool) from the session's last hook events: working, idle, or waiting with the tool a prompt holds.

    (None, None) when the log's tail has no row for the session. Stop ends a turn. A PermissionRequest row, or a
    Notification of type permission_prompt, is a tool held on a prompt; an untyped Notification right after a
    PreToolUse is read the same way, after anything else it is only the idle nudge.
    """
    mine = [r for r in rows if r.get("session_id") == session]
    if not mine:
        return None, None
    last = mine[-1]
    event, kind = last.get("event"), last.get("notification_type")
    tool = next((r.get("tool_name") for r in reversed(mine) if r.get("tool_name")), None)
    if event == "PermissionRequest" or kind == "permission_prompt":
        return STATE_WAITING, tool
    if event == "Notification":
        if kind:
            return STATE_IDLE, None
        before = next((r.get("event") for r in reversed(mine) if r.get("event") != "Notification"), None)
        return (STATE_WAITING, tool) if before == "PreToolUse" else (STATE_IDLE, None)
    return (STATE_IDLE, None) if event in ("Stop", "SessionStart", "SessionEnd") else (STATE_WORKING, None)


def agent_state(row: Dict[str, Any], rows: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    """(state, tool) of one roster row: its hook events, else its transcript's age; (None, None) when neither."""
    session = transcript.session_of(row)
    state, tool = hook_state(str(session), rows) if session else (None, None)
    if state is None:
        path = transcript.transcript_path(row)
        if path is not None and path.exists():
            state = STATE_WORKING if time.time() - path.stat().st_mtime < WORKING_SECONDS else STATE_IDLE
    return state, tool


def live_fields(row: Dict[str, Any], rows: List[Dict[str, Any]], busy_sessions: Set[str]) -> Dict[str, Any]:
    """What /v1/fleet adds to one row: state, busy, the waiting tool, the transcript's model, delegating.

    Only a working seat (interactive or dispatched, the rows the roster carries) is read; any other row is asleep
    and answers state null. The model read is cached by the transcript's mtime, so a poll costs a stat per seat.
    """
    if not (row.get("interactive") or row.get("dispatched")):
        return {"state": None, "busy": False, "tool": None, "model": None, "delegating": False}
    state, tool = agent_state(row, rows)
    return {
        "state": state,
        "busy": state in (STATE_WORKING, STATE_WAITING),
        "tool": tool,
        "model": transcript.current_model(transcript.transcript_path(row)),
        "delegating": transcript.session_of(row) in busy_sessions,
    }


def add_live_state(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """The /v1/fleet envelope with every branch row's live fields added; no existing field is changed."""
    rows = engine_rows() or []
    busy_sessions = delegating(rows)
    for branch in envelope.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        try:
            fields = live_fields(branch, rows, busy_sessions)
        except OSError as exc:
            # One unreadable transcript must not take the whole fleet read down.
            logger.warning("[host_api] live state of %s unread: %s", branch.get("name"), exc)
            fields = {"state": None, "busy": False, "tool": None, "model": None, "delegating": False}
        branch.update({key: value for key, value in fields.items() if key not in branch})
    return envelope


def feed(project: str, name: str, since: Optional[int] = None) -> Dict[str, Any]:
    """One live agent's feed: {lines, busy, waiting, session}; AgentUnknown or TranscriptUnavailable when unread."""
    row = find_agent(project, name)
    path = transcript.transcript_path(row)
    if path is None:
        # shortcut: Claude and Codex only; OpenCode's db needs its own reader.
        raise TranscriptUnavailable("not_written" if row.get("provider") == "codex" else "unsupported_provider")
    try:
        lines = transcript.read_feed(path, since)
    except FileNotFoundError as exc:
        raise TranscriptUnavailable("missing") from exc
    state, tool = agent_state(row, engine_rows() or [])
    json_handler.log_operation("host_api_agent_feed", {"agent": name, "project": project, "lines": len(lines)})
    return {
        "lines": lines,
        "busy": state in (STATE_WORKING, STATE_WAITING),
        "waiting": {"tool": tool} if state == STATE_WAITING else None,
        "session": transcript.session_of(row),
    }


def clean_text(text: str) -> str:
    """A chat line as it is typed: control characters to spaces, trimmed, cut at TEXT_CAP."""
    return CONTROL.sub(" ", text).strip()[:TEXT_CAP]


def _roomed(project: str, name: str) -> None:
    """Refuse before any keystroke: AgentUnknown, AgentNoRoom, or FleetUnavailable when there is no binary."""
    if not find_agent(project, name).get("own_room_live"):
        raise AgentNoRoom(f"{name} in {project}")
    host_fleet.snapshot_binary()


def _send_room(project: str, name: str, payload: List[str]) -> Optional[str]:
    """One --send-room call; None when @baud says sent, else why not (for the log)."""
    try:
        outcome = host_fleet.send_room(name, project, payload, SEND_TIMEOUT_SECONDS)
    except host_fleet.FleetUnavailable as exc:
        return str(exc)
    if outcome.get("sent"):
        return None
    return str(outcome.get("error") or "not sent")


def send(project: str, name: str, text: str) -> None:
    """Type one chat line into a live agent's room and press Enter; SendFailed when any call fails.

    The text is cleaned first, so it cannot close the paste frame early. On a failure after the first chunk the
    frame is closed and no Enter is pressed, so a half line never submits.
    """
    _roomed(project, name)
    typed = f"{PASTE_START}{clean_text(text)}{PASTE_END}"
    chunks = [typed[i : i + BAUD_TEXT_LIMIT] for i in range(0, len(typed), BAUD_TEXT_LIMIT)]
    payloads = [*(["--text", chunk] for chunk in chunks), ["--key", "Enter"]]
    for index, payload in enumerate(payloads):
        reason = _send_room(project, name, payload)
        if reason is None:
            continue
        if 0 < index < len(chunks):
            closed = _send_room(project, name, ["--text", PASTE_END])
            if closed:
                logger.warning("[host_api] could not close the paste frame in %s's room: %s", name, closed)
        where = f"call {index + 1} of {len(payloads)}"
        logger.warning("[host_api] send to %s in %s failed at %s: %s", name, project, where, reason)
        raise SendFailed(f"{where}: {reason}")
    json_handler.log_operation("host_api_agent_send", {"agent": name, "project": project, "chars": len(typed)})


def press(project: str, name: str, action: str) -> None:
    """Press the key for *action* (interrupt, allow, deny) in a live agent's room; SendFailed when @baud fails."""
    key = KEYS[action]
    _roomed(project, name)
    reason = _send_room(project, name, ["--key", key])
    if reason is not None:
        logger.warning("[host_api] %s for %s in %s failed: %s", action, name, project, reason)
        raise SendFailed(f"{action}: {reason}")
    json_handler.log_operation("host_api_agent_key", {"agent": name, "project": project, "action": action})
