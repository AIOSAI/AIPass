# =================== AIPass ====================
# Name: orchestrator.py
# Description: Rollover Orchestration Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Rollover Orchestration Handler

Contains the core rollover execution logic: trigger detection, extraction,
embedding, vector storage, and line count sync. Called by the rollover
module which handles display/CLI concerns.

Purpose:
    Implementation logic for rollover workflow, separated from CLI/display
    layer to satisfy thin-module standard.
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

# logger imported from aipass.prax

# Handler imports (relative within the memory package)
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover import extractor
from aipass.memory.apps.handlers.tracking import line_counter

# Subprocess scripts for ML operations (run in memory venv)
_HANDLERS_DIR = Path(__file__).resolve().parent.parent
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"
EMBED_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "vector" / "embed_subprocess.py"

# Memory venv python — auto-detect from memory/.venv/ or use env var override
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


def _get_memory_python() -> str:
    """Get the Python executable for memory ML operations."""
    env_override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if env_override:
        return env_override
    if _MEMORY_VENV_PYTHON.exists():
        return str(_MEMORY_VENV_PYTHON)
    return sys.executable


MEMORY_PYTHON = _get_memory_python()


# =============================================================================
# REPO ROOT DISCOVERY
# =============================================================================


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()


# =============================================================================
# VECTOR STORAGE (SUBPROCESS)
# =============================================================================


def store_vectors_subprocess(
    branch: str, memory_type: str, embeddings: list, documents: list, metadatas: list, db_path: str | Path | None = None
) -> dict:
    """
    Store vectors via subprocess.

    This ensures ChromaDB compatibility regardless of calling Python version.

    Args:
        branch: Branch name
        memory_type: Type of memory (e.g., 'sessions', 'observations')
        embeddings: List of embedding vectors
        documents: List of text documents
        metadatas: List of metadata dicts
        db_path: Path to Chroma database (None for global)

    Returns:
        Dict with success status and storage details
    """
    # Convert numpy arrays to lists for JSON serialization
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

    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Subprocess failed"}

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("[orchestrator] Vector storage operation timed out")
        return {"success": False, "error": "Storage operation timed out"}
    except json.JSONDecodeError as e:
        logger.warning(f"[orchestrator] Invalid JSON from storage subprocess: {e}")
        return {"success": False, "error": f"Invalid JSON response: {e}"}
    except Exception as e:
        logger.warning(f"[orchestrator] Vector storage subprocess error: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# EMBEDDING VIA SUBPROCESS
# =============================================================================


def encode_batch_subprocess(texts: list) -> dict:
    """
    Encode texts via subprocess using memory venv's sentence-transformers.

    Args:
        texts: List of text strings to encode

    Returns:
        Dict with success, embeddings, count, dimension
    """
    input_data = json.dumps({"texts": texts})

    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(EMBED_SUBPROCESS_SCRIPT)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Embedding subprocess failed"}

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("[orchestrator] Embedding subprocess timed out")
        return {"success": False, "error": "Embedding timed out"}
    except json.JSONDecodeError as e:
        logger.warning(f"[orchestrator] Invalid JSON from embedding subprocess: {e}")
        return {"success": False, "error": f"Invalid JSON from embedder: {e}"}
    except Exception as e:
        logger.warning(f"[orchestrator] Embedding subprocess error: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# PATH HELPERS
# =============================================================================


def get_branch_local_chroma_path(branch_name: str) -> Path | None:
    """
    Get local .chroma path for branch

    Args:
        branch_name: Branch name (e.g., "SEEDGO", "AIPASS")

    Returns:
        Path to branch's local .chroma directory, or None if branch not found
    """
    if not branch_name:
        return None

    registry = detector._read_registry()

    for branch in registry:
        if branch.get("name", "").upper() == branch_name.upper():
            branch_path = Path(branch.get("path", ""))
            if branch_path.exists():
                chroma_path = branch_path / ".chroma"
                # Auto-create .chroma directory if missing
                if not chroma_path.exists():
                    chroma_path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"[rollover] Created local .chroma directory for {branch_name}")
                return chroma_path

    logger.warning(f"[rollover] Branch {branch_name} not found in registry")
    return None


# =============================================================================
# TEXT EXTRACTION HELPERS
# =============================================================================


def extract_text_from_memories(memories: List[Dict]) -> List[str]:
    """
    Extract text content from memory items for vectorization

    Memory items have different structures:
    - sessions: 'activities' array (join into text)
    - observations: might have 'content' or 'text' field
    - generic: convert to JSON string

    Args:
        memories: List of memory items

    Returns:
        List of text strings for embedding
    """
    texts = []

    for memory in memories:
        # Try common text fields
        if "activities" in memory and isinstance(memory["activities"], list):
            # Sessions type (v1) - join activities
            text = "\n".join(str(a) for a in memory["activities"])
        elif "summary" in memory:
            # Sessions type (v2) - summary field
            text = str(memory["summary"])
        elif "_type" in memory and memory["_type"] == "key_learning":
            # Key learnings (v2) - key:value pair
            text = f"{memory.get('key', '')}: {memory.get('value', '')}"
        elif "content" in memory:
            text = str(memory["content"])
        elif "text" in memory:
            text = str(memory["text"])
        elif "message" in memory:
            text = str(memory["message"])
        else:
            # Fallback - convert to string representation
            text = str(memory)

        texts.append(text)

    return texts


# =============================================================================
# ROLLOVER EXECUTION
# =============================================================================


def execute_rollover() -> Dict[str, Any]:
    """
    Execute rollover workflow for all triggered branches.

    Workflow:
    1. Check all branches for triggers
    2. For each trigger:
       - Create backup
       - Extract oldest entries
       - Generate embeddings
       - Store in local + global Chroma
       - Update line counts
    3. Return results

    Returns:
        Dict with success status, counts, and details for each trigger
    """
    # Step 1: Detect triggers
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
        }

    triggers = triggers_result.get("triggers", [])
    if not triggers:
        logger.info("[rollover] No rollover triggers detected")
        return {
            "success": True,
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "results": [],
        }

    logger.info(f"[rollover] Found {len(triggers)} files ready for rollover")

    # Process each trigger
    success_count = 0
    failed = []
    results = []

    for trigger in triggers:
        # Step 1: CREATE BACKUP (safety net)
        backup_result = extractor.create_rollover_backup(trigger.file_path)

        if not backup_result["success"]:
            error_msg = backup_result.get("error", "Backup failed")
            logger.error(f"[rollover] Backup failed for {trigger}: {error_msg}")
            failed.append({"trigger": str(trigger), "stage": "backup", "error": error_msg})
            continue  # Don't proceed without backup

        logger.info(f"[rollover] {backup_result.get('message')}")

        # Step 2: Extract memories (auto-calculates percentage)
        extract_result = extractor.extract_with_metadata(trigger.file_path)

        if not extract_result["success"]:
            error_msg = extract_result.get("error", "Unknown error")
            logger.error(f"[rollover] Extraction failed for {trigger}: {error_msg}")

            # RESTORE from backup
            restore_result = extractor.restore_from_backup(trigger.file_path)
            if restore_result["success"]:
                logger.info("[rollover] Restored from backup after extraction failure")

            failed.append({"trigger": str(trigger), "stage": "extraction", "error": error_msg})
            continue

        memories = extract_result.get("entries", [])
        branch = extract_result.get("branch", "") or trigger.branch
        memory_type = extract_result.get("type", "unknown") or trigger.memory_type
        old_lines = extract_result.get("old_lines", 0)
        new_lines = extract_result.get("new_lines", 0)

        if not branch:
            logger.error(f"[rollover] No branch found in extraction result for {trigger}")
            failed.append({"trigger": str(trigger), "stage": "extraction", "error": "No branch in result"})
            continue

        logger.info(f"[rollover] Extracted {len(memories)} items from {trigger} ({old_lines} -> {new_lines} lines)")

        # Convert memory items to text for vectorization
        texts = extract_text_from_memories(memories)

        # Step 3: Generate embeddings (via subprocess in memory venv)
        embed_result = encode_batch_subprocess(texts)

        if not embed_result["success"]:
            error_msg = embed_result.get("error", "Unknown error")
            logger.error(f"[rollover] Embedding failed for {trigger}: {error_msg}")

            # RESTORE from backup
            restore_result = extractor.restore_from_backup(trigger.file_path)
            if restore_result["success"]:
                logger.info("[rollover] Restored from backup after embedding failure")

            failed.append({"trigger": str(trigger), "stage": "embedding", "error": error_msg})
            continue

        embeddings = embed_result.get("embeddings", [])
        if not embeddings:
            logger.error(f"[rollover] No embeddings generated for {trigger}")
            failed.append({"trigger": str(trigger), "stage": "embedding", "error": "No embeddings in result"})
            continue

        logger.info(f"[rollover] Generated {len(embeddings)} embeddings for {trigger}")

        # Step 4: Prepare metadata for vectorization
        metadatas = []
        for memory in memories:
            metadata = memory.get("_metadata", {})
            metadata["timestamp"] = memory.get("timestamp", "")
            metadatas.append(metadata)

        # Step 5: Store in LOCAL branch Chroma (via subprocess)
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
                # Continue anyway - global storage is primary
            else:
                logger.info(f"[rollover] Stored {len(embeddings)} vectors in local Chroma for {branch}")

        # Step 6: Store in GLOBAL Memory Chroma (via subprocess)
        global_store_result = store_vectors_subprocess(
            branch=branch_str,
            memory_type=memory_type_str,
            embeddings=embeddings_list,
            documents=texts,
            metadatas=metadatas,
            # db_path=None means global
        )

        if not global_store_result["success"]:
            error_msg = global_store_result.get("error", "Unknown error")
            logger.error(f"[rollover] Global storage failed for {trigger}: {error_msg}")

            # RESTORE from backup (CRITICAL - file was modified but storage failed)
            restore_result = extractor.restore_from_backup(trigger.file_path)
            if restore_result["success"]:
                logger.info("[rollover] Restored from backup after storage failure")
            else:
                logger.error(f"[rollover] CRITICAL: Failed to restore from backup: {restore_result.get('error')}")

            failed.append({"trigger": str(trigger), "stage": "global_storage", "error": error_msg})
            continue

        logger.info(f"[rollover] Stored {len(embeddings)} vectors in global Chroma for {branch}")

        # Step 7: Update line count metadata
        update_result = line_counter.update_line_count(trigger.file_path)
        if update_result["success"]:
            logger.info(f"[rollover] Updated line count metadata for {trigger.file_path.name}")
        else:
            logger.warning(
                f"[rollover] Failed to update line count for {trigger.file_path.name}: {update_result.get('error')}"
            )

        # Success!
        success_count += 1
        global_collection = global_store_result.get("collection")
        global_total = global_store_result.get("total_vectors")

        local_ok = local_store_result and local_store_result["success"]
        results.append(
            {
                "trigger": str(trigger),
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

    # Summary logging
    if success_count > 0:
        logger.info(f"[rollover] Rollover complete: {success_count}/{len(triggers)} successful")
    if failed:
        logger.error(f"[rollover] {len(failed)} operations failed")

    # =========================================================================
    # Post-rollover processing chain
    # =========================================================================
    if success_count > 0:
        # Post-rollover: fire event for trigger system
        try:
            from aipass.trigger.apps.modules.core import Trigger

            Trigger.fire(
                "rollover_complete", triggers_count=len(triggers), success_count=success_count, failed_count=len(failed)
            )
            logger.info("[rollover] Fired rollover_complete event")
        except Exception as e:
            logger.warning(f"[orchestrator] Failed to fire rollover_complete event: {e}")

        # Post-rollover: update central stats
        try:
            from aipass.memory.apps.handlers.central_writer import update_central

            central_result = update_central()
            if central_result and central_result.get("success"):
                logger.info("[rollover] Central stats updated")
            else:
                logger.warning(f"[rollover] Central update returned: {central_result}")
        except Exception as e:
            logger.warning(f"[rollover] Central writer unavailable: {e}")

        # Post-rollover: push dashboard
        try:
            from aipass.memory.apps.handlers.dashboard_push import push_memory_bank_dashboard

            dash_ok = push_memory_bank_dashboard()
            if dash_ok:
                logger.info("[rollover] Dashboard pushed")
            else:
                logger.warning("[rollover] Dashboard push returned False")
        except Exception as e:
            logger.warning(f"[rollover] Dashboard push unavailable: {e}")

        # Post-rollover: process memory pool if files waiting
        try:
            from aipass.memory.apps.handlers.intake.pool_processor import process_memory_pool

            pool_result = process_memory_pool()
            if pool_result and pool_result.get("files_processed", 0) > 0:
                logger.info(f"[rollover] Memory pool: {pool_result['files_processed']} files processed")
        except Exception as e:
            logger.info(f"[rollover] Memory pool check: {e}")

    json_handler.log_operation(
        "rollover_execute",
        {
            "triggers": len(triggers),
            "success_count": success_count,
            "failed_count": len(failed),
            "success": success_count > 0 or len(triggers) == 0,
        },
    )

    return {
        "success": success_count > 0 or len(triggers) == 0,
        "triggers_count": len(triggers),
        "success_count": success_count,
        "failed": failed,
        "results": results,
    }


# =============================================================================
# LINE COUNT SYNC
# =============================================================================


def sync_line_counts() -> Dict[str, Any]:
    """
    Update line count metadata for all branch memory files.

    Reads actual line counts and updates document_metadata.status.current_lines
    for all *.local.json and *.observations.json files in AIPASS_REGISTRY.

    Returns:
        Dict with success status, updated count, and failures
    """
    result = line_counter.update_all_memory_files()

    if result["success"]:
        logger.info(f"[rollover] Synced line counts: {result['updated']} updated, {result['failed']} failed")
    else:
        logger.error("[rollover] Failed to sync line counts")

    return result
