# =================== AIPass ====================
# Name: agent_transcript.py
# Description: Host API Agent Transcript — find a live agent's session file and read it as chat lines
# Version: 1.0.0
# Created: 2026-11-04
# Modified: 2026-11-05
# =============================================

"""
Host API Agent Transcript
Reference: docs/host_agent_chat.md. Ported from Seed Dev's deck (ui/agents.py): a Claude Code session file
(~/.claude/projects/<munged path>/<session>.jsonl) or a Codex rollout (~/.codex/sessions/**/rollout-*-<id>.jsonl),
read from its tail into {n, role, text, time, model?} lines. Read-only: nothing here writes or execs.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

TAIL_BYTES = 4 * 1024 * 1024  # tool results (file reads, images) make rows big: 512 KB held only a few turns
MODEL_TAIL_BYTES = 1024 * 1024  # assistant rows are small; the big rows are tool results, which carry no model
FEED_ROWS = 80
TEXT_CAP = 20000  # a whole reply: 2000 cut long ones mid-sentence
TOOL_CAP = 120
PASTED = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.S)
# A teammate's report lands as a user row; Claude Code shows it as one line, so the feed does too.
TEAMMATE = re.compile(
    r'^Another Claude session sent a message:\s*<teammate-message teammate_id="([^"]*)"([^>]*)>\s*(\S*)'
)
TEAMMATE_SUMMARY = re.compile(r'summary="([^"]*)"')
COMPACTED = "This session is being continued from a previous conversation"
BASH_INPUT = re.compile(r"^<bash-input>(.*?)</bash-input>", re.S)
CODEX_SESSIONS = Path(".codex") / "sessions"
CLAUDE_PROJECTS = Path(".claude") / "projects"
# What Codex itself writes as user rows; a typed '#' or '<' prompt still shows.
CODEX_WRAPPERS = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<realtime_delegation>",
    "<recommended_plugins>",
    "<skill>",
    "<turn_aborted>",
)
SESSION_ID = re.compile(r"[\w-]+")  # a roster id goes into a glob: no wildcards
# One Codex exec script can make several calls: tools.<name>({cmd:"..."}) or tools.apply_patch("*** Update File: p").
CODEX_CALL = re.compile(
    r'tools\.(\w+)\(\s*(?:\{\s*cmd:\s*"((?:[^"\\]|\\.)*)"|"\*\*\* Begin Patch\\n\*\*\* \w+ File: ([^"\\]+))?'
)

# Tool name -> (verb, key argument). A path argument is shown by its file name only.
TOOL_LINES = {
    "Bash": ("ran:", "command"),
    "Edit": ("edited", "file_path"),
    "MultiEdit": ("edited", "file_path"),
    "Write": ("wrote", "file_path"),
    "NotebookEdit": ("edited", "notebook_path"),
    "Read": ("read", "file_path"),
    "Grep": ("searched:", "pattern"),
    "Glob": ("listed:", "pattern"),
    "Agent": ("agent:", "description"),
    "Task": ("agent:", "description"),
    "WebFetch": ("fetched", "url"),
    "WebSearch": ("searched web:", "query"),
}

# One table, id -> display name; an id not here shows as is.
MODEL_NAMES = {
    "claude-fable-5-1": "Claude Fable 5.1",
    "claude-fable-5": "Claude Fable 5",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-opus-5": "Claude Opus 5",
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6.1-terra": "GPT-6.1 Terra",
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
}

_rollouts: Dict[Tuple[Path, str], Path] = {}
_models: Dict[Path, Tuple[float, Optional[str]]] = {}


def display_model(model_id: Optional[str]) -> Optional[str]:
    """The display name of a model id; None for no id or Claude Code's '<synthetic>' (an error row, no model ran)."""
    if not model_id or model_id == "<synthetic>":
        return None
    return MODEL_NAMES.get(model_id, model_id)


def session_of(row: Dict[str, Any]) -> Optional[str]:
    """A roster row's session id: the run record's, else its resume pointer."""
    return (row.get("run") or {}).get("session_id") or row.get("resume_id") or None


def rollout_path(session: str) -> Optional[Path]:
    """Codex's rollout for a session id (rollout-<start>-<id>.jsonl in a date folder), or None until it is written."""
    root = Path.home() / CODEX_SESSIONS
    key = (root, session)
    known = _rollouts.get(key)
    if known is not None and known.exists():
        return known
    if not SESSION_ID.fullmatch(session) or not root.is_dir():
        return None
    found = next(root.rglob(f"rollout-*-{session}.jsonl"), None)
    if found is not None:
        _rollouts[key] = found
    return found


def transcript_path(row: Dict[str, Any]) -> Optional[Path]:
    """This session's transcript: Claude Code's session file or Codex's rollout; None for another provider."""
    session = session_of(row)
    if row.get("provider") == "codex" and session:
        return rollout_path(str(session))
    # No provider field: an older baud binary, whose resume_id is a Claude session; the file check settles it.
    if row.get("provider") not in ("claude", None) or not session or not row.get("path"):
        return None
    # Claude's own munge: every non-alphanumeric character of the absolute path becomes '-'.
    folder = re.sub(r"[^A-Za-z0-9]", "-", str(row["path"]))
    return Path.home() / CLAUDE_PROJECTS / folder / f"{session}.jsonl"


def tail_rows(path: Path, limit: int) -> List[Tuple[int, bytes]]:
    """(byte offset, line) for each whole line in a file's last *limit* bytes; a line cut by the seek is dropped."""
    with path.open("rb") as fh:
        size = fh.seek(0, 2)
        start = max(0, size - limit)
        fh.seek(start)
        raw = fh.read().split(b"\n")
    rows, offset = [], start
    for index, chunk in enumerate(raw):
        if not (index == 0 and start > 0):
            rows.append((offset, chunk))
        offset += len(chunk) + 1
    return rows


def tool_line(name: str, args: Dict[str, Any]) -> str:
    """One line for a tool call: its verb and key argument, never its full input."""
    verb, key = TOOL_LINES.get(name, (f"{name}:", ""))
    value = args.get(key) if key else next((v for v in args.values() if isinstance(v, str)), "")
    value = str(value or "").strip().splitlines()[0] if value else ""
    if key.endswith("_path"):
        value = Path(value).name
    return f"{verb} {value}".strip()[:TOOL_CAP]


def codex_tool_lines(script: str, stamp: Optional[str]) -> List[dict]:
    """One line per call in a Codex exec script: commands as ran:, patches as edited, write_stdin (a poll) left out."""
    out = []
    for name, cmd, patched in CODEX_CALL.findall(script):
        if name == "write_stdin":
            continue
        if cmd:
            try:
                cmd = json.loads(f'"{cmd}"')
            except json.JSONDecodeError as exc:
                logger.info("[host_api] a Codex command kept as written (%s)", exc)
            line = tool_line("Bash", {"command": cmd})
        else:
            line = tool_line("Edit", {"file_path": patched}) if patched else tool_line(name, {})
        out.append({"role": "tool", "text": line, "time": stamp})
    return out or [{"role": "tool", "text": tool_line("exec", {"script": script}), "time": stamp}]


def codex_lines(row: Dict[str, Any], model: Optional[str]) -> List[dict]:
    """The lines for one Codex rollout response_item: the user's prompts, the agent's text, its tool calls."""
    item, stamp = row.get("payload") or {}, row.get("timestamp")
    kind = item.get("type")
    if kind == "custom_tool_call":
        return codex_tool_lines(str(item.get("input") or ""), stamp)
    if kind == "function_call":
        try:
            args = json.loads(item.get("arguments") or "{}")
        except json.JSONDecodeError as exc:
            logger.info("[host_api] a Codex tool call with unreadable arguments: %s", exc)
            args = {}
        line = tool_line(str(item.get("name") or "?"), args if isinstance(args, dict) else {})
        return [{"role": "tool", "text": line, "time": stamp}]
    if kind != "message" or item.get("role") not in ("user", "assistant"):
        return []
    out = []
    for part in item.get("content") or []:
        text = str(part.get("text") or "").strip() if isinstance(part, dict) else ""
        if item["role"] == "assistant" and text:
            out.append({"role": "agent", "text": text[:TEXT_CAP], "time": stamp, "model": model})
        elif item["role"] == "user" and text and not text.startswith(CODEX_WRAPPERS):
            out.append({"role": "user", "text": PASTED.sub(r"\1", text).strip()[:TEXT_CAP], "time": stamp})
    return out


def _claude_part(part: Any, kind: str, stamp: Any, model: Optional[str]) -> Optional[dict]:
    """The line for one content part of a Claude user or assistant row, or None for a part that shows nothing."""
    if not isinstance(part, dict):
        return None
    if part.get("type") == "tool_use":
        args = part.get("input")
        line = tool_line(str(part.get("name") or "?"), args if isinstance(args, dict) else {})
        return {"role": "tool", "text": line, "time": stamp}
    if part.get("type") != "text":
        return None
    text = (part.get("text") or "").strip()
    if kind == "user":
        # A long prompt arrives wrapped as pasted content; a user row starting with '<' is a harness wrapper.
        text = PASTED.sub(r"\1", text).strip()
        shell = BASH_INPUT.match(text)
        if shell:
            # A '!' command typed in the chat: the line the sender sees, so its pending mark can settle.
            return {"role": "user", "text": f"! {shell.group(1).strip()}"[:TEXT_CAP], "time": stamp}
        if text.startswith(COMPACTED):
            return {"role": "tool", "text": "context compacted", "time": stamp}
        mate = TEAMMATE.match(text)
        if mate:
            if mate.group(3).startswith("{"):
                return None  # an idle notification: the report already came
            summary = TEAMMATE_SUMMARY.search(mate.group(2))
            return {
                "role": "tool",
                "text": f"teammate {mate.group(1)}: {summary.group(1) if summary else 'finished'}",
                "time": stamp,
            }
        return {"role": "user", "text": text[:TEXT_CAP], "time": stamp} if text and not text.startswith("<") else None
    return {"role": "agent", "text": text[:TEXT_CAP], "time": stamp, "model": model} if text else None


def to_lines(row: Dict[str, Any], model: Optional[str] = None) -> List[dict]:
    """The lines for one transcript row: the user's prompts, the agent's text, one line per tool call."""
    if row.get("type") == "response_item":
        return codex_lines(row, model)
    queued = row.get("attachment") if row.get("type") == "attachment" else None
    if isinstance(queued, dict) and queued.get("type") == "queued_command" and queued.get("commandMode") == "prompt":
        # A message sent while the agent worked is not a user row: Claude Code folds it into the running turn.
        text = PASTED.sub(r"\1", str(queued.get("prompt") or "")).strip()
        return [{"role": "user", "text": text[:TEXT_CAP], "time": row.get("timestamp")}] if text else []
    if row.get("type") not in ("user", "assistant") or row.get("isMeta") or row.get("isSidechain"):
        return []
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    kind = row["type"]
    model = display_model((row.get("message") or {}).get("model")) if kind == "assistant" else None
    lines = (_claude_part(part, kind, row.get("timestamp"), model) for part in content)
    return [line for line in lines if line is not None]


def read_feed(path: Path, since: Optional[int] = None) -> List[dict]:
    """The transcript's lines after *since* (all in the tail when None), the last FEED_ROWS of them.

    A line's n is the byte offset of its row in the file plus the line's index within that row: stable while the
    file grows, so a poller keeps its place; it starts again near 0 in a new session's file.
    """
    lines: List[dict] = []
    model = None  # Codex's, from the last turn_context row read
    for offset, chunk in tail_rows(path, TAIL_BYTES):
        if not chunk.strip():
            continue
        try:
            row = json.loads(chunk)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("[host_api] skipped a bad transcript line in %s: %s", path.name, exc)
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "turn_context":
            model = display_model((row.get("payload") or {}).get("model"))
        for index, line in enumerate(to_lines(row, model)):
            if since is None or offset + index > since:
                lines.append({"n": offset + index, **line})
    json_handler.log_operation("host_api_agent_transcript_read", {"lines": len(lines), "since": since})
    return lines[-FEED_ROWS:]


def current_model(path: Optional[Path]) -> Optional[str]:
    """The display name of the model on a transcript's last assistant row, re-read only when the file changed."""
    if path is None or not path.exists():
        return None
    mtime = path.stat().st_mtime
    if path in _models and _models[path][0] == mtime:
        return _models[path][1]
    model = None
    for _, chunk in reversed(tail_rows(path, MODEL_TAIL_BYTES)):
        if b'"assistant"' not in chunk and b'"turn_context"' not in chunk:
            continue
        try:
            row = json.loads(chunk)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.info("[host_api] skipped a bad transcript line in %s: %s", path.name, exc)
            continue
        if isinstance(row, dict) and row.get("type") in ("assistant", "turn_context"):
            # Claude names the model on each reply, Codex on each turn's context row.
            model = display_model((row.get("message") or row.get("payload") or {}).get("model"))
            if model:
                break
    _models[path] = (mtime, model)
    return model
