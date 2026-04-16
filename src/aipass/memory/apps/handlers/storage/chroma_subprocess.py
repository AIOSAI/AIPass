# =================== AIPass ====================
# Name: chroma_subprocess.py
# Description: ChromaDB Subprocess Handler
# Version: 1.2.0
# Created: 2025-11-27
# Modified: 2026-03-12
# =============================================

"""
ChromaDB Subprocess Handler

Called via subprocess from rollover orchestrator to ensure ChromaDB operations
run in the memory-specific venv (AIPASS_MEMORY_PYTHON).

Self-contained — does NOT import from aipass package (not available in memory venv).

Input: JSON on stdin with operation and parameters
Output: JSON on stdout with result
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# CHROMADB OPERATIONS (inline — no aipass imports)
# =============================================================================

# Default global chroma path: memory/.chroma
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = _MEMORY_ROOT / ".chroma"

# Singleton clients per path
_clients = {}


def _get_client(db_path=None):
    """Get or create ChromaDB PersistentClient."""
    import chromadb

    if db_path is None:
        db_path = _DEFAULT_DB_PATH

    db_path = Path(db_path)
    path_str = str(db_path)

    if path_str not in _clients:
        db_path.mkdir(parents=True, exist_ok=True)
        _clients[path_str] = chromadb.PersistentClient(path=path_str)

    return _clients[path_str]


def _store_vectors(branch, memory_type, embeddings, documents, metadatas, db_path=None):
    """Store vectors in branch-specific collection."""
    client = _get_client(db_path)

    collection_name = f"{branch.lower()}_{memory_type.lower()}"
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine", "branch": branch, "type": memory_type},
        embedding_function=None,
    )

    existing_count = collection.count()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ids = [f"{branch}_{memory_type}_{existing_count + i}_{timestamp}" for i in range(len(embeddings))]

    # Chroma expects lists, not numpy arrays
    embeddings_list = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    collection.add(embeddings=embeddings_list, documents=documents, metadatas=metadatas, ids=ids)

    new_count = collection.count()

    return {
        "success": True,
        "collection": collection_name,
        "count": len(embeddings),
        "total_vectors": new_count,
        "ids": ids,
    }


def _list_collections(db_path=None):
    """List all collections."""
    client = _get_client(db_path)
    collections = client.list_collections()
    names = [col.name for col in collections]
    return {"success": True, "collections": names, "count": len(names)}


def _check_plan(plan_label, db_path=None):
    """Check if a plan has been vectorized in ChromaDB.

    Args:
        plan_label: Plan label to search for (e.g., "FPLAN-0126")
        db_path: Optional path to Chroma database

    Returns:
        Dict with found status, count of matching chunks, and source files
    """
    client = _get_client(db_path)

    collection_name = "flow_flow_plans"
    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except Exception as e:
        logger.warning(f"[chroma_subprocess] Collection '{collection_name}' not found during plan check: {e}")
        return {
            "success": True,
            "found": False,
            "count": 0,
            "source_files": [],
            "message": f"Collection {collection_name} does not exist",
        }

    result = collection.get(include=["metadatas"])
    metadatas = result.get("metadatas", [])

    matching_files = set()
    match_count = 0
    for metadata in metadatas:
        source_file = metadata.get("source_file", "")
        if plan_label in source_file:
            match_count += 1
            matching_files.add(source_file)

    return {"success": True, "found": match_count > 0, "count": match_count, "source_files": sorted(matching_files)}


def _search_vectors(query_embedding, branch=None, memory_type=None, n_results=5, db_path=None):
    """Search for similar vectors."""
    client = _get_client(db_path)

    # Determine which collections to search
    if branch and memory_type:
        collection_names = [f"{branch.lower()}_{memory_type.lower()}"]
    else:
        all_collections = client.list_collections()
        collection_names = [col.name for col in all_collections]
        if branch:
            collection_names = [c for c in collection_names if c.startswith(branch.lower())]
        if memory_type:
            collection_names = [c for c in collection_names if c.endswith(memory_type.lower())]

    if not collection_names:
        return {"success": True, "results": [], "message": "No matching collections"}

    all_results = []
    for cname in collection_names:
        try:
            collection = client.get_collection(cname, embedding_function=None)
            results = collection.query(query_embeddings=[query_embedding], n_results=n_results)
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    all_results.append(
                        {
                            "collection": cname,
                            "document": doc,
                            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                            "distance": results["distances"][0][i] if results["distances"] else None,
                            "id": results["ids"][0][i] if results["ids"] else None,
                        }
                    )
        except Exception as e:
            logger.warning(f"[chroma_subprocess] Skipping collection '{cname}' during search: {e}")
            continue

    all_results.sort(key=lambda x: x["distance"] if x["distance"] is not None else float("inf"))

    return {
        "success": True,
        "results": all_results,
        "collections_searched": len(collection_names),
        "total_results": len(all_results),
    }


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Process ChromaDB operation from stdin JSON."""
    try:
        input_data = json.load(sys.stdin)
        operation = input_data.get("operation")

        if operation == "store_vectors":
            result = _store_vectors(
                branch=input_data.get("branch"),
                memory_type=input_data.get("memory_type"),
                embeddings=input_data.get("embeddings"),
                documents=input_data.get("documents"),
                metadatas=input_data.get("metadatas"),
                db_path=input_data.get("db_path"),
            )
        elif operation == "list_collections":
            result = _list_collections(db_path=input_data.get("db_path"))
        elif operation == "search_vectors":
            result = _search_vectors(
                query_embedding=input_data.get("query_embedding"),
                branch=input_data.get("branch"),
                memory_type=input_data.get("memory_type"),
                n_results=input_data.get("n_results", 5),
                db_path=input_data.get("db_path"),
            )
        elif operation == "check_plan":
            result = _check_plan(plan_label=input_data.get("plan_label"), db_path=input_data.get("db_path"))
        else:
            result = {"success": False, "error": f"Unknown operation: {operation}"}

        print(json.dumps(result))

    except Exception as e:
        logger.error(f"[chroma_subprocess] Subprocess operation failed: {e}")
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
