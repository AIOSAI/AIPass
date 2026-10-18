# =================== AIPass ====================
# Name: cc_transcripts.py
# Version: 1.1.2
# Description: CC-native transcript reader — the chats, not the processes
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""CC-native transcript reader — what conversations exist in a branch.

Transcripts survive Ctrl+C (session files do not); liveness comes from cc_sessions.
"""

import json
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import err_console

CONSOLE = err_console


def _claude_home() -> Path:
    """Home directory for Claude's state, or an unusable sentinel if unknown.

    Path.home() raises on Windows without %USERPROFILE%; at module scope that is an import crash.
    """
    try:
        return Path.home()
    except RuntimeError as e:
        logger.warning("[%s] Cannot resolve home directory (%s) - treating ~/.claude as absent", __name__, e)
        return Path("<no-home>")


PROJECTS_ROOT = _claude_home() / ".claude" / "projects"

# CC's own rule: past 200 chars the mangled name is truncated and gets "-" + a hash of the ORIGINAL path.
_NAME_LIMIT = 200


def _mangle(path_text: str) -> str:
    """CC's own path-to-dirname rule, applied to a raw path string.

    No drive-letter special case: the CLI has none, so C:\\Work becomes C--Work.
    """
    # UTF-16 units, not code points: JS writes two dashes for a non-BMP char.
    units = path_text.encode("utf-16-le")
    out = []
    for i in range(0, len(units), 2):
        char = chr(units[i] | (units[i + 1] << 8))
        out.append(char if ("0" <= char <= "9" or "A" <= char <= "Z" or "a" <= char <= "z") else "-")
    return "".join(out)


def _cc_path_hash(path_text: str) -> str:
    """Reproduce the CLI's 31-hash of a path: int32 wraparound, base36, unsigned."""
    value = 0
    units = path_text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        code = units[i] | (units[i + 1] << 8)
        value = (value * 31 + code) & 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    value = abs(value)
    if value == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = digits[rem] + out
    return out


def project_dir_for(cwd: str | Path) -> Path:
    """Return the transcript directory CC uses for *cwd*."""
    resolved = str(Path(cwd).resolve())
    mangled = _mangle(resolved)
    if len(mangled) > _NAME_LIMIT:
        mangled = f"{mangled[:_NAME_LIMIT]}-{_cc_path_hash(resolved)}"
    return PROJECTS_ROOT / mangled


def _parse_record(line: str) -> dict | None:
    """One transcript line as a dict, or None when it is not one."""
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError) as exc:
        # debug: a transcript still being written ends mid-line as a matter of course.
        logger.debug("[CC_TRANSCRIPTS] skipping unparseable transcript line: %s", exc)
        return None
    return record if isinstance(record, dict) else None


def _is_real_user_turn(record: dict) -> bool:
    """True for a user record that carries text the user actually typed.

    Tool results are user records too and sub-agent turns are isSidechain; both inflate the count.
    """
    if record.get("type") != "user" or record.get("isSidechain"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "text" for block in content
    )


def _summarize(path: Path) -> tuple[int, str]:
    """Count real user turns in a transcript and return its latest AI title."""
    messages = 0
    title = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                record = _parse_record(line)
                if record is None:
                    continue
                title = str(record.get("aiTitle", "")) or title if record.get("type") == "ai-title" else title
                messages += 1 if _is_real_user_turn(record) else 0
    except OSError as exc:
        logger.info("[CC_TRANSCRIPTS] unreadable transcript %s: %s", path.name, exc)
        return 0, ""
    return messages, title


def recent_chats(cwd: str | Path, limit: int = 5) -> list[dict]:
    """Return the most recently touched chats for *cwd*, newest first.

    Each transcript is fully scanned, so *limit* bounds the work; zero-turn launches are dropped.
    """
    directory = project_dir_for(cwd)
    if not directory.is_dir():
        logger.info("[CC_TRANSCRIPTS] no transcript dir for %s", cwd)
        return []

    try:
        candidates = sorted(
            directory.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[: max(0, limit)]
    except OSError as exc:
        logger.info("[CC_TRANSCRIPTS] cannot list %s: %s", directory, exc)
        return []

    chats = []
    for path in candidates:
        messages, title = _summarize(path)
        if messages == 0:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError as exc:
            logger.info("[CC_TRANSCRIPTS] cannot stat %s: %s", path, exc)
            continue
        chats.append(
            {
                "session_id": path.stem,
                "title": title,
                "messages": messages,
                "modified": modified,
                "path": str(path),
            }
        )
    return chats


def chat_for(cwd: str | Path, session_id: str) -> dict | None:
    """Return the chat for one sessionId, or None when it has no transcript.

    A live process may hold a chat older than recent_chats' limit; this keeps it joinable.
    """
    if not session_id:
        return None
    path = project_dir_for(cwd) / f"{session_id}.jsonl"
    if not path.is_file():
        return None
    messages, title = _summarize(path)
    try:
        modified = path.stat().st_mtime
    except OSError as exc:
        logger.info("[CC_TRANSCRIPTS] cannot stat %s: %s", path, exc)
        return None
    return {
        "session_id": session_id,
        "title": title,
        "messages": messages,
        "modified": modified,
        "path": str(path),
    }


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]cc_transcripts[/bold cyan] — CC transcript reader (the chats, not the processes)")
