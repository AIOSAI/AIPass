# =================== AIPass ====================
# Name: output_merge.py
# Version: 1.0.0
# Description: One hook output, one document - merges fan-out handler stdouts for the engine
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-09-10
# Modified: 2026-09-10
# =============================================

"""Merges every handler's stdout on one event into the ONE document Claude Code reads.

The engine used to join fan-out handler outputs with a newline. Claude Code
2.1.267 parses a hook's stdout as a single document (its parser, read from the
installed binary for devpulse bc1bcc45): text that starts with "{" goes to
JSON.parse, and two objects on two lines fail it. Both valid, so the "several
JSON documents" escape does not apply either, and the result is a non-blocking
hook error with NEITHER object applied. Plain text that does not start with "{"
is taken as plain text, so a JSON answer after it is silently ignored.
"""

import json

from aipass.prax.apps.modules.logger import system_logger as logger


#: Claude Code 2.1.267 persists an additionalContext longer than this many
#: UTF-16 units to a file and shows the agent a 2,000-char preview (threshold
#: ``sgr = 1e4``, measured for issue #752 - see post_compact_regrounding.py).
CONTEXT_LIMIT = 10_000

#: Handlers whose context is placed first when a merge would cross the limit.
#: The post-compact re-ground is budgeted to fit alone (9,000) and is the one
#: context an agent cannot get back from anywhere else mid-turn.
_CONTEXT_PRIORITY = frozenset({"post_compact_regrounding"})

#: Events whose PLAIN stdout Claude Code hands the model as context. On every
#: other event plain stdout is shown to the user, so a plain output folded into
#: a merged document keeps its audience: context here, systemMessage elsewhere.
_PLAIN_IS_CONTEXT = frozenset({"UserPromptSubmit", "SessionStart"})

_CONTEXT_SEP = "\n\n"


def _cc_len(text: str) -> int:
    """Length the way Claude Code measures it: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def _as_object(stdout: str) -> dict | None:
    """The handler's output as a JSON object, or None when it is plain text."""
    text = stdout.strip()
    if not text.startswith("{"):
        return None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def combine_outputs(event_type: str, outputs: list[tuple[str, str, str]]) -> str:
    """Every handler's stdout as the ONE document Claude Code will read.

    Until 2026-09-10 this was a newline join. Claude Code 2.1.267 parses a hook's
    stdout as one document: two JSON objects on two lines fail to parse, are
    reported as "looks like a JSON object but is not valid JSON" - a non-blocking
    hook error - and NEITHER is applied. Measured in the transcripts: four
    post-compact re-grounds lost that way (devpulse x3, trigger x1, 2026-09-02 to
    09-08), each on an Edit where auto_fix had printed its "[diagnostics] ok".

    Plain text with no JSON beside it is joined exactly as before, and a single
    output passes through untouched. Once any handler answers in JSON the answer
    is one object: additionalContext joined in handler order by a blank line
    (within CONTEXT_LIMIT, see _fit_contexts), systemMessage joined by a newline,
    every other key first-handler-wins (a conflicting later value is logged),
    and a plain output folded in where its audience is (_PLAIN_IS_CONTEXT).

    Args:
        event_type: The hook event, which the merged hookSpecificOutput must name.
        outputs: (hook entry name, handler path, stdout) per handler, in run order.
    """
    docs = [(name, handler, stdout, _as_object(stdout)) for name, handler, stdout in outputs]
    if len(docs) < 2 or all(doc is None for *_, doc in docs):
        return "\n".join(stdout for _, _, stdout, _ in docs)

    merged: dict = {}
    specific: dict = {}
    contexts: list[tuple[int, str, str, bool]] = []
    messages: list[str] = []
    for order, (name, handler, stdout, doc) in enumerate(docs):
        priority = name in _CONTEXT_PRIORITY or bool(_CONTEXT_PRIORITY.intersection(handler.split(".")))
        if doc is None:
            if event_type in _PLAIN_IS_CONTEXT:
                contexts.append((order, name, stdout.strip(), priority))
            else:
                messages.append(stdout.strip())
            continue
        own = doc.get("hookSpecificOutput")
        own = own if isinstance(own, dict) else {}
        if own.get("additionalContext"):
            contexts.append((order, name, str(own["additionalContext"]), priority))
        if doc.get("systemMessage"):
            messages.append(str(doc["systemMessage"]))
        _first_wins(merged, doc, ("hookSpecificOutput", "systemMessage"), f"{event_type}.{name}")
        _first_wins(specific, own, ("hookEventName", "additionalContext"), f"{event_type}.{name}")

    kept = _fit_contexts(contexts, event_type)
    if kept or specific:
        merged["hookSpecificOutput"] = {"hookEventName": event_type, **specific}
        if kept:
            merged["hookSpecificOutput"]["additionalContext"] = _CONTEXT_SEP.join(kept)
    if messages:
        merged["systemMessage"] = "\n".join(messages)
    logger.info("[HOOKS] %s: %d outputs merged into one document, %d context(s) kept", event_type, len(docs), len(kept))
    return json.dumps(merged)


def _first_wins(into: dict, doc: dict, skip: tuple[str, ...], where: str) -> None:
    """Copy *doc*'s keys (minus *skip*) into *into*; an earlier value is never overwritten."""
    for key, value in doc.items():
        if key in skip:
            continue
        if key in into and into[key] != value:
            logger.warning("[HOOKS] %s: %r conflicts with an earlier handler's value - earlier kept", where, key)
            continue
        into[key] = value


def _fit_contexts(contexts: list[tuple[int, str, str, bool]], event_type: str) -> list[str]:
    """The contexts that fit CONTEXT_LIMIT together, returned in handler order.

    Priority handlers are placed first, then the rest in handler order. A context
    that would carry the total past the limit is dropped with a warning naming
    it and its size, never silently. The first context placed is always kept:
    one output on its own was never this merge's to cut.
    """
    placed: list[tuple[int, str]] = []
    total = 0
    for order, name, text, _priority in sorted(contexts, key=lambda c: (not c[3], c[0])):
        size = _cc_len(text) + (_cc_len(_CONTEXT_SEP) if placed else 0)
        if placed and total + size > CONTEXT_LIMIT:
            logger.warning(
                "[HOOKS] %s.%s context DROPPED (%d units): the merged additionalContext would cross %d",
                event_type,
                name,
                _cc_len(text),
                CONTEXT_LIMIT,
            )
            continue
        placed.append((order, text))
        total += size
    return [text for _, text in sorted(placed)]
