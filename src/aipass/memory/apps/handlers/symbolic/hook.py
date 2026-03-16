#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: hook.py - Fragmented Memory Hook Handler
# Date: 2026-02-04
# Version: 0.2.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-02-15): v2 schema support in format_fragment_recall/format_multiple_recalls
#   - v0.1.0 (2026-02-04): Initial version - Fragmented Memory Phase 4
#
# CODE STANDARDS:
#   - Handler independence: No module imports
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <300 lines target
# =============================================

"""
Fragmented Memory Hook Handler

Surfaces relevant memory fragments during conversation without explicit queries.
Implements the "This reminds me of..." associative memory pattern.

Key Functions:
    - extract_conversation_context() - get keywords/themes from recent messages
    - find_relevant_fragments() - query fragments based on context
    - format_fragment_recall() - format as natural "reminds me of..." text
    - should_surface_fragment() - check threshold/frequency rules
    - load_config() - load configuration from JSON file
"""

import re
import time
from pathlib import Path
from typing import Dict, List, Any, Tuple

# Infrastructure setup
import sys
AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))

# Handler imports (domain-organized, no modules)
from MEMORY_BANK.apps.handlers.symbolic import retriever
from MEMORY_BANK.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_CONFIG_PATH = Path.home() / "MEMORY_BANK" / "apps" / "json_templates" / "custom" / "fragmented_memory_config.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "threshold": 0.3,
    "max_fragments_per_session": 5,
    "min_messages_between": 10,
    "cooldown_seconds": 300
}

# Session state for tracking surfacing frequency
SESSION_STATE = {
    "fragments_surfaced": 0,
    "messages_since_last": 0,
    "last_surface_time": 0,
    "surfaced_ids": set()
}


# =============================================================================
# CONFIGURATION
# =============================================================================

def load_config(config_path: Path | None = None) -> Dict[str, Any]:
    """
    Load hook configuration from JSON file

    Args:
        config_path: Path to config JSON (default: fragmented_memory_config.json)

    Returns:
        Dict with configuration values, defaults used if file not found
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if path.exists():
        result = json_handler.read_memory_file(path)
        if result.get('success'):
            config = result.get('data', {})
            # Merge with defaults for any missing keys
            return {**DEFAULT_CONFIG, **config}

    return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any], config_path: Path | None = None) -> Dict[str, Any]:
    """
    Save hook configuration to JSON file

    Args:
        config: Configuration dict to save
        config_path: Path to config JSON

    Returns:
        Dict with 'success' and details
    """
    path = config_path or DEFAULT_CONFIG_PATH

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    return json_handler.write_memory_file(path, config)


# =============================================================================
# CONTEXT EXTRACTION
# =============================================================================

def extract_conversation_context(
    messages: List[Dict[str, Any]],
    max_messages: int = 5
) -> Dict[str, Any]:
    """
    Extract keywords, themes, and mood from recent conversation messages

    Analyzes recent messages to identify:
    - Key terms and keywords
    - Emotional tone/mood
    - Technical themes

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        max_messages: Maximum recent messages to analyze

    Returns:
        Dict with 'success', 'keywords', 'mood', 'themes'
    """
    if not messages:
        return {
            'success': True,
            'keywords': [],
            'mood': 'neutral',
            'themes': [],
            'message': 'No messages to analyze'
        }

    # Take only recent messages
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    # Combine all content
    all_content = ' '.join((msg.get('content') or '') for msg in recent).lower()

    # Extract keywords (technical terms and significant words)
    keyword_pattern = (
        r'\b(?:error|bug|fix|debug|issue|problem|solution|work|stuck|'
        r'module|system|memory|vector|storage|file|function|method|class|'
        r'api|token|embedding|json|import|script|handler|branch|pattern|'
        r'frustrated|excited|confused|understand|learn|discover|insight|'
        r'help|create|build|implement|design|architecture)\b'
    )

    keywords = list(set(re.findall(keyword_pattern, all_content)))

    # Detect mood
    mood = _detect_mood(all_content)

    # Extract themes
    themes = _extract_themes(all_content)

    return {
        'success': True,
        'keywords': keywords[:10],  # Limit to top 10
        'mood': mood,
        'themes': themes,
        'analyzed_messages': len(recent),
        'content_length': len(all_content)
    }


def _detect_mood(content: str) -> str:
    """
    Detect emotional mood from content

    Args:
        content: Text content to analyze

    Returns:
        Detected mood string (frustrated, curious, excited, confused, focused, or neutral)
    """
    mood_indicators = {
        'frustrated': ['frustrated', 'annoying', 'stuck', 'difficult', 'ugh', 'damn', 'hate'],
        'curious': ['wonder', 'curious', 'interesting', 'what if', 'how does', 'why'],
        'excited': ['cool', 'awesome', 'great', 'amazing', 'perfect', 'love', 'finally'],
        'confused': ['confused', 'unclear', 'dont understand', "don't understand", 'lost'],
        'focused': ['need to', 'want to', 'lets', "let's", 'should', 'must']
    }

    mood_scores: Dict[str, int] = {}
    for mood, indicators in mood_indicators.items():
        score = sum(1 for ind in indicators if ind in content)
        if score > 0:
            mood_scores[mood] = score

    if mood_scores:
        return max(mood_scores, key=lambda k: mood_scores[k])
    return 'neutral'


def _extract_themes(content: str) -> List[str]:
    """
    Extract technical and conversation themes from content

    Args:
        content: Text content to analyze

    Returns:
        List of detected theme strings
    """
    themes = []

    theme_patterns = {
        'debugging': ['debug', 'error', 'fix', 'trace', 'bug'],
        'building': ['create', 'build', 'implement', 'design', 'architecture'],
        'learning': ['learn', 'understand', 'discover', 'insight', 'realize'],
        'memory_systems': ['memory', 'storage', 'vector', 'embedding', 'chroma'],
        'coding': ['code', 'function', 'module', 'class', 'import'],
        'problem_solving': ['problem', 'solution', 'approach', 'method', 'way']
    }

    for theme, indicators in theme_patterns.items():
        if any(ind in content for ind in indicators):
            themes.append(theme)

    return themes


# =============================================================================
# FRAGMENT FINDING
# =============================================================================

def find_relevant_fragments(
    context: Dict[str, Any],
    n_results: int = 3,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Query fragments based on extracted conversation context

    Uses vector similarity and trigger keywords to find relevant fragments.

    Args:
        context: Output from extract_conversation_context()
        n_results: Maximum fragments to return
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'fragments' list with relevance scores
    """
    keywords = context.get('keywords', [])
    mood = context.get('mood', 'neutral')
    themes = context.get('themes', [])

    if not keywords and not themes:
        return {
            'success': True,
            'fragments': [],
            'message': 'No context to search with'
        }

    # Build search query from context
    search_terms = keywords[:5] + themes[:3]
    if mood != 'neutral':
        search_terms.append(mood)

    query = ' '.join(search_terms)

    # Use retriever to find fragments
    result = retriever.retrieve_fragments(
        query=query,
        trigger_keywords=keywords[:5] if keywords else None,
        n_results=n_results,
        db_path=db_path
    )

    if not result.get('success'):
        return result

    # Filter results by minimum threshold
    config = load_config()
    threshold = config.get('threshold', 0.3)

    fragments = [
        frag for frag in result.get('results', [])
        if frag.get('relevance_score', frag.get('similarity', 0)) >= threshold
    ]

    return {
        'success': True,
        'fragments': fragments,
        'query_used': query,
        'threshold_applied': threshold,
        'total_before_filter': len(result.get('results', []))
    }


# =============================================================================
# FRAGMENT FORMATTING
# =============================================================================

def format_fragment_recall(fragment: Dict[str, Any]) -> str:
    """
    Format a fragment as natural recall text

    Supports both v1 (dimension-based) and v2 (LLM-extracted) fragment schemas.
    v2 fragments use episodic memory format with type-based prefixes.
    v1 fragments use the original "This reminds me of..." associative pattern.

    Args:
        fragment: Fragment dict with 'content' and 'metadata'

    Returns:
        Formatted recall string
    """
    content = fragment.get('content', '')
    metadata = fragment.get('metadata', {})

    # v2 schema: LLM-extracted fragments with summary/insight/type
    if metadata.get('schema_version') == 'v2':
        return _format_v2_recall(content, metadata)

    # v1 schema: dimension-based fragments (original format)
    return _format_v1_recall(content, metadata)


def _format_v2_recall(content: str, metadata: Dict[str, Any]) -> str:
    """
    Format a v2 LLM-extracted fragment as episodic memory recall text

    Uses type-based prefixes for natural episodic memory surfacing.

    Args:
        content: Fragment content text
        metadata: Fragment metadata with summary, insight, type fields

    Returns:
        Formatted v2 recall string
    """
    summary = metadata.get('summary', content or 'a past experience')
    insight = metadata.get('insight', '')
    frag_type = metadata.get('type', '')

    # Type-based opening
    TYPE_PREFIXES = {
        'episodic': f"During a session, {summary}",
        'procedural': f"We learned how to: {summary}",
        'semantic': f"An important concept: {summary}",
        'emotional': f"A meaningful moment: {summary}",
    }

    recall_text = TYPE_PREFIXES.get(frag_type, f"I remember: {summary}")

    # Append insight if available
    if insight:
        recall_text = f"{recall_text}. The key insight: {insight}."
    else:
        # Ensure trailing period
        if not recall_text.endswith('.'):
            recall_text += '.'

    return recall_text


def _format_v1_recall(content: str, metadata: Dict[str, Any]) -> str:
    """
    Format a v1 dimension-based fragment as associative recall text

    Uses the original "This reminds me of..." pattern with dimension metadata.

    Args:
        content: Fragment content text
        metadata: Fragment metadata with emotional_0, technical_0, learnings_0 fields

    Returns:
        Formatted v1 recall string
    """
    emotional = metadata.get('emotional_0', '')
    technical = metadata.get('technical_0', '')
    learnings = metadata.get('learnings_0', '')

    # Build recall phrase
    recall_parts = []

    # Opening
    if emotional and 'frustration' in emotional:
        recall_parts.append("This reminds me of a conversation where we dealt with a similar frustration")
    elif emotional and 'curiosity' in emotional:
        recall_parts.append("This brings back a curious exploration")
    elif emotional and 'excitement' in emotional:
        recall_parts.append("This reminds me of an exciting moment")
    else:
        recall_parts.append("This reminds me of a past conversation")

    # Context
    if technical:
        technical_desc = technical.replace('_', ' ')
        recall_parts.append(f"involving {technical_desc}")

    # Pattern
    if emotional:
        emotional_desc = emotional.replace('_', '-')
        recall_parts.append(f"The pattern was \"{emotional_desc}\"")

    # Insight
    if learnings:
        learnings_desc = learnings.replace('_', ' ')
        recall_parts.append(f"and the key insight was about {learnings_desc}")

    recall_text = '. '.join(recall_parts) + '.'

    # Add compressed content if available
    if content and len(content) < 200:
        recall_text = f"{recall_text}\n\n> {content}"

    return recall_text


def format_multiple_recalls(fragments: List[Dict[str, Any]]) -> str:
    """
    Format multiple fragments for display

    Handles mixed v1 and v2 fragments, adding schema version tags
    to each recall for clarity.

    Args:
        fragments: List of fragment dicts with 'content' and 'metadata'

    Returns:
        Formatted string with all recalls separated by dividers
    """
    if not fragments:
        return ""

    recalls = []
    for frag in fragments:
        metadata = frag.get('metadata', {})
        schema = metadata.get('schema_version', 'v1')
        recall = format_fragment_recall(frag)
        recalls.append(f"[{schema}] {recall}")

    return "\n\n---\n\n".join(recalls)


# =============================================================================
# SURFACING CONTROL
# =============================================================================

def should_surface_fragment(
    fragment: Dict[str, Any] | None = None,
    config: Dict[str, Any] | None = None
) -> Tuple[bool, str]:
    """
    Check if a fragment should be surfaced based on rules

    Checks:
    - Is hook enabled?
    - Have we hit max fragments for session?
    - Have enough messages passed since last surface?
    - Has cooldown elapsed?
    - Has this fragment already been surfaced?

    Args:
        fragment: Optional fragment to check (for duplicate detection)
        config: Optional config dict (loads from file if not provided)

    Returns:
        Tuple of (should_surface: bool, reason: str)
    """
    if config is None:
        config = load_config()

    # Check if enabled
    if not config.get('enabled', True):
        return False, "Hook is disabled"

    # Check max fragments per session
    max_frags = config.get('max_fragments_per_session', 5)
    if SESSION_STATE['fragments_surfaced'] >= max_frags:
        return False, f"Max fragments ({max_frags}) reached for session"

    # Check messages since last surface
    min_messages = config.get('min_messages_between', 10)
    if SESSION_STATE['messages_since_last'] < min_messages:
        return False, f"Only {SESSION_STATE['messages_since_last']}/{min_messages} messages since last surface"

    # Check cooldown
    cooldown = config.get('cooldown_seconds', 300)
    elapsed = time.time() - SESSION_STATE['last_surface_time']
    if elapsed < cooldown:
        remaining = int(cooldown - elapsed)
        return False, f"Cooldown active ({remaining}s remaining)"

    # Check if already surfaced
    if fragment:
        frag_id = fragment.get('id')
        if frag_id and frag_id in SESSION_STATE['surfaced_ids']:
            return False, "Fragment already surfaced this session"

    return True, "Ready to surface"


def record_surface(fragment: Dict[str, Any]) -> None:
    """
    Record that a fragment was surfaced

    Updates session state for frequency tracking.

    Args:
        fragment: The fragment that was surfaced
    """
    SESSION_STATE['fragments_surfaced'] += 1
    SESSION_STATE['messages_since_last'] = 0
    SESSION_STATE['last_surface_time'] = time.time()

    frag_id = fragment.get('id')
    if frag_id:
        SESSION_STATE['surfaced_ids'].add(frag_id)


def record_message() -> None:
    """
    Record that a message was processed

    Increments the messages_since_last counter.
    """
    SESSION_STATE['messages_since_last'] += 1


def reset_session() -> None:
    """
    Reset session state for new conversation

    Clears all tracking counters and surfaced fragment IDs.
    """
    SESSION_STATE['fragments_surfaced'] = 0
    SESSION_STATE['messages_since_last'] = 0
    SESSION_STATE['last_surface_time'] = 0
    SESSION_STATE['surfaced_ids'] = set()


def get_session_state() -> Dict[str, Any]:
    """
    Get current session state for debugging

    Returns:
        Dict with session state values
    """
    return {
        "fragments_surfaced": SESSION_STATE['fragments_surfaced'],
        "messages_since_last": SESSION_STATE['messages_since_last'],
        "last_surface_time": SESSION_STATE['last_surface_time'],
        "surfaced_count": len(SESSION_STATE['surfaced_ids'])
    }


# =============================================================================
# MAIN HOOK FUNCTION
# =============================================================================

def process_hook(
    messages: List[Dict[str, Any]],
    config: Dict[str, Any] | None = None,
    db_path: Path | None = None
) -> Dict[str, Any]:
    """
    Main hook function - process messages and surface relevant fragments

    This is the primary entry point for the hook integration.

    Args:
        messages: Recent conversation messages
        config: Optional config dict
        db_path: Optional ChromaDB path

    Returns:
        Dict with 'success', 'surfaced' bool, 'recall' text if surfaced
    """
    if config is None:
        config = load_config()

    # Check if we should attempt to surface
    can_surface, reason = should_surface_fragment(config=config)
    if not can_surface:
        return {
            'success': True,
            'surfaced': False,
            'reason': reason
        }

    # Extract context from recent messages
    context = extract_conversation_context(messages)
    if not context.get('success'):
        return {
            'success': False,
            'error': context.get('error', 'Context extraction failed')
        }

    # Find relevant fragments
    result = find_relevant_fragments(context, n_results=1, db_path=db_path)
    if not result.get('success'):
        return {
            'success': False,
            'error': result.get('error', 'Fragment retrieval failed')
        }

    fragments = result.get('fragments', [])
    if not fragments:
        return {
            'success': True,
            'surfaced': False,
            'reason': 'No relevant fragments found above threshold'
        }

    # Check the specific fragment
    fragment = fragments[0]
    can_surface, reason = should_surface_fragment(fragment=fragment, config=config)
    if not can_surface:
        return {
            'success': True,
            'surfaced': False,
            'reason': reason
        }

    # Format the recall
    recall_text = format_fragment_recall(fragment)

    # Record the surface
    record_surface(fragment)

    return {
        'success': True,
        'surfaced': True,
        'recall': recall_text,
        'fragment_id': fragment.get('id'),
        'relevance_score': fragment.get('relevance_score', fragment.get('similarity', 0)),
        'context_used': {
            'keywords': context.get('keywords', []),
            'mood': context.get('mood'),
            'themes': context.get('themes', [])
        }
    }
