# =================== AIPass ====================
# Name: ledger.py
# Description: CI red lane ledger - run verdicts and cure states in trigger_json/ci_ledger.json
# Version: 1.1.0
# Created: 2026-10-22
# Modified: 2026-10-23
# =============================================

"""
CI Ledger Handler - every run the lane has seen and every cure it is carrying

Not on a `<module>_<config|data|log>.json` name: json_handler regenerates those and would blank this shape.
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator

from aipass.trigger.apps.config import TRIGGER_JSON_DIR, atomic_write_json, json_file_lock, read_text_with_retry
from aipass.trigger.apps.handlers.json import json_handler

LEDGER_FILE = TRIGGER_JSON_DIR / "ci_ledger.json"

# Waiting for the two-awake cap: the next poll drains both.
QUEUED = {"queued", "review_queued"}


def utc_now() -> str:
    """Now as GitHub stamps a run's creation, so the two compare as strings."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty() -> Dict[str, Any]:
    """The ledger's shape before its first run."""
    return {"version": 1, "runs": {}, "cures": {}}


def load() -> Dict[str, Any]:
    """Read the ledger; a missing file is an empty ledger, an unreadable one raises."""
    if not LEDGER_FILE.exists():
        return _empty()
    try:
        data = json.loads(read_text_with_retry(LEDGER_FILE))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"ci ledger unreadable ({LEDGER_FILE.name}): {exc}") from exc
    data.setdefault("runs", {})
    data.setdefault("cures", {})
    return data


@contextmanager
def update() -> Iterator[Dict[str, Any]]:
    """Read-modify-write the ledger under its lock; the write happens only when the block completes."""
    with json_file_lock(LEDGER_FILE):
        data = load()
        yield data
        atomic_write_json(LEDGER_FILE, data)
    json_handler.log_operation("ci_ledger_written", {"runs": len(data["runs"]), "cures": len(data["cures"])})


def cure_key(run_id: Any, owner: str) -> str:
    """One cure per run and owner: a run that names two branches carries two cures."""
    return f"{run_id}@{owner.lstrip('@').lower()}"


def set_cure(data: Dict[str, Any], run_id: Any, owner: str, state: str, /, **fields: Any) -> Dict[str, Any]:
    """Create or move a cure to *state*, stamping when it moved."""
    cure = data["cures"].setdefault(cure_key(run_id, owner), {"run_id": str(run_id), "owner": owner.lstrip("@")})
    cure.update(fields)
    cure["state"] = state
    cure["updated"] = utc_now()
    return cure


def supersede(data: Dict[str, Any], newest: Dict[str, Dict[str, str]]) -> list:
    """Mark every red that is no longer its workflow's newest run superseded.

    Its queued and gated cures go with it; a cure already woken keeps its course, since the owner's work is real."""
    newest_ids = {row["run_id"] for row in newest.values()}
    moved = []
    for run_id, run in data["runs"].items():
        if run.get("verdict") != "red" or run_id in newest_ids or run.get("workflow") not in newest:
            continue
        run["verdict"] = "superseded"
        moved.append(run_id)
        for cure in data["cures"].values():
            if cure["run_id"] == run_id and cure["state"] in ("queued", "gated"):
                cure["state"] = "superseded"
                cure["updated"] = utc_now()
    return moved
