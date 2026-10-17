# =================== AIPass ====================
# Name: comment_budget.py
# Version: 1.2.0
# Description: Comment budget — measures every edit's comment share (PostToolUse)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Measures an edited file's comment share and tells the agent when it is over budget (docs/comments.md)."""

import importlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aipass.prax import append_jsonl
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.lifecycle.auto_fix import _scratch_ground
from aipass.hooks.apps.handlers.module_root import module_file

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CONTEXT_CAP = 700
HELD_FRESH_SECONDS = 10
BRANCH_ROOT = module_file(__file__).parent.parent.parent.parent
_PROD_LEDGER = BRANCH_ROOT / "logs" / "comments.jsonl"
_SILENT = {"stdout": "", "exit_code": 0}
comment_scan = importlib.import_module("aipass.hooks.apps.modules.comment_scan")


def ledger_file() -> Path:
    """The ledger path: the test log dir under pytest, logs/comments.jsonl otherwise."""
    if "_pytest" not in sys.modules:
        return _PROD_LEDGER
    folder = Path(os.environ.get("AIPASS_TEST_LOG_DIR") or tempfile.gettempdir()) / "hooks"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "comments.jsonl"


def ledger_rows() -> list[dict]:
    """Every ledger row, oldest first, the rotated generation included."""
    rows: list[dict] = []
    current = ledger_file()
    for path in (current.with_name(current.name + ".1"), current):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.info("[HOOKS] comment_budget: unreadable ledger row skipped: %s", exc)
    return rows


def _percent(share: float) -> str:
    """A share as a whole percent."""
    return f"{round(share * 100)}%"


def _added(tool_name: str, tool_input: dict, kind: str, file_key: str, comments: int) -> int | None:
    """Comment lines this edit added (negative: removed), None when it cannot be known."""
    if tool_name == "Edit":
        edits = [tool_input]
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits") or []
    elif tool_name == "Write":
        prior = [row for row in ledger_rows() if row.get("file") == file_key]
        return comments - prior[-1]["comments"] if prior else None
    else:
        return None
    count = 0
    for edit in edits:
        count += comment_scan.scan(edit.get("new_string") or "", kind).comments
        count -= comment_scan.scan(edit.get("old_string") or "", kind).comments
    return count


RULE = (
    "A comment says why when the code cannot. Never what the next line does, never the chat, the plan, "
    "the wave or the reviewer. Trim this file's runs in your next edit of it. "
    "drone @hooks comments <path> lists every run."
)


def _over_context(overs: list[tuple]) -> str:
    """The answer the model reads for the over-budget (name, scan, added) files, worst first."""
    heads = []
    for name, scan, added in overs:
        head = (
            f"[COMMENTS] {name} is over the comment budget: {scan.comments} of {scan.body} lines are comments "
            f"({_percent(scan.share)}, budget {comment_scan.BUDGET_PERCENT}%, {scan.over()} over)."
        )
        if added:
            head += f" This edit {'added' if added > 0 else 'removed'} {abs(added)}."
        runs = ", ".join(f"L{a}-{b} ({b - a + 1})" for a, b in scan.heaviest())
        heads.append(f"{head}\nHeaviest runs: {runs}.")
    return "\n".join(heads)[: CONTEXT_CAP - len(RULE) - 2] + "\n" + RULE


def _bash_written(hook_data: dict) -> list[str]:
    """The files a Bash command wrote: grammar targets, and held paths touched in the last seconds."""
    bash_writes = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
    command = (hook_data.get("tool_input") or {}).get("command") or ""
    written: list[str] = []
    for path, how in bash_writes.write_targets(command, hook_data.get("cwd") or ""):
        if bash_writes.HELD_BY_INTERPRETER in how and not _fresh(path):
            continue
        if str(path) not in written:
            written.append(str(path))
    return written


def _fresh(path: Path) -> bool:
    """Whether *path* is a file modified within HELD_FRESH_SECONDS."""
    return path.is_file() and time.time() - path.stat().st_mtime <= HELD_FRESH_SECONDS


def _judge(hook_data: dict, tool_name: str, tool_input: dict, file_path: str) -> str | tuple | None:
    """Scan one written file and log its row: a skip line, (name, scan, added), or None when unjudged."""
    kind = comment_scan.kind_of(file_path)
    if kind is None:
        return None
    scratch = _scratch_ground(file_path)
    if scratch:
        return f"skipped: {scratch} is scratch"
    path = Path(file_path)
    if not path.is_file():
        return None
    file_key = os.path.abspath(file_path)
    scan = comment_scan.scan(path, kind)
    added = _added(tool_name, tool_input, kind, file_key, scan.comments)
    append_jsonl(
        ledger_file(),
        {
            "time": datetime.now().isoformat(timespec="seconds"),
            "seat": importlib.import_module("aipass.hooks.apps.modules.diagnostics_state").seat_key(hook_data),
            "tool": tool_name,
            "file": file_key,
            "body": scan.body,
            "comments": scan.comments,
            "share": round(scan.share, 4),
            "over": max(scan.over(), 0),
            "added": added,
        },
    )
    return path.name, scan, added


def _status(verdict: str | tuple) -> str:
    """One file's statusline part."""
    if isinstance(verdict, str):
        return verdict
    name, scan, _added_count = verdict
    if not scan.judged:
        return f"{name} {_percent(scan.share)}, not judged: under {comment_scan.MIN_BODY_LINES} lines"
    if scan.over() <= 0:
        return f"{name} {_percent(scan.share)} ok"
    return f"{name} {_percent(scan.share)}, {scan.over()} over budget"


def handle(hook_data: dict) -> dict:
    """Judge the comment share of every file the tool wrote; never blocks."""
    try:
        tool_name = hook_data.get("tool_name", "")
        tool_input = hook_data.get("tool_input") or {}
        if tool_name == "Bash":
            paths = _bash_written(hook_data)
        elif tool_name in EDIT_TOOLS:
            paths = [tool_input.get("file_path") or tool_input.get("notebook_path") or ""]
        else:
            return _SILENT
        verdicts = [v for v in (_judge(hook_data, tool_name, tool_input, p) for p in paths if p) if v is not None]
        if not verdicts:
            return _SILENT
        result: dict = {"systemMessage": "[comments] " + "; ".join(_status(v) for v in verdicts)}
        overs = [v for v in verdicts if not isinstance(v, str) and v[1].judged and v[1].over() > 0]
        if overs:
            overs.sort(key=lambda v: v[1].over(), reverse=True)
            result = {
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": _over_context(overs)},
                **result,
            }
        return {"stdout": json.dumps(result), "exit_code": 0}
    except Exception as exc:
        logger.warning("[HOOKS] comment_budget: unexpected error (allowing): %s", exc)
        return _SILENT
