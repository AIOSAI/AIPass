# =================== AIPass ====================
# Name: query_executor.py
# Description: Search Query Execution Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-03-12
# =============================================

"""
Search Query Execution Handler

Contains the core search execution logic: subprocess-based vector search,
query encoding via subprocess embedder, similarity calculation, and result filtering.
Called by the search module which handles display/CLI concerns.

Purpose:
    Implementation logic for semantic search, separated from CLI/display
    layer to satisfy thin-module standard.
"""

import subprocess
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

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

# Minimum similarity threshold - filter out irrelevant results
MIN_SIMILARITY_THRESHOLD = 0.40  # 40% minimum relevance


# =============================================================================
# SUBPROCESS EMBEDDING
# =============================================================================

def encode_query_subprocess(query: str) -> dict:
    """
    Encode query text via subprocess using memory venv's sentence-transformers.

    Args:
        query: Search query text

    Returns:
        Dict with success, embedding (list of floats), dimension
    """
    input_data = json.dumps({'texts': [query]})

    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(EMBED_SUBPROCESS_SCRIPT)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            return {'success': False, 'error': result.stderr or 'Embedding subprocess failed'}

        data = json.loads(result.stdout)
        if not data.get('success'):
            return data

        embeddings = data.get('embeddings', [])
        if not embeddings:
            return {'success': False, 'error': 'No embedding generated'}

        return {
            'success': True,
            'embedding': embeddings[0],
            'dimension': data.get('dimension', 384)
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Embedding timed out'}
    except json.JSONDecodeError as e:
        return {'success': False, 'error': f'Invalid JSON from embedder: {e}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# =============================================================================
# SUBPROCESS VECTOR SEARCH
# =============================================================================

def search_vectors_subprocess(
    query_embedding: list,
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5,
    db_path: str | Path | None = None
) -> dict:
    """
    Search vectors via subprocess.

    Args:
        query_embedding: Query embedding vector (list of floats)
        branch: Optional branch filter
        memory_type: Optional memory type filter
        n_results: Number of results to return
        db_path: Path to Chroma database (None for global)

    Returns:
        Dict with success status and search results
    """
    input_data = {
        'operation': 'search_vectors',
        'query_embedding': query_embedding,
        'branch': branch,
        'memory_type': memory_type,
        'n_results': n_results,
        'db_path': str(db_path) if db_path else None
    }

    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            return {'success': False, 'error': result.stderr or 'Subprocess failed'}

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Search operation timed out'}
    except json.JSONDecodeError as e:
        return {'success': False, 'error': f'Invalid JSON response: {e}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# =============================================================================
# RESULT PROCESSING
# =============================================================================

def _calculate_similarity(distance: float) -> float:
    """
    Calculate similarity from ChromaDB cosine distance.

    ChromaDB cosine distance: 0=identical, 2=opposite.

    Args:
        distance: Cosine distance from ChromaDB

    Returns:
        Similarity score between 0 and 1
    """
    return max(0, 1 - (distance / 2))


def _filter_results(results: list, n_results: int) -> list:
    """
    Filter search results by similarity threshold and quality.

    Args:
        results: Raw search results from subprocess
        n_results: Maximum number of results to return

    Returns:
        List of filtered result dicts with similarity scores added
    """
    filtered = []
    for result in results[:n_results]:
        document = result.get('document', '')
        distance = result.get('distance', 0)

        similarity = _calculate_similarity(distance)

        if not document or not document.strip():
            continue
        if similarity < MIN_SIMILARITY_THRESHOLD:
            continue

        result['similarity'] = similarity
        filtered.append(result)

    return filtered


# =============================================================================
# PUBLIC API
# =============================================================================

def execute_search(
    query: str,
    branch: str | None = None,
    memory_type: str | None = None,
    n_results: int = 5
) -> Dict[str, Any]:
    """
    Execute semantic search: encode query, search vectors, filter results.

    Workflow:
    1. Encode query to embedding vector via subprocess (memory venv)
    2. Search ChromaDB via subprocess
    3. Filter and score results by similarity

    Args:
        query: Search query text
        branch: Optional branch filter
        memory_type: Optional memory type filter
        n_results: Number of results to return

    Returns:
        Dict with success, results, collections_searched, total_results
    """
    # Step 1: Encode query via subprocess
    embed_result = encode_query_subprocess(query)

    if not embed_result['success']:
        error_msg = embed_result.get('error', 'Unknown error')
        logger.error(f"[search] Failed to encode query: {error_msg}")
        return {
            'success': False,
            'error': f'Failed to encode query: {error_msg}',
            'query': query,
        }

    query_embedding = embed_result['embedding']
    logger.info(f"[search] Encoded query to {len(query_embedding)}-dim vector")

    # Step 2: Search via subprocess
    search_result = search_vectors_subprocess(
        query_embedding=query_embedding,
        branch=branch,
        memory_type=memory_type,
        n_results=n_results
    )

    if not search_result['success']:
        error_msg = search_result.get('error', 'Unknown error')
        logger.error(f"[search] Search failed: {error_msg}")
        return {
            'success': False,
            'error': f'Search failed: {error_msg}',
            'query': query,
        }

    raw_results = search_result.get('results', [])
    collections_searched = search_result.get('collections_searched', 0)
    total_results = search_result.get('total_results', 0)

    logger.info(f"[search] Found {total_results} results across {collections_searched} collections")

    # Step 3: Filter and score results
    filtered_results = _filter_results(raw_results, n_results)

    logger.info(f"[search] Filtered to {len(filtered_results)} relevant results")

    log_operation("search_execute", {"query_len": len(query), "results": len(filtered_results), "success": True})
    return {
        'success': True,
        'query': query,
        'branch': branch,
        'memory_type': memory_type,
        'results': filtered_results,
        'collections_searched': collections_searched,
        'total_results': total_results,
        'filtered_count': len(filtered_results),
    }
