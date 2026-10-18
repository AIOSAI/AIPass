# =================== AIPass ====================
# Name: central_writer.py
# Description: Central File Writer Handler
# Version: 0.3.0
# Created: 2025-11-27
# Modified: 2026-10-17
# =============================================

"""
Central File Writer Handler

MEMORY.central.json is memory's API output; dashboards read it.
"""

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
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    Kept as a local name because callers and tests patch it here.
    """
    return repo_root.find_repo_root(caller="central_writer")


CENTRAL_FILE = _find_repo_root() / ".ai_central" / "MEMORY.central.json"
CHROMA_DB_PATH = _MEMORY_ROOT / ".chroma"
ARCHIVE_DIR = _MEMORY_ROOT / ".archive"


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


def count_archive_files() -> int:
    """Count total archive files in .archive directory"""
    try:
        if not ARCHIVE_DIR.exists():
            return 0

        archive_files = list(ARCHIVE_DIR.glob("*.md"))
        return len(archive_files)

    except Exception as e:
        logger.error(f"[central_writer] Failed to count archive files: {e}")
        raise Exception(f"Failed to count archive files: {e}")


def get_last_rollover_timestamp() -> str:
    """Get timestamp of last rollover operation"""
    try:
        if not ARCHIVE_DIR.exists():
            return ""

        archive_files = list(ARCHIVE_DIR.glob("*.md"))
        if not archive_files:
            return ""

        latest = max(archive_files, key=lambda f: f.stat().st_mtime)
        mtime = datetime.fromtimestamp(latest.stat().st_mtime)

        return mtime.isoformat()

    except Exception as e:
        logger.error(f"[central_writer] Failed to get rollover timestamp: {e}")
        raise Exception(f"Failed to get rollover timestamp: {e}")


def collect_stats() -> Dict[str, Any]:
    """Collect all memory statistics"""
    return {
        "total_vectors": count_chroma_vectors(),
        "total_archives": count_archive_files(),
        "last_rollover": get_last_rollover_timestamp(),
    }


def read_central_file() -> Dict[str, Any]:
    """Read current central file contents"""
    try:
        if not CENTRAL_FILE.exists():
            return {
                "service": "memory",
                "last_updated": "",
                "stats": {"total_vectors": 0, "total_archives": 0, "last_rollover": ""},
            }

        with open(CENTRAL_FILE, "r", encoding="utf-8") as f:
            return json_load(f)

    except Exception as e:
        logger.error(f"[central_writer] Failed to read central file: {e}")
        raise Exception(f"Failed to read central file: {e}")


def write_central_file(data: Dict[str, Any]) -> None:
    """Write data to central file"""
    try:
        CENTRAL_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(CENTRAL_FILE, "w", encoding="utf-8") as f:
            json_dump(data, f, indent=2, ensure_ascii=False)

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


def get_current_stats() -> Dict[str, Any]:
    """Get current memory statistics without writing to file"""
    try:
        stats = collect_stats()
        return {"success": True, **stats}

    except Exception as e:
        logger.warning(f"[central_writer] Failed to get current stats: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("\n=== Memory Central Writer ===\n")

    print("Collecting statistics...")
    stats_result = get_current_stats()

    if stats_result["success"]:
        print(f"  Total Vectors: {stats_result.get('total_vectors', 0)}")
        print(f"  Total Archives: {stats_result.get('total_archives', 0)}")
        print(f"  Last Rollover: {stats_result.get('last_rollover', 'Never')}")
    else:
        print(f"Error collecting stats: {stats_result.get('error')}")

    print()

    print("Updating central file...")
    result = update_central(verbose=True)

    if result["success"]:
        print(f"Updated: {result['updated']}")
        if "stats" in result:
            print(f"  Vectors: {result['stats']['total_vectors']}")
            print(f"  Archives: {result['stats']['total_archives']}")
    else:
        print(f"Update failed: {result.get('error')}")

    print()
