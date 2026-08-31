# =================== AIPass ====================
# Name: chroma_subprocess.py
# Description: ChromaDB Subprocess Handler
# Version: 1.5.0
# Created: 2025-11-27
# Modified: 2026-08-23
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
import subprocess
import logging
import hashlib
from pathlib import Path
from aipass.memory.apps.handlers.repo_root import module_file

logger = logging.getLogger(__name__)


# =============================================================================
# CHROMADB OPERATIONS (inline — no aipass imports)
# =============================================================================

# Default global chroma path: memory/.chroma
_MEMORY_ROOT = module_file(__file__).parents[3]
_DEFAULT_DB_PATH = _MEMORY_ROOT / ".chroma"

# Sibling embedder script -- same venv, invoked by path. Encoding lives behind
# this handler on purpose: a caller that picks its own embedding model can put
# vectors from two models in one collection, which fails silently rather than
# loudly (no error, just wrong neighbours). The store owns the model choice.
_EMBED_SCRIPT = module_file(__file__).parent.parent / "vector" / "embed_subprocess.py"

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

    # Content-hash IDs — idempotent across runs.  When metadata carries
    # source_file (e.g. plans intake), salt the hash so identical boilerplate
    # from different files gets distinct IDs and per-file provenance survives.
    ids = []
    for doc, meta in zip(documents, metadatas):
        salt = meta.get("source_file", "") if isinstance(meta, dict) else ""
        hash_input = f"{salt}:{doc}" if salt else doc
        ids.append(f"{branch}_{memory_type}_{hashlib.sha256(hash_input.encode()).hexdigest()[:16]}")

    # Chroma expects lists, not numpy arrays
    embeddings_list = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    # Safety net: deduplicate within batch — ChromaDB rejects non-unique IDs
    # in a single upsert call.
    seen = {}
    for i, doc_id in enumerate(ids):
        seen[doc_id] = i
    if len(seen) < len(ids):
        unique_indices = sorted(seen.values())
        ids = [ids[i] for i in unique_indices]
        embeddings_list = [embeddings_list[i] for i in unique_indices]
        documents = [documents[i] for i in unique_indices]
        metadatas = [metadatas[i] for i in unique_indices]

    # Upsert: idempotent — same content gets same ID, no duplicates
    collection.upsert(embeddings=embeddings_list, documents=documents, metadatas=metadatas, ids=ids)

    new_count = collection.count()

    return {
        "success": True,
        "collection": collection_name,
        "count": len(embeddings),
        "total_vectors": new_count,
        "ids": ids,
    }


def _vectorize_and_store(branch, memory_type, texts, metadatas, db_path=None):
    """Encode raw texts and store them -- the text-in entry point.

    Callers send text and get a verdict; they never pick an embedding model.
    Every failure returns success=False with a reason: a caller that deletes its
    originals on the strength of this answer must be able to trust it.

    Args:
        branch: Owning branch name (e.g. "AI_MAIL")
        memory_type: Collection suffix (e.g. "email_sent")
        texts: Raw strings to encode and store
        metadatas: One metadata dict per text, same order
        db_path: Optional path to Chroma database

    Returns:
        Dict with success, collection, count -- or success=False and an error
    """
    if not branch or not memory_type:
        return {"success": False, "error": "branch and memory_type are required"}

    texts = texts or []
    metadatas = metadatas or []

    if not texts:
        return {"success": True, "count": 0, "message": "No texts to store"}

    # zip() in the store path would truncate a mismatch silently and hand a row
    # someone else's provenance. Refuse instead.
    if len(metadatas) != len(texts):
        return {"success": False, "error": f"metadatas ({len(metadatas)}) does not match texts ({len(texts)})"}

    timeout = max(30, len(texts) * 3)
    try:
        completed = subprocess.run(
            [sys.executable, str(_EMBED_SCRIPT)],
            input=json.dumps({"texts": texts}),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[chroma_subprocess] Embedding timed out after {timeout}s for {len(texts)} texts")
        return {"success": False, "error": f"Embedding timed out after {timeout}s"}
    except Exception as e:
        logger.warning(f"[chroma_subprocess] Embed subprocess failed: {e}")
        return {"success": False, "error": f"Embedding subprocess failed: {e}"}

    if completed.returncode != 0:
        return {"success": False, "error": completed.stderr or "Embedding failed"}

    try:
        embed_reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Unreadable output is not evidence of success.
        logger.warning(f"[chroma_subprocess] Unreadable embedder reply: {e}")
        return {"success": False, "error": f"Unreadable embedder reply: {e}"}

    if not isinstance(embed_reply, dict) or not embed_reply.get("success"):
        error = embed_reply.get("error") if isinstance(embed_reply, dict) else None
        return {"success": False, "error": str(error or "Embedding refused without a reason")}

    embeddings = embed_reply.get("embeddings") or []
    if len(embeddings) != len(texts):
        return {"success": False, "error": f"embeddings ({len(embeddings)}) does not match texts ({len(texts)})"}

    return _store_vectors(
        branch=branch,
        memory_type=memory_type,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
        db_path=db_path,
    )


def _list_collections(db_path=None):
    """List all collections."""
    client = _get_client(db_path)
    collections = client.list_collections()
    names = [col.name for col in collections]
    return {"success": True, "collections": names, "count": len(names)}


def _source_matches(source, pattern):
    """Whether pattern occurs in source at a non-alphanumeric boundary.

    A plain `pattern in source` test lets a label match inside a longer one --
    DPLAN-0012 answers to a TDPLAN-0012 filename, so verification miscounts and
    the search pin promotes the wrong plan. A hit only counts when the label
    starts the string or follows a non-alphanumeric character.

    Args:
        source: The source_file value from a chunk's metadata
        pattern: The label to look for (e.g. "DPLAN-0012")

    Returns:
        True if pattern occurs at a boundary in source
    """
    if not source or not pattern:
        return False

    idx = source.find(pattern)
    while idx != -1:
        # Keep scanning past a rejected hit: the same source may carry the
        # label again at a real boundary ("TDPLAN-0012_supersedes_DPLAN-0012").
        if idx == 0 or not source[idx - 1].isalnum():
            return True
        idx = source.find(pattern, idx + 1)

    return False


def _check_plan(plan_label, db_path=None):
    """Check if a plan has been vectorized in ChromaDB.

    Args:
        plan_label: Plan label to search for (e.g., "FPLAN-0126")
        db_path: Optional path to Chroma database

    Returns:
        Dict with found status, count of matching chunks, and source files
    """
    client = _get_client(db_path)

    collection_name = "flow_plans"
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
        if _source_matches(source_file, plan_label):
            match_count += 1
            matching_files.add(source_file)

    return {"success": True, "found": match_count > 0, "count": match_count, "source_files": sorted(matching_files)}


def _get_by_source(collection_name, source_pattern, n_results=5, db_path=None):
    """Fetch documents whose source_file metadata contains a pattern.

    Args:
        collection_name: Name of the ChromaDB collection
        source_pattern: Label to match at a boundary in source_file metadata
        n_results: Maximum number of results to return
        db_path: Optional path to Chroma database

    Returns:
        Dict with success, results list (document, metadata, id)
    """
    client = _get_client(db_path)

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except Exception as e:
        logger.warning(f"[chroma_subprocess] Collection '{collection_name}' not found in get_by_source: {e}")
        return {"success": False, "error": f"Collection '{collection_name}' not found: {e}"}

    result = collection.get(include=["metadatas", "documents"])
    matches = []
    for i, meta in enumerate(result.get("metadatas", [])):
        source = meta.get("source_file", "")
        if _source_matches(source, source_pattern):
            matches.append(
                {
                    "collection": collection_name,
                    "document": result["documents"][i],
                    "metadata": meta,
                    "id": result["ids"][i],
                    "distance": 0.0,
                }
            )
            if len(matches) >= n_results:
                break

    return {"success": True, "results": matches, "count": len(matches)}


def _delete_by_source(collection_name, source_pattern, db_path=None):
    """Delete vectors whose source_file metadata contains a pattern.

    Args:
        collection_name: Name of the ChromaDB collection
        source_pattern: Label to match at a boundary in source_file metadata
        db_path: Optional path to Chroma database

    Returns:
        Dict with success, deleted count, and matched IDs
    """
    client = _get_client(db_path)

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except Exception as e:
        logger.warning(f"[chroma_subprocess] Collection '{collection_name}' not found in delete_by_source: {e}")
        return {"success": False, "error": f"Collection '{collection_name}' not found: {e}"}

    result = collection.get(include=["metadatas"])
    ids_to_delete = []
    for i, meta in enumerate(result.get("metadatas", [])):
        source = meta.get("source_file", "")
        if _source_matches(source, source_pattern):
            ids_to_delete.append(result["ids"][i])

    if not ids_to_delete:
        return {"success": True, "deleted": 0, "ids": [], "message": "No matching vectors found"}

    collection.delete(ids=ids_to_delete)
    return {"success": True, "deleted": len(ids_to_delete), "ids": ids_to_delete}


def _get_by_ids(collection_name, ids, db_path=None):
    """Fetch documents by their exact IDs -- the read-back behind verification.

    Exists so a caller that is about to DELETE its originals can prove the copy
    landed instead of trusting the writer's own success flag. ``get_by_source``
    could not serve that role: it matches on a metadata substring and caps at
    n_results, so a partial hit reads like a full one.

    Args:
        collection_name: Name of the ChromaDB collection
        ids: Exact vector IDs to fetch
        db_path: Optional path to Chroma database

    Returns:
        Dict with success and a documents map {id: document}. Missing IDs are
        simply absent from the map -- the caller decides what that means.
    """
    client = _get_client(db_path)

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except Exception as e:
        logger.warning(f"[chroma_subprocess] Collection '{collection_name}' not found in get_by_ids: {e}")
        return {"success": False, "error": f"Collection '{collection_name}' not found: {e}"}

    ids = list(ids or [])
    if not ids:
        return {"success": True, "documents": {}, "count": 0}

    result = collection.get(ids=ids, include=["documents"])
    documents = {}
    for i, found_id in enumerate(result.get("ids", [])):
        documents[found_id] = result["documents"][i]

    return {"success": True, "documents": documents, "count": len(documents)}


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
        elif operation == "vectorize_and_store":
            result = _vectorize_and_store(
                branch=input_data.get("branch"),
                memory_type=input_data.get("memory_type"),
                texts=input_data.get("texts"),
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
        elif operation == "get_by_source":
            result = _get_by_source(
                collection_name=input_data.get("collection_name"),
                source_pattern=input_data.get("source_pattern"),
                n_results=input_data.get("n_results", 5),
                db_path=input_data.get("db_path"),
            )
        elif operation == "get_by_ids":
            result = _get_by_ids(
                collection_name=input_data.get("collection_name"),
                ids=input_data.get("ids"),
                db_path=input_data.get("db_path"),
            )
        elif operation == "delete_by_source":
            result = _delete_by_source(
                collection_name=input_data.get("collection_name"),
                source_pattern=input_data.get("source_pattern"),
                db_path=input_data.get("db_path"),
            )
        else:
            result = {"success": False, "error": f"Unknown operation: {operation}"}

        print(json.dumps(result))

    except Exception as e:
        logger.error(f"[chroma_subprocess] Subprocess operation failed: {e}")
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
