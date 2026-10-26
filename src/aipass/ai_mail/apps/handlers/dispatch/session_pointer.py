# =================== AIPass ====================
# Name: session_pointer.py
# Description: Durable per-branch "current session" pointer for dispatch
# Version: 1.1.0
# Created: 2026-08-20
# Modified: 2026-10-25
# =============================================

"""Durable per-branch current-session pointer.

``-c`` resumes the newest transcript by mtime; this pointer names the session instead.
Nothing here raises: a bad pointer degrades the dispatch to ``-c``.
"""

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

POINTER_DIR_NAME = ".ai_mail.local"
POINTER_FILE_NAME = "session.json"

CLAUDE = "claude"
CODEX = "codex"

# MiB, to match what `ls -lh` and `du -h` show.
_BYTES_PER_MB = 1024 * 1024


def _log_operation(operation: str, data: dict) -> None:
    """Record an operation in the branch's JSON op log, swallowing any failure."""
    try:
        json_handler.log_operation(operation, data)
    except Exception as e:
        logger.info("[session_pointer] log_operation(%s) failed: %s", operation, e)


def mint_session_id() -> str:
    """Return a fresh session id for a dispatch about to start."""
    return str(uuid.uuid4())


_HOME_FAILURE_WARNED = False


def _claude_home() -> Optional[Path]:
    """This machine's home directory, or None when it cannot be named.

    Path.home() can raise (Windows); never hoist it to module scope, where that is an import-time crash.
    """
    global _HOME_FAILURE_WARNED

    try:
        return Path.home()
    except RuntimeError as e:
        if not _HOME_FAILURE_WARNED:
            _HOME_FAILURE_WARNED = True
            logger.warning(
                "[session_pointer] cannot determine the home directory (%s) — no ~/.claude/projects "
                "can be located, so transcript lookups will report absence and dispatches fall back "
                "to -c. On Windows this means USERPROFILE and HOMEDRIVE+HOMEPATH are all unset.",
                e,
            )
        return None


def transcript_dir(cwd: str | Path) -> Optional[Path]:
    """Return Claude's transcript directory for a working directory.

    The fleet's only copy of Claude's cwd encoding. None when the home cannot be named.
    """
    encoded = str(cwd).replace("\\", "-").replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-")
    home = _claude_home()
    if home is None:
        return None

    return home / ".claude" / "projects" / encoded


def transcript_file(cwd: str | Path, session_id: str) -> Optional[Path]:
    """Return the transcript path for one session inside a working directory."""
    directory = transcript_dir(cwd)
    if directory is None:
        return None

    return directory / f"{session_id}.jsonl"


def codex_thread_file(thread_id: str) -> Optional[Path]:
    """Return Codex's rollout file for a thread, or None when it is absent or the home cannot be named."""
    home = _claude_home()
    if home is None:
        return None
    matches = sorted((home / ".codex" / "sessions").glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    return matches[0] if matches else None


def pointer_path(branch_path: Path) -> Path:
    """Return the pointer file path for a branch."""
    return Path(branch_path) / POINTER_DIR_NAME / POINTER_FILE_NAME


def read_pointer(branch_path: Path) -> Optional[dict]:
    """Read a branch's session pointer, or None when there isn't a usable one."""
    path = pointer_path(branch_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("[session_pointer] No pointer at %s", path)
        return None
    except OSError as e:
        logger.warning("[session_pointer] Failed to read pointer %s: %s", path, e)
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[session_pointer] Malformed pointer JSON at %s: %s", path, e)
        return None

    if not isinstance(data, dict):
        logger.warning("[session_pointer] Pointer at %s is %s, not an object", path, type(data).__name__)
        return None

    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        logger.warning("[session_pointer] Pointer at %s has no usable session_id", path)
        return None

    return data


def write_pointer(branch_path: Path, session_id: str, set_by: str, provider: str = CLAUDE) -> bool:
    """Record `session_id` as the branch's current session. Returns success.

    Atomic (temp + fsync + os.replace): a half-written id would fail the next ``--resume``. Never raises.
    """
    path = pointer_path(branch_path)
    payload = {
        "session_id": session_id,
        "set_at": datetime.now().astimezone().isoformat(),
        "set_by": set_by,
        # Resolved: resolve_resume_target compares it to detect a moved or copied branch.
        "cwd": str(Path(branch_path).resolve()),
        # A pointer without the key is a Claude pointer: every pointer written before the key existed.
        "provider": provider,
    }

    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory as the target, or os.replace stops being atomic.
        fd, tmp_name = tempfile.mkstemp(prefix=".session.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
        tmp_name = None
        logger.info("[session_pointer] %s → session %s (set_by=%s)", path, session_id, set_by)
        _log_operation("write_session_pointer", {"branch": payload["cwd"], "session_id": session_id, "set_by": set_by})
        return True
    except OSError as e:
        logger.warning("[session_pointer] Failed to write pointer %s: %s", path, e)
        return False
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError as e:
                logger.info("[session_pointer] Could not remove temp file %s: %s", tmp_name, e)


def _transcript_candidates(branch_path: Path, session_id: str) -> Optional[list[Path]]:
    """Transcript paths to check for a branch, most literal first.

    A symlinked branch gives two: Claude encodes the resolved cwd, the caller may hold the literal one.
    """
    literal = transcript_file(branch_path, session_id)
    if literal is None:
        return None

    candidates = [literal]
    resolved = transcript_file(Path(branch_path).resolve(), session_id)
    if resolved is not None and resolved != literal:
        candidates.append(resolved)
    return candidates


def _quote_path(value: object) -> str:
    """Render a path inside a human-facing message: quoted, but never escaped.

    Not repr(): it doubles Windows backslashes. Quotes keep a blank cwd visible.
    """
    if value is None:
        return "<absent>"
    return f"'{value}'"


def resolve_resume_target(
    branch_path: Path, max_transcript_mb: Optional[float] = None, provider: str = CLAUDE
) -> Tuple[Optional[str], str]:
    """Decide which session a dispatch to `branch_path` should resume.

    An id only when the pointer parses, names this provider, its cwd matches this branch, and the
    transcript exists; never raises. Codex has no -c, so its fallback is a fresh thread.
    """
    fallback = "falling back to -c" if provider == CLAUDE else "starting fresh"
    try:
        pointer = read_pointer(branch_path)
    except (TypeError, AttributeError, ValueError) as e:
        # Only a non-path argument gets here; narrow so a real bug is not hidden as a -c fallback.
        logger.warning("[session_pointer] read_pointer raised for %s: %s", branch_path, e)
        return None, f"pointer unreadable ({type(e).__name__}: {e}) - {fallback}"

    if pointer is None:
        return None, f"no usable pointer at {pointer_path(branch_path)} - {fallback}"

    session_id = str(pointer.get("session_id", "")).strip()

    pointer_provider = pointer.get("provider", CLAUDE)
    if pointer_provider != provider:
        return None, f"pointer is for {pointer_provider}, waking on {provider} - starting fresh"

    try:
        expected_cwd = str(Path(branch_path).resolve())
    except OSError as e:
        logger.warning("[session_pointer] Cannot resolve branch path %s: %s", branch_path, e)
        return None, f"branch path {branch_path} could not be resolved ({e}) - {fallback}"

    pointer_cwd = pointer.get("cwd")
    if pointer_cwd != expected_cwd:
        return None, (
            f"pointer cwd mismatch - pointer says {_quote_path(pointer_cwd)} but this branch resolves to "
            f"{_quote_path(expected_cwd)} (moved or copied branch?) - {fallback}"
        )

    if provider == CODEX:
        candidates = None if _claude_home() is None else [codex_thread_file(session_id)]
    else:
        candidates = _transcript_candidates(branch_path, session_id)
    if candidates is None:
        return None, (
            f"cannot determine this machine's home directory, so there is no transcript store to search - {fallback}"
        )

    found = None
    for candidate in candidates:
        try:
            if candidate is not None and candidate.is_file():
                found = candidate
                break
        except OSError as e:
            logger.warning("[session_pointer] Cannot stat transcript %s: %s", candidate, e)

    if found is None:
        checked = " or ".join(str(c) for c in candidates if c is not None) or "~/.codex/sessions"
        return None, f"transcript for session {session_id} not found at {checked} - {fallback}"

    if max_transcript_mb is None:
        return session_id, f"pointer valid - resuming session {session_id} (transcript {found})"

    try:
        size_mb = found.stat().st_size / _BYTES_PER_MB
    except OSError as e:
        logger.warning("[session_pointer] Cannot size transcript %s: %s", found, e)
        return session_id, f"pointer valid - resuming session {session_id} (transcript size unknown: {e})"

    if size_mb > max_transcript_mb:
        return session_id, (
            f"pointer valid but transcript is {size_mb:.1f}MB (over {max_transcript_mb:.1f}MB threshold) "
            f"- rotation advised - resuming session {session_id} anyway"
        )

    return session_id, f"pointer valid - resuming session {session_id} ({size_mb:.1f}MB transcript)"
