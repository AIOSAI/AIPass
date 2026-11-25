# =================== AIPass ====================
# Name: chroma_subprocess.py
# Description: ChromaDB Subprocess Handler
# Version: 1.11.0
# Created: 2025-11-27
# Modified: 2026-11-25
# =============================================

"""
ChromaDB Subprocess Handler

Runs in the memory venv (AIPASS_MEMORY_PYTHON): JSON request on stdin, JSON result on stdout.
"""

import sys
import json
import subprocess
import hashlib
from pathlib import Path
from typing import TextIO

_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = _MEMORY_ROOT / ".chroma"

# The store owns the model choice: two models in one collection give silently wrong neighbours.
_EMBED_SCRIPT = Path(__file__).resolve().parent.parent / "vector" / "embed_subprocess.py"

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

    # Content-hash IDs stay idempotent; the source_file salt keeps per-file provenance of shared text.
    ids = []
    for doc, meta in zip(documents, metadatas):
        salt = meta.get("source_file", "") if isinstance(meta, dict) else ""
        hash_input = f"{salt}:{doc}" if salt else doc
        ids.append(f"{branch}_{memory_type}_{hashlib.sha256(hash_input.encode()).hexdigest()[:16]}")

    embeddings_list = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    # ChromaDB rejects non-unique IDs within one upsert call.
    seen = {}
    for i, doc_id in enumerate(ids):
        seen[doc_id] = i
    if len(seen) < len(ids):
        unique_indices = sorted(seen.values())
        ids = [ids[i] for i in unique_indices]
        embeddings_list = [embeddings_list[i] for i in unique_indices]
        documents = [documents[i] for i in unique_indices]
        metadatas = [metadatas[i] for i in unique_indices]

    collection.upsert(embeddings=embeddings_list, documents=documents, metadatas=metadatas, ids=ids)

    new_count = collection.count()

    return {
        "success": True,
        "collection": collection_name,
        "count": len(embeddings),
        "total_vectors": new_count,
        "ids": ids,
    }


def embedder_reason(completed) -> str:
    """The reason a failed embed run gave: its JSON refusal on stdout first, then stderr.

    Every caller of embed_subprocess.py reads its refusal through this one function.
    """
    stderr = (completed.stderr or "").strip() or "empty"
    if not (completed.stdout or "").strip():
        return f"no JSON reply on stdout (it was empty); stderr: {stderr}"
    try:
        reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return f"no JSON reply on stdout ({exc}); stderr: {stderr}"
    if isinstance(reply, dict) and reply.get("error"):
        return str(reply["error"])
    return (completed.stderr or "").strip() or "no reason given"


def _vectorize_and_store(branch, memory_type, texts, metadatas, db_path=None):
    """Encode raw texts and store them -- the text-in entry point.

    Every failure returns success=False with a reason: callers delete their originals on this answer.
    """
    if not branch or not memory_type:
        return {"success": False, "error": "branch and memory_type are required"}

    texts = texts or []
    metadatas = metadatas or []

    if not texts:
        return {"success": True, "count": 0, "message": "No texts to store"}

    # zip() in the store path would truncate a mismatch and hand a row someone else's provenance.
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
    except subprocess.TimeoutExpired as e:
        return {"success": False, "error": f"Embedding timed out after {timeout}s: {e}"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"success": False, "error": f"Embedding subprocess failed: {e}"}

    if completed.returncode != 0:
        return {
            "success": False,
            "error": f"Embedding failed (exit {completed.returncode}): {embedder_reason(completed)}",
        }

    try:
        embed_reply = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # Unreadable output is not evidence of success.
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


def _count_vectors(collection_name, db_path=None):
    """How many vectors one collection holds; 0 for a collection that does not exist."""
    client = _get_client(db_path)
    if collection_name not in [col.name for col in client.list_collections()]:
        return {"success": True, "count": 0, "exists": False}
    return {"success": True, "count": client.get_collection(name=collection_name).count(), "exists": True}


def _source_matches(source, pattern):
    """Whether pattern occurs in source at a non-alphanumeric boundary (DPLAN-0012 must not match TDPLAN-0012)."""
    if not source or not pattern:
        return False

    idx = source.find(pattern)
    while idx != -1:
        # Keep scanning: the label may recur at a real boundary ("TDPLAN-0012_supersedes_DPLAN-0012").
        if idx == 0 or not source[idx - 1].isalnum():
            return True
        idx = source.find(pattern, idx + 1)

    return False


def _check_plan(plan_label, db_path=None):
    """Check if a plan has been vectorized in ChromaDB."""
    client = _get_client(db_path)

    from chromadb.errors import NotFoundError

    collection_name = "flow_plans"
    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except NotFoundError as e:
        return {
            "success": True,
            "found": False,
            "count": 0,
            "source_files": [],
            "message": f"Collection {collection_name} does not exist: {e}",
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


def _owner(collection) -> dict:
    """The branch and type the collection was created with: its name cannot be split (ai_mail_email_sent)."""
    meta = collection.metadata or {}
    return {"branch": str(meta.get("branch", "")).lower(), "type": str(meta.get("type", ""))}


def _get_by_source(collection_name, source_pattern, n_results=5, db_path=None):
    """Fetch documents whose source_file metadata contains a pattern."""
    client = _get_client(db_path)

    from chromadb.errors import NotFoundError

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except NotFoundError as e:
        # A store nothing has written plans to yet is a state, the answer _count_vectors gives too.
        return {"success": True, "results": [], "count": 0, "exists": False, "message": str(e)}

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
                    **_owner(collection),
                }
            )
            if len(matches) >= n_results:
                break

    return {"success": True, "results": matches, "count": len(matches)}


def _delete_by_source(collection_name, source_pattern, db_path=None):
    """Delete vectors whose source_file metadata contains a pattern."""
    client = _get_client(db_path)

    from chromadb.errors import NotFoundError

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except NotFoundError as e:
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
    """Fetch documents by their exact IDs -- the read-back behind verification; missing IDs are absent.

    ``get_by_source`` cannot verify: it matches a substring and caps at n_results.
    """
    client = _get_client(db_path)

    from chromadb.errors import NotFoundError

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except NotFoundError as e:
        return {"success": False, "error": f"Collection '{collection_name}' not found: {e}"}

    ids = list(ids or [])
    if not ids:
        return {"success": True, "documents": {}, "count": 0}

    result = collection.get(ids=ids, include=["documents"])
    documents = {}
    for i, found_id in enumerate(result.get("ids", [])):
        documents[found_id] = result["documents"][i]

    return {"success": True, "documents": documents, "count": len(documents)}


_BATCH = 1000  # under Chroma's max batch size for one get/add call


def _read_collection(collection_name, db_path=None):
    """Every row of one collection as stored, embeddings included; an absent collection answers ``exists: False``."""
    client = _get_client(db_path)

    from chromadb.errors import NotFoundError

    try:
        collection = client.get_collection(collection_name, embedding_function=None)
    except NotFoundError as e:
        empty = {"ids": [], "embeddings": [], "documents": [], "metadatas": []}
        return {"success": True, "exists": False, "message": str(e), **empty}

    result = collection.get(include=["embeddings", "documents", "metadatas"])
    return {
        "success": True,
        "exists": True,
        "metadata": collection.metadata,
        "ids": list(result["ids"]),
        "embeddings": [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in result["embeddings"]],
        "documents": list(result["documents"]),
        "metadatas": list(result["metadatas"]),
    }


def _add_missing(collection_name, ids, embeddings, documents, metadatas, metadata=None, db_path=None):
    """Add, exactly as given, the rows whose ids the collection lacks; a present id is counted and never touched."""
    client = _get_client(db_path)
    collection = client.get_or_create_collection(
        name=collection_name, metadata=metadata or {"hnsw:space": "cosine"}, embedding_function=None
    )

    ids = list(ids or [])
    present = set()
    for start in range(0, len(ids), _BATCH):
        present.update(collection.get(ids=ids[start : start + _BATCH], include=[])["ids"])
    missing = [i for i, doc_id in enumerate(ids) if doc_id not in present]
    for start in range(0, len(missing), _BATCH):
        batch = missing[start : start + _BATCH]
        collection.add(
            ids=[ids[i] for i in batch],
            embeddings=[embeddings[i] for i in batch],
            documents=[documents[i] for i in batch],
            metadatas=[metadatas[i] for i in batch],
        )
    return {"success": True, "collection": collection_name, "added": len(missing), "present": len(present)}


def _merge_collection(source, target, db_path=None):
    """Move every row of *source* into *target* as stored; *source* is dropped only once all its ids read back there."""
    rows = _read_collection(source, db_path=db_path)
    if not rows["exists"]:
        return {"success": True, "exists": False, "source": source, "target": target, "moved": 0}
    copied = _add_missing(
        target,
        rows["ids"],
        rows["embeddings"],
        rows["documents"],
        rows["metadatas"],
        metadata=rows["metadata"],
        db_path=db_path,
    )
    client = _get_client(db_path)
    landed = client.get_collection(target, embedding_function=None)
    present = set()
    for start in range(0, len(rows["ids"]), _BATCH):
        present.update(landed.get(ids=rows["ids"][start : start + _BATCH], include=[])["ids"])
    lost = len(rows["ids"]) - len(present)
    if lost:
        return {"success": False, "error": f"{lost} of {len(rows['ids'])} {source} ids not in {target} - {source} kept"}
    client.delete_collection(source)
    return {
        "success": True,
        "exists": True,
        "source": source,
        "target": target,
        "moved": copied["added"],
        "already_there": copied["present"],
        "target_count": landed.count(),
    }


# Every archive that rolls over owns a "<name>_local" or "<name>_observations" collection.
_OWNER_SUFFIXES = ("_local", "_observations")


def _branch_collections(collection_names, branch):
    """The collections a --branch filter owns, bounded by the owners in the store.

    "<branch>_" is not a boundary (aipass_site_local starts with "aipass_"): a longer owner's names are dropped.
    """
    prefix = f"{branch.lower()}_"
    owners = {name[: -len(suffix)] for name in collection_names for suffix in _OWNER_SUFFIXES if name.endswith(suffix)}
    longer = [owner for owner in owners if owner.startswith(prefix)]
    return [
        name
        for name in collection_names
        if name.startswith(prefix) and not any(name.startswith(f"{owner}_") for owner in longer)
    ]


def _search_vectors(query_embedding, branch=None, memory_type=None, n_results=5, db_path=None, owner=None):
    """Search for similar vectors; ``owner`` reads only that citizen's rows of a shared store (its own collections
    and the ``flow_plans`` chunks tagged with its branch)."""
    client = _get_client(db_path)

    if owner:
        names = [col.name for col in client.list_collections()]
        collection_names = _branch_collections(names, owner) + [c for c in names if c == "flow_plans"]
    elif branch and memory_type:
        collection_names = [f"{branch.lower()}_{memory_type.lower()}"]
    else:
        all_collections = client.list_collections()
        collection_names = [col.name for col in all_collections]
        if branch:
            collection_names = _branch_collections(collection_names, branch)
        if memory_type:
            collection_names = [c for c in collection_names if c.endswith(memory_type.lower())]

    if not collection_names:
        return {"success": True, "results": [], "message": "No matching collections"}

    all_results = []
    failed = []
    for cname in collection_names:
        try:
            collection = client.get_collection(cname, embedding_function=None)
            mine = {"where": {"branch": owner}} if owner and cname == "flow_plans" else {}
            results = collection.query(query_embeddings=[query_embedding], n_results=n_results, **mine)
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    all_results.append(
                        {
                            "collection": cname,
                            "document": doc,
                            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                            "distance": results["distances"][0][i] if results["distances"] else None,
                            "id": results["ids"][0][i] if results["ids"] else None,
                            **_owner(collection),
                        }
                    )
        except Exception as e:
            failed.append({"collection": cname, "error": f"{type(e).__name__}: {e}"})

    # A collection that raised was not searched; if none could be, the search did not run.
    if len(failed) == len(collection_names):
        names = ", ".join(f["collection"] for f in failed)
        return {"success": False, "error": f"Every collection failed: {names}", "collections_failed": failed}

    all_results.sort(key=lambda x: x["distance"] if x["distance"] is not None else float("inf"))

    return {
        "success": True,
        "results": all_results,
        "collections_searched": len(collection_names) - len(failed),
        "collections_failed": failed,
        "total_results": len(all_results),
    }


def main(stdin: TextIO | None = None):
    """Process ChromaDB operation from stdin JSON (``stdin`` is a test seam; products pass None)."""
    try:
        input_data = json.load(sys.stdin if stdin is None else stdin)
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
        elif operation == "count_vectors":
            result = _count_vectors(input_data.get("collection_name"), db_path=input_data.get("db_path"))
        elif operation == "search_vectors":
            result = _search_vectors(
                query_embedding=input_data.get("query_embedding"),
                branch=input_data.get("branch"),
                memory_type=input_data.get("memory_type"),
                n_results=input_data.get("n_results", 5),
                db_path=input_data.get("db_path"),
                owner=input_data.get("owner"),
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
        elif operation == "read_collection":
            result = _read_collection(input_data.get("collection_name"), db_path=input_data.get("db_path"))
        elif operation == "add_missing":
            result = _add_missing(
                collection_name=input_data.get("collection_name"),
                ids=input_data.get("ids"),
                embeddings=input_data.get("embeddings"),
                documents=input_data.get("documents"),
                metadatas=input_data.get("metadatas"),
                metadata=input_data.get("metadata"),
                db_path=input_data.get("db_path"),
            )
        elif operation == "merge_collection":
            result = _merge_collection(
                input_data.get("source"), input_data.get("target"), db_path=input_data.get("db_path")
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
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
