#!/home/aipass/MEMORY_BANK/.venv/bin/python3

# ===================AIPASS====================
# META DATA HEADER
# Name: extractor.py - Symbolic Memory Extractor Handler
# Date: 2026-02-04
# Version: 0.2.0
# Category: memory_bank/handlers/symbolic
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-02-15): Phase 2 - LLM-based extraction via OpenRouter (FPLAN-0341)
#   - v0.1.0 (2026-02-04): Initial version - ported from symbolic_memory.py
#
# CODE STANDARDS:
#   - Handler independence: No module imports (OpenRouter lazy-imported)
#   - Error handling: Return status dicts (3-tier architecture)
#   - File size: <400 lines target
# =============================================

"""
Symbolic Memory Extractor Handler

v1 (regex): extract_technical_flow, extract_emotional_journey,
    extract_collaboration_patterns, extract_key_learnings,
    extract_context_triggers, extract_symbolic_dimensions, analyze_conversation
v2 (LLM):  extract_fragments_llm, analyze_conversation_llm
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

AIPASS_ROOT = Path.home() / "aipass_core"
sys.path.insert(0, str(AIPASS_ROOT))

# =============================================================================
# v1 REGEX EXTRACTION (fallback)
# =============================================================================

def extract_technical_flow(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect problem/debug/breakthrough patterns via keyword matching."""
    if not chat_history:
        return {'success': True, 'patterns': ['no_conversation'], 'details': {}}
    patterns = []
    indicators = {
        'problems': ['error', 'bug', 'issue', 'problem', 'broken', 'fail', 'wrong'],
        'debugging': ['debug', 'trace', 'check', 'test', 'try', 'attempt'],
        'solutions': ['fix', 'solve', 'work', 'success', 'breakthrough', 'got it'],
        'struggle': ['stuck', 'confused', 'difficult', 'hard', 'frustrating'],
        'learning': ['understand', 'learn', 'realize', 'discover', 'insight']
    }
    cat_counts = {cat: 0 for cat in indicators}
    for msg in chat_history:
        content = (msg.get('content') or '').lower()
        role = msg.get('role', '')
        for cat, kws in indicators.items():
            if any(kw in content for kw in kws):
                patterns.append(f'{cat}_{role}')
                cat_counts[cat] += 1
    ps = ' '.join(patterns)
    if 'problems' in ps and 'solutions' in ps:
        flow = ['problem_struggle_breakthrough'] if 'struggle' in ps else ['problem_solution_flow']
    elif 'debugging' in ps:
        flow = ['debugging_session']
    elif 'learning' in ps:
        flow = ['learning_conversation']
    else:
        flow = ['general_technical']
    return {'success': True, 'patterns': flow,
            'details': {'category_counts': cat_counts, 'raw_patterns': patterns[:10]}}


def extract_emotional_journey(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect emotional arc via tone markers."""
    if not chat_history:
        return {'success': True, 'arc': ['neutral'], 'details': {}}
    markers = {
        'frustration': ['frustrated', 'annoying', 'difficult', 'stuck', 'ugh', 'damn'],
        'excitement': ['cool', 'awesome', 'great', 'amazing', 'perfect', 'brilliant'],
        'confidence': ['sure', 'certain', 'definitely', 'absolutely', 'know'],
        'uncertainty': ['maybe', 'possibly', 'not sure', 'think', 'guess'],
        'breakthrough': ['got it', 'understand', 'works', 'success', 'finally'],
        'curiosity': ['wonder', 'curious', 'interesting', 'what if', 'how']
    }
    timeline = []
    for msg in chat_history:
        content = (msg.get('content') or '').lower()
        role = msg.get('role', '')
        emos = [e for e, ms in markers.items() if any(m in content for m in ms)]
        if emos:
            timeline.append((role, emos))
    if not timeline:
        return {'success': True, 'arc': ['neutral_tone'], 'details': {'timeline': []}}
    all_emos = [e for _, es in timeline for e in es]
    if 'frustration' in all_emos and 'breakthrough' in all_emos:
        arc = ['frustration_to_breakthrough']
    elif 'curiosity' in all_emos and 'excitement' in all_emos:
        arc = ['curiosity_to_excitement']
    elif 'uncertainty' in all_emos and 'confidence' in all_emos:
        arc = ['uncertainty_to_confidence']
    else:
        arc = [e for e, _ in Counter(all_emos).most_common(2)]
    return {'success': True, 'arc': arc,
            'details': {'timeline': timeline[:10], 'emotion_counts': dict(Counter(all_emos))}}


def extract_collaboration_patterns(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Identify interaction dynamics (user-directed, balanced, teaching, etc.)."""
    if not chat_history:
        return {'success': True, 'patterns': ['no_interaction'], 'details': {}}
    u_msgs = [m for m in chat_history if m.get('role') == 'user']
    a_msgs = [m for m in chat_history if m.get('role') == 'assistant']
    if not u_msgs or not a_msgs:
        return {'success': True, 'patterns': ['one_sided_conversation'], 'details': {}}
    patterns = []
    avg_u = sum(len(m.get('content', '')) for m in u_msgs) / len(u_msgs)
    avg_a = sum(len(m.get('content', '')) for m in a_msgs) / len(a_msgs)
    if avg_u > avg_a * 1.5:
        patterns.append('user_directed')
    elif avg_a > avg_u * 1.5:
        patterns.append('assistant_detailed')
    else:
        patterns.append('balanced_exchange')
    u_qs = sum(1 for m in u_msgs if '?' in m.get('content', ''))
    if u_qs > len(u_msgs) * 0.6:
        patterns.append('question_heavy')
    uc = ' '.join(m.get('content', '').lower() for m in u_msgs)
    ac = ' '.join(m.get('content', '').lower() for m in a_msgs)
    if any(i in uc for i in ['try', "let's", 'what if', 'how about', 'consider']):
        patterns.append('user_coaching')
    if any(i in ac for i in ['explain', 'show', 'understand', 'learn', 'because']):
        patterns.append('assistant_teaching')
    if any(i in uc + ac for i in ["let's build", 'we can', 'together', 'collaborate']):
        patterns.append('collaborative_building')
    return {'success': True, 'patterns': patterns or ['standard_interaction'],
            'details': {'avg_user_length': int(avg_u), 'avg_assistant_length': int(avg_a),
                        'user_questions': u_qs, 'total_user_messages': len(u_msgs)}}


def extract_key_learnings(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract insight categories (discovery, problem_solving, etc.)."""
    if not chat_history:
        return {'success': True, 'insights': ['no_insights'], 'details': {}}
    insights = []
    lp = {'discovery': ['discovered', 'found out', 'realized', 'learned'],
          'problem_solving': ['solution', 'approach', 'method', 'way to'],
          'understanding': ['understand', 'makes sense', 'clear', 'see'],
          'improvement': ['better', 'improve', 'optimize', 'enhance'],
          'mistakes': ['wrong', 'mistake', 'error', 'incorrect']}
    ac = ' '.join((m.get('content') or '').lower() for m in chat_history)
    for cat, inds in lp.items():
        if any(i in ac for i in inds):
            insights.append(cat)
    if 'module' in ac and 'toggle' in ac:
        insights.append('module_system_learning')
    if 'memory' in ac and 'compression' in ac:
        insights.append('memory_system_learning')
    if 'debug' in ac and 'fix' in ac:
        insights.append('debugging_skills')
    return {'success': True, 'insights': insights or ['general_conversation'],
            'details': {'content_length': len(ac)}}


def extract_context_triggers(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract keyword triggers for future memory recall."""
    if not chat_history:
        return {'success': True, 'triggers': [], 'details': {}}
    ac = ' '.join((m.get('content') or '') for m in chat_history).lower()
    pat = (r'\b(?:module|system|debug|memory|compression|vector|symbolic|cortex|'
           r'registry|toggle|profile|chat|context|api|token|embedding|storage|'
           r'json|function|method|class|import|file|script|error|fix|solution|'
           r'breakthrough|pattern|analysis|extraction|conversation|interaction|'
           r'collaboration|learning|insight|discovery|handler|branch|rollover)\b')
    terms = re.findall(pat, ac)
    tc = Counter(terms)
    triggers = [t for t, c in tc.most_common(10) if c > 1]
    return {'success': True, 'triggers': triggers,
            'details': {'term_counts': dict(tc.most_common(15))}}


def extract_symbolic_dimensions(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run all v1 extractors and combine into unified dimensions dict."""
    tech = extract_technical_flow(chat_history)
    emo = extract_emotional_journey(chat_history)
    collab = extract_collaboration_patterns(chat_history)
    learn = extract_key_learnings(chat_history)
    trig = extract_context_triggers(chat_history)
    return {
        'success': True,
        'dimensions': {
            'technical': tech.get('patterns', []), 'emotional': emo.get('arc', []),
            'collaboration': collab.get('patterns', []),
            'learnings': learn.get('insights', []), 'triggers': trig.get('triggers', [])},
        'details': {
            'technical': tech.get('details', {}), 'emotional': emo.get('details', {}),
            'collaboration': collab.get('details', {}),
            'learnings': learn.get('details', {}), 'triggers': trig.get('details', {})}}


def analyze_conversation(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """v1 entry point: symbolic dimensions + conversation metadata."""
    if not chat_history:
        return {'success': True, 'message_count': 0, 'dimensions': {}, 'metadata': {}}
    dims = extract_symbolic_dimensions(chat_history)
    total_chars = sum(len(m.get('content') or '') for m in chat_history)
    total_words = sum(len((m.get('content') or '').split()) for m in chat_history)
    if total_words > 2000 and len(chat_history) > 20:
        depth = 'deep_extended'
    elif total_words > 1000 and len(chat_history) > 10:
        depth = 'substantial'
    elif total_words > 500:
        depth = 'moderate'
    else:
        depth = 'light'
    return {
        'success': True, 'message_count': len(chat_history),
        'dimensions': dims.get('dimensions', {}),
        'metadata': {'timestamp': datetime.now().isoformat(), 'total_chars': total_chars,
                     'total_words': total_words, 'depth': depth},
        'details': dims.get('details', {})}


# =============================================================================
# v2 LLM EXTRACTION (OpenRouter / Llama 3.3 70B)
# =============================================================================

LLM_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
CHUNK_THRESHOLD = 25   # messages before chunking
CHUNK_SIZE = 20        # messages per chunk
CHUNK_OVERLAP = 5      # overlap between chunks

EXTRACTION_SYSTEM_PROMPT = (
    "You are a memory extraction system for an AI collaboration platform.\n"
    "Extract genuinely memorable fragments from human-AI conversations.\n"
    "Only extract noteworthy moments: breakthroughs, insights, decisions, "
    "frustrations overcome, or technical discoveries.\n\n"
    "Return a JSON array of fragment objects with this schema:\n"
    '{"summary":"One sentence of what happened",'
    '"insight":"Key takeaway or lesson",'
    '"type":"episodic|procedural|semantic|emotional",'
    '"triggers":["kw1","kw2","kw3"],'
    '"emotional_tone":"neutral|frustrated|excited|curious|confident",'
    '"technical_domain":"optional domain tag"}\n\n'
    "Types: episodic=specific event, procedural=how-to, "
    "semantic=concept/fact, emotional=significant feeling\n\n"
    "Rules:\n"
    "- 1-5 fragments based on richness. Mundane chat = empty array []\n"
    "- triggers: 2-5 keywords for future recall\n"
    "- summary: complete sentence, not a label\n"
    "- insight: capture WHY it matters\n\n"
    "Example 1:\n"
    "user: ChromaDB returns empty results even though I added documents\n"
    "assistant: Are you using the same embedding function for add and query?\n"
    "user: I was using default for add but sentence-transformers for query\n"
    "assistant: That's the issue. Embedding spaces don't match.\n"
    "user: Fixed it! That was a 2-hour bug.\n"
    'Output: [{"summary":"Discovered ChromaDB requires same embedding function '
    'for add and query","insight":"Mismatched embedding functions produce empty '
    'results silently - verify embedding consistency","type":"procedural",'
    '"triggers":["chromadb","embeddings","empty results"],'
    '"emotional_tone":"excited","technical_domain":"chromadb"}]\n\n'
    "Example 2:\n"
    "user: Branches need broadcast, not just point-to-point mail\n"
    "assistant: A pub/sub pattern - branches subscribe to topics\n"
    "user: And The Commons for human-readable versions\n"
    "assistant: Clean separation - machine events via pub/sub, human context via Commons\n"
    'Output: [{"summary":"Designed dual-channel architecture: pub/sub for machine '
    'events, Commons for human context","insight":"Branch communication needs both '
    'structured events and natural-language channels","type":"semantic",'
    '"triggers":["pub/sub","commons","broadcast","architecture"],'
    '"emotional_tone":"curious","technical_domain":"memory_systems"}]\n\n'
    "Extract fragments from the following conversation. Return ONLY the JSON array."
)


def _format_conversation_for_prompt(messages: List[Dict[str, Any]]) -> str:
    """Format conversation messages into readable text for the LLM prompt."""
    lines = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = (msg.get('content') or '').strip()
        if content:
            if len(content) > 1500:
                content = content[:1500] + "... [truncated]"
            lines.append(f"{role}: {content}")
    return '\n'.join(lines)


def _chunk_messages(messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split long conversations into overlapping chunks for LLM processing."""
    if len(messages) <= CHUNK_THRESHOLD:
        return [messages]
    chunks = []
    start = 0
    while start < len(messages):
        end = min(start + CHUNK_SIZE, len(messages))
        chunks.append(messages[start:end])
        next_start = start + CHUNK_SIZE - CHUNK_OVERLAP
        remaining = len(messages) - next_start
        if 0 < remaining < CHUNK_OVERLAP:
            chunks[-1] = messages[start:len(messages)]
            break
        start = next_start
    return chunks


def _parse_llm_json(raw_text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse JSON array from LLM response, stripping markdown fences if needed."""
    if not raw_text or not raw_text.strip():
        return None
    text = raw_text.strip()
    # Attempt 1: Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    # Attempt 2: Strip markdown fences
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _validate_fragment(fragment: Any) -> bool:
    """Check fragment dict has required fields with valid enum values."""
    if not isinstance(fragment, dict):
        return False
    required = {'summary', 'insight', 'type', 'triggers', 'emotional_tone'}
    if not required.issubset(fragment.keys()):
        return False
    if fragment.get('type') not in {'episodic', 'procedural', 'semantic', 'emotional'}:
        return False
    if fragment.get('emotional_tone') not in {'neutral', 'frustrated', 'excited', 'curious', 'confident'}:
        return False
    if not isinstance(fragment.get('triggers'), list):
        return False
    return True


def extract_fragments_llm(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract memory fragments via OpenRouter LLM (Llama 3.3 70B).
    Chunks long conversations. Returns status dict with 'fragments' list.
    """
    empty = {'success': True, 'fragments': [], 'chunk_count': 0, 'error': None}
    if not chat_history:
        return empty

    # Direct OpenRouter API call via urllib (no cross-branch imports needed)
    import urllib.request
    import urllib.error
    from pathlib import Path

    # Load API key from env file
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
        return {'success': False, 'fragments': [], 'chunk_count': 0,
                'error': "No OpenRouter API key found in env files"}

    chunks = _chunk_messages(chat_history)
    all_fragments = []
    chunk_errors = []
    chunks_succeeded = 0
    for i, chunk in enumerate(chunks):
        conv_text = _format_conversation_for_prompt(chunk)
        if not conv_text.strip():
            continue
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": conv_text}
        ]
        payload = json.dumps({
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2000
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
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError) as e:
            err_msg = f"Chunk {i+1}/{len(chunks)}: {type(e).__name__}: {e}"
            chunk_errors.append(err_msg)
            # Error tracked in chunk_errors for module-layer logging
            continue
        if not content:
            continue
        parsed = _parse_llm_json(content)
        if parsed is None:
            continue
        chunks_succeeded += 1
        for frag in parsed:
            if _validate_fragment(frag):
                frag.setdefault('technical_domain', '')
                all_fragments.append(frag)

    all_failed = len(chunks) > 0 and chunks_succeeded == 0 and len(chunk_errors) > 0
    return {
        'success': not all_failed,
        'fragments': all_fragments,
        'chunk_count': len(chunks),
        'chunks_succeeded': chunks_succeeded,
        'chunks_failed': len(chunk_errors),
        'error': '; '.join(chunk_errors) if all_failed else None,
        'chunk_errors': chunk_errors
    }


def analyze_conversation_llm(chat_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Full analysis: LLM fragments + regex metadata merged.
    Returns status dict with 'fragments', 'metadata', 'message_count'.
    """
    if not chat_history:
        return {'success': True, 'fragments': [], 'metadata': {},
                'message_count': 0, 'error': None}
    llm = extract_fragments_llm(chat_history)
    reg = analyze_conversation(chat_history)
    return {
        'success': llm.get('success', False),
        'fragments': llm.get('fragments', []),
        'metadata': {
            'timestamp': reg.get('metadata', {}).get('timestamp', datetime.now().isoformat()),
            'total_chars': reg.get('metadata', {}).get('total_chars', 0),
            'total_words': reg.get('metadata', {}).get('total_words', 0),
            'depth': reg.get('metadata', {}).get('depth', 'unknown'),
            'dimensions': reg.get('dimensions', {}),
            'chunk_count': llm.get('chunk_count', 0)},
        'message_count': reg.get('message_count', len(chat_history)),
        'error': llm.get('error')}
