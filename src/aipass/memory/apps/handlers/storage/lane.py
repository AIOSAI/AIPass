# =================== AIPass ====================
# Name: lane.py
# Description: The memory interpreter and the JSON-over-stdin subprocess lane every ML handler shares
# Version: 1.0.0
# Created: 2026-10-23
# Modified: 2026-10-23
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
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.storage.chroma_subprocess import embedder_reason

_HANDLERS_DIR = module_file(__file__).parents[1]
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"
EMBED_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "vector" / "embed_subprocess.py"

_MEMORY_ROOT = module_file(__file__).parents[3]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


def memory_python() -> str:
    """The interpreter that owns the ML deps: env override, the memory venv, then ours."""
    override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if override:
        return override
    if _MEMORY_VENV_PYTHON.exists():
        return str(_MEMORY_VENV_PYTHON)
    return sys.executable


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

    if completed.returncode != 0:
        reason = embedder_reason(completed)
        return {"success": False, "error": f"{label} failed (exit {completed.returncode}): {reason}"}

    try:
        reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(f"[lane] Invalid JSON from {label}: {exc}")
        return {"success": False, "error": f"Invalid JSON response: {exc}"}

    if not isinstance(reply, dict):
        return {"success": False, "error": f"{label} reply was not an object"}
    json_handler.log_operation(
        "subprocess_lane",
        {"label": label, "success": bool(reply.get("success")), "count": reply.get("count")},
        module_name="lane",
    )
    return reply
