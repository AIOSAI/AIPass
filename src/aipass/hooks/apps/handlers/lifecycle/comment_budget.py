# =================== AIPass ====================
# Name: comment_budget.py
# Version: 1.0.0
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
from datetime import datetime
from pathlib import Path

from aipass.prax import append_jsonl
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.lifecycle.auto_fix import _scratch_ground
from aipass.hooks.apps.handlers.module_root import module_file

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CONTEXT_CAP = 700
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


def _over_context(name: str, scan, added: int | None) -> str:
    """The answer the model reads when *name* is over budget."""
    over = scan.over()
    head = (
        f"[COMMENTS] {name} is over the comment budget: {scan.comments} of {scan.body} lines are comments "
        f"({_percent(scan.share)}, budget {comment_scan.BUDGET_PERCENT}%, {over} over)."
    )
    if added:
        head += f" This edit {'added' if added > 0 else 'removed'} {abs(added)}."
    runs = ", ".join(f"L{a}-{b} ({b - a + 1})" for a, b in scan.heaviest())
    rule = (
        "A comment says why when the code cannot. Never what the next line does, never the chat, the plan, "
        "the wave or the reviewer. Trim this file's runs in your next edit of it. "
        "drone @hooks comments <path> lists every run."
    )
    return f"{head}\nHeaviest runs: {runs}.\n{rule}"[:CONTEXT_CAP]


def handle(hook_data: dict) -> dict:
    """Judge the edited file's comment share; never blocks."""
    try:
        tool_name = hook_data.get("tool_name", "")
        tool_input = hook_data.get("tool_input") or {}
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        kind = comment_scan.kind_of(file_path) if file_path else None
        if tool_name not in EDIT_TOOLS or kind is None:
            return _SILENT
        scratch = _scratch_ground(file_path)
        if scratch:
            return {
                "stdout": json.dumps({"systemMessage": f"[comments] skipped: {scratch} is scratch"}),
                "exit_code": 0,
            }
        path = Path(file_path)
        if not path.is_file():
            return _SILENT
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
        name = path.name
        if scan.over() <= 0:
            return {
                "stdout": json.dumps({"systemMessage": f"[comments] {name} {_percent(scan.share)} ok"}),
                "exit_code": 0,
            }
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": _over_context(name, scan, added),
            },
            "systemMessage": f"[comments] {name} {_percent(scan.share)}, {scan.over()} over budget",
        }
        return {"stdout": json.dumps(result), "exit_code": 0}
    except Exception as exc:
        logger.warning("[HOOKS] comment_budget: unexpected error (allowing): %s", exc)
        return _SILENT
