# =================== AIPass ====================
# Name: orchestrator.py
# Description: Rollover Orchestration Handler
# Version: 1.4.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Rollover Orchestration Handler

Reference: docs/rollover_pipeline.md
"""

from pathlib import Path
from typing import List, Dict, Any

from aipass.memory.apps.handlers import repo_root, write_fence
from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.monitor.detector import RegistryUnreadable
from aipass.memory.apps.handlers.rollover import extractor
from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, EMBED_SUBPROCESS_SCRIPT, run_json


def _find_repo_root() -> Path:
    """Repo root for this lane; a local name because tests patch it, the body lives in ``repo_root.py``."""
    return repo_root.find_repo_root(caller="orchestrator")


_REPO_ROOT = _find_repo_root()


def store_vectors_subprocess(
    branch: str, memory_type: str, embeddings: list, documents: list, metadatas: list, db_path: str | Path | None = None
) -> dict:
    """Store vectors via subprocess, so ChromaDB works whatever the calling Python; ``db_path=None`` is global."""
    # Fence here: the child that would write the store has not started yet.
    if db_path:
        refusal = write_fence.fence_write(db_path, lane="store_vectors_local")
        if refusal is not None:
            return {"success": False, "error": refusal}

    embeddings_serializable = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    input_data = {
        "operation": "store_vectors",
        "branch": branch,
        "memory_type": memory_type,
        "embeddings": embeddings_serializable,
        "documents": documents,
        "metadatas": metadatas,
        "db_path": str(db_path) if db_path else None,
    }

    return run_json(CHROMA_SUBPROCESS_SCRIPT, input_data, timeout=60, label="Storage operation")


def encode_batch_subprocess(texts: list) -> dict:
    """Encode texts via subprocess using memory venv's fastembed."""
    return run_json(EMBED_SUBPROCESS_SCRIPT, {"texts": texts}, timeout=120, label="Embedding")


# Why a lookup found no local store; the push report names which.
LOCAL_STORE_REGISTRY_UNREADABLE = "registry unreadable"
LOCAL_STORE_ABSENT = "no local store"


def local_store_lookup(branch_name: str) -> tuple[Path | None, str | None]:
    """Find a branch's local .chroma: ``(path, None)`` or ``(None, reason)``.

    Never raises on an unreadable registry: this runs after the file is trimmed,
    and a raise would leave the entries in neither store.
    """
    if not branch_name:
        return None, LOCAL_STORE_ABSENT

    try:
        registry = detector._read_registry()
    except RegistryUnreadable as e:
        logger.error(f"[rollover] No local store for {branch_name}: {e}")
        return None, LOCAL_STORE_REGISTRY_UNREADABLE

    for branch in registry:
        if branch.get("name", "").upper() == branch_name.upper():
            branch_path = Path(branch.get("path", ""))
            if branch_path.exists():
                chroma_path = branch_path / ".chroma"
                # Existing is not permission: the store writes wherever it is handed.
                if write_fence.fence_write(chroma_path, lane="local_chroma") is not None:
                    return None, LOCAL_STORE_ABSENT
                if not chroma_path.exists():
                    chroma_path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"[rollover] Created local .chroma directory for {branch_name}")
                return chroma_path, None

    logger.warning(f"[rollover] Branch {branch_name} not found in registry")
    return None, LOCAL_STORE_ABSENT


def get_branch_local_chroma_path(branch_name: str) -> Path | None:
    """The path ``local_store_lookup`` finds, or None for every reason it gives."""
    return local_store_lookup(branch_name)[0]


def extract_text_from_memories(memories: List[Dict]) -> List[str]:
    """Extract the text of each memory item for vectorization, by whichever shape it has."""
    texts = []

    for memory in memories:
        if "activities" in memory and isinstance(memory["activities"], list):
            text = "\n".join(str(a) for a in memory["activities"])
        elif "summary" in memory:
            text = str(memory["summary"])
        elif "key" in memory and "value" in memory:
            text = f"{memory.get('key', '')}: {memory.get('value', '')}"
        elif "content" in memory:
            text = str(memory["content"])
        elif "text" in memory:
            text = str(memory["text"])
        elif "message" in memory:
            text = str(memory["message"])
        elif "note" in memory:
            text = str(memory["note"])
        else:
            text = str(memory)

        texts.append(text)

    return texts


def execute_rollover() -> Dict[str, Any]:
    """Execute rollover for all triggered branches: extract, embed, store local + global, then trim the file.

    The live file is written LAST. A failure anywhere before leaves it whole, so nothing needs restoring.
    """
    triggers_result = detector.check_all_branches()

    if not triggers_result["success"]:
        error = triggers_result.get("error", "Unknown error")
        logger.error(f"[rollover] Failed to check branches: {error}")
        return {
            "success": False,
            "error": f"Failed to check for rollover triggers: {error}",
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "skipped": [],
        }

    triggers = triggers_result.get("triggers", [])
    # Over a limit no run can drain (a dict container): not triggers, but carried on
    # every return so the caller can say so.
    undrainable = [str(item) for item in triggers_result.get("undrainable", [])]
    if not triggers:
        logger.info("[rollover] No rollover triggers detected")
        return {
            "success": True,
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "skipped": [],
            "results": [],
            "undrainable": undrainable,
        }

    logger.info(f"[rollover] Found {len(triggers)} files ready for rollover")

    success_count = 0
    failed = []
    skipped = []
    results = []

    for trigger in triggers:
        extract_result = extractor.extract_with_metadata(trigger.file_path)

        if not extract_result["success"]:
            error_msg = extract_result.get("error", "Unknown error")
            logger.error(f"[rollover] Extraction failed for {trigger}: {error_msg}")
            failed.append({"trigger": str(trigger), "stage": "extraction", "error": error_msg})
            continue

        if extract_result.get("skipped"):
            # Reported, never dropped: a trigger in neither tally reads "0/1" beside no
            # failures, and a skip may still have persisted an order repair.
            reason = extract_result.get("message", "no excess")
            logger.info(f"[rollover] Extraction skipped for {trigger}: {reason}")
            skipped.append({"trigger": str(trigger), "reason": reason})
            continue

        memories = extract_result.get("entries", [])
        branch = extract_result.get("branch", "") or trigger.branch
        memory_type = extract_result.get("type", "unknown") or trigger.memory_type
        old_lines = extract_result.get("old_lines", 0)

        if not branch:
            logger.error(f"[rollover] No branch found in extraction result for {trigger}")
            failed.append({"trigger": str(trigger), "stage": "extraction", "error": "No branch in result"})
            continue

        logger.info(f"[rollover] Extracted {len(memories)} items from {trigger} ({old_lines} lines)")

        texts = extract_text_from_memories(memories)

        embed_result = encode_batch_subprocess(texts)

        if not embed_result["success"]:
            error_msg = embed_result.get("error", "Unknown error")
            logger.error(f"[rollover] Embedding failed for {trigger}: {error_msg}")
            failed.append({"trigger": str(trigger), "stage": "embedding", "error": error_msg})
            continue

        embeddings = embed_result.get("embeddings", [])
        if not embeddings:
            logger.error(f"[rollover] No embeddings generated for {trigger}")
            failed.append({"trigger": str(trigger), "stage": "embedding", "error": "No embeddings in result"})
            continue

        logger.info(f"[rollover] Generated {len(embeddings)} embeddings for {trigger}")

        metadatas = []
        for memory in memories:
            metadata = memory.get("_metadata", {})
            metadata["timestamp"] = memory.get("timestamp", "")
            metadatas.append(metadata)

        branch_str: str = branch
        memory_type_str: str = memory_type
        embeddings_list: list = embeddings

        local_chroma_path = get_branch_local_chroma_path(branch_str)
        local_store_result = None

        if local_chroma_path:
            local_store_result = store_vectors_subprocess(
                branch=branch_str,
                memory_type=memory_type_str,
                embeddings=embeddings_list,
                documents=texts,
                metadatas=metadatas,
                db_path=str(local_chroma_path),
            )

            if not local_store_result["success"]:
                logger.warning(f"[rollover] Local storage failed for {branch}: {local_store_result.get('error')}")
                # Global storage is primary; a local failure does not restore.
            else:
                logger.info(f"[rollover] Stored {len(embeddings)} vectors in local Chroma for {branch}")

        global_store_result = store_vectors_subprocess(
            branch=branch_str,
            memory_type=memory_type_str,
            embeddings=embeddings_list,
            documents=texts,
            metadatas=metadatas,
        )

        if not global_store_result["success"]:
            error_msg = global_store_result.get("error", "Unknown error")
            logger.error(f"[rollover] Global storage failed for {trigger}: {error_msg}")
            failed.append({"trigger": str(trigger), "stage": "global_storage", "error": error_msg})
            continue

        logger.info(f"[rollover] Stored {len(embeddings)} vectors in global Chroma for {branch}")

        # Stored, so the file may shrink. A refused write leaves the entries in place and the
        # next run upserts the same content-hash ids: a retry, never a loss.
        commit_result = extractor.commit_trimmed(trigger.file_path, extract_result.get("trimmed"))
        if not commit_result["success"]:
            error_msg = commit_result.get("error", "Unknown error")
            logger.error(f"[rollover] Trim refused for {trigger} after storage: {error_msg}")
            failed.append({"trigger": str(trigger), "stage": "commit", "error": error_msg})
            continue
        new_lines = commit_result.get("new_lines", 0)

        success_count += 1
        global_collection = global_store_result.get("collection")
        global_total = global_store_result.get("total_vectors")

        local_ok = local_store_result and local_store_result["success"]
        results.append(
            {
                "trigger": str(trigger),
                "branch": branch_str,
                "memories_count": len(memories),
                "old_lines": old_lines,
                "new_lines": new_lines,
                "global_collection": global_collection,
                "global_total": global_total,
                "local_stored": local_ok,
            }
        )

        logger.info(
            f"[rollover] Successfully rolled over {trigger}: {len(memories)} items, {old_lines} -> {new_lines} lines"
        )

    if success_count > 0:
        logger.info(f"[rollover] Rollover complete: {success_count}/{len(triggers)} successful")
    if failed:
        logger.error(f"[rollover] {len(failed)} operations failed")

    if success_count > 0:
        try:
            # The published door is the instance; aliased, `trigger` is this function's loop name.
            from aipass.trigger.apps.modules.core import trigger as trigger_bus

            trigger_bus.fire(
                "rollover_complete", triggers_count=len(triggers), success_count=success_count, failed_count=len(failed)
            )
            logger.info("[rollover] Fired rollover_complete event")
        except Exception as e:
            logger.warning(f"[orchestrator] Failed to fire rollover_complete event: {e}")

        try:
            from aipass.memory.apps.handlers.central_writer import update_central

            central_result = update_central()
            if central_result and central_result.get("success"):
                logger.info("[rollover] Central stats updated")
            else:
                logger.warning(f"[rollover] Central update returned: {central_result}")
        except Exception as e:
            logger.warning(f"[rollover] Central writer unavailable: {e}")

        try:
            from aipass.memory.apps.handlers.intake.pool_processor import process_memory_pool

            pool_result = process_memory_pool()
            if pool_result and pool_result.get("files_processed", 0) > 0:
                logger.info(f"[rollover] Memory pool: {pool_result['files_processed']} files processed")
        except Exception as e:
            logger.info(f"[rollover] Memory pool check: {e}")

    # An all-skipped run is not a fault, and a mixed run still succeeds (its failures
    # are reported by name).
    run_ok = not failed or success_count > 0

    json_handler.log_operation(
        "rollover_execute",
        {
            "triggers": len(triggers),
            "success_count": success_count,
            "failed_count": len(failed),
            "skipped_count": len(skipped),
            "success": run_ok,
        },
    )

    return {
        "success": run_ok,
        "triggers_count": len(triggers),
        "success_count": success_count,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "undrainable": undrainable,
    }
