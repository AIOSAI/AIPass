# =================== AIPass ====================
# Name: grounding_receipt.py
# Version: 1.0.1
# Description: The grounding receipt, .ai_mail.local/grounding.json: did the five grounding entries reach the model
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-28
# Modified: 2026-10-28
# =============================================

"""The grounding receipt beside a branch's session pointer: one current row plus a history of 20.

OpenCode is the one CLI whose store shows what a model call received. instruction_state.current_values
moves at each step boundary to what that step rendered, and a compaction baselines the new epoch from
it (measured on canary across a forced compaction). Read at the prompt hook, before this turn's puts,
it is what the last call had; instruction_entry is what we asked for. Claude Code and Codex show
nothing, so their receipt says unverified with boundary none. A compaction sets pending until the
next prompt reads the store again.
"""

import hashlib
import json
import os
import time
from contextlib import closing
from pathlib import Path

from aipass.cli.apps.modules import console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.modules import context_window
from aipass.prax.apps.modules.logger import system_logger as logger

#: The grounding entries (bridges/opencode.py GROUNDING) and where a seat re-reads each one.
SOURCES = {
    "aipass-branch-prompt": "<branch>/.aipass/aipass_local_prompt.md",
    "aipass-culture": "$AIPASS_HOME/.claude/AGENTS.md",
    "aipass-identity": "<branch>/.trinity/passport.json",
    "aipass-kernel": "$AIPASS_HOME/.aipass/tier0_kernel.md",
    "aipass-navmap": "$AIPASS_HOME/.aipass/tier1_navmap.md",
}
REQUIRED = tuple(sorted(SOURCES))
REVISION = hashlib.sha256("\n".join(REQUIRED).encode("utf-8")).hexdigest()[:12]
HISTORY_CAP = 20
RECEIPT = Path(".ai_mail.local") / "grounding.json"

_ENTRIES = "SELECT key, value FROM instruction_entry WHERE session_id = ? AND removed = 0"
_STATE = "SELECT current_values FROM instruction_state WHERE session_id = ?"
_BLOB = "SELECT value FROM instruction_blob WHERE hash = ?"
_COMPACTIONS = (
    "SELECT count(*) FROM session_message WHERE session_id = ? AND type = 'compaction'"
    " AND json_extract(data, '$.status') = 'completed'"
)


def _digest(values: dict) -> str:
    """sha256 over the required keys in order and their stored values (None when absent)."""
    material = json.dumps([[key, values.get(key)] for key in REQUIRED])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _receipt_path(hook_data: dict) -> Path | None:
    """The branch's receipt file; None without a session or an explicit cwd inside a branch."""
    if not hook_data.get("session_id") or not hook_data.get("cwd"):
        return None
    branch_dir = context_window.find_branch_dir(hook_data["cwd"])
    return branch_dir / RECEIPT if branch_dir else None


def _read_store(session_id: str) -> tuple[dict, dict, int]:
    """(asked, in effect, completed compactions) for an OpenCode session, values as the store keeps them."""
    with closing(context_window.opencode_store()) as conn:
        asked = {k: v for k, v in conn.execute(_ENTRIES, (session_id,)) if k in SOURCES}
        state = conn.execute(_STATE, (session_id,)).fetchone()
        hashes = json.loads(state[0]) if state else {}
        effect = {}
        for key in REQUIRED:
            blob = conn.execute(_BLOB, (hashes[f"api/{key}"],)).fetchone() if f"api/{key}" in hashes else None
            if blob is not None:
                effect[key] = blob[0]
        generation = conn.execute(_COMPACTIONS, (session_id,)).fetchone()[0]
    return asked, effect, generation


def _opencode_row(session_id: str) -> dict:
    asked, effect, generation = _read_store(session_id)
    missing = [key for key in REQUIRED if key not in effect]
    stale = [key for key in REQUIRED if key in effect and asked.get(key) != effect[key]]
    if not asked:
        status, missing, stale = "pending", [], []  # nothing asked yet: this turn's puts are the first delivery
    else:
        status = "ungrounded" if missing or stale else "verified"
    return {
        "generation": generation,
        "expected_digest": _digest(asked),
        "observed_digest": _digest(effect),
        "observation_boundary": "opencode_store",
        "status": status,
        "missing": missing,
        "stale": stale,
    }


def _write(path: Path, row: dict) -> None:
    """Make *row* current; the old current moves to history when more than its clock changed."""
    doc = json_handler.read_json(path)
    doc = doc if isinstance(doc, dict) else {}
    history = doc.get("history")
    history = history if isinstance(history, list) else []
    old = doc.get("current")
    if isinstance(old, dict) and {k: v for k, v in old.items() if k != "checked_at"} != {
        k: v for k, v in row.items() if k != "checked_at"
    }:
        history = [old, *history][:HISTORY_CAP]
    if not json_handler.write_json(path, {"current": row, "history": history}):
        logger.error("[HOOKS] grounding_receipt: receipt not written at %s", path)


def _base(hook_data: dict, path: Path) -> dict:
    return {
        "session_id": hook_data["session_id"],
        "branch": path.parent.parent.name,
        "required_set_revision": REVISION,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _previous(path: Path, session_id: str) -> dict:
    doc = json_handler.read_json(path)
    current = doc.get("current") if isinstance(doc, dict) else None
    return current if isinstance(current, dict) and current.get("session_id") == session_id else {}


def observe(hook_data: dict) -> str:
    """Write this seat's receipt at the prompt; the one line to tell the citizen when it is ungrounded, else ""."""
    path = _receipt_path(hook_data)
    if path is None:
        return ""
    if hook_data.get("provider") == "opencode":
        if not context_window.opencode_db_path().is_file():
            logger.error("[HOOKS] grounding_receipt: no OpenCode store at %s", context_window.opencode_db_path())
            return ""
        row = _opencode_row(hook_data["session_id"])
    else:
        row = {
            "generation": _previous(path, hook_data["session_id"]).get("generation", 0),
            "expected_digest": None,
            "observed_digest": None,
            "observation_boundary": "none",
            "status": "unverified",
            "missing": [],
            "stale": [],
        }
    _write(path, {**_base(hook_data, path), **row})
    json_handler.log_operation("grounding_receipt", {"status": row["status"], "generation": row["generation"]})
    if row["status"] != "ungrounded":
        return ""
    lost = sorted({*row["missing"], *row["stale"]})
    return (
        f"GROUNDING RECEIPT: your last model call did not carry {', '.join(lost)}. "
        f"Re-read: {'; '.join(SOURCES[key] for key in lost)}."
    )


def mark_pending(hook_data: dict) -> None:
    """A compaction is starting: the receipt says pending, one generation on, until the next prompt reads it."""
    path = _receipt_path(hook_data)
    if path is None:
        return
    previous = _previous(path, hook_data["session_id"])
    row = {
        **{k: v for k, v in previous.items() if k not in ("session_id", "branch", "checked_at")},
        "generation": previous.get("generation", 0) + 1,
        "observed_digest": None,
        "observation_boundary": previous.get("observation_boundary", "none"),
        "status": "pending",
        "missing": [],
        "stale": [],
    }
    row.setdefault("expected_digest", None)
    _write(path, {**_base(hook_data, path), **row})


def print_introspection() -> None:
    """Print module structure for drone routing."""
    console.print("[bold cyan]grounding_receipt[/bold cyan] — Did the grounding entries reach the model, per seat")
    console.print(f"  Receipt: <branch>/{RECEIPT.as_posix()} · required set {REVISION}: {', '.join(REQUIRED)}")
    console.print("  Written by: handlers/prompt/context_gauge.py (prompt), handlers/lifecycle/compact.py (pending)")


def handle_command(command: str, args: list) -> bool:
    """Route `drone @hooks receipt`: the current receipt of the branch at CWD."""
    if command != "receipt":
        return False
    if not args:
        print_introspection()
    if wants_help(args):
        console.print("[bold cyan]receipt[/bold cyan] — the grounding receipt of the branch you stand in")
        console.print("  drone @hooks receipt     status, generation, boundary, missing and stale keys")
        return True
    branch_dir = context_window.find_branch_dir(os.environ.get("AIPASS_CALLER_CWD") or os.getcwd())
    doc = json_handler.read_json(branch_dir / RECEIPT) if branch_dir else None
    current = doc.get("current") if isinstance(doc, dict) else None
    if not isinstance(current, dict):
        console.print("  No receipt here yet.")
        return True
    console.print(
        f"[bold]receipt[/bold] @{current.get('branch')} {current.get('status')} gen {current.get('generation')} "
        f"boundary {current.get('observation_boundary')} session {current.get('session_id')} "
        f"at {current.get('checked_at')}"
    )
    for name in ("missing", "stale"):
        if current.get(name):
            console.print(f"  {name}: {', '.join(current[name])}")
    return True
