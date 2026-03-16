#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: retriever.py - Symbolic Fragment Retrieval Handler
# Date: 2026-02-04
# Version: 0.2.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-02-15): Add relevance_tier labels to query/get results (FPLAN-0341 P4)
#   - v0.1.1 (2026-02-15): Fix: embedding_function=None on all get_collection(),
#     cosine similarity formula, use shared chroma_client singleton
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 3
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <300 lines target
# =============================================

"""
Symbolic Fragment Retrieval Handler

Retrieves symbolic memory fragments from ChromaDB using multiple methods:
1. Vector similarity - semantic closeness to query
2. Dimension filtering - filter by symbolic dimensions (technical, emotional, etc.)
3. Trigger keywords - keyword matching in context triggers

Key Functions:
    - retrieve_fragments() - main retrieval combining all methods
    - search_by_vector() - pure vector similarity search
    - search_by_dimensions() - filter by symbolic dimensions
    - search_by_triggers() - keyword matching in triggers field
"""

import sys
from typing import Dict, List, Any
from pathlib import Path

# Infrastructure setup
AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# Handler imports (domain-organized, no modules)
from MEMORY_BANK.apps.handlers.vector import embedder


# =============================================================================
# CONSTANTS
# =============================================================================

COLLECTION_NAME = "symbolic_fragments"
DEFAULT_N_RESULTS = 5

# Import shared chroma client
from MEMORY_BANK.apps.handlers.symbolic.chroma_client import get_chroma_client


# =============================================================================
# VECTOR SIMILARITY SEARCH
# =============================================================================

def search_by_vector(
    query: str,
    n_results: int = DEFAULT_N_RESULTS,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by vector similarity

    Encodes query to embedding and searches ChromaDB for semantically
    similar fragments.

    Args:
        query: Search query text
        n_results: Number of results to return
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', 'results' list containing fragments with scores
    """
    if not query:
        return {
            'success': False,
            'error': 'Query text required'
        }

    # Encode query to embedding
    embed_result = embedder.encode_batch([query])
    if not embed_result.get('success'):
        return {
            'success': False,
            'error': f"Embedding failed: {embed_result.get('error', 'Unknown error')}"
        }

    embeddings = embed_result.get('embeddings', [])
    if not embeddings:
        return {
            'success': False,
            'error': 'No embedding generated'
        }

    query_vec = embeddings[0]
    if hasattr(query_vec, 'tolist'):
        query_vec = query_vec.tolist()

    try:
        client = get_chroma_client(db_path)

        # Get collection
        try:
            collection = client.get_collection(
                COLLECTION_NAME,
                embedding_function=None
            )
        except Exception:
            return {
                'success': True,
                'results': [],
                'message': f'Collection {COLLECTION_NAME} not found'
            }

        # Query by vector similarity
        results = collection.query(
            query_embeddings=[query_vec],
            n_results=n_results
        )

        # Format results
        formatted = _format_query_results(results)

        return {
            'success': True,
            'results': formatted,
            'total_results': len(formatted),
            'search_type': 'vector'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Vector search failed: {e}"
        }


# =============================================================================
# DIMENSION FILTERING
# =============================================================================

def search_by_dimensions(
    dimension_filters: Dict[str, str],
    n_results: int = DEFAULT_N_RESULTS,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by symbolic dimension filters

    Filters fragments by matching dimension values in metadata.
    Example: {'emotional_0': 'frustration_to_breakthrough'}

    Args:
        dimension_filters: Dict of dimension_key: value pairs to match
        n_results: Number of results to return
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', 'results' list of matching fragments
    """
    if not dimension_filters:
        return {
            'success': False,
            'error': 'Dimension filters required'
        }

    try:
        client = get_chroma_client(db_path)

        # Get collection
        try:
            collection = client.get_collection(
                COLLECTION_NAME,
                embedding_function=None
            )
        except Exception:
            return {
                'success': True,
                'results': [],
                'message': f'Collection {COLLECTION_NAME} not found'
            }

        # Build where clause for filtering
        # ChromaDB where clause: {"$and": [{"key": {"$eq": "value"}}, ...]}
        where_conditions = []
        for key, value in dimension_filters.items():
            where_conditions.append({key: {"$eq": value}})

        if len(where_conditions) == 1:
            where_clause = where_conditions[0]
        else:
            where_clause = {"$and": where_conditions}

        # Query with filter (no embedding, just metadata filter)
        results = collection.get(
            where=where_clause,
            limit=n_results,
            include=['documents', 'metadatas']
        )

        # Format results (get() returns different structure than query())
        formatted = _format_get_results(results)

        return {
            'success': True,
            'results': formatted,
            'total_results': len(formatted),
            'search_type': 'dimension_filter',
            'filters_applied': dimension_filters
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Dimension search failed: {e}"
        }


# =============================================================================
# TRIGGER KEYWORD SEARCH
# =============================================================================

def search_by_triggers(
    keywords: List[str],
    n_results: int = DEFAULT_N_RESULTS,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by trigger keywords

    Searches for fragments where the triggers metadata field contains
    any of the specified keywords. Triggers are stored as comma-separated
    strings in metadata.

    Args:
        keywords: List of keywords to search for in triggers
        n_results: Number of results to return
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', 'results' list of matching fragments
    """
    if not keywords:
        return {
            'success': False,
            'error': 'Keywords required'
        }

    try:
        client = get_chroma_client(db_path)

        # Get collection
        try:
            collection = client.get_collection(
                COLLECTION_NAME,
                embedding_function=None
            )
        except Exception:
            return {
                'success': True,
                'results': [],
                'message': f'Collection {COLLECTION_NAME} not found'
            }

        # Get all fragments and filter in Python
        # ChromaDB metadata where doesn't support $contains for strings
        # Triggers are stored as comma-separated strings in metadata
        all_results = collection.get(
            include=['documents', 'metadatas']
        )

        # Filter by trigger keywords
        matching_indices = []
        keywords_lower = [k.lower() for k in keywords]

        if all_results.get('metadatas'):
            for i, meta in enumerate(all_results['metadatas']):
                triggers_str = meta.get('triggers', '')
                if triggers_str:
                    # Triggers are comma-separated
                    fragment_triggers = [t.strip().lower() for t in triggers_str.split(',')]
                    # Check if any keyword matches any trigger
                    for kw in keywords_lower:
                        if any(kw in trigger for trigger in fragment_triggers):
                            matching_indices.append(i)
                            break

        # Build filtered results
        filtered_results = {
            'ids': [all_results['ids'][i] for i in matching_indices] if all_results.get('ids') else [],
            'documents': [all_results['documents'][i] for i in matching_indices] if all_results.get('documents') else [],
            'metadatas': [all_results['metadatas'][i] for i in matching_indices] if all_results.get('metadatas') else []
        }

        # Limit results
        if len(filtered_results['ids']) > n_results:
            filtered_results['ids'] = filtered_results['ids'][:n_results]
            filtered_results['documents'] = filtered_results['documents'][:n_results]
            filtered_results['metadatas'] = filtered_results['metadatas'][:n_results]

        # Format results
        formatted = _format_get_results(filtered_results)

        return {
            'success': True,
            'results': formatted,
            'total_results': len(formatted),
            'search_type': 'trigger_keywords',
            'keywords_searched': keywords
        }

    except Exception as e:
        return {
            'success': False,
            'error': f"Trigger search failed: {e}"
        }


# =============================================================================
# COMBINED RETRIEVAL
# =============================================================================

def retrieve_fragments(
    query: str | None = None,
    dimension_filters: Dict[str, str] | None = None,
    trigger_keywords: List[str] | None = None,
    n_results: int = DEFAULT_N_RESULTS,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Main retrieval function combining all search methods

    Combines vector similarity with dimension filtering and trigger matching.
    When multiple methods are used, results are merged and re-ranked.

    Priority:
    1. If query provided: Vector similarity search
    2. If dimension_filters provided: Filter by dimensions
    3. If trigger_keywords provided: Match triggers
    4. Merge and rank results

    Args:
        query: Optional search query for vector similarity
        dimension_filters: Optional dict of dimension filters
        trigger_keywords: Optional list of trigger keywords
        n_results: Number of results to return
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', 'results' list with relevance scores
    """
    if not query and not dimension_filters and not trigger_keywords:
        return {
            'success': False,
            'error': 'At least one search method required (query, dimension_filters, or trigger_keywords)'
        }

    all_results = []
    search_methods_used = []

    # 1. Vector similarity search (if query provided)
    if query:
        vector_result = search_by_vector(query, n_results=n_results * 2, db_path=db_path)
        if vector_result.get('success') and vector_result.get('results'):
            search_methods_used.append('vector')
            for result in vector_result['results']:
                result['_source'] = 'vector'
                all_results.append(result)

    # 2. Dimension filter search (if filters provided)
    if dimension_filters:
        dim_result = search_by_dimensions(dimension_filters, n_results=n_results * 2, db_path=db_path)
        if dim_result.get('success') and dim_result.get('results'):
            search_methods_used.append('dimension')
            for result in dim_result['results']:
                result['_source'] = 'dimension'
                all_results.append(result)

    # 3. Trigger keyword search (if keywords provided)
    if trigger_keywords:
        trigger_result = search_by_triggers(trigger_keywords, n_results=n_results * 2, db_path=db_path)
        if trigger_result.get('success') and trigger_result.get('results'):
            search_methods_used.append('trigger')
            for result in trigger_result['results']:
                result['_source'] = 'trigger'
                all_results.append(result)

    if not all_results:
        return {
            'success': True,
            'results': [],
            'message': 'No matching fragments found',
            'search_methods': search_methods_used
        }

    # Merge and deduplicate results
    merged = _merge_results(all_results)

    # Calculate combined relevance scores
    ranked = _rank_results(merged, search_methods_used)

    # Return top n_results
    final_results = ranked[:n_results]

    return {
        'success': True,
        'results': final_results,
        'total_results': len(final_results),
        'search_methods': search_methods_used,
        'total_before_merge': len(all_results)
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _format_query_results(results: Dict) -> List[Dict[str, Any]]:
    """
    Format ChromaDB query() results into standard fragment format

    query() returns: {'ids': [[...]], 'documents': [[...]], 'metadatas': [[...]], 'distances': [[...]]}
    Adds relevance_tier based on similarity score thresholds.
    """
    formatted = []

    if not results.get('documents') or not results['documents'][0]:
        return formatted

    for i, doc in enumerate(results['documents'][0]):
        frag = {
            'id': results['ids'][0][i] if results.get('ids') else None,
            'content': doc,
            'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
            'distance': results['distances'][0][i] if results.get('distances') else None
        }

        # Calculate similarity score (cosine distance: 0=identical, 2=opposite)
        if frag['distance'] is not None:
            frag['similarity'] = max(0, 1 - frag['distance'])
        else:
            frag['similarity'] = 0

        # Assign relevance tier
        frag['relevance_tier'] = _compute_relevance_tier(frag['similarity'])

        formatted.append(frag)

    return formatted


def _format_get_results(results: Dict) -> List[Dict[str, Any]]:
    """
    Format ChromaDB get() results into standard fragment format

    get() returns: {'ids': [...], 'documents': [...], 'metadatas': [...]}
    Adds relevance_tier based on default similarity score.
    """
    formatted = []

    if not results.get('documents'):
        return formatted

    for i, doc in enumerate(results['documents']):
        similarity = 0.5  # Default score for filter-only results
        frag = {
            'id': results['ids'][i] if results.get('ids') else None,
            'content': doc,
            'metadata': results['metadatas'][i] if results.get('metadatas') else {},
            'distance': None,
            'similarity': similarity,
            'relevance_tier': _compute_relevance_tier(similarity)
        }
        formatted.append(frag)

    return formatted


def _compute_relevance_tier(similarity: float) -> str:
    """
    Compute a human-readable relevance tier from a similarity score

    Tiers:
        - strong: similarity >= 0.65
        - moderate: similarity >= 0.45
        - serendipity: similarity >= 0.30
        - weak: below 0.30

    Args:
        similarity: Float similarity score between 0 and 1

    Returns:
        Relevance tier string
    """
    if similarity >= 0.65:
        return 'strong'
    if similarity >= 0.45:
        return 'moderate'
    if similarity >= 0.30:
        return 'serendipity'
    return 'weak'


def _merge_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge and deduplicate results from multiple search methods

    If same fragment found by multiple methods, combine their scores.
    """
    merged = {}

    for result in results:
        frag_id = result.get('id')
        if not frag_id:
            continue

        if frag_id not in merged:
            merged[frag_id] = result.copy()
            merged[frag_id]['_sources'] = [result.get('_source', 'unknown')]
        else:
            # Fragment found by multiple methods - combine scores
            existing = merged[frag_id]
            existing['_sources'].append(result.get('_source', 'unknown'))

            # Take best similarity if both have scores
            if result.get('similarity', 0) > existing.get('similarity', 0):
                existing['similarity'] = result['similarity']

    return list(merged.values())


def _rank_results(results: List[Dict[str, Any]], _methods_used: List[str]) -> List[Dict[str, Any]]:
    """
    Rank merged results by combined relevance

    Scoring:
    - Base: similarity score (0-1)
    - Bonus: +0.1 for each additional method that found the fragment
    """
    for result in results:
        sources = result.get('_sources', [])
        base_score = result.get('similarity', 0)

        # Bonus for being found by multiple methods
        multi_method_bonus = (len(sources) - 1) * 0.1

        result['relevance_score'] = min(1.0, base_score + multi_method_bonus)

        # Clean up internal fields
        if '_source' in result:
            del result['_source']

    # Sort by relevance score descending
    results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

    return results
