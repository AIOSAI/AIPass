# =================== AIPass ====================
# Name: central_writer.py
# Description: Central File Writer Handler
# Version: 0.4.0
# Created: 2025-11-27
# Modified: 2026-10-23
# =============================================

"""
Central File Writer Handler

MEMORY.central.json is memory's API output; dashboards read it.
"""

import os
from json import load as json_load, dump as json_dump
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from aipass.memory.apps.handlers import repo_root
from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file

logger = get_system_logger()

_MEMORY_ROOT = module_file(__file__).parents[2]


def _find_repo_root() -> Path:
    """Repo root via ``handlers/repo_root.py``; a local name because callers and tests patch it here."""
    return repo_root.find_repo_root(caller="central_writer")


CENTRAL_FILE = _find_repo_root() / ".ai_central" / "MEMORY.central.json"
CHROMA_DB_PATH = _MEMORY_ROOT / ".chroma"


def count_chroma_vectors() -> int:
    """
    Count total vectors across all ChromaDB collections

    Raises sqlite3.Error rather than answer 0: an empty count would publish as success.
    """
    if not CHROMA_DB_PATH.exists():
        return 0

    import sqlite3

    db_file = CHROMA_DB_PATH / "chroma.sqlite3"
    if not db_file.exists():
        return 0

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def collect_stats() -> Dict[str, Any]:
    """Collect all memory statistics"""
    return {"total_vectors": count_chroma_vectors()}


def read_central_file() -> Dict[str, Any]:
    """Read current central file contents"""
    try:
        if not CENTRAL_FILE.exists():
            return {"service": "memory", "last_updated": "", "stats": {"total_vectors": 0}}

        with open(CENTRAL_FILE, "r", encoding="utf-8") as f:
            return json_load(f)

    except Exception as e:
        logger.error(f"[central_writer] Failed to read central file: {e}")
        raise Exception(f"Failed to read central file: {e}")


def write_central_file(data: Dict[str, Any]) -> None:
    """Write data to central file; a reader never sees a half-written one."""
    try:
        CENTRAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CENTRAL_FILE.with_suffix(".tmp")

        with open(tmp, "w", encoding="utf-8") as f:
            json_dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CENTRAL_FILE)

    except Exception as e:
        logger.error(f"[central_writer] Failed to write central file: {e}")
        raise Exception(f"Failed to write central file: {e}")


def update_central(verbose: bool = False) -> Dict[str, Any]:
    """Update memory central.json with current statistics"""
    try:
        stats = collect_stats()

        # Read-modify-write: extra fields others put in the file survive.
        central_data = read_central_file()

        central_data["last_updated"] = datetime.now().isoformat()
        central_data["stats"] = stats

        if "_note" in central_data:
            del central_data["_note"]

        write_central_file(central_data)

        result = {"success": True, "updated": CENTRAL_FILE.as_posix()}

        if verbose:
            result["stats"] = stats

        json_handler.log_operation("update_central", {"vectors": stats.get("total_vectors", 0), "success": True})

        return result

    except Exception as e:
        logger.error(f"[central_writer] Failed to update central: {e}")
        return {"success": False, "error": str(e)}
