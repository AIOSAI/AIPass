# =================== AIPass ====================
# Name: lane.py
# Description: The memory interpreter and the JSON-over-stdin subprocess lane every ML handler shares
# Version: 1.1.0
# Created: 2026-10-23
# Modified: 2026-11-15
# =============================================

"""
Subprocess Lane

Embedding and Chroma run in the memory venv's python, in a subprocess; the parent never imports them.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.storage.chroma_subprocess import embedder_reason

_HANDLERS_DIR = Path(__file__).resolve().parents[1]
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"
EMBED_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "vector" / "embed_subprocess.py"

_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


_ANNOUNCED: set[str] = set()


def memory_python() -> str:
    """The interpreter that owns the ML deps: env override, the memory venv, then ours (logged once per choice)."""
    override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if override:
        choice, why = override, "AIPASS_MEMORY_PYTHON"
    elif _MEMORY_VENV_PYTHON.exists():
        choice, why = str(_MEMORY_VENV_PYTHON), "the memory venv"
    else:
        choice, why = sys.executable, f"this process: no {_MEMORY_VENV_PYTHON}, no AIPASS_MEMORY_PYTHON"
    if choice not in _ANNOUNCED:
        _ANNOUNCED.add(choice)
        logger.info(f"[lane] ML interpreter {choice} ({why})")
    return choice


def run_json(script: Path, payload: Dict[str, Any], timeout: int, label: str) -> Dict[str, Any]:
    """Run ``script`` with ``payload`` on stdin; its JSON reply, or a failure dict, never an exception.

    An unreadable reply is a failure, never an empty success: callers delete originals on this answer.
    """
    try:
        completed = subprocess.run(
            [memory_python(), str(script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[lane] {label} timed out after {timeout}s")
        return {"success": False, "error": f"{label} timed out"}
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"[lane] {label} could not run: {exc}")
        return {"success": False, "error": f"{label} could not run: {exc}"}

    failed = f"{label} failed (exit {completed.returncode})"
    try:
        reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        if completed.returncode != 0:
            # No reply means the child died before it could speak; its stderr is the only crash record.
            tail = "\n".join((completed.stderr or "").strip().splitlines()[-20:])[-2000:] or "empty"
            logger.warning(f"[lane] {failed}, died before replying; stderr tail:\n{tail}")
            return {"success": False, "error": f"{failed}: {embedder_reason(completed)}"}
        logger.warning(f"[lane] Invalid JSON from {label}: {exc}")
        return {"success": False, "error": f"Invalid JSON response: {exc}"}

    if completed.returncode != 0:
        return {"success": False, "error": f"{failed}: {embedder_reason(completed)}"}

    if not isinstance(reply, dict):
        logger.warning(f"[lane] {label} reply was not an object: {type(reply).__name__}")
        return {"success": False, "error": f"{label} reply was not an object"}
    json_handler.log_operation(
        "subprocess_lane",
        {"label": label, "success": bool(reply.get("success")), "count": reply.get("count")},
        module_name="lane",
    )
    return reply
