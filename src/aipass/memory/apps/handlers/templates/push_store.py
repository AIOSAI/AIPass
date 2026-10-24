# =================== AIPass ====================
# Name: push_store.py
# Description: Vector-store client for the trinity push — store and read-back, both via subprocess
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Trinity Push Vector Store Client

Store and read-back are two INDEPENDENT subprocess round-trips: the read-back must never echo the store's reply.
"""

from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, run_json


def vectorize_and_store_subprocess(
    branch: str,
    memory_type: str,
    texts: list,
    metadatas: list,
    db_path=None,
) -> dict:
    """Embed *texts* and store them in ``<branch>_<memory_type>``, the collections rollover archives into."""
    payload = {
        "operation": "vectorize_and_store",
        "branch": branch,
        "memory_type": memory_type,
        "texts": texts,
        "metadatas": metadatas,
        "db_path": str(db_path) if db_path else None,
    }
    return run_json(CHROMA_SUBPROCESS_SCRIPT, payload, timeout=max(60, len(texts) * 3), label="vectorize_and_store")


def get_by_ids_subprocess(collection_name: str, ids: list, db_path=None) -> dict:
    """Fetch documents by exact ID — the read-back half of the verification."""
    payload = {
        "operation": "get_by_ids",
        "collection_name": collection_name,
        "ids": list(ids),
        "db_path": str(db_path) if db_path else None,
    }
    return run_json(CHROMA_SUBPROCESS_SCRIPT, payload, timeout=60, label="get_by_ids")
