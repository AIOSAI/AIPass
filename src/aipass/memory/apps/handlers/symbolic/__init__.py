#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Symbolic Memory Handler Package
# Date: 2026-02-04
# Version: 0.1.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 1
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Return status dicts (3-tier architecture)
# =============================================

"""
Symbolic Memory Handler Package

Extracts symbolic dimensions from conversations for fragmented memory storage.
Part of the Fragmented Memory implementation.

Modules:
    - extractor.py: Core extraction functions for symbolic dimensions
    - storage.py: Fragment storage in ChromaDB
    - retriever.py: Fragment retrieval with vector/dimension/trigger search
    - chroma_client.py: Shared ChromaDB client singleton
"""

from .extractor import (
    extract_technical_flow,
    extract_emotional_journey,
    extract_collaboration_patterns,
    extract_key_learnings,
    extract_context_triggers,
    extract_symbolic_dimensions,
    analyze_conversation
)

from .chroma_client import get_chroma_client

__all__ = [
    'extract_technical_flow',
    'extract_emotional_journey',
    'extract_collaboration_patterns',
    'extract_key_learnings',
    'extract_context_triggers',
    'extract_symbolic_dimensions',
    'analyze_conversation',
    'get_chroma_client'
]
