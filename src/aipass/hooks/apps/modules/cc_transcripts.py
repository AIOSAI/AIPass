# =================== AIPass ====================
# Name: cc_transcripts.py
# Version: 1.1.1
# Description: CC-native transcript reader — the chats, not the processes
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-18
# Modified: 2026-08-23
# =============================================

"""CC-native transcript reader — what conversations exist in a branch.

The boot picker used to enumerate ~/.claude/sessions/<pid>.json, which answers
"what processes are running". The user asks "where is my conversation". Those
are different questions, and on 2026-08-18 the difference cost a chat: Ctrl+C
deletes the dead chat's session file, so the one conversation Patrick wanted was
the one thing the menu could not show, while three background leftovers were
offered as if they were his chats.

Transcripts outlive processes. ~/.claude/projects/<mangled-cwd>/<sessionId>.jsonl
survives Ctrl+C, background adoption, and sessionId forking, so it is the honest
source for "your chats". Liveness still comes from cc_sessions — a transcript
says a conversation exists, not that a brain is attached to it.
"""

import json
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import err_console

CONSOLE = err_console


def _claude_home() -> Path:
    """Home directory for Claude's state, or an unusable sentinel if unknown.

    `Path.home()` RAISES RuntimeError("Could not determine home directory.")
    when expanduser cannot answer — on POSIX only if the pwd lookup also fails,
    but on Windows whenever %USERPROFILE% is absent, since ntpath has no pwd to
    fall back on. Evaluated at module scope, that turns an unresolvable home
    into an IMPORT-time crash: the whole module dies, not the one call that
    wanted a path.

    A missing home is not an emergency here — it means there is no
    ~/.claude to read, which is the same answer as an empty one. So resolution
    degrades to a path that cannot exist, letting the `.is_dir()` / `.exists()`
    checks downstream report "nothing here" instead of raising. The fallback is
    logged, never silent: a machine that cannot name its own home is worth a
    line in the log even though it does not stop us.
    """
    try:
        return Path.home()
    except RuntimeError as e:
        logger.warning("[%s] Cannot resolve home directory (%s) - treating ~/.claude as absent", __name__, e)
        return Path("<no-home>")


PROJECTS_ROOT = _claude_home() / ".claude" / "projects"

# CC truncates a mangled name at 200 chars and appends a hash of the ORIGINAL
# path. Read out of the shipping CLI (2.1.228), not inferred:
#   dpo(e) = e.replace(/[^a-zA-Z0-9]/g, "-")
#   gv(e)  = dpo(e).length <= 200 ? dpo(e) : dpo(e).slice(0,200) + "-" + hash(e)
#   hash(e): t = 0; for each UTF-16 unit c: t = (t<<5) - t + c | 0
#            -> Math.abs(t).toString(36)
_NAME_LIMIT = 200


def _mangle(path_text: str) -> str:
    """CC's own path-to-dirname rule, applied to a raw path string.

    Every non-alphanumeric becomes a dash — including the colon and backslashes
    of a Windows path, which is why C:\\Users\\p becomes C--Users-p. There is no
    drive-letter special case in the CLI, so there is none here.
    """
    # Walk UTF-16 code units, not Python code points. JavaScript's regex sees a
    # non-BMP character as a SURROGATE PAIR and writes two dashes where Python
    # would write one, so a path containing an emoji would otherwise resolve to
    # a directory CC never created. Cross-checked against the CLI's own dpo().
    units = path_text.encode("utf-16-le")
    out = []
    for i in range(0, len(units), 2):
        char = chr(units[i] | (units[i + 1] << 8))
        out.append(char if ("0" <= char <= "9" or "A" <= char <= "Z" or "a" <= char <= "z") else "-")
    return "".join(out)


def _cc_path_hash(path_text: str) -> str:
    """Reproduce the CLI's 31-hash of a path: int32 wraparound, base36, unsigned.

    Iterates UTF-16 code units, not Python code points, so a path containing a
    non-BMP character hashes the way JavaScript hashes it rather than merely
    close to it.
    """
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
    """One transcript line as a dict, or None when it is not one.

    A transcript being written while we read it can end mid-line, so an
    unparseable tail is ordinary — it is skipped, never fatal.
    """
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError) as exc:
        # debug, not info: this fires per LINE, and a transcript appended to
        # while we read it ends mid-line as a matter of course. At info it
        # would bury the log for a non-event.
        logger.debug("[CC_TRANSCRIPTS] skipping unparseable transcript line: %s", exc)
        return None
    return record if isinstance(record, dict) else None


def _is_real_user_turn(record: dict) -> bool:
    """True for a user record that carries text the user actually typed.

    Tool results are also recorded as user records, and sub-agent turns are
    marked isSidechain; counting either inflates the number roughly fourfold
    (472 raw vs the 109 the user recognises as the length of that chat).
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
    """Count real user turns in a transcript and return its latest AI title.

    A "real user turn" is a non-sidechain user record carrying text — tool
    results are also recorded as user records and would inflate the count
    roughly fourfold (472 raw vs 109 real on the transcript from the incident,
    where 109 is the number the user recognises as the length of the chat).
    """
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

    Args:
        cwd: Branch directory.
        limit: How many transcripts to read. Each is fully scanned, so this
            bounds the work — 13MB across five files measured 0.14s.

    Returns:
        List of {session_id, title, messages, modified, path}. Empty when the
        branch has no transcript directory. Transcripts with no real user turn
        are dropped: a zero-message file is a launch that never became a chat,
        and offering it as one is the same lie the PID menu told.
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

    The menu lists the most recent chats, but a live process may hold an older
    one. Without this, a seat whose transcript had fallen past the limit would
    be visible in the process list and unreachable from the menu — offering a
    seat you cannot join is the same defect as hiding a chat you want.
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
