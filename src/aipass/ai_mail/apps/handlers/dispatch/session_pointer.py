# =================== AIPass ====================
# Name: session_pointer.py
# Description: Durable per-branch "current session" pointer for dispatch
# Version: 1.3.1
# Created: 2026-08-20
# Modified: 2026-10-28
# =============================================

"""Durable per-branch current-session pointer.

``-c`` resumes the newest transcript by mtime; this pointer names the session instead.
Nothing here raises: a bad pointer degrades the dispatch to ``-c``.
"""

import json
import os
import re
import sqlite3
from contextlib import closing
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

POINTER_DIR_NAME = ".ai_mail.local"
POINTER_FILE_NAME = "session.json"

CLAUDE = "claude"
CODEX = "codex"
OPENCODE = "opencode"
OPENCODE_DB_ENV = "OPENCODE_DB"

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
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
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


def opencode_db() -> Optional[Path]:
    """OpenCode's session store: OPENCODE_DB, else ~/.local/share/opencode/opencode.db; None without a home."""
    override = os.environ.get(OPENCODE_DB_ENV)
    if override:
        return Path(override)
    home = _claude_home()
    if home is None:
        return None
    return home / ".local" / "share" / "opencode" / "opencode.db"


def opencode_session_directory(session_id: str) -> Tuple[Optional[str], str]:
    """The `directory` OpenCode recorded for a session, or (None, why it is not there). Read-only."""
    db = opencode_db()
    if db is None:
        return None, "cannot determine this machine's home directory, so there is no opencode store to search"
    if not db.is_file():
        return None, f"opencode store {db} does not exist"
    try:
        with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            row = conn.execute("select directory from session_v2 where id=?", (session_id,)).fetchone()
    except sqlite3.Error as e:
        logger.warning("[session_pointer] Cannot read opencode store %s: %s", db, e)
        return None, f"opencode store {db} unreadable ({e})"
    if row is None:
        return None, f"session {session_id} not found in {db}"
    return str(row[0]), ""


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


PENDING = "pending"
CLI_DEFAULT = "cli_default"
RUN_KEYS = ("host_cli", "model_provider", "model_requested", "model_observed", "selection_source", "observed_at")


def write_pointer(
    branch_path: Path, session_id: str, set_by: str, provider: str = CLAUDE, *, run: Optional[dict] = None
) -> bool:
    """Record `session_id` as the branch's current session, with its run record. Returns success.

    `run` sets any of RUN_KEYS; the rest default to host_cli=provider, pending and cli_default.

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
        "host_cli": provider,
        "model_provider": PENDING,
        "model_requested": CLI_DEFAULT,
        "model_observed": PENDING,
        "selection_source": CLI_DEFAULT,
        "observed_at": None,
    }
    payload.update({key: value for key, value in (run or {}).items() if key in RUN_KEYS})

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


def record_run(branch_path: Path, run: dict) -> bool:
    """Stamp this run's record onto the branch's current pointer.

    False when there is no pointer, or when the run's host is not the pointer's: that session is
    not this run's, so the record is reset to pending rather than pairing one host with another's id.
    """
    pointer = read_pointer(branch_path)
    if pointer is None:
        return False
    provider = pointer.get("provider", CLAUDE)
    set_by = pointer.get("set_by", "unknown")
    host = run.get("host_cli", provider)
    if host != provider:
        logger.warning(
            "[session_pointer] run on %s but pointer %s is %s's - run record left pending",
            host,
            pointer["session_id"],
            provider,
        )
        write_pointer(branch_path, pointer["session_id"], set_by, provider)
        return False
    return write_pointer(branch_path, pointer["session_id"], set_by, provider, run=run)


def observe_model(branch_path: Path, session_id: str, provider: str) -> Tuple[Optional[str], Optional[str]]:
    """(vendor, model id) from the runtime's own newest assistant row for the session, or (None, None) unseen."""
    try:
        if provider == OPENCODE:
            return _observe_opencode(session_id)
        if provider == CODEX:
            return _observe_codex(session_id)
        return _observe_claude(branch_path, session_id)
    except (OSError, sqlite3.Error, ValueError) as e:
        logger.info("[session_pointer] %s model for %s not observable: %s", provider, session_id, e)
        return None, None


def _observe_opencode(session_id: str) -> Tuple[Optional[str], Optional[str]]:
    db = opencode_db()
    if db is None or not db.is_file():
        return None, None
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        row = conn.execute(
            "select data from session_message where session_id=? and type='assistant' order by seq desc limit 1",
            (session_id,),
        ).fetchone()
    model = json.loads(row[0]).get("model") if row else None
    if not isinstance(model, dict) or not model.get("id"):
        return None, None
    return model.get("providerID"), model["id"]


def _jsonl_rows(path: Optional[Path]) -> Iterator:
    # Line by line: a long-lived transcript runs past 100 MB.
    if path is None or not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                logger.info("[session_pointer] skipping a non-JSON line in %s: %s", path, e)
                continue
            if isinstance(row, dict):
                yield row


def _observe_codex(thread_id: str) -> Tuple[Optional[str], Optional[str]]:
    vendor, model = None, None
    for row in _jsonl_rows(codex_thread_file(thread_id)):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if row.get("type") == "session_meta":
            vendor = payload.get("model_provider") or vendor
        elif row.get("type") == "turn_context" and payload.get("model"):
            model = payload["model"]
    return (vendor, model) if model else (None, None)


def _observe_claude(branch_path: Path, session_id: str) -> Tuple[Optional[str], Optional[str]]:
    model = None
    for row in _jsonl_rows(transcript_file(branch_path, session_id)):
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        if row.get("type") == "assistant" and message.get("model"):
            model = message["model"]
    # Claude Code names Anthropic's models only; the transcript row carries no vendor field.
    return ("anthropic", model) if model else (None, None)


def format_run_line(record: Optional[dict]) -> str:
    """One line from a run record: observed when seen, else requested and said so. Never a config's contents."""
    if not record:
        return "run: no pointer recorded"
    host = record.get("host_cli") or record.get("provider", CLAUDE)
    source = record.get("selection_source", CLI_DEFAULT)
    session = record.get("session_id", "?")
    observed = record.get("model_observed", PENDING)
    if observed and observed != PENDING:
        vendor = record.get("model_provider")
        shown = observed if "/" in observed or not vendor or vendor == PENDING else f"{vendor}/{observed}"
        return f"run: {host} · {shown} (observed; {source}) session {session}"
    requested = record.get("model_requested", CLI_DEFAULT)
    return f"run: {host} · {requested} (requested, observed pending; {source}) session {session}"


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
    transcript (OpenCode: its session_v2 row) exists; never raises. Codex and OpenCode fall back to fresh.
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

    if provider == OPENCODE:
        directory, why = opencode_session_directory(session_id)
        if directory is None:
            return None, f"{why} - {fallback}"
        if directory != expected_cwd:
            return None, (
                f"opencode session {session_id} belongs to {_quote_path(directory)}, not "
                f"{_quote_path(expected_cwd)} - {fallback}"
            )
        return session_id, f"pointer valid - resuming opencode session {session_id}"

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
