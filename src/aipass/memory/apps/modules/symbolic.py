#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: symbolic.py - Symbolic Memory Orchestration Module
# Date: 2026-02-04
# Version: 0.3.0
# Category: memory_bank/modules
#
# CHANGELOG (Max 5 entries):
#   - v0.3.0 (2026-02-15): v2 schema display in CLI, extract command, v2 demo/hook-test (FPLAN-0341 P4)
#   - v0.2.0 (2026-02-15): Add LLM dedup pipeline extract_and_store_llm (FPLAN-0341 P3)
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 1
#
# CODE STANDARDS:
#   - Thin orchestration: Delegate all logic to handlers
#   - No business logic: Only coordinate workflow
#   - handle_command() pattern
# =============================================

"""
Symbolic Memory Orchestration Module

Exposes symbolic memory extraction functions for fragmented memory storage.
This module provides the public API for analyzing conversations and extracting
symbolic dimensions (technical flow, emotional arc, collaboration patterns, etc.)

Part of the Fragmented Memory implementation.
"""

import json
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Infrastructure setup
AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))  # For MEMORY_BANK package imports

# Service imports
from prax.apps.modules.logger import system_logger as logger
from cli.apps.modules import console, header

# Handler imports (domain-organized)
from MEMORY_BANK.apps.handlers.symbolic import extractor
from MEMORY_BANK.apps.handlers.symbolic import storage
from MEMORY_BANK.apps.handlers.symbolic import retriever
from MEMORY_BANK.apps.handlers.symbolic import hook
from MEMORY_BANK.apps.handlers.symbolic import deduplicator


# =============================================================================
# PUBLIC API - Delegated to handlers
# =============================================================================

def extract_technical_flow(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze technical patterns from conversation

    Detects problem/debug/breakthrough patterns.

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with 'success', 'patterns' list, and analysis details
    """
    return extractor.extract_technical_flow(chat_history)


def extract_emotional_journey(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Detect emotional arc from conversation tone and patterns

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with 'success', 'arc' list, and emotion timeline
    """
    return extractor.extract_emotional_journey(chat_history)


def extract_collaboration_patterns(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Identify relationship dynamics and interaction patterns

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with 'success', 'patterns' list, and interaction metrics
    """
    return extractor.extract_collaboration_patterns(chat_history)


def extract_key_learnings(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract core insights and lessons from conversation

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with 'success', 'insights' list, and detected categories
    """
    return extractor.extract_key_learnings(chat_history)


def extract_context_triggers(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract keywords that should trigger this memory in future conversations

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with 'success', 'triggers' list, and term frequencies
    """
    return extractor.extract_context_triggers(chat_history)


def extract_symbolic_dimensions(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract all symbolic dimensions from conversation

    Calls all individual extractors and combines results into
    a unified symbolic representation.

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with all extracted dimensions and metadata
    """
    return extractor.extract_symbolic_dimensions(chat_history)


def analyze_conversation(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Main entry point for conversation analysis

    Extracts symbolic dimensions and adds conversation metadata
    for complete fragmented memory representation.

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys

    Returns:
        Dict with full analysis including dimensions and metadata
    """
    return extractor.analyze_conversation(chat_history)


# =============================================================================
# STORAGE API - Delegated to handlers
# =============================================================================

def create_fragment(
    analysis: Dict[str, Any],
    content: str | None = None,
    source_branch: str | None = None
) -> Dict[str, Any]:
    """Create fragment from analysis, fire trigger on success"""
    result = storage.create_fragment(analysis, content, source_branch)
    if result.get('success'):
        try:
            from trigger.apps.modules.core import trigger
            trigger.fire('fragment_created',
                        fragment_id=result['fragment'].get('id'),
                        source_branch=source_branch or 'unknown')
        except Exception:
            pass  # Trigger optional
    return result


def store_fragment(
    fragment: Dict[str, Any],
    db_path: Path | None = None
) -> Dict[str, Any]:
    """Store fragment in ChromaDB, fire trigger on success"""
    result = storage.store_fragment(fragment, db_path)
    if result.get('success'):
        try:
            from trigger.apps.modules.core import trigger
            trigger.fire('fragment_stored', fragment_id=result.get('fragment_id'))
        except Exception:
            pass  # Trigger optional
    return result


def store_fragments_batch(
    fragments: List[Dict[str, Any]],
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Store multiple fragments in ChromaDB in batch

    More efficient than storing one at a time when processing
    multiple conversations.

    Args:
        fragments: List of fragment dicts from create_fragment()
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', batch storage details
    """
    return storage.store_fragments_batch(fragments, db_path)


def flatten_dimensions(fragment: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten fragment dimensions for ChromaDB metadata storage

    ChromaDB metadata must be flat (string/int/float/bool).
    This converts nested dimensions to indexed keys.

    Args:
        fragment: Fragment dict with nested dimensions

    Returns:
        Dict with 'success', 'metadata' containing flattened metadata
    """
    return storage.flatten_dimensions(fragment)


# =============================================================================
# v2 LLM PIPELINE - Extract, Deduplicate, Store
# =============================================================================

def store_llm_fragment(
    fragment: Dict[str, Any],
    source_branch: str | None = None,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Store a single LLM-extracted fragment in ChromaDB

    Args:
        fragment: LLM-extracted fragment dict (summary/insight/type/triggers/etc.)
        source_branch: Optional branch name for filtering
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'fragment_id', 'collection', 'total_fragments'
    """
    return storage.store_llm_fragment(fragment, source_branch, db_path)


def store_llm_fragments_batch(
    fragments: List[Dict[str, Any]],
    source_branch: str | None = None,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Store multiple LLM-extracted fragments in ChromaDB in batch

    Args:
        fragments: List of LLM-extracted fragment dicts
        source_branch: Optional branch name for filtering
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'stored' count, 'collection', 'total_fragments'
    """
    return storage.store_llm_fragments_batch(fragments, source_branch, db_path)


def deduplicate_fragment(
    new_fragment: Dict[str, Any],
    existing_fragments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compare a new LLM-extracted fragment against existing ones via AUDN pattern

    Args:
        new_fragment: New LLM-extracted fragment dict
        existing_fragments: List of similar existing fragments from ChromaDB

    Returns:
        Dict with 'success', 'action' (ADD|UPDATE|DELETE|NOOP),
        'fragment', 'reason'
    """
    return deduplicator.deduplicate_fragment(new_fragment, existing_fragments)


def extract_and_store_llm(
    chat_history: List[Dict[str, Any]],
    source_branch: str | None = None,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    End-to-end pipeline: extract LLM fragments, deduplicate, and store

    Steps:
    1. Extract fragments from chat via LLM (extractor.extract_fragments_llm)
    2. For each fragment, find similar existing fragments in ChromaDB
    3. Deduplicate via LLM (deduplicator.deduplicate_fragment)
    4. Store based on AUDN action (ADD/UPDATE stored, DELETE noted, NOOP skipped)

    Args:
        chat_history: List of message dicts with 'role' and 'content' keys
        source_branch: Optional branch name for filtering
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'processed', 'added', 'updated', 'skipped', 'errors'
    """
    # Step 1: Extract fragments via LLM
    logger.info("[symbolic] Starting LLM extract-and-store pipeline")
    extract_result = extractor.extract_fragments_llm(chat_history)

    # Log any per-chunk errors even on partial success
    chunk_errors = extract_result.get('chunk_errors', [])
    if chunk_errors:
        for ce in chunk_errors:
            logger.warning(f"[symbolic] Chunk extraction error: {ce}")

    if not extract_result.get('success'):
        error_msg = extract_result.get('error', 'Unknown extraction error')
        logger.error(f"[symbolic] LLM extraction failed: {error_msg}")
        try:
            from trigger.apps.modules.errors import report_error
            report_error(
                error_type="ExtractionError",
                message=error_msg,
                component="MEMORY_BANK",
                severity="high"
            )
        except Exception:
            pass  # Trigger unavailable — prax log is the fallback
        return {
            'success': False,
            'processed': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': [error_msg]
        }

    fragments = extract_result.get('fragments', [])
    if not fragments:
        logger.info("[symbolic] No fragments extracted from conversation")
        return {
            'success': True,
            'processed': 0,
            'added': 0,
            'updated': 0,
            'skipped': 0,
            'errors': []
        }

    logger.info(f"[symbolic] Extracted {len(fragments)} fragments, starting dedup")

    added = 0
    updated = 0
    skipped = 0
    errors: List[str] = []

    # Step 2-4: Deduplicate and store each fragment
    for frag in fragments:
        try:
            # Find similar existing fragments via vector search
            search_query = frag.get('summary', '')
            similar_result = retriever.search_by_vector(
                search_query, n_results=5, db_path=db_path
            )

            existing = []
            if similar_result.get('success'):
                existing = similar_result.get('results', [])

            # Deduplicate
            dedup_result = deduplicator.deduplicate_fragment(frag, existing)
            action = dedup_result.get('action', 'ADD')
            deduped_frag = dedup_result.get('fragment', frag)

            if action == 'ADD':
                store_result = storage.store_llm_fragment(
                    deduped_frag, source_branch, db_path
                )
                if store_result.get('success'):
                    added += 1
                else:
                    errors.append(
                        f"ADD store failed: {store_result.get('error', 'Unknown')}"
                    )

            elif action == 'UPDATE':
                store_result = storage.store_llm_fragment(
                    deduped_frag, source_branch, db_path
                )
                if store_result.get('success'):
                    updated += 1
                else:
                    errors.append(
                        f"UPDATE store failed: {store_result.get('error', 'Unknown')}"
                    )

            elif action == 'DELETE':
                delete_id = dedup_result.get('delete_id', '')
                if delete_id:
                    del_result = storage.delete_fragment(delete_id, db_path)
                    if del_result.get('success'):
                        logger.info(
                            f"[symbolic] DELETED {delete_id}: "
                            f"{dedup_result.get('reason', 'no reason')}"
                        )
                    else:
                        logger.warning(
                            f"[symbolic] DELETE failed for {delete_id}: "
                            f"{del_result.get('error', 'unknown')}"
                        )
                skipped += 1

            else:  # NOOP
                skipped += 1

        except Exception as e:
            errors.append(f"Fragment processing error: {e}")

    total_processed = added + updated + skipped
    logger.info(
        f"[symbolic] Pipeline complete: {total_processed} processed, "
        f"{added} added, {updated} updated, {skipped} skipped, "
        f"{len(errors)} errors"
    )

    return {
        'success': True,
        'processed': total_processed,
        'added': added,
        'updated': updated,
        'skipped': skipped,
        'errors': errors
    }


# =============================================================================
# RETRIEVAL API - Delegated to handlers
# =============================================================================

def retrieve_fragments(
    query: str | None = None,
    dimension_filters: Dict[str, str] | None = None,
    trigger_keywords: List[str] | None = None,
    n_results: int = 5,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Retrieve fragments using combined search methods

    Combines vector similarity with dimension filtering and trigger matching.

    Args:
        query: Optional search query for vector similarity
        dimension_filters: Optional dict of dimension filters
        trigger_keywords: Optional list of trigger keywords
        n_results: Number of results to return
        db_path: Optional ChromaDB path (default: MEMORY_BANK/.chroma)

    Returns:
        Dict with 'success', 'results' list with relevance scores
    """
    return retriever.retrieve_fragments(query, dimension_filters, trigger_keywords, n_results, db_path)


def search_fragments_by_vector(
    query: str,
    n_results: int = 5,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by vector similarity only

    Args:
        query: Search query text
        n_results: Number of results to return
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'results' list
    """
    return retriever.search_by_vector(query, n_results, db_path)


def search_fragments_by_dimensions(
    dimension_filters: Dict[str, str],
    n_results: int = 5,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by dimension filters only

    Args:
        dimension_filters: Dict of dimension_key: value pairs
        n_results: Number of results to return
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'results' list
    """
    return retriever.search_by_dimensions(dimension_filters, n_results, db_path)


def search_fragments_by_triggers(
    keywords: List[str],
    n_results: int = 5,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Search fragments by trigger keywords only

    Args:
        keywords: List of keywords to search
        n_results: Number of results to return
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'results' list
    """
    return retriever.search_by_triggers(keywords, n_results, db_path)


# =============================================================================
# HOOK API - Delegated to handlers
# =============================================================================

def extract_conversation_context(
    messages: List[Dict[str, Any]],
    max_messages: int = 5
) -> Dict[str, Any]:
    """
    Extract keywords, themes, and mood from recent conversation messages

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        max_messages: Maximum recent messages to analyze

    Returns:
        Dict with 'success', 'keywords', 'mood', 'themes'
    """
    return hook.extract_conversation_context(messages, max_messages)


def find_relevant_fragments(
    context: Dict[str, Any],
    n_results: int = 3,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Query fragments based on extracted conversation context

    Args:
        context: Output from extract_conversation_context()
        n_results: Maximum fragments to return
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'fragments' list with relevance scores
    """
    return hook.find_relevant_fragments(context, n_results, db_path)


def format_fragment_recall(fragment: Dict[str, Any]) -> str:
    """
    Format a fragment as natural recall text

    Creates a "This reminds me of..." style output.

    Args:
        fragment: Fragment dict with 'content' and 'metadata'

    Returns:
        Formatted recall string
    """
    return hook.format_fragment_recall(fragment)


def should_surface_fragment(
    fragment: Dict[str, Any] | None = None,
    config: Dict[str, Any] | None = None
) -> tuple:
    """
    Check if a fragment should be surfaced based on rules

    Args:
        fragment: Optional fragment to check
        config: Optional config dict

    Returns:
        Tuple of (should_surface: bool, reason: str)
    """
    return hook.should_surface_fragment(fragment, config)


def process_hook(
    messages: List[Dict[str, Any]],
    config: Dict[str, Any] | None = None,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Main hook function - process messages and surface relevant fragments

    Args:
        messages: Recent conversation messages
        config: Optional config dict
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'surfaced' bool, 'recall' text if surfaced
    """
    return hook.process_hook(messages, config, db_path)


def load_hook_config(config_path: Path | None = None) -> Dict[str, Any]:
    """
    Load hook configuration from JSON file

    Args:
        config_path: Path to config JSON

    Returns:
        Dict with configuration values
    """
    return hook.load_config(config_path)


def reset_hook_session() -> None:
    """Reset hook session state for new conversation"""
    return hook.reset_session()


def get_hook_session_state() -> Dict[str, Any]:
    """
    Get current hook session state for debugging

    Returns:
        Dict with session state values
    """
    return hook.get_session_state()


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle symbolic memory commands

    Commands supported:
    - analyze <file>: Analyze a JSON conversation file (v1 pipeline)
    - extract <file>: Extract and store fragments via LLM (v2 pipeline)
    - fragments <query>: Search symbolic fragments
    - hook-test <text>: Test hook with sample conversation
    - demo: Run a demonstration analysis
    - help: Show help message

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    if command in ('--help', '-h', 'help'):
        print_help()
        return True

    if command == 'demo':
        run_demo()
        return True

    if command == 'analyze':
        if not args:
            console.print("[red]Error:[/red] File path required")
            console.print("Usage: symbolic analyze <conversation.json>")
            return True
        analyze_file(args[0])
        return True

    if command == 'extract':
        if not args:
            console.print("[red]Error:[/red] File path required")
            console.print("Usage: symbolic extract <conversation.json>")
            return True
        extract_file(args[0], source_branch=args[1] if len(args) > 1 else None)
        return True

    if command == 'bootstrap':
        max_sessions = 8
        for arg in args:
            if arg.startswith('--max='):
                max_sessions = int(arg.split('=')[1])
        bootstrap_from_jsonl(max_sessions=max_sessions)
        return True

    if command == 'fragments':
        search_fragments_cli(args)
        return True

    if command == 'hook-test':
        run_hook_test(args)
        return True

    return False


def print_help() -> None:
    """Display symbolic module help"""
    console.print()
    header("Symbolic Memory Module - Conversation Analysis")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  python3 symbolic.py <command> [args]")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]demo[/cyan]               Run demonstration analysis (v1 + v2 mock)")
    console.print("  [cyan]analyze <file>[/cyan]     Analyze a conversation JSON file (v1 pipeline)")
    console.print("  [cyan]extract <file>[/cyan]     Extract fragments via LLM and store (v2 pipeline)")
    console.print("  [cyan]bootstrap[/cyan]           Populate fragments from session JONLs (--max=N)")
    console.print("  [cyan]fragments <query>[/cyan]  Search symbolic fragments (v1 + v2)")
    console.print("  [cyan]hook-test <text>[/cyan]   Test hook with sample conversation text")
    console.print("  [cyan]help[/cyan]               Show this help message")
    console.print()
    console.print("[bold]FRAGMENTS OPTIONS:[/bold]")
    console.print("  [cyan]--dimension KEY=VALUE[/cyan]  Filter by dimension (e.g., emotional_0=frustration)")
    console.print("  [cyan]--trigger KEYWORD[/cyan]      Match trigger keyword")
    console.print("  [cyan]--n N[/cyan]                  Number of results (default: 5)")
    console.print()
    console.print("[bold]HOOK-TEST OPTIONS:[/bold]")
    console.print("  [cyan]--bypass[/cyan]               Bypass frequency/cooldown checks")
    console.print()
    console.print("[bold]EXTRACTED DIMENSIONS:[/bold]")
    console.print("  [yellow]Technical Flow[/yellow]       - problem/debug/breakthrough patterns")
    console.print("  [yellow]Emotional Journey[/yellow]    - frustration/excitement arcs")
    console.print("  [yellow]Collaboration[/yellow]        - user_directed/balanced dynamics")
    console.print("  [yellow]Key Learnings[/yellow]        - discoveries, insights")
    console.print("  [yellow]Context Triggers[/yellow]     - keywords that should surface memory")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  # Run demo analysis")
    console.print("  [dim]python3 symbolic.py demo[/dim]")
    console.print()
    console.print("  # Analyze conversation file (v1 dimensions)")
    console.print("  [dim]python3 symbolic.py analyze chat_history.json[/dim]")
    console.print()
    console.print("  # Extract and store via LLM (v2 pipeline)")
    console.print("  [dim]python3 symbolic.py extract chat_history.json[/dim]")
    console.print()
    console.print("  # Extract with source branch tag")
    console.print("  [dim]python3 symbolic.py extract chat_history.json memory_bank[/dim]")
    console.print()
    console.print("  # Search fragments by query")
    console.print("  [dim]python3 symbolic.py fragments \"debugging frustration\"[/dim]")
    console.print()
    console.print("  # Search with dimension filter")
    console.print("  [dim]python3 symbolic.py fragments \"debug\" --dimension emotional_0=frustration_to_breakthrough[/dim]")
    console.print()
    console.print("  # Search with trigger keywords")
    console.print("  [dim]python3 symbolic.py fragments \"error\" --trigger error --trigger debug[/dim]")
    console.print()
    console.print("  # Test hook with sample text")
    console.print("  [dim]python3 symbolic.py hook-test \"I'm stuck on this error\"[/dim]")
    console.print()
    console.print("  # Test hook bypassing cooldown")
    console.print("  [dim]python3 symbolic.py hook-test \"debugging frustration\" --bypass[/dim]")
    console.print()


def run_demo() -> None:
    """Run demonstration of symbolic analysis"""
    console.print()
    header("Symbolic Memory - Demo Analysis")
    console.print()

    # Sample conversation
    demo_chat = [
        {"role": "user", "content": "I have an error in my code, it keeps failing and I'm stuck"},
        {"role": "assistant", "content": "Let me help debug this issue. Can you trace where it's failing?"},
        {"role": "user", "content": "I tried checking the logs but I'm confused about what's wrong"},
        {"role": "assistant", "content": "Let's try a different approach. I'll explain the fix step by step."},
        {"role": "user", "content": "Got it! That works! Finally a breakthrough! This is awesome!"}
    ]

    console.print("[cyan]Sample conversation:[/cyan]")
    for msg in demo_chat:
        role = msg['role'].capitalize()
        console.print(f"  [{role}]: {msg['content'][:60]}...")
    console.print()

    # Analyze
    result = analyze_conversation(demo_chat)

    if result['success']:
        dims = result['dimensions']
        meta = result['metadata']

        console.print("[green]✓[/green] Analysis complete")
        console.print()

        console.print("[bold cyan]Extracted Dimensions:[/bold cyan]")
        console.print(f"  [yellow]Technical:[/yellow]     {dims.get('technical', [])}")
        console.print(f"  [yellow]Emotional:[/yellow]     {dims.get('emotional', [])}")
        console.print(f"  [yellow]Collaboration:[/yellow] {dims.get('collaboration', [])}")
        console.print(f"  [yellow]Learnings:[/yellow]     {dims.get('learnings', [])}")
        console.print(f"  [yellow]Triggers:[/yellow]      {dims.get('triggers', [])}")
        console.print()

        console.print("[bold cyan]Metadata:[/bold cyan]")
        console.print(f"  [dim]Messages:[/dim] {result['message_count']}")
        console.print(f"  [dim]Words:[/dim]    {meta.get('total_words', 0)}")
        console.print(f"  [dim]Depth:[/dim]    {meta.get('depth', 'unknown')}")
        console.print()
    else:
        console.print(f"[red]✗[/red] Analysis failed: {result.get('error', 'Unknown error')}")

    # v2 LLM Extraction mock preview
    console.print()
    header("v2 LLM Extraction (mock - requires API)")
    console.print()

    mock_fragments = [
        {
            "summary": "User was stuck on a code error for a while, then solved it with assistant's step-by-step debugging guidance",
            "insight": "Step-by-step debugging with explanation is more effective than just providing the fix",
            "type": "episodic",
            "triggers": ["error", "debug", "stuck", "breakthrough"],
            "emotional_tone": "excited",
            "technical_domain": "debugging"
        },
        {
            "summary": "Collaborative pattern where assistant explains reasoning before giving solutions leads to better understanding",
            "insight": "Teaching approach builds deeper knowledge than direct answers",
            "type": "procedural",
            "triggers": ["explain", "step by step", "understanding"],
            "emotional_tone": "focused",
            "technical_domain": "collaboration"
        }
    ]

    for i, frag in enumerate(mock_fragments, 1):
        console.print(f"  [bold cyan]Fragment {i}:[/bold cyan]")
        console.print(f"    [yellow]Type:[/yellow]       {frag['type']}")
        console.print(f"    [yellow]Summary:[/yellow]    {frag['summary']}")
        console.print(f"    [yellow]Insight:[/yellow]    {frag['insight']}")
        console.print(f"    [yellow]Tone:[/yellow]       {frag['emotional_tone']}")
        console.print(f"    [yellow]Domain:[/yellow]     {frag['technical_domain']}")
        console.print(f"    [yellow]Triggers:[/yellow]   {', '.join(frag['triggers'])}")

        # Show how format_fragment_recall would render this
        mock_stored = {
            'content': frag['summary'],
            'metadata': {
                'schema_version': 'v2',
                'summary': frag['summary'],
                'insight': frag['insight'],
                'type': frag['type'],
                'emotional_tone': frag['emotional_tone'],
                'technical_domain': frag['technical_domain'],
            }
        }
        recall = format_fragment_recall(mock_stored)
        console.print(f"    [green]Recall:[/green]     {recall}")
        console.print()

    console.print("[dim]Note: Run 'symbolic extract <file>' to use the real LLM pipeline[/dim]")
    console.print()


def search_fragments_cli(args: List[str]) -> None:
    """Execute fragment search from CLI arguments"""
    from rich.panel import Panel

    # Parse arguments
    query_parts = []
    dimension_filters: Dict[str, str] = {}
    trigger_keywords: List[str] = []
    n_results = 5

    i = 0
    while i < len(args):
        if args[i] == '--dimension' and i + 1 < len(args):
            # Parse KEY=VALUE
            dim_arg = args[i + 1]
            if '=' in dim_arg:
                key, value = dim_arg.split('=', 1)
                dimension_filters[key] = value
            else:
                console.print(f"[red]Error:[/red] Invalid dimension format: {dim_arg}")
                console.print("Expected: --dimension KEY=VALUE")
                return
            i += 2
        elif args[i] == '--trigger' and i + 1 < len(args):
            trigger_keywords.append(args[i + 1])
            i += 2
        elif args[i] == '--n' and i + 1 < len(args):
            try:
                n_results = int(args[i + 1])
            except ValueError:
                console.print(f"[red]Error:[/red] Invalid number: {args[i + 1]}")
                return
            i += 2
        else:
            query_parts.append(args[i])
            i += 1

    query = ' '.join(query_parts) if query_parts else None

    if not query and not dimension_filters and not trigger_keywords:
        console.print("[red]Error:[/red] Search query, dimension filter, or trigger required")
        console.print("Usage: symbolic fragments <query> [--dimension KEY=VALUE] [--trigger KEYWORD]")
        return

    console.print()
    header("Symbolic Fragments - Search")
    console.print()

    if query:
        console.print(f"[cyan]Query:[/cyan] {query}")
    if dimension_filters:
        console.print(f"[cyan]Dimensions:[/cyan] {dimension_filters}")
    if trigger_keywords:
        console.print(f"[cyan]Triggers:[/cyan] {trigger_keywords}")
    console.print()

    # Execute search
    console.print("[dim]Searching fragments...[/dim]")

    result = retrieve_fragments(
        query=query,
        dimension_filters=dimension_filters if dimension_filters else None,
        trigger_keywords=trigger_keywords if trigger_keywords else None,
        n_results=n_results
    )

    if not result.get('success'):
        error_msg = result.get('error', 'Unknown error')
        logger.error(f"[symbolic] Fragment search failed: {error_msg}")
        console.print(f"[red]Error:[/red] {error_msg}")
        return

    results = result.get('results', [])
    methods = result.get('search_methods', [])

    console.print(f"[green]Found {len(results)} fragments[/green] (methods: {', '.join(methods)})")
    console.print()

    if not results:
        console.print("[yellow]No matching fragments found[/yellow]")
        console.print()
        console.print("[dim]Try:[/dim]")
        console.print("  Different search terms")
        console.print("  Broader query without filters")
        console.print("  Store fragments first: python3 symbolic.py demo")
        return

    # Display results
    for i, frag in enumerate(results, 1):
        content = frag.get('content', '')
        metadata = frag.get('metadata', {})
        relevance = frag.get('relevance_score', frag.get('similarity', 0))
        sources = frag.get('_sources', ['unknown'])
        tier = frag.get('relevance_tier', '')

        # Build metadata display
        meta_lines = []
        if metadata.get('timestamp'):
            meta_lines.append(f"Time: {metadata['timestamp']}")
        if metadata.get('source_branch'):
            meta_lines.append(f"Branch: {metadata['source_branch']}")

        # Schema-aware metadata display
        if metadata.get('schema_version') == 'v2':
            # v2 fragment: show summary, insight, type, tone, domain
            if metadata.get('type'):
                meta_lines.append(f"Type: {metadata['type']}")
            if metadata.get('emotional_tone'):
                meta_lines.append(f"Tone: {metadata['emotional_tone']}")
            if metadata.get('technical_domain'):
                meta_lines.append(f"Domain: {metadata['technical_domain']}")

            meta_text = " | ".join(meta_lines) if meta_lines else ""

            # Build rich content for v2
            panel_content = ""
            if metadata.get('summary'):
                panel_content += f"[bold]Summary:[/bold] {metadata['summary']}\n"
            if metadata.get('insight'):
                panel_content += f"[bold]Insight:[/bold] {metadata['insight']}\n"
            if content and content != metadata.get('summary', ''):
                panel_content += f"\n> {content}\n"
            if meta_text:
                panel_content += f"\n[dim]{meta_text}[/dim]"
        else:
            # v1 fragment: show dimensions
            if metadata.get('depth'):
                meta_lines.append(f"Depth: {metadata['depth']}")

            dim_parts = []
            for key in ['technical_0', 'emotional_0', 'collaboration_0', 'learnings_0']:
                if key in metadata:
                    dim_parts.append(f"{key.replace('_0', '')}: {metadata[key]}")
            if dim_parts:
                meta_lines.append(f"Dims: {', '.join(dim_parts)}")

            meta_text = " | ".join(meta_lines) if meta_lines else ""

            panel_content = content
            if meta_text:
                panel_content += f"\n\n[dim]{meta_text}[/dim]"

        schema_tag = f"v2" if metadata.get('schema_version') == 'v2' else "v1"
        tier_tag = f" [{tier}]" if tier else ""
        panel_title = f"Result {i} ({schema_tag}) - Relevance: {relevance:.2%}{tier_tag} (via {', '.join(sources)})"

        console.print(Panel(
            panel_content,
            title=panel_title,
            title_align="left",
            border_style="cyan" if relevance > 0.7 else "blue" if relevance > 0.5 else "dim"
        ))

    console.print()
    logger.info(f"[symbolic] Displayed {len(results)} fragment results")


def run_hook_test(args: List[str]) -> None:
    """Test hook with sample conversation text"""
    from rich.panel import Panel

    # Parse arguments
    text_parts = []
    bypass_checks = False

    for arg in args:
        if arg == '--bypass':
            bypass_checks = True
        else:
            text_parts.append(arg)

    text = ' '.join(text_parts) if text_parts else "I'm stuck on this error and need help debugging"

    console.print()
    header("Fragmented Memory Hook - Test")
    console.print()

    # Build sample messages from text
    messages = [
        {"role": "user", "content": text}
    ]

    console.print(f"[cyan]Test input:[/cyan] {text}")
    console.print(f"[cyan]Bypass checks:[/cyan] {bypass_checks}")
    console.print()

    # Reset session for clean test
    reset_hook_session()

    # If bypassing, set session state to allow surfacing
    if bypass_checks:
        hook.SESSION_STATE['messages_since_last'] = 100
        hook.SESSION_STATE['last_surface_time'] = 0

    # Extract context first
    console.print("[bold]Step 1: Context Extraction[/bold]")
    context = extract_conversation_context(messages)

    if context.get('success'):
        console.print(f"  [green]Keywords:[/green] {context.get('keywords', [])}")
        console.print(f"  [green]Mood:[/green] {context.get('mood', 'neutral')}")
        console.print(f"  [green]Themes:[/green] {context.get('themes', [])}")
    else:
        console.print(f"  [red]Failed:[/red] {context.get('error', 'Unknown')}")
        return

    console.print()

    # Find relevant fragments
    console.print("[bold]Step 2: Fragment Search[/bold]")
    frag_result = find_relevant_fragments(context, n_results=3)

    if frag_result.get('success'):
        fragments = frag_result.get('fragments', [])
        console.print(f"  [green]Query used:[/green] {frag_result.get('query_used', '')}")
        console.print(f"  [green]Threshold:[/green] {frag_result.get('threshold_applied', 0.3)}")
        console.print(f"  [green]Fragments found:[/green] {len(fragments)}")

        if fragments:
            for i, frag in enumerate(fragments, 1):
                score = frag.get('relevance_score', frag.get('similarity', 0))
                content = frag.get('content', '')[:80]
                console.print(f"    [{i}] Score: {score:.2%} - {content}...")
    else:
        console.print(f"  [yellow]No fragments:[/yellow] {frag_result.get('message', frag_result.get('error', ''))}")

    console.print()

    # Check surfacing rules
    console.print("[bold]Step 3: Surfacing Check[/bold]")
    can_surface, reason = should_surface_fragment()
    console.print(f"  [cyan]Can surface:[/cyan] {can_surface}")
    console.print(f"  [cyan]Reason:[/cyan] {reason}")

    console.print()

    # Run full hook process
    console.print("[bold]Step 4: Full Hook Process[/bold]")
    result = process_hook(messages)

    if result.get('success'):
        if result.get('surfaced'):
            console.print("[green]Fragment surfaced![/green]")
            console.print()

            recall = result.get('recall', '')
            console.print(Panel(
                recall,
                title="Memory Recall",
                border_style="green"
            ))

            console.print()
            console.print(f"[dim]Fragment ID: {result.get('fragment_id')}[/dim]")
            console.print(f"[dim]Relevance: {result.get('relevance_score', 0):.2%}[/dim]")
        else:
            console.print(f"[yellow]Not surfaced:[/yellow] {result.get('reason', 'Unknown')}")
    else:
        console.print(f"[red]Hook failed:[/red] {result.get('error', 'Unknown')}")

    console.print()

    # v2 Format Preview - show how found fragments would look with v2 formatting
    console.print("[bold]Step 5: v2 Format Preview[/bold]")
    if frag_result.get('success') and frag_result.get('fragments'):
        for i, frag in enumerate(frag_result['fragments'], 1):
            frag_metadata = frag.get('metadata', {})
            if frag_metadata.get('schema_version') == 'v2':
                recall_preview = format_fragment_recall(frag)
                console.print(f"  [green]Fragment {i} (v2):[/green] {recall_preview}")
            else:
                # Show what it would look like if it were v2
                console.print(f"  [dim]Fragment {i} (v1 - no v2 metadata)[/dim]")
                recall_preview = format_fragment_recall(frag)
                console.print(f"    [dim]Current format:[/dim] {recall_preview[:100]}...")
    else:
        console.print("  [dim]No fragments found to preview[/dim]")
    console.print()

    # Show session state
    console.print("[bold]Session State:[/bold]")
    state = get_hook_session_state()
    console.print(f"  [dim]Fragments surfaced:[/dim] {state.get('fragments_surfaced', 0)}")
    console.print(f"  [dim]Messages since last:[/dim] {state.get('messages_since_last', 0)}")
    console.print()


def analyze_file(file_path: str) -> None:
    """Analyze a conversation JSON file"""
    from MEMORY_BANK.apps.handlers.json import json_handler

    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        return

    read_result = json_handler.read_memory_file(path)
    if not read_result.get('success'):
        console.print(f"[red]Error:[/red] {read_result.get('error', 'Failed to read JSON')}")
        return

    chat_history = read_result.get('data')

    if not isinstance(chat_history, list):
        console.print("[red]Error:[/red] Expected JSON array of messages")
        return

    console.print()
    header(f"Analyzing: {path.name}")
    console.print()

    result = analyze_conversation(chat_history)

    if result['success']:
        dims = result['dimensions']
        meta = result['metadata']

        console.print("[green]✓[/green] Analysis complete")
        console.print()

        console.print("[bold cyan]Extracted Dimensions:[/bold cyan]")
        console.print(f"  [yellow]Technical:[/yellow]     {dims.get('technical', [])}")
        console.print(f"  [yellow]Emotional:[/yellow]     {dims.get('emotional', [])}")
        console.print(f"  [yellow]Collaboration:[/yellow] {dims.get('collaboration', [])}")
        console.print(f"  [yellow]Learnings:[/yellow]     {dims.get('learnings', [])}")
        console.print(f"  [yellow]Triggers:[/yellow]      {dims.get('triggers', [])}")
        console.print()

        console.print("[bold cyan]Metadata:[/bold cyan]")
        console.print(f"  [dim]Messages:[/dim] {result['message_count']}")
        console.print(f"  [dim]Words:[/dim]    {meta.get('total_words', 0)}")
        console.print(f"  [dim]Depth:[/dim]    {meta.get('depth', 'unknown')}")
        console.print()
    else:
        console.print(f"[red]✗[/red] Analysis failed: {result.get('error', 'Unknown error')}")


def extract_file(file_path: str, source_branch: str | None = None) -> None:
    """
    Extract and store v2 LLM fragments from a conversation JSON file

    Reads a JSON conversation file and runs the full v2 pipeline:
    extract via LLM, deduplicate via AUDN, and store in ChromaDB.

    Args:
        file_path: Path to JSON conversation file
        source_branch: Optional branch name tag for stored fragments
    """
    from MEMORY_BANK.apps.handlers.json import json_handler

    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        return

    read_result = json_handler.read_memory_file(path)
    if not read_result.get('success'):
        console.print(f"[red]Error:[/red] {read_result.get('error', 'Failed to read JSON')}")
        return

    chat_history = read_result.get('data')

    if not isinstance(chat_history, list):
        console.print("[red]Error:[/red] Expected JSON array of messages")
        return

    console.print()
    header(f"v2 LLM Extract: {path.name}")
    console.print()

    console.print(f"[cyan]Messages:[/cyan] {len(chat_history)}")
    if source_branch:
        console.print(f"[cyan]Branch:[/cyan] {source_branch}")
    console.print()

    console.print("[dim]Running LLM extraction pipeline...[/dim]")
    logger.info(f"[symbolic] extract_file: {path.name} ({len(chat_history)} messages)")

    result = extract_and_store_llm(chat_history, source_branch=source_branch)

    if result.get('success'):
        console.print("[green]Pipeline complete[/green]")
        console.print()
        console.print(f"  [cyan]Processed:[/cyan]  {result.get('processed', 0)}")
        console.print(f"  [green]Added:[/green]      {result.get('added', 0)}")
        console.print(f"  [yellow]Updated:[/yellow]    {result.get('updated', 0)}")
        console.print(f"  [dim]Skipped:[/dim]    {result.get('skipped', 0)}")

        if result.get('errors'):
            console.print()
            console.print(f"  [red]Errors ({len(result['errors'])}):[/red]")
            for err in result['errors']:
                console.print(f"    - {err}")
    else:
        console.print(f"[red]Pipeline failed:[/red] {result.get('errors', ['Unknown error'])}")

    console.print()
    logger.info(f"[symbolic] extract_file complete: {result}")


# =============================================================================
# BOOTSTRAP - Populate fragments from session JONLs
# =============================================================================


def _parse_jsonl_to_chat_history(jsonl_path: Path) -> List[Dict[str, Any]]:
    """
    Convert a Claude Code JSONL transcript to chat_history format.

    Reads the JSONL file, extracts user and assistant text messages,
    and returns them in the [{role, content}] format expected by
    extract_and_store_llm().

    Args:
        jsonl_path: Path to a .jsonl transcript file

    Returns:
        List of {role, content} message dicts
    """
    messages = []
    try:
        with open(jsonl_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get('type', '')
                msg_data = entry.get('message', {})
                role = msg_data.get('role', '')
                content = msg_data.get('content', '')

                if msg_type == 'user' and role == 'user':
                    if isinstance(content, str) and content.strip():
                        messages.append({'role': 'user', 'content': content.strip()})
                    elif isinstance(content, list):
                        texts = [
                            item.get('text', '').strip()
                            for item in content
                            if isinstance(item, dict)
                            and item.get('type') == 'text'
                            and item.get('text', '').strip()
                        ]
                        if texts:
                            messages.append({'role': 'user', 'content': ' '.join(texts)})

                elif msg_type == 'assistant' and role == 'assistant':
                    if isinstance(content, str) and content.strip():
                        messages.append({'role': 'assistant', 'content': content.strip()})
                    elif isinstance(content, list):
                        texts = [
                            item.get('text', '').strip()
                            for item in content
                            if isinstance(item, dict)
                            and item.get('type') == 'text'
                            and item.get('text', '').strip()
                        ]
                        if texts:
                            messages.append({'role': 'assistant', 'content': ' '.join(texts)})

    except OSError as e:
        logger.error(f"[symbolic] Failed to read JSONL: {e}")

    return messages


def _find_bootstrap_sessions(max_sessions: int = 8) -> List[Path]:
    """
    Find diverse, medium-sized JSONL session files for bootstrapping.

    Selects sessions from different branches, preferring files between
    100KB and 3MB (rich enough for fragments, not too large to process).

    Args:
        max_sessions: Maximum number of sessions to return

    Returns:
        List of JSONL file paths
    """
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return []

    # Priority branch directories (diverse content sources)
    priority_dirs = [
        '-home-aipass-MEMORY-BANK',
        '-home-aipass-aipass-os-dev-central',
        '-home-aipass-seed',
        '-home-aipass-aipass-core-drone',
        '-home-aipass-aipass-core-flow',
        '-home-aipass-The-Commons',
        '-home-aipass-aipass-core-prax',
        '-home-aipass-aipass-core-cortex',
        '-home-aipass-aipass-core-ai-mail',
        '-home-aipass-aipass-core-api',
    ]

    selected = []
    seen_dirs = set()

    # First pass: one per priority branch (medium-sized files)
    for dirname in priority_dirs:
        if len(selected) >= max_sessions:
            break
        branch_dir = projects_dir / dirname
        if not branch_dir.exists():
            continue

        candidates = []
        for f in branch_dir.glob("*.jsonl"):
            if f.name.startswith("agent-"):
                continue
            size = f.stat().st_size
            # 100KB-3MB range: rich enough, not too large
            if 100_000 <= size <= 3_000_000:
                candidates.append((f, size))

        if candidates:
            # Pick the largest in range (most content)
            candidates.sort(key=lambda x: x[1], reverse=True)
            selected.append(candidates[0][0])
            seen_dirs.add(dirname)

    # Second pass: fill remaining slots from any branch
    if len(selected) < max_sessions:
        for project_dir in projects_dir.iterdir():
            if len(selected) >= max_sessions:
                break
            if not project_dir.is_dir() or project_dir.name in seen_dirs:
                continue
            candidates = []
            for f in project_dir.glob("*.jsonl"):
                if f.name.startswith("agent-"):
                    continue
                size = f.stat().st_size
                if 100_000 <= size <= 3_000_000:
                    candidates.append((f, size))
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                selected.append(candidates[0][0])

    return selected


def bootstrap_from_jsonl(max_sessions: int = 8) -> None:
    """
    Bootstrap the fragment collection from existing session JONLs.

    Finds diverse session transcripts in ~/.claude/projects/, converts
    them to chat_history format, and runs them through the full v2
    LLM extraction + AUDN dedup + storage pipeline.

    Args:
        max_sessions: Maximum number of sessions to process
    """
    console.print()
    header("Fragment Bootstrap from Session JONLs")
    console.print()

    # Find sessions
    console.print("[dim]Scanning for session files...[/dim]")
    sessions = _find_bootstrap_sessions(max_sessions)

    if not sessions:
        console.print("[red]No suitable session files found in ~/.claude/projects/[/red]")
        return

    console.print(f"[cyan]Found {len(sessions)} sessions to process[/cyan]")
    console.print()

    total_added = 0
    total_updated = 0
    total_skipped = 0
    total_errors = 0
    processed_count = 0

    for i, jsonl_path in enumerate(sessions, 1):
        # Derive branch name from parent directory
        branch_dir = jsonl_path.parent.name
        branch_name = branch_dir.replace('-home-aipass-', '').replace('-', '_').upper()
        if branch_name.startswith('AIPASS_CORE_'):
            branch_name = branch_name.replace('AIPASS_CORE_', '')
        if branch_name.startswith('AIPASS_OS_'):
            branch_name = branch_name.replace('AIPASS_OS_', '')

        file_size_kb = jsonl_path.stat().st_size / 1024
        console.print(
            f"[cyan][{i}/{len(sessions)}][/cyan] "
            f"{branch_name} ({file_size_kb:.0f}KB) - "
            f"[dim]{jsonl_path.name[:12]}...[/dim]"
        )

        # Convert JSONL to chat_history
        chat_history = _parse_jsonl_to_chat_history(jsonl_path)
        if len(chat_history) < 4:
            console.print("  [dim]Too few messages, skipping[/dim]")
            continue

        console.print(f"  {len(chat_history)} messages, extracting...")
        logger.info(
            f"[symbolic] bootstrap [{i}/{len(sessions)}]: "
            f"{branch_name} ({len(chat_history)} msgs)"
        )

        # Run the extraction pipeline
        result = extract_and_store_llm(
            chat_history,
            source_branch=branch_name
        )

        if result.get('success'):
            a = result.get('added', 0)
            u = result.get('updated', 0)
            s = result.get('skipped', 0)
            e = len(result.get('errors', []))
            total_added += a
            total_updated += u
            total_skipped += s
            total_errors += e
            processed_count += 1
            console.print(
                f"  [green]+{a} added[/green]"
                f"{f', {u} updated' if u else ''}"
                f"{f', {s} skipped' if s else ''}"
                f"{f', [red]{e} errors[/red]' if e else ''}"
            )
        else:
            total_errors += 1
            err_msg = result.get('errors', ['Unknown'])
            console.print(f"  [red]Failed: {err_msg}[/red]")

        # Brief pause between API calls to avoid rate limiting
        if i < len(sessions):
            time.sleep(2)

    # Summary
    console.print()
    header("Bootstrap Summary")
    console.print()
    console.print(f"  [cyan]Sessions processed:[/cyan] {processed_count}/{len(sessions)}")
    console.print(f"  [green]Fragments added:[/green]   {total_added}")
    console.print(f"  [yellow]Fragments updated:[/yellow] {total_updated}")
    console.print(f"  [dim]Skipped (dedup):[/dim]   {total_skipped}")
    if total_errors:
        console.print(f"  [red]Errors:[/red]             {total_errors}")
    console.print()

    # Verify collection count
    try:
        import chromadb
        client = chromadb.PersistentClient(
            path=str(Path(__file__).resolve().parent.parent.parent / '.chroma')
        )
        col = client.get_collection('symbolic_fragments')
        console.print(f"  [bold green]Collection total: {col.count()} fragments[/bold green]")
    except Exception:
        pass

    console.print()
    logger.info(
        f"[symbolic] bootstrap complete: {processed_count} sessions, "
        f"{total_added} added, {total_updated} updated, "
        f"{total_skipped} skipped, {total_errors} errors"
    )


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    # Handle --help before argparse (module standard)
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h', 'help'):
        handle_command('help', [])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        console.print(f"[red]Unknown command:[/red] {command}")
        console.print("Run with [cyan]help[/cyan] for available commands")
        sys.exit(1)
