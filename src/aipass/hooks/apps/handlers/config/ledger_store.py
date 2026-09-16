# =================== AIPass ====================
# Name: ledger_store.py
# Version: 1.0.0
# Description: The injection ledger's file: what counts as injected, one JSONL record per dispatch, folded per turn
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-09-16
# Modified: 2026-09-16
# =============================================

"""Storage for the injection ledger (DPLAN-0347, hooks row 3).

apps/modules/injection_ledger.py orchestrates: it asks cadence for the turn
token and hands the numbers here. This file owns the record's shape, the file
it lives in and the fold that reads it back. Why the token and not the turn
number is written once, in docs/diagnostics.md.

One file per session in the temp dir, beside cadence's own state: it lives as
long as the session's other guard files and needs no rotation of its own.
"""

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from aipass.hooks.apps.handlers.config.output_merge import CONTEXT_LIMIT
from aipass.prax.apps.modules.logger import system_logger as logger

#: The events whose output can reach the model at all. PreCompact and Stop
#: output never does, so recording them would be a ledger of nothing.
LEDGER_EVENTS = frozenset({"UserPromptSubmit", "SessionStart", "PreToolUse", "PostToolUse"})

#: Plain stdout is context only on these; on tool events only additionalContext is.
_PLAIN_IS_CONTEXT = frozenset({"UserPromptSubmit", "SessionStart"})

_LEDGER_DIR = Path(tempfile.gettempdir())
_PREFIX = "aipass-ledger-"
_SHA_CHARS = 12
#: The session id becomes a filename, so it must be one: CC sends a UUID.
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def cc_len(text: str) -> int:
    """Length the way Claude Code measures it: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def is_session_id(session_id: str) -> bool:
    """True when *session_id* is safe to use as a filename."""
    return bool(_SESSION_ID_RE.fullmatch(session_id))


def ledger_path(session_id: str) -> Path:
    """The ledger file for *session_id*."""
    return _LEDGER_DIR / f"{_PREFIX}{session_id}.jsonl"


def newest_session() -> str | None:
    """The session whose ledger was written most recently, or None when there is none."""
    ledgers = sorted(_LEDGER_DIR.glob(f"{_PREFIX}*.jsonl"), key=lambda p: p.stat().st_mtime)
    return ledgers[-1].stem.removeprefix(_PREFIX) if ledgers else None


def injected_text(event_type: str, stdout: str) -> str:
    """The part of one hook output that reaches the model, or "" when none does.

    Args:
        event_type: The hook event the output answers.
        stdout: What the hook (or the merge) printed.

    Returns:
        additionalContext when the output is a JSON object carrying one; the
        plain text on the two events where plain text is context; else "".
    """
    text = stdout.strip()
    if not text:
        return ""
    if not text.startswith("{"):
        return text if event_type in _PLAIN_IS_CONTEXT else ""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        # A brace that does not parse is text, but it is also a hook that meant
        # JSON and did not produce it — worth a line, because CC will not parse it either.
        logger.info("[HOOKS] injection_ledger: %s output opens like JSON but does not parse: %s", event_type, exc)
        return text if event_type in _PLAIN_IS_CONTEXT else ""
    if not isinstance(doc, dict):
        return text if event_type in _PLAIN_IS_CONTEXT else ""
    specific = doc.get("hookSpecificOutput")
    context = specific.get("additionalContext") if isinstance(specific, dict) else None
    return context if isinstance(context, str) else ""


def measure_hooks(event_type: str, outputs: list[tuple[str, str, str]]) -> dict[str, dict]:
    """Per hook, the chars and a short sha of what it injected; hooks that injected nothing are left out.

    WARNS for a single injection over the persist line: the model was shown a
    preview, not the text, so the seat was told less than it looks like.
    """
    hooks: dict[str, dict] = {}
    for hook_name, _handler, stdout in outputs:
        text = injected_text(event_type, stdout)
        if not text:
            continue
        chars = cc_len(text)
        hooks[hook_name] = {"chars": chars, "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:_SHA_CHARS]}
        if chars > CONTEXT_LIMIT:
            logger.warning(
                "[HOOKS] injection_ledger: %s.%s injected %d chars, over the %d persist line — "
                "the model was shown a preview, not this text",
                event_type,
                hook_name,
                chars,
                CONTEXT_LIMIT,
            )
    return hooks


def append_record(session_id: str, event_type: str, hooks: dict, merged: str, token, turn) -> dict | None:
    """Write one record. A record that cannot be written WARNS: a gap in the ledger must not be silent.

    "total" is what the hooks produced and "delivered" is what the merged
    document carried to the model; they differ only when the merge dropped a block.

    Returns:
        The record written, or None when the write failed.
    """
    entry = {
        "ts": round(time.time(), 3),
        "event": event_type,
        "token": token,
        "turn": turn,
        "hooks": hooks,
        "total": sum(h["chars"] for h in hooks.values()),
        "delivered": cc_len(injected_text(event_type, merged)),
    }
    try:
        with ledger_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.warning("[HOOKS] injection_ledger: record NOT written for %s (a gap in the ledger): %s", event_type, exc)
        return None
    return entry


def read_turns(session_id: str) -> list[dict]:
    """The ledger folded to one row per injection moment: every sibling of a turn shares its token.

    Args:
        session_id: The session whose ledger to read.

    Returns:
        Rows in first-seen order, each {"event", "token", "turn", "ts", "hooks", "total"}.
    """
    path = ledger_path(session_id)
    if not path.exists():
        return []
    rows: dict[tuple, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.info("[HOOKS] injection_ledger: unreadable line skipped in %s: %s", path.name, exc)
            continue
        key = (entry.get("event"), entry.get("token"))
        row = rows.setdefault(key, {**entry, "hooks": {}, "total": 0, "turn": entry.get("turn")})
        row["hooks"].update(entry.get("hooks", {}))
        row["total"] = sum(h.get("chars", 0) for h in row["hooks"].values())
        # The largest number any sibling read is the one that had seen the increment.
        numbers = [n for n in (row.get("turn"), entry.get("turn")) if isinstance(n, int)]
        row["turn"] = max(numbers) if numbers else None
    return list(rows.values())
