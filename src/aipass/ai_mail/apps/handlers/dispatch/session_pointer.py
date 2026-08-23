# =================== AIPass ====================
# Name: session_pointer.py
# Description: Durable per-branch "current session" pointer for dispatch
# Version: 1.0.0
# Created: 2026-08-20
# Modified: 2026-08-20
# =============================================

"""Durable per-branch current-session pointer.

A non-fresh dispatch runs ``claude -c -p "..."``. The ``-c`` flag means
"continue the most recently MODIFIED transcript in this directory" — it binds
an agent's conversation thread to a FILE MTIME, not to the agent. Anything that
touches the branch directory silently re-points where the NEXT dispatch lands:
a ``--fresh`` run, a late-finishing dispatch that flushes its transcript after a
newer one started, or a human opening a terminal there. The agent wakes into
somebody else's thread and its memory of the last dispatch is simply gone.

This module is the STORE for the fix: a small JSON file per branch naming the
session id that dispatch should resume, so the choice is made by a written
record instead of by whichever file happened to be touched last.

Two verified CLI facts make the pointer possible (pinned CLI 2.1.228):

Minting
    ``claude -p "..." --session-id <uuid> --output-format json`` accepts an id
    we generate, and returns that same id. The pointer can therefore be written
    BEFORE the process starts — no scraping stdout, no window where a crash
    leaves a session nobody recorded.

Resuming
    ``claude --resume <id> -p "..."`` continues the same session: same id back,
    same single transcript file, no fork.

Nothing here raises. A pointer that is missing, stale, corrupt or unreadable
must degrade a dispatch to today's ``-c`` behaviour — never block an agent from
waking. Every function returns a value, and every refusal comes with a reason
string written for whoever is reading the log at 2am.

Wiring lives elsewhere: this module does not touch wake.py or
dispatch_monitor.py, and it does not spawn anything.
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

# Directory each branch keeps its dispatch-local state in — same home as the
# dispatch lock, so the pointer travels with the lock it sits beside.
POINTER_DIR_NAME = ".ai_mail.local"
POINTER_FILE_NAME = "session.json"

# Bytes per megabyte for the oversize report. Binary MB (MiB) — matches what
# `ls -lh` and `du -h` show, which is what the person reading the reason string
# will compare it against.
_BYTES_PER_MB = 1024 * 1024


def _log_operation(operation: str, data: dict) -> None:
    """Record an operation in the branch's JSON op log, swallowing any failure.

    The op log is the audit trail for "who repointed this branch and when" —
    worth having, never worth failing a dispatch over. log_operation touches
    files of its own, so its failure must not become this module's exception.
    """
    try:
        json_handler.log_operation(operation, data)
    except Exception as e:
        logger.info("[session_pointer] log_operation(%s) failed: %s", operation, e)


def mint_session_id() -> str:
    """Return a fresh session id for a dispatch about to start.

    One line, but it lives here so no caller ever invents its own id format.
    The CLI takes this verbatim via ``--session-id`` and hands it straight back
    in the result JSON, so the shape of what we generate is a contract.
    """
    return str(uuid.uuid4())


_HOME_FAILURE_WARNED = False


def _claude_home() -> Optional[Path]:
    """This machine's home directory, or None when it cannot be named.

    ``Path.home()`` was called bare here, and it was the ONE unguarded call on
    the resume path (reported by @hooks, 2026-08-23, found while fixing their
    own Windows CI red — tracebacks landed on this line). It delegates to
    ``os.path.expanduser``, which raises RuntimeError when it cannot answer.

    POSIX honours $HOME and then falls back to the pwd database, so it is very
    nearly unfailable there. ntpath has no such fallback: it reads USERPROFILE,
    then HOMEDRIVE + HOMEPATH, and absent all three returns "~" unchanged, at
    which point pathlib raises. So this is a Windows-shaped hole that is
    invisible on the machines any of us can actually run.

    IT SITS ON THE HAPPY PATH, which is why it earns a fix rather than a note:
    it is only reached once a pointer EXISTS and its cwd MATCHES. A branch with
    no pointer returns early and never touches it, so the branches exposed are
    exactly the correctly-pointed ones.

    None rather than a fabricated path: "this machine cannot name its home" and
    "there is no transcript there" are different facts, and a sentinel that
    cannot exist would render them identically — the same collapse this branch
    removed from the dispatch register and from find_repo_root the same night.

    Warned once per process. This is called per path construction, so a line per
    call is the runaway-log problem; a warning nobody can read is another kind
    of silence.

    NOT HOISTED TO A MODULE CONSTANT, deliberately. @hooks hit the nastier half
    of this defect in two of their own modules, where the home lookup ran at
    MODULE SCOPE: an unresolvable home became an IMPORT-time crash that took the
    whole module down, and it stayed invisible in CI only because some earlier
    test had imported it outside a cleared environ. Import order was the only
    thing between that and a red board. Computing inside the call keeps the
    failure local to the caller that wanted a path.
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

    Claude stores transcripts under ``~/.claude/projects/<encoded-cwd>``, where
    the encoding replaces ``\\``, ``/``, ``:``, ``_`` and ``.`` with ``-``. A
    Windows path ``C:\\repo\\AIPass`` becomes ``C--repo-AIPass``.

    This module is the CANONICAL home for that encoding.
    ``dispatch_monitor._get_jsonl_projects_dir`` carries an identical copy and
    is being pointed here, so the rule lives in one place: the day Claude
    changes how it encodes a cwd, there is a single line to fix rather than a
    search for every branch that guessed.

    The cwd is encoded exactly as handed in — no resolving. Callers should pass
    the same path the agent actually runs in, since that is what Claude encoded.

    Returns None when this machine cannot name its own home directory. That is
    an ABSENT ANSWER, not a path — see ``_claude_home``. Callers must handle it;
    a sentinel path that cannot exist would read as "no transcript here", which
    is a different fact and the one that hides the real failure.
    """
    encoded = str(cwd).replace("\\", "-").replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-")
    home = _claude_home()
    if home is None:
        return None

    return home / ".claude" / "projects" / encoded


def transcript_file(cwd: str | Path, session_id: str) -> Optional[Path]:
    """Return the transcript path for one session inside a working directory.

    Existence of this file is what makes a pointer trustworthy: an id with no
    transcript behind it would make ``--resume`` fail and cost the branch a
    whole dispatch, so callers check the file rather than believing the id.

    None when the home directory cannot be named — propagated from
    ``transcript_dir`` rather than papered over.
    """
    directory = transcript_dir(cwd)
    if directory is None:
        return None

    return directory / f"{session_id}.jsonl"


def pointer_path(branch_path: Path) -> Path:
    """Return the pointer file path for a branch."""
    return Path(branch_path) / POINTER_DIR_NAME / POINTER_FILE_NAME


def read_pointer(branch_path: Path) -> Optional[dict]:
    """Read a branch's session pointer, or None when there isn't a usable one.

    Returns None — never raises — when the file is missing, unreadable, not
    valid JSON, not a JSON object, or carries no non-blank ``session_id``. A
    pointer that cannot be trusted is the same as no pointer at all: the caller
    falls back to ``-c`` and the branch still wakes.
    """
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


def write_pointer(branch_path: Path, session_id: str, set_by: str) -> bool:
    """Record `session_id` as the branch's current session. Returns success.

    The write is ATOMIC: content lands in a temp file in the SAME directory,
    is flushed to disk, and is then moved into place with ``os.replace``. A
    dispatch that reads the pointer mid-write sees either the whole old value
    or the whole new one — a half-written pointer would send an agent to
    ``--resume`` with a truncated id, which fails the dispatch outright.

    Args:
        branch_path: The branch directory. ``.ai_mail.local/`` is created if
            absent.
        session_id: The id minted for this session.
        set_by: Who set it (e.g. "wake", "dispatch_monitor", "manual") — the
            first thing worth knowing when a pointer looks wrong.

    Returns:
        True on success, False on any OSError. Never raises: a branch whose
        pointer cannot be written must still be dispatchable.
    """
    path = pointer_path(branch_path)
    payload = {
        "session_id": session_id,
        "set_at": datetime.now().astimezone().isoformat(),
        "set_by": set_by,
        # Resolved on purpose — this is the value resolve_resume_target compares
        # against, and it is what makes a copied or moved branch detectable.
        "cwd": str(Path(branch_path).resolve()),
    }

    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same directory as the target, or os.replace would be a cross-device
        # move and stop being atomic.
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
        # A failed replace leaves the temp behind; the old pointer is untouched
        # and must stay readable, so only the scratch file is cleaned up.
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError as e:
                logger.info("[session_pointer] Could not remove temp file %s: %s", tmp_name, e)


def _transcript_candidates(branch_path: Path, session_id: str) -> Optional[list[Path]]:
    """Transcript paths to check for a branch, most literal first.

    Normally one path. A branch reached through a symlink gives two: Claude
    encodes the cwd its process actually reports, which is the resolved one,
    while the caller may hold the unresolved path. Checking both costs a stat
    and avoids throwing away a perfectly good session over a symlink.
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

    ``{value!r}`` used to do this job and it broke the Windows CI runner
    (PR 739's windows-setup job, 2026-08-23). repr() escapes for a Python
    literal, so every backslash in a Windows path DOUBLES: a caller comparing
    against ``str(path)`` can never match, and — the half that matters more —
    the human reading the log is shown ``C:\\Users\\x``, which matches nothing
    they can paste into a terminal or eyeball against their own directory. On
    POSIX the bug is invisible, because repr of a slash path only adds quotes.

    The quoting SURVIVES because that is what repr was actually buying here: an
    empty or whitespace-only cwd renders as ``''`` instead of vanishing into the
    sentence, which is the difference between "the pointer is blank" and "the
    pointer is missing from this message". Bare str() would have traded a
    Windows bug for a blank-value bug.

    ``None`` is spelled out rather than quoted, so an absent key cannot be
    confused with a pointer whose cwd is the literal text "None".
    """
    if value is None:
        return "<absent>"
    return f"'{value}'"


def resolve_resume_target(branch_path: Path, max_transcript_mb: Optional[float] = None) -> Tuple[Optional[str], str]:
    """Decide which session a dispatch to `branch_path` should resume.

    THE decision function. Returns ``(session_id_or_None, reason)``. The reason
    is always populated and always explains the verdict, because it goes
    straight into a dispatch log line and is the only trace left when an agent
    wakes somewhere unexpected.

    A session id comes back only when all three hold:

    1. The pointer exists and parses.
    2. ``pointer["cwd"]`` matches this branch's resolved path — a branch that
       was moved or copied inherits a pointer aimed at the ORIGINAL directory's
       transcripts, and resuming into those would graft another branch's memory
       onto this one.
    3. The transcript file for that id exists — ``--resume`` on a missing
       transcript fails the dispatch, and falling back to ``-c`` costs nothing.

    Anything else returns ``(None, "<why>")`` and the caller falls back to
    today's ``-c`` behaviour. This never raises.

    Args:
        branch_path: The branch directory being dispatched to.
        max_transcript_mb: Optional size alarm, in binary MB. When the pointed
            transcript is larger, the id is STILL returned and the reason says
            so loudly. Rotation is a deliberate human decision and is not armed
            here — this only tells someone it is time to make that decision.

    Returns:
        (session_id, reason) or (None, reason).
    """
    try:
        pointer = read_pointer(branch_path)
    except (TypeError, AttributeError, ValueError) as e:
        # read_pointer already swallows its own I/O and parse failures; the only
        # way it still raises is a caller handing us something that isn't a path
        # at all, which dies in Path(). Narrow on purpose rather than bare
        # Exception: this function sits on the dispatch hot path so "never
        # raises" has to hold even for a caller's mistake, but swallowing
        # everything would hide a real bug in here as a routine -c fallback.
        logger.warning("[session_pointer] read_pointer raised for %s: %s", branch_path, e)
        return None, f"pointer unreadable ({type(e).__name__}: {e}) - falling back to -c"

    if pointer is None:
        return None, f"no usable pointer at {pointer_path(branch_path)} - falling back to -c"

    session_id = str(pointer.get("session_id", "")).strip()

    try:
        expected_cwd = str(Path(branch_path).resolve())
    except OSError as e:
        logger.warning("[session_pointer] Cannot resolve branch path %s: %s", branch_path, e)
        return None, f"branch path {branch_path} could not be resolved ({e}) - falling back to -c"

    pointer_cwd = pointer.get("cwd")
    if pointer_cwd != expected_cwd:
        return None, (
            f"pointer cwd mismatch - pointer says {_quote_path(pointer_cwd)} but this branch resolves to "
            f"{_quote_path(expected_cwd)} (moved or copied branch?) - falling back to -c"
        )

    candidates = _transcript_candidates(branch_path, session_id)
    if candidates is None:
        return None, (
            "cannot determine this machine's home directory, so there is no ~/.claude/projects "
            "to search - falling back to -c"
        )

    found = None
    for candidate in candidates:
        try:
            if candidate.is_file():
                found = candidate
                break
        except OSError as e:
            logger.warning("[session_pointer] Cannot stat transcript %s: %s", candidate, e)

    if found is None:
        checked = " or ".join(str(c) for c in candidates)
        return None, f"transcript for session {session_id} not found at {checked} - falling back to -c"

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
