# =================== AIPass ====================
# Name: compact.py
# Version: 2.0.0
# Description: PreCompact writes the summary's instructions; SessionStart compact re-injects the work still out
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-11-25
# =============================================

"""Compaction: what the summary must carry, and what the first turn after it resumes.

Claude Code hands a PreCompact hook's stdout to the summarizer as its instructions, so ``handle`` writes
to the summarizer, not to the model after it. ``handle_resume`` (SessionStart, source compact) puts the
same live list in front of that model, because the PostToolUse re-ground needs a tool call it may not make.
"""

import importlib
import json
import os
import subprocess
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger

RESUME_SENTENCE = "Next turn: resume the Work still out list first; answer the user's last line only inside that work."
# Claude Code cuts a PreCompact hook's output at 10,000 characters; each part is capped so the whole stays under.
_MAX_FILES = 25
_MAX_DISPATCHES = 8
_INSTRUCTION_CAP = 1500
_LINE_CAP = 300
_TAIL_BYTES = 4_000_000
_LOG_HEADINGS = ("## Night Log", "## Execution Log")


def _read_last_session(branch_dir: Path) -> str | None:
    local_path = branch_dir / ".trinity" / "local.json"
    if not local_path.is_file():
        return None
    try:
        data = json.loads(local_path.read_text(encoding="utf-8"))
        result: list[str] = []
        sessions = data.get("sessions", [])
        if sessions:
            last = sessions[0]
            sid = last.get("number", "?")
            sdate = last.get("date", "?")
            ssum = last.get("summary", "no summary")
            result.append(f"Last session (#{sid}, {sdate}): {ssum}")
        learnings = data.get("key_learnings", [])
        if isinstance(learnings, list) and learnings:
            # newest-first: [:10] is the ten most recent, not [-10:] (the ten oldest)
            keys = [entry.get("key", "?") for entry in learnings[:10] if isinstance(entry, dict)]
            if keys:
                result.append(f"Key learnings available: {', '.join(keys)}")
        return "\n".join(result) if result else None
    except Exception as exc:
        logger.warning("[hooks] compact: read session failed: %s", exc)
        return None


def _cut(text: str, cap: int = _LINE_CAP) -> str:
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _fact(label: str, read, *args) -> str:
    """``label: answer``; a reader that raises is logged and written into the list as unread, never dropped."""
    try:
        return f"{label}: {read(*args)}"
    except Exception as exc:
        logger.warning("[hooks] compact: %s could not be read: %s", label, exc)
        return f"{label}: could not be read ({type(exc).__name__}: {_cut(str(exc), 120)})"


def _dirty_files(cwd: Path) -> str:
    """The seat tree's uncommitted files, counted and named up to a cap; other branches' files are not its work."""
    done = subprocess.run(
        ["git", "status", "--porcelain", "--", "."],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        cwd=cwd,
    )
    if done.returncode != 0:
        raise RuntimeError(_cut(done.stderr or f"git status exited {done.returncode}", 120))
    dirty = [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]
    more = f" (+{len(dirty) - _MAX_FILES} more)" if len(dirty) > _MAX_FILES else ""
    return f"{len(dirty)}" + (f": {', '.join(dirty[:_MAX_FILES])}{more}" if dirty else "")


def _unread(branch_dir: Path) -> int:
    count = json.loads((branch_dir / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))["unread_count"]
    if not isinstance(count, int):
        raise ValueError(f"unread_count is {count!r}")
    return count


def _dispatches(branch: str) -> str:
    """Open dispatches this seat sent or still owes, newest first."""
    rows = importlib.import_module("aipass.ai_mail").outstanding_dispatches()
    me = f"@{branch}"
    lines = []
    for row in rows:
        if row.get("sender") == me:
            lines.append(f"sent to {row.get('target')}: {_cut(str(row.get('subject', '')), 120)}")
        elif row.get("target") == me:
            lines.append(f"from {row.get('sender')}, still open: {_cut(str(row.get('subject', '')), 120)}")
    return "; ".join(lines[:_MAX_DISPATCHES]) or "none"


def _last_log_line(plan: Path) -> str:
    """The last line under the plan's Night Log or Execution Log heading, "" when it has none.

    The plan template closes its log with bold notes and a fenced command block: neither is a log line."""
    last, inside, fenced = "", False, False
    for line in plan.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text.startswith("```"):
            fenced = not fenced
        elif line.startswith("## "):
            inside, fenced = text in _LOG_HEADINGS, False
        elif inside and not fenced and text and text != "---" and not text.startswith("**"):
            last = text
    return last


def _newest_plan(branch_dir: Path) -> str:
    """The branch's newest open plan and its last log line, or "none"."""
    plans = importlib.import_module("aipass.flow").get_open_plans()
    here = str(branch_dir.resolve())
    mine = sorted((i for _n, i in plans if i.get("location") == here), key=lambda i: i.get("created", ""))
    if not mine:
        return "none"
    path = Path(mine[-1]["file_path"])
    log = _last_log_line(path)
    return path.name + (f"; last log line: {_cut(log)}" if log else "; no log line yet")


def _user_text(entry: dict) -> str | None:
    """A person's prompt from one transcript row; None for tool results, meta rows and harness wake-ups."""
    if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isMeta"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    text = content.strip() if isinstance(content, str) else ""
    return None if not text or text.startswith(("<", "[SYSTEM NOTIFICATION", "Caveat:")) else text


def _last_instruction(transcript_path: str) -> str:
    """The newest prompt a person typed, read from the transcript's tail, or "none in the transcript"."""
    with open(transcript_path, "rb") as fh:
        fh.seek(max(0, os.fstat(fh.fileno()).st_size - _TAIL_BYTES))
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        text = _user_text(json.loads(line)) if line.startswith("{") and line.endswith("}") else None
        if text:
            return text if len(text) <= _INSTRUCTION_CAP else text[:_INSTRUCTION_CAP] + " […cut]"
    return "none in the transcript"


def _work_still_out(hook_data: dict) -> tuple[str, list[str]]:
    """(branch name, one fact per line) for the seat that is compacting."""
    cwd = Path(hook_data.get("cwd") or os.getcwd())
    branch_dir = importlib.import_module("aipass.hooks.apps.modules.context_window").find_branch_dir(str(cwd))
    branch = branch_dir.name if branch_dir else "unknown"
    facts = [_fact("Uncommitted files", _dirty_files, branch_dir or cwd), _fact("Open dispatches", _dispatches, branch)]
    if branch_dir:
        facts += [_fact("Unread mail", _unread, branch_dir), _fact("Newest open plan", _newest_plan, branch_dir)]
        session = _read_last_session(branch_dir)
        if session:
            facts.append(_cut(session.splitlines()[0]))
    transcript = hook_data.get("transcript_path") or ""
    facts.append(_fact("The user's last instruction, verbatim", _last_instruction, transcript))
    return branch, facts


def handle(hook_data: dict) -> dict:
    """Write the compaction summary's instructions; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Reset cadence, mark the grounding receipt pending, and tell the summarizer what to carry."""
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        cadence.reset_counter(hook_data=hook_data, caller="compact")
    except Exception as exc:
        logger.warning("[hooks] compact: cadence reset failed: %s", exc)

    try:
        importlib.import_module("aipass.hooks.apps.modules.grounding_receipt").mark_pending(hook_data)
    except Exception as exc:
        logger.error("[hooks] compact: grounding receipt not set pending: %s", exc)

    branch, facts = _work_still_out(hook_data)
    lines = [
        f"Instructions for this summary (AIPass hooks, seat @{branch}):",
        'End the summary with a section headed "Work still out". In it, list every task, dispatch and plan still '
        "open in this conversation with its next step, the uncommitted files, the unread mail count, the newest "
        "open plan and its last log line, and the user's last instruction verbatim. Carry the live facts below "
        "into it.",
    ]
    if os.environ.get("AIPASS_SESSION_TYPE") == "dispatched":
        lines.append("This seat is a dispatched agent: the section also says the next turn saves its memories first.")
    lines += ["", "Live facts at compaction:", *(f"- {fact}" for fact in facts), ""]
    lines.append(f'Make this the summary\'s final sentence, verbatim: "{RESUME_SENTENCE}"')
    return {"stdout": "\n".join(lines), "exit_code": 0, "sound": "pre compact"}


def handle_resume(hook_data: dict) -> dict:
    """SessionStart after a compaction: re-inject the work still out; each call leaves one json trail entry."""
    result = _handle_resume(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle_resume", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle_resume(hook_data: dict) -> dict:
    """Only source compact: a startup, resume or clear has no work in flight that a summary dropped."""
    if hook_data.get("source") != "compact":
        return {"stdout": "", "exit_code": 0}
    branch, facts = _work_still_out(hook_data)
    context = "\n".join(
        [
            f"WORK STILL OUT — @{branch}, read at the compaction just now:",
            *(f"- {fact}" for fact in facts),
            "",
            "Resume this list before replying: answer the user's last line only inside that work.",
        ]
    )
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    return {"stdout": json.dumps(out), "exit_code": 0}
