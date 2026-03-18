# ===================AIPASS====================
# META DATA HEADER
# Name: pool_processor.py - Memory Pool Intake Handler
# Date: 2025-11-27
# Version: 0.2.0
# Category: memory/handlers/intake
#
# CHANGELOG (Max 5 entries):
#   - v0.2.0 (2026-03-16): Modernize imports, paths, remove MEMORY_BANK references
#   - v0.1.0 (2025-11-27): Initial version - process memory_pool files to vectors
#
# CODE STANDARDS:
#   - Pure handler: No orchestration, just processing logic
#   - Stateless functions
#   - Returns dict with success/error
# =============================================

"""
Memory Pool Intake Handler

Processes markdown/text files from memory_pool directory:
1. Reads files and extracts content
2. Chunks large files for embedding
3. Vectorizes via ChromaDB
4. Archives old files based on retention config

All settings read from memory_bank.config.json
"""

import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from aipass.memory.apps.handlers.json.json_handler import log_operation

# Paths
_MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # handlers/intake/ → handlers/ → apps/ → memory/
CONFIG_PATH = _MEMORY_ROOT / "config" / "memory_bank.config.json"
MEMORY_POOL_PATH = _MEMORY_ROOT / "memory_pool"
CHROMA_PATH = _MEMORY_ROOT / ".chroma"


AI_MAIL_PATH = _MEMORY_ROOT.parent / "ai_mail" / "apps" / "ai_mail.py"


def _notify_failure(subject: str, message: str) -> None:
    """Send failure notification to @dev_central via ai_mail."""
    try:
        subprocess.run(
            ["python3", str(AI_MAIL_PATH), "send", "@dev_central", subject, message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_MEMORY_ROOT)
        )
    except Exception:
        pass  # Best-effort - don't let notification failure break processing


def _update_central_and_dashboard() -> None:
    """
    Update memory central stats and push dashboard section after vector writes.

    Uses subprocess to call sibling handlers (central_writer, dashboard_push)
    to maintain handler independence. Failures are silent.
    """
    import sys

    # Update central stats
    try:
        subprocess.run(
            [sys.executable, "-c",
             "from aipass.memory.apps.handlers.central_writer import update_central;"
             "update_central()"],
            capture_output=True, text=True, timeout=30
        )
    except Exception:
        pass  # Non-critical: central update failure does not break pool processing

    # Push dashboard to all branches
    try:
        subprocess.run(
            [sys.executable, "-c",
             "from aipass.memory.apps.handlers.dashboard_push import push_memory_bank_dashboard;"
             "push_memory_bank_dashboard()"],
            capture_output=True, text=True, timeout=60
        )
    except Exception:
        pass  # Non-critical: dashboard push failure does not break pool processing


def find_source_file(filename: str) -> Path | None:
    """
    Find full source file from search result metadata.

    Checks active pool first, then archive.

    Args:
        filename: Source filename from search metadata

    Returns:
        Path to file if found, None otherwise
    """
    # Check active pool first
    active = MEMORY_POOL_PATH / filename
    if active.exists():
        return active

    # Check archive
    archived = MEMORY_POOL_PATH / ".archive" / filename
    if archived.exists():
        return archived

    return None


def load_config() -> dict:
    """Load memory_pool config from memory_bank.config.json"""
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        return config.get('memory_pool', {})
    except Exception as e:
        return {'enabled': False, 'error': str(e)}


def get_pool_files(extensions: List[str] | None = None) -> List[Path]:
    """
    Get all files from memory_pool sorted by modification time (newest first).

    Args:
        extensions: List of extensions to include (e.g., ['.md', '.txt'])

    Returns:
        List of Path objects sorted newest to oldest
    """
    if extensions is None:
        extensions = ['.md', '.txt']

    if not MEMORY_POOL_PATH.exists():
        return []

    files = []
    for ext in extensions:
        files.extend(MEMORY_POOL_PATH.glob(f'*{ext}'))

    # Sort by modification time, newest first
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def read_file_content(file_path: Path) -> dict:
    """
    Read content from a file.

    Returns:
        dict with 'success', 'content', 'metadata'
    """
    try:
        content = file_path.read_text(encoding='utf-8')
        stat = file_path.stat()

        return {
            'success': True,
            'content': content,
            'metadata': {
                'filename': file_path.name,
                'path': str(file_path),
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'extension': file_path.suffix
            }
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def chunk_content(content: str, chunk_size: int = 1000, overlap: int = 100) -> List[Dict[str, Any]]:
    """
    Split content into overlapping chunks for embedding.

    Args:
        content: Full text content
        chunk_size: Target size per chunk (characters)
        overlap: Overlap between chunks

    Returns:
        List of dicts with 'text' and 'chunk_index'
    """
    if len(content) <= chunk_size:
        return [{'text': content, 'chunk_index': 0}]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(content):
        end = start + chunk_size

        # Try to break at paragraph or sentence
        if end < len(content):
            # Look for paragraph break
            para_break = content.rfind('\n\n', start, end)
            if para_break > start + chunk_size // 2:
                end = para_break + 2
            else:
                # Look for sentence break
                sentence_break = content.rfind('. ', start, end)
                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 2

        chunk_text = content[start:end].strip()
        if chunk_text:
            chunks.append({
                'text': chunk_text,
                'chunk_index': chunk_index
            })
            chunk_index += 1

        start = end - overlap if end < len(content) else len(content)

    return chunks


def process_file_to_vectors(file_path: Path, collection_name: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> dict:
    """
    Process a single file: read, chunk, and store vectors.

    Args:
        file_path: Path to the file
        collection_name: ChromaDB collection name
        chunk_size: Characters per chunk
        chunk_overlap: Overlap between chunks

    Returns:
        dict with 'success', 'chunks_stored', 'error'
    """
    # Read file
    read_result = read_file_content(file_path)
    if not read_result['success']:
        return read_result

    content = read_result['content']
    metadata = read_result['metadata']

    # Chunk content
    chunks = chunk_content(content, chunk_size, chunk_overlap)

    # Import ChromaDB and sentence transformers (late import for venv compatibility)
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_or_create_collection(name=collection_name)
        model = SentenceTransformer('all-MiniLM-L6-v2')

        # Generate embeddings and store
        documents = []
        embeddings_list = []
        ids = []
        metadatas = []

        for chunk in chunks:
            doc_id = f"{file_path.stem}_{chunk['chunk_index']}"
            documents.append(chunk['text'])
            ids.append(doc_id)
            metadatas.append({
                'source': metadata['filename'],
                'chunk_index': chunk['chunk_index'],
                'total_chunks': len(chunks),
                'processed_at': datetime.now().isoformat(),
                'type': 'memory_pool'
            })

        # Batch encode
        embeddings = model.encode(documents).tolist()

        # Upsert (update if exists, insert if not)
        collection.upsert(
            documents=documents,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas
        )

        return {
            'success': True,
            'file': metadata['filename'],
            'chunks_stored': len(chunks),
            'collection': collection_name
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def archive_old_files(keep_recent: int, archive_path: str = 'memory_pool_archive') -> dict:
    """
    Archive files beyond the keep_recent limit.

    Args:
        keep_recent: Number of files to keep in memory_pool
        archive_path: Subdirectory name for archived files

    Returns:
        dict with 'success', 'archived_count', 'kept_count'
    """
    config = load_config()
    extensions = config.get('supported_extensions', ['.md', '.txt'])

    files = get_pool_files(extensions)

    if len(files) <= keep_recent:
        return {
            'success': True,
            'archived_count': 0,
            'kept_count': len(files),
            'message': 'No files need archiving'
        }

    # Files to keep (most recent)
    keep_files = files[:keep_recent]
    archive_files = files[keep_recent:]

    # Create archive directory
    archive_dir = _MEMORY_ROOT / archive_path
    archive_dir.mkdir(exist_ok=True)

    archived_count = 0
    errors = []

    for file_path in archive_files:
        try:
            dest = archive_dir / file_path.name
            # If file exists in archive, add timestamp
            if dest.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                dest = archive_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"

            shutil.move(str(file_path), str(dest))
            archived_count += 1
        except Exception as e:
            errors.append(f"{file_path.name}: {e}")

    result = {
        'success': len(errors) == 0,
        'archived_count': archived_count,
        'kept_count': len(keep_files),
        'errors': errors if errors else None
    }

    if errors:
        _notify_failure(
            f"Pool Archive Failed: {len(errors)} files",
            f"Failed to archive {len(errors)} memory pool files.\n\n"
            f"Errors:\n" + '\n'.join(errors)
        )

    return result


def process_memory_pool() -> dict:
    """
    Main entry point: Process all memory_pool files.

    Reads config, processes files to vectors, archives old files.

    Returns:
        dict with full processing results
    """
    # Ensure memory_pool directory exists for file drops
    MEMORY_POOL_PATH.mkdir(parents=True, exist_ok=True)

    config = load_config()

    if not config.get('enabled', False):
        return {'success': False, 'error': 'memory_pool processing is disabled in config'}

    keep_recent = config.get('keep_recent', 10)
    collection_name = config.get('collection_name', 'memory_pool_docs')
    chunk_size = config.get('chunk_size', 1000)
    chunk_overlap = config.get('chunk_overlap', 100)
    extensions = config.get('supported_extensions', ['.md', '.txt'])
    archive_path = config.get('archive_path', 'memory_pool_archive')

    # Get all files
    files = get_pool_files(extensions)

    if not files:
        return {
            'success': True,
            'message': 'No files in memory_pool to process',
            'files_processed': 0
        }

    results = {
        'success': True,
        'files_found': len(files),
        'files_processed': 0,
        'total_chunks': 0,
        'errors': [],
        'processed_files': []
    }

    # Process each file
    for file_path in files:
        result = process_file_to_vectors(
            file_path,
            collection_name,
            chunk_size,
            chunk_overlap
        )

        if result['success']:
            results['files_processed'] += 1
            results['total_chunks'] += result.get('chunks_stored', 0)
            results['processed_files'].append(result['file'])
        else:
            results['errors'].append(f"{file_path.name}: {result.get('error')}")

    # Archive old files
    archive_result = archive_old_files(keep_recent, archive_path)
    results['archive'] = archive_result

    if results['errors']:
        results['success'] = False

        # Notify @dev_central about processing failures
        error_count = len(results['errors'])
        total_files = results['files_found']
        error_summary = '\n'.join(results['errors'][:10])  # Cap at 10 for readability
        if error_count > 10:
            error_summary += f'\n... and {error_count - 10} more errors'

        _notify_failure(
            f"Pool Processing Failed: {error_count}/{total_files} files",
            f"Memory pool processing encountered {error_count} failures "
            f"out of {total_files} files.\n\n"
            f"Errors:\n{error_summary}\n\n"
            f"Successfully processed: {results['files_processed']}/{total_files}"
        )

    # Update central stats and push dashboard after processing vectors
    if results['files_processed'] > 0:
        _update_central_and_dashboard()

    log_operation("process_memory_pool", {"files_processed": results['files_processed'], "total_chunks": results['total_chunks'], "success": results['success']})

    return results


def get_pool_status() -> dict:
    """
    Get current status of memory_pool.

    Returns:
        dict with file counts, config, and collection info
    """
    config = load_config()
    extensions = config.get('supported_extensions', ['.md', '.txt'])
    files = get_pool_files(extensions)

    # Get collection count
    collection_count = 0
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection_name = config.get('collection_name', 'memory_pool_docs')
        if collection_name in [c.name for c in client.list_collections()]:
            collection = client.get_collection(name=collection_name)
            collection_count = collection.count()
    except Exception:
        pass

    return {
        'enabled': config.get('enabled', False),
        'files_in_pool': len(files),
        'keep_recent': config.get('keep_recent', 10),
        'vectors_stored': collection_count,
        'collection_name': config.get('collection_name', 'memory_pool_docs'),
        'newest_file': files[0].name if files else None,
        'oldest_file': files[-1].name if files else None
    }


# Standalone execution for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        status = get_pool_status()
        print(json.dumps(status, indent=2))
    else:
        print("Processing memory_pool...")
        result = process_memory_pool()
        print(json.dumps(result, indent=2))
