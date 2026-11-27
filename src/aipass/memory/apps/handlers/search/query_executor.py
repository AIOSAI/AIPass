# =================== AIPass ====================
# Name: query_executor.py
# Description: Search Query Execution Handler
# Version: 1.4.2
# Created: 2026-03-08
# Modified: 2026-11-23
# =============================================

"""
Search Query Execution Handler
"""

import re
from pathlib import Path
from typing import Dict, Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli import caller_gate
from aipass.memory.apps.handlers.rollover import orchestrator, todo_roll
from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, EMBED_SUBPROCESS_SCRIPT, run_json

# The store chroma_subprocess writes when handed no db_path.
_GLOBAL_STORE = (Path(CHROMA_SUBPROCESS_SCRIPT).resolve().parent.parent.parent.parent / ".chroma").resolve()

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
    owner: str | None = None,
) -> dict:
    """Search vectors via subprocess (db_path None means the global store; ``owner`` narrows a shared store)."""
    input_data = {
        "operation": "search_vectors",
        "query_embedding": query_embedding,
        "branch": branch,
        "memory_type": memory_type,
        "n_results": n_results,
        "db_path": str(db_path) if db_path else None,
        "owner": owner,
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


def _fetch_plan_by_metadata(plan_id: str, n_results: int, db_path: Path | None = None) -> list | None:
    """Plan chunks by source_file: [] for no match or no flow_plans yet, None (warned) when the store cannot answer."""
    skipped = f"[search] Plan metadata fetch failed for {plan_id}"
    input_data = {
        "operation": "get_by_source",
        "collection_name": "flow_plans",
        "source_pattern": plan_id,
        "n_results": n_results,
        "db_path": str(db_path) if db_path else None,
    }
    data = run_json(CHROMA_SUBPROCESS_SCRIPT, input_data, timeout=30, label="store")
    if not data.get("success"):
        logger.warning(f"{skipped}: {data.get('error', 'store refused')} — exact-ID pin skipped")
        return None
    if data.get("exists") is False:
        logger.info(f"[search] No flow_plans in {db_path or 'the global store'} yet — no plan to pin for {plan_id}")
    return data.get("results", [])


def _pin_plan_id_matches(
    query: str, filtered: list, n_results: int, db_path: Path | None = None, owner: str | None = None
) -> list:
    """Pin exact plan-ID matches (fetched by metadata, not similarity) to the top; ``owner`` keeps only its own."""
    plan_id = _extract_plan_id(query)
    if not plan_id:
        return filtered

    exact = _fetch_plan_by_metadata(plan_id, n_results, db_path)
    if exact and owner:
        exact = [r for r in exact if (r.get("metadata") or {}).get("branch") == owner]
    if not exact:
        return filtered

    for r in exact:
        r["similarity"] = 1.0

    logger.info(f"[search] Pinned {len(exact)} exact matches for {plan_id}")

    seen_ids = {r.get("id") for r in exact}
    rest = [r for r in filtered if r.get("id") not in seen_ids]
    return (exact + rest)[:n_results]


def caller_local_store() -> Dict[str, Any]:
    """The caller's branch and its local .chroma (which may not exist yet), or the one sentence that refuses.

    The verified-caller rail first, then the branch directory the caller's cwd sits in.
    """
    try:
        caller, _admin = caller_gate.verified_caller()
    except Exception as exc:  # a dark rail is said, never read as "no caller"
        logger.warning(f"[search] Verified-caller rail unavailable: {exc!r}")
        return {"refusal": f"search needs your branch and the verified-caller rail is unavailable ({exc!r})"}
    name = caller.lstrip("@")
    if not name:
        target = todo_roll.resolve_target(None)
        name = target.get("name") or ""
        if not name:
            why = target.get("error") or target.get("reason")
            return {"refusal": f"search reads your own branch's store and no branch resolves here ({why})"}
    db_path, reason = orchestrator.local_store_lookup(name, create=False)
    if db_path is None:
        return {"refusal": f"search reads your own branch's store and @{name} has none in the memory scope ({reason})"}
    # The global store is also @memory's local one: its seat reads only its own rows there.
    owner = name if Path(db_path).resolve() == _GLOBAL_STORE else None
    return {"branch": name, "db_path": db_path, "owner": owner}


def execute_search(
    query: str,
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5,
    db_path: Path | None = None,
    owner: str | None = None,
) -> Dict[str, Any]:
    """Encode, search, filter; ``db_path`` None is the global store, ``owner`` narrows a shared one to its rows."""
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
        query_embedding=query_embedding,
        branch=branch,
        memory_type=memory_type,
        n_results=n_results,
        db_path=db_path,
        owner=owner,
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

    filtered_results = _pin_plan_id_matches(query, filtered_results, n_results, db_path, owner)

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
        "collections_failed": search_result.get("collections_failed", []),
        "total_results": total_results,
        "filtered_count": len(filtered_results),
    }
