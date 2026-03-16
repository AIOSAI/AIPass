#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: deduplicator.py - Symbolic Fragment Deduplication Handler
# Date: 2026-02-15
# Version: 0.1.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.1.0 (2026-02-15): Initial version - FPLAN-0341 Phase 3 AUDN dedup
#
# CODE STANDARDS:
#   - Handler independence: No module imports (OpenRouter lazy-imported)
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <300 lines target
# =============================================

"""
Symbolic Fragment Deduplication Handler

Implements the AUDN (Add/Update/Delete/Noop) deduplication pattern for
LLM-extracted memory fragments. Compares new fragments against existing
similar fragments and decides the correct action via LLM.

Key Functions:
    - deduplicate_fragment() - compare new fragment to existing, return AUDN action
    - _build_dedup_prompt() - build LLM messages for dedup decision
    - _parse_dedup_response() - parse and validate LLM JSON response
"""

import json
import re
import sys
from typing import Dict, List, Any, Optional
from pathlib import Path

# Infrastructure setup
AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))
sys.path.insert(0, str(Path.home()))


# =============================================================================
# CONSTANTS
# =============================================================================

LLM_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

DEDUP_SYSTEM_PROMPT = (
    "You are a memory deduplication system. Compare a new memory fragment "
    "against existing ones and decide the correct action.\n\n"
    "Actions:\n"
    "- ADD: The new fragment contains genuinely new information not covered by existing fragments. Keep as-is.\n"
    "- UPDATE: The new fragment overlaps with an existing one. Merge into a better, combined version.\n"
    "- DELETE: An existing fragment is now obsolete because the new one supersedes it. Return the existing ID to delete.\n"
    "- NOOP: The new fragment is a duplicate of an existing one. Skip entirely.\n\n"
    "Return ONLY a JSON object with this schema:\n"
    '{"action": "ADD|UPDATE|DELETE|NOOP", '
    '"merged_summary": "combined summary if UPDATE, else empty string", '
    '"merged_insight": "combined insight if UPDATE, else empty string", '
    '"delete_id": "existing fragment ID if DELETE, else empty string", '
    '"reason": "brief explanation of your decision"}\n\n'
    "Rules:\n"
    "- If the new fragment adds unique information, use ADD\n"
    "- If it overlaps significantly, merge the best of both into UPDATE\n"
    "- If an existing fragment is completely superseded, use DELETE\n"
    "- If it's essentially a duplicate, use NOOP\n"
    "- Be conservative: prefer ADD over NOOP when in doubt\n"
    "- For UPDATE, write a merged_summary and merged_insight that combines both fragments\n"
    "- Return ONLY the JSON object, no other text"
)

VALID_ACTIONS = {'ADD', 'UPDATE', 'DELETE', 'NOOP'}


# =============================================================================
# DEDUPLICATION
# =============================================================================

def deduplicate_fragment(
    new_fragment: Dict[str, Any],
    existing_fragments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compare a new LLM-extracted fragment against existing similar fragments
    and decide the AUDN action via LLM.

    Args:
        new_fragment: New LLM-extracted fragment dict with summary/insight/type/etc.
        existing_fragments: List of similar existing fragments from ChromaDB
            (each with 'id', 'content', 'metadata' keys)

    Returns:
        Dict with 'success', 'action' (ADD|UPDATE|DELETE|NOOP),
        'fragment' (updated or original), 'reason' (explanation)
    """
    if not new_fragment:
        return {
            'success': False,
            'action': 'NOOP',
            'fragment': new_fragment,
            'reason': 'No fragment provided'
        }

    # If no existing fragments to compare, always ADD
    if not existing_fragments:
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': 'No existing fragments to compare against'
        }

    # Build prompt and call LLM
    messages = _build_dedup_prompt(new_fragment, existing_fragments)

    # Direct OpenRouter API call via urllib (no cross-branch imports needed)
    import urllib.request
    import urllib.error
    from pathlib import Path

    api_key = None
    for env_path in [
        Path.home() / "aipass_core" / "api" / "apps" / ".env",
        Path.home() / "aipass_core" / "api" / ".env",
    ]:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("OPENROUTER_API_KEY="):
                        api_key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if api_key:
            break

    if not api_key:
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': 'No OpenRouter API key found, defaulting to ADD'
        }

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 500
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aipass.dev",
            "X-Title": "AIPass Memory Bank"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError):
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': 'LLM request failed, defaulting to ADD'
        }

    if not content:
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': 'Empty LLM response, defaulting to ADD'
        }
    data = {'content': content}

    # Parse LLM decision
    parsed = _parse_dedup_response(data['content'])
    if parsed is None:
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': 'Failed to parse LLM dedup response, defaulting to ADD'
        }

    action = parsed['action']
    reason = parsed.get('reason', 'No reason provided')

    # Apply action to fragment
    if action == 'UPDATE':
        # Merge content from LLM response into fragment
        updated_fragment = new_fragment.copy()
        if parsed.get('merged_summary'):
            updated_fragment['summary'] = parsed['merged_summary']
        if parsed.get('merged_insight'):
            updated_fragment['insight'] = parsed['merged_insight']
        return {
            'success': True,
            'action': 'UPDATE',
            'fragment': updated_fragment,
            'reason': reason
        }

    elif action == 'DELETE':
        return {
            'success': True,
            'action': 'DELETE',
            'fragment': new_fragment,
            'delete_id': parsed.get('delete_id', ''),
            'reason': reason
        }

    elif action == 'NOOP':
        return {
            'success': True,
            'action': 'NOOP',
            'fragment': new_fragment,
            'reason': reason
        }

    else:  # ADD
        return {
            'success': True,
            'action': 'ADD',
            'fragment': new_fragment,
            'reason': reason
        }


# =============================================================================
# PROMPT BUILDING
# =============================================================================

def _build_dedup_prompt(
    new_fragment: Dict[str, Any],
    existing_fragments: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """
    Build system/user messages for the deduplication LLM call.

    Args:
        new_fragment: New LLM-extracted fragment dict
        existing_fragments: List of existing fragments (up to 3 used)

    Returns:
        List of message dicts for the LLM API call
    """
    # Format the new fragment
    new_text = (
        f"NEW FRAGMENT:\n"
        f"  Summary: {new_fragment.get('summary', '')}\n"
        f"  Insight: {new_fragment.get('insight', '')}\n"
        f"  Type: {new_fragment.get('type', '')}\n"
        f"  Triggers: {', '.join(new_fragment.get('triggers', []))}\n"
        f"  Emotional tone: {new_fragment.get('emotional_tone', '')}\n"
        f"  Technical domain: {new_fragment.get('technical_domain', '')}"
    )

    # Format existing fragments (limit to top 3)
    existing_parts = []
    for i, frag in enumerate(existing_fragments[:3]):
        frag_id = frag.get('id', f'unknown_{i}')
        content = frag.get('content', '')
        metadata = frag.get('metadata', {})

        # Extract summary/insight from metadata if available (v2 fragments)
        summary = metadata.get('summary', content[:200] if content else '')
        insight = metadata.get('insight', '')
        frag_type = metadata.get('type', '')
        triggers = metadata.get('triggers', '')

        existing_parts.append(
            f"EXISTING FRAGMENT {i + 1} (ID: {frag_id}):\n"
            f"  Summary: {summary}\n"
            f"  Insight: {insight}\n"
            f"  Type: {frag_type}\n"
            f"  Triggers: {triggers}\n"
            f"  Full content: {content[:300]}"
        )

    existing_text = "\n\n".join(existing_parts)

    user_content = (
        f"{new_text}\n\n"
        f"EXISTING FRAGMENTS TO COMPARE AGAINST:\n\n"
        f"{existing_text}\n\n"
        f"Decide: should the new fragment be ADDed, UPDATEd (merged with existing), "
        f"DELETE an existing one, or NOOP (skip as duplicate)?"
    )

    return [
        {"role": "system", "content": DEDUP_SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]


# =============================================================================
# RESPONSE PARSING
# =============================================================================

def _parse_dedup_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse the JSON response from the deduplication LLM call.

    Handles markdown fences and validates the action field.

    Args:
        raw_text: Raw text response from LLM

    Returns:
        Parsed dict with 'action', 'merged_summary', 'merged_insight',
        'delete_id', 'reason' keys, or None if parsing fails
    """
    if not raw_text or not raw_text.strip():
        return None

    text = raw_text.strip()

    # Attempt 1: Direct JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, dict) and _validate_dedup_result(result):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: Strip markdown fences
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict) and _validate_dedup_result(result):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # Attempt 3: Find JSON object in text
    match = re.search(r'\{[^{}]*"action"\s*:\s*"[A-Z]+"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict) and _validate_dedup_result(result):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _validate_dedup_result(result: Dict[str, Any]) -> bool:
    """
    Validate that a parsed dedup result has the required action field.

    Args:
        result: Parsed JSON dict

    Returns:
        True if action is valid
    """
    action = result.get('action', '').upper()
    if action not in VALID_ACTIONS:
        return False
    # Normalize action to uppercase
    result['action'] = action
    return True
