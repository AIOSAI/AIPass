# =================== AIPass ====================
# Name: plans_processor.py
# Description: Plan Archival Vectorization Handler
# Version: 1.0.0
# Created: 2026-03-12
# Modified: 2026-03-12
# =============================================

"""
Plan Archival Vectorization Handler

Reads closed plan files from flow/processed_plans/, chunks them,
generates embeddings via subprocess, and stores vectors in ChromaDB.

Called by memory_watcher._check_plans() during watch mode
and can be invoked directly for manual processing.

Uses subprocess pattern for ML operations (memory venv isolation).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.prax import logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

# Subprocess scripts
_HANDLERS_DIR = Path(__file__).resolve().parent.parent
EMBED_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "vector" / "embed_subprocess.py"
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"

# Memory venv python
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def _get_memory_python() -> str:
    env_override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if env_override:
        return env_override
    if _MEMORY_VENV_PYTHON.exists():
        return str(_MEMORY_VENV_PYTHON)
    return sys.executable


MEMORY_PYTHON = _get_memory_python()

# Track which files have been processed
_PROCESSED_MANIFEST = _MEMORY_ROOT / "config" / ".plans_processed.json"

# Chunk settings
MAX_CHUNK_CHARS = 1500  # ~375 tokens, fits well with all-MiniLM-L6-v2


# =============================================================================
# CHUNKING
# =============================================================================

def _chunk_plan_text(text: str, filename: str) -> List[Dict[str, str]]:
    """
    Chunk plan text into sections for vectorization.

    Splits on markdown headers (## / ###), with fallback to paragraph splitting.
    Each chunk gets metadata about its source.

    Args:
        text: Full plan text
        filename: Source filename for metadata

    Returns:
        List of dicts with 'text' and 'section' keys
    """
    chunks = []

    # Split by markdown headers
    lines = text.split('\n')
    current_section = filename
    current_lines = []

    for line in lines:
        if line.startswith('## ') or line.startswith('### '):
            # Flush previous section
            if current_lines:
                section_text = '\n'.join(current_lines).strip()
                if section_text and len(section_text) > 30:
                    chunks.append({'text': section_text, 'section': current_section})
            current_section = line.lstrip('#').strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last section
    if current_lines:
        section_text = '\n'.join(current_lines).strip()
        if section_text and len(section_text) > 30:
            chunks.append({'text': section_text, 'section': current_section})

    # If no headers found, chunk by size
    if not chunks:
        full_text = text.strip()
        if len(full_text) > MAX_CHUNK_CHARS:
            for i in range(0, len(full_text), MAX_CHUNK_CHARS):
                chunk_text = full_text[i:i + MAX_CHUNK_CHARS].strip()
                if chunk_text and len(chunk_text) > 30:
                    chunks.append({'text': chunk_text, 'section': f'{filename}_part{i // MAX_CHUNK_CHARS}'})
        elif len(full_text) > 30:
            chunks.append({'text': full_text, 'section': filename})

    # Split oversized chunks
    final_chunks = []
    for chunk in chunks:
        if len(chunk['text']) > MAX_CHUNK_CHARS * 2:
            text_content = chunk['text']
            for i in range(0, len(text_content), MAX_CHUNK_CHARS):
                part = text_content[i:i + MAX_CHUNK_CHARS].strip()
                if part and len(part) > 30:
                    final_chunks.append({
                        'text': part,
                        'section': f"{chunk['section']}_part{i // MAX_CHUNK_CHARS}"
                    })
        else:
            final_chunks.append(chunk)

    return final_chunks


# =============================================================================
# PROCESSED MANIFEST
# =============================================================================

def _load_manifest() -> Dict[str, str]:
    """Load processed files manifest."""
    if _PROCESSED_MANIFEST.exists():
        try:
            return json.loads(_PROCESSED_MANIFEST.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _save_manifest(manifest: Dict[str, str]) -> None:
    """Save processed files manifest."""
    _PROCESSED_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _PROCESSED_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding='utf-8')


# =============================================================================
# SUBPROCESS WRAPPERS
# =============================================================================

def _embed_texts(texts: List[str]) -> dict:
    """Encode texts via subprocess."""
    input_data = json.dumps({'texts': texts})
    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(EMBED_SUBPROCESS_SCRIPT)],
            input=input_data,
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return {'success': False, 'error': result.stderr or 'Embedding failed'}
        return json.loads(result.stdout)
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _store_vectors(embeddings, documents, metadatas, collection_name="flow_plans") -> dict:
    """Store vectors via subprocess."""
    input_data = {
        'operation': 'store_vectors',
        'branch': 'FLOW',
        'memory_type': collection_name,
        'embeddings': embeddings,
        'documents': documents,
        'metadatas': metadatas,
        'db_path': None  # global
    }
    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return {'success': False, 'error': result.stderr or 'Storage failed'}
        return json.loads(result.stdout)
    except Exception as e:
        return {'success': False, 'error': str(e)}


# =============================================================================
# PUBLIC API
# =============================================================================

def process_plans() -> Dict[str, Any]:
    """
    Process plan files from flow/processed_plans/ into vector storage.

    Workflow:
    1. Load config to find plans directory
    2. Scan for unprocessed .md files
    3. Chunk each file into sections
    4. Embed all chunks via subprocess
    5. Store vectors in ChromaDB
    6. Update processed manifest

    Returns:
        Dict with success, files_processed, total_chunks
    """
    # Load config
    config_path = _MEMORY_ROOT / "config" / "memory_bank.config.json"
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        plans_config = config.get('plans', {})
    except Exception as e:
        return {'success': False, 'error': f'Config load failed: {e}'}

    if not plans_config.get('enabled', False):
        return {'success': True, 'skipped': True, 'reason': 'plans disabled'}

    # Resolve plans directory (relative to repo root)
    plans_dir = plans_config.get('path', 'src/aipass/flow/processed_plans')
    repo_root = _find_repo_root()
    plans_path = Path(plans_dir) if Path(plans_dir).is_absolute() else repo_root / plans_dir
    extensions = plans_config.get('supported_extensions', ['.md'])
    collection_name = plans_config.get('collection_name', 'flow_plans')

    if not plans_path.exists():
        return {'success': True, 'files_processed': 0, 'total_chunks': 0, 'reason': 'plans dir not found'}

    # Get plan files
    files = []
    for ext in extensions:
        files.extend(plans_path.glob(f'*{ext}'))

    if not files:
        return {'success': True, 'files_processed': 0, 'total_chunks': 0}

    # Load manifest to skip already-processed files
    manifest = _load_manifest()
    unprocessed = [f for f in files if f.name not in manifest]

    if not unprocessed:
        return {'success': True, 'files_processed': 0, 'total_chunks': 0, 'reason': 'all files already processed'}

    logger.info(f"[plans] Found {len(unprocessed)} unprocessed plan files")

    total_chunks = 0
    files_processed = 0
    errors = []

    for plan_file in unprocessed:
        try:
            text = plan_file.read_text(encoding='utf-8')
        except Exception as e:
            errors.append(f'{plan_file.name}: read error: {e}')
            continue

        # Chunk the plan
        chunks = _chunk_plan_text(text, plan_file.name)
        if not chunks:
            manifest[plan_file.name] = datetime.now().isoformat()
            continue

        # Extract texts and build metadata
        texts = [c['text'] for c in chunks]
        metadatas = [
            {
                'source_file': plan_file.name,
                'section': c['section'],
                'processed_at': datetime.now().isoformat(),
                'type': 'plan'
            }
            for c in chunks
        ]

        # Embed
        embed_result = _embed_texts(texts)
        if not embed_result.get('success'):
            errors.append(f"{plan_file.name}: embed error: {embed_result.get('error')}")
            continue

        embeddings = embed_result.get('embeddings', [])
        if not embeddings:
            errors.append(f'{plan_file.name}: no embeddings returned')
            continue

        # Store
        store_result = _store_vectors(embeddings, texts, metadatas, collection_name)
        if not store_result.get('success'):
            errors.append(f"{plan_file.name}: store error: {store_result.get('error')}")
            continue

        # Mark as processed
        manifest[plan_file.name] = datetime.now().isoformat()
        files_processed += 1
        total_chunks += len(chunks)
        logger.info(f"[plans] Processed {plan_file.name}: {len(chunks)} chunks vectorized")

    # Save manifest
    _save_manifest(manifest)

    result = {
        'success': files_processed > 0 or not errors,
        'files_processed': files_processed,
        'total_chunks': total_chunks,
    }
    if errors:
        result['errors'] = errors

    log_operation("process_plans", {"files_processed": files_processed, "total_chunks": total_chunks, "success": result['success']})

    return result
