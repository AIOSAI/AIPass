# =================== AIPass ====================
# Name: query_executor.py
# Description: Search Query Execution Handler
# Version: 1.3.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Search Query Execution Handler
"""

import re
from pathlib import Path
from typing import Dict, Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, EMBED_SUBPROCESS_SCRIPT, run_json

MIN_SIMILARITY_THRESHOLD = 0.40


def encode_query_subprocess(query: str) -> dict:
    """Encode query text via subprocess using memory venv's fastembed."""
    data = run_json(EMBED_SUBPROCESS_SCRIPT, {"texts": [query]}, timeout=120, label="Embedding")
    if not data.get("success"):
        return data

    embeddings = data.get("embeddings", [])
    if not embeddings:
        return {"success": False, "error": "No embedding generated"}

    return {"success": True, "embedding": embeddings[0], "dimension": data.get("dimension", 384)}


def search_vectors_subprocess(
    query_embedding: list,
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5,
    db_path: str | Path | None = None,
) -> dict:
    """Search vectors via subprocess (db_path None means the global store)."""
    input_data = {
        "operation": "search_vectors",
        "query_embedding": query_embedding,
        "branch": branch,
        "memory_type": memory_type,
        "n_results": n_results,
        "db_path": str(db_path) if db_path else None,
    }

    return run_json(CHROMA_SUBPROCESS_SCRIPT, input_data, timeout=60, label="Search operation")


def _calculate_similarity(distance: float) -> float:
    """Similarity 0..1 from ChromaDB cosine distance (0=identical, 2=opposite)."""
    return max(0, 1 - (distance / 2))


def _filter_results(results: list, n_results: int) -> list:
    """Filter search results by similarity threshold and quality."""
    filtered = []
    for result in results[:n_results]:
        document = result.get("document", "")
        distance = result.get("distance", 0)

        similarity = _calculate_similarity(distance)

        if not document or not document.strip():
            continue
        if similarity < MIN_SIMILARITY_THRESHOLD:
            continue

        result["similarity"] = similarity
        filtered.append(result)

    return filtered


_PLAN_ID_RE = re.compile(
    r"(?:^|\b)((?:d|f|p|td|a)plan)[\s\-_]*(\d{3,5})\b",
    re.IGNORECASE,
)


def _extract_plan_id(query: str) -> str | None:
    """Extract a normalized plan ID (e.g. 'FPLAN-0332') from a query string."""
    m = _PLAN_ID_RE.search(query)
    if not m:
        return None
    prefix = m.group(1).upper()
    number = m.group(2)
    return f"{prefix}-{number}"


def _fetch_plan_by_metadata(plan_id: str, n_results: int) -> list | None:
    """Fetch plan chunks by source_file metadata: [] for no match, None (warned) when the store cannot answer."""
    skipped = f"[search] Plan metadata fetch failed for {plan_id}"
    input_data = {
        "operation": "get_by_source",
        "collection_name": "flow_plans",
        "source_pattern": plan_id,
        "n_results": n_results,
    }
    data = run_json(CHROMA_SUBPROCESS_SCRIPT, input_data, timeout=30, label="store")
    if not data.get("success"):
        logger.warning(f"{skipped}: {data.get('error', 'store refused')} — exact-ID pin skipped")
        return None
    return data.get("results", [])


def _pin_plan_id_matches(query: str, filtered: list, n_results: int) -> list:
    """Pin exact plan-ID matches (fetched by metadata, not similarity) to the top of results."""
    plan_id = _extract_plan_id(query)
    if not plan_id:
        return filtered

    exact = _fetch_plan_by_metadata(plan_id, n_results)
    if not exact:
        return filtered

    for r in exact:
        r["similarity"] = 1.0

    logger.info(f"[search] Pinned {len(exact)} exact matches for {plan_id}")

    seen_ids = {r.get("id") for r in exact}
    rest = [r for r in filtered if r.get("id") not in seen_ids]
    return (exact + rest)[:n_results]


def execute_search(
    query: str, branch: str | None = None, memory_type: str | None = None, n_results: int = 5
) -> Dict[str, Any]:
    """Execute semantic search: encode query, search vectors, filter results."""
    embed_result = encode_query_subprocess(query)

    if not embed_result["success"]:
        error_msg = embed_result.get("error", "Unknown error")
        logger.error(f"[search] Failed to encode query: {error_msg}")
        return {
            "success": False,
            "error": f"Failed to encode query: {error_msg}",
            "query": query,
        }

    query_embedding = embed_result["embedding"]
    logger.info(f"[search] Encoded query to {len(query_embedding)}-dim vector")

    search_result = search_vectors_subprocess(
        query_embedding=query_embedding, branch=branch, memory_type=memory_type, n_results=n_results
    )

    if not search_result["success"]:
        error_msg = search_result.get("error", "Unknown error")
        logger.error(f"[search] Search failed: {error_msg}")
        return {
            "success": False,
            "error": f"Search failed: {error_msg}",
            "query": query,
        }

    raw_results = search_result.get("results", [])
    collections_searched = search_result.get("collections_searched", 0)
    total_results = search_result.get("total_results", 0)

    logger.info(f"[search] Found {total_results} results across {collections_searched} collections")

    filtered_results = _filter_results(raw_results, n_results)

    filtered_results = _pin_plan_id_matches(query, filtered_results, n_results)

    logger.info(f"[search] Filtered to {len(filtered_results)} relevant results")

    json_handler.log_operation(
        "search_execute", {"query_len": len(query), "results": len(filtered_results), "success": True}
    )
    return {
        "success": True,
        "query": query,
        "branch": branch,
        "memory_type": memory_type,
        "results": filtered_results,
        "collections_searched": collections_searched,
        "total_results": total_results,
        "filtered_count": len(filtered_results),
    }
