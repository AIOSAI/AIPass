# =================== AIPass ====================
# Name: push_store.py
# Description: Vector-store client for the trinity push — store and read-back, both via subprocess
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Trinity Push Vector Store Client

Two calls, both through ``chroma_subprocess.py`` in the memory venv: one to
store pruned entries, one to read them back by ID.

They live together in their own module for a reason. The push's safety rests
entirely on ``store`` and ``read back`` being INDEPENDENT operations — the
second must not be able to answer from the first's return value. Keeping them
as two separate subprocess round-trips over the real database is what makes
the verification evidence rather than an echo, and a test double that
implements only one of them cannot fake the pair.
"""

import json
import os
import subprocess
import sys

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file

_HANDLERS_DIR = module_file(__file__).parents[1]
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"

_MEMORY_ROOT = module_file(__file__).parents[3]


def _memory_python() -> str:
    """The interpreter that owns the ML deps — env override, venv, then ours."""
    override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if override:
        return override
    venv_python = _MEMORY_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _run(payload: dict, timeout: int) -> dict:
    """Run one chroma operation and return its payload, never an exception.

    An unreadable reply is reported as a failure, never as an empty success:
    the caller is about to delete originals on the strength of this answer.

    Args:
        payload: The operation document handed to the subprocess on stdin.
        timeout: Seconds to wait before giving up on the call.

    Returns:
        The handler's parsed payload, or a ``success: False`` dict naming why.
    """
    try:
        completed = subprocess.run(
            [_memory_python(), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[push_store] {payload.get('operation')} timed out after {timeout}s")
        return {"success": False, "error": f"{payload.get('operation')} timed out after {timeout}s"}
    except OSError as exc:
        logger.warning(f"[push_store] {payload.get('operation')} could not start: {exc}")
        return {"success": False, "error": f"subprocess failed: {exc}"}

    if completed.returncode != 0:
        return {"success": False, "error": completed.stderr or "subprocess failed"}

    try:
        reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"[push_store] Unreadable reply from {payload.get('operation')}: {exc}")
        return {"success": False, "error": f"unreadable reply: {exc}"}

    if not isinstance(reply, dict):
        return {"success": False, "error": "reply was not an object"}

    json_handler.log_operation(
        "push_store_call",
        {"operation": payload.get("operation"), "success": bool(reply.get("success")), "count": reply.get("count")},
        module_name="push_store",
    )
    return reply


def vectorize_and_store_subprocess(
    branch: str,
    memory_type: str,
    texts: list,
    metadatas: list,
    db_path=None,
) -> dict:
    """Embed *texts* and store them in ``<branch>_<memory_type>``.

    Args:
        branch: Owning branch name.
        memory_type: Collection suffix — ``local`` or ``observations``, the
            same collections rollover archives into, so a pushed entry is
            found by the same ``drone @memory search`` the note promises.
        texts: Verbatim entry documents.
        metadatas: One metadata dict per text, same order.
        db_path: Chroma path, or None for the global store.

    Returns:
        The handler's payload, including ``ids`` for the read-back.
    """
    payload = {
        "operation": "vectorize_and_store",
        "branch": branch,
        "memory_type": memory_type,
        "texts": texts,
        "metadatas": metadatas,
        "db_path": str(db_path) if db_path else None,
    }
    return _run(payload, timeout=max(60, len(texts) * 3))


def get_by_ids_subprocess(collection_name: str, ids: list, db_path=None) -> dict:
    """Fetch documents by exact ID — the read-back half of the verification.

    Args:
        collection_name: Collection the vectors were written to.
        ids: Exact IDs to fetch.
        db_path: Chroma path, or None for the global store.

    Returns:
        ``{"success": bool, "documents": {id: document}}``.
    """
    payload = {
        "operation": "get_by_ids",
        "collection_name": collection_name,
        "ids": list(ids),
        "db_path": str(db_path) if db_path else None,
    }
    return _run(payload, timeout=60)
