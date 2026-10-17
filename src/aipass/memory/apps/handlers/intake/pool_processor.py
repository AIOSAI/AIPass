# =================== AIPass ====================
# Name: pool_processor.py
# Description: Memory Pool Processor
# Version: 0.1.0
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""
Memory Pool Intake Handler
"""

import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parent.parent.parent.parent  # handlers/intake/ → handlers/ → apps/ → memory/
MEMORY_POOL_PATH = _MEMORY_ROOT / "memory_pool"
CHROMA_PATH = _MEMORY_ROOT / ".chroma"


AI_MAIL_PATH = _MEMORY_ROOT.parent / "ai_mail" / "apps" / "ai_mail.py"


def _notify_failure(subject: str, message: str) -> None:
    """Send failure notification to @devpulse via ai_mail."""
    try:
        subprocess.run(
            ["python3", str(AI_MAIL_PATH), "send", "@devpulse", subject, message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_MEMORY_ROOT),
        )
    except Exception as e:
        logger.warning(f"[pool_processor] Failed to send failure notification: {e}")


def _update_central_and_dashboard() -> None:
    """Update memory central stats in a subprocess (handler independence); failures only log."""
    import sys

    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from aipass.memory.apps.handlers.central_writer import update_central;update_central()",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"[pool_processor] Central stats update failed: {e}")


def find_source_file(filename: str) -> Path | None:
    """Find a search hit's source file: the active pool first, then the archive."""
    active = MEMORY_POOL_PATH / filename
    if active.exists():
        return active

    archived = MEMORY_POOL_PATH / ".archive" / filename
    if archived.exists():
        return archived

    return None


def load_config() -> dict:
    """Load memory_pool config from memory.config.json via config_loader."""
    return config_loader.section("memory_pool")


def get_pool_files(extensions: List[str] | None = None) -> List[Path]:
    """Get all files from memory_pool sorted by modification time (newest first)."""
    if extensions is None:
        extensions = [".md", ".txt"]

    if not MEMORY_POOL_PATH.exists():
        return []

    files = []
    for ext in extensions:
        files.extend(MEMORY_POOL_PATH.glob(f"*{ext}"))

    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def read_file_content(file_path: Path) -> dict:
    """Read content from a file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        stat = file_path.stat()

        return {
            "success": True,
            "content": content,
            "metadata": {
                "filename": file_path.name,
                "path": str(file_path),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": file_path.suffix,
            },
        }
    except Exception as e:
        logger.warning(f"[pool_processor] Failed to read file content: {e}")
        return {"success": False, "error": str(e)}


def chunk_content(content: str, chunk_size: int = 1000, overlap: int = 100) -> List[Dict[str, Any]]:
    """Split content into overlapping chunks for embedding."""
    if len(content) <= chunk_size:
        return [{"text": content, "chunk_index": 0}]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(content):
        end = start + chunk_size

        if end < len(content):
            para_break = content.rfind("\n\n", start, end)
            if para_break > start + chunk_size // 2:
                end = para_break + 2
            else:
                sentence_break = content.rfind(". ", start, end)
                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 2

        chunk_text = content[start:end].strip()
        if chunk_text:
            chunks.append({"text": chunk_text, "chunk_index": chunk_index})
            chunk_index += 1

        start = end - overlap if end < len(content) else len(content)

    return chunks


def process_file_to_vectors(
    file_path: Path, collection_name: str, chunk_size: int = 1000, chunk_overlap: int = 100
) -> dict:
    """Process a single file: read, chunk, and store vectors."""
    read_result = read_file_content(file_path)
    if not read_result["success"]:
        return read_result

    content = read_result["content"]
    metadata = read_result["metadata"]

    chunks = chunk_content(content, chunk_size, chunk_overlap)

    # Late import: chromadb/fastembed are not importable from every venv.
    try:
        import chromadb
        from fastembed import TextEmbedding

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection = client.get_or_create_collection(name=collection_name)
        model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

        documents = []
        ids = []
        metadatas = []

        for chunk in chunks:
            doc_id = f"{file_path.stem}_{chunk['chunk_index']}"
            documents.append(chunk["text"])
            ids.append(doc_id)
            metadatas.append(
                {
                    "source": metadata["filename"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": len(chunks),
                    "processed_at": datetime.now().isoformat(),
                    "type": "memory_pool",
                }
            )

        embeddings = [e.tolist() for e in model.embed(documents)]

        collection.upsert(documents=documents, embeddings=embeddings, ids=ids, metadatas=metadatas)

        return {
            "success": True,
            "file": metadata["filename"],
            "chunks_stored": len(chunks),
            "collection": collection_name,
        }

    except Exception as e:
        logger.warning(f"[pool_processor] Failed to process file to vectors: {e}")
        return {"success": False, "error": str(e)}


def archive_old_files(keep_recent: int, archive_path: str = "memory_pool_archive") -> dict:
    """Archive files beyond the keep_recent limit."""
    config = load_config()
    extensions = config.get("supported_extensions", [".md", ".txt"])

    files = get_pool_files(extensions)

    if len(files) <= keep_recent:
        return {"success": True, "archived_count": 0, "kept_count": len(files), "message": "No files need archiving"}

    keep_files = files[:keep_recent]
    archive_files = files[keep_recent:]

    archive_dir = _MEMORY_ROOT / archive_path
    archive_dir.mkdir(exist_ok=True)

    archived_count = 0
    errors = []

    for file_path in archive_files:
        try:
            dest = archive_dir / file_path.name
            if dest.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = archive_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"

            shutil.move(str(file_path), str(dest))
            archived_count += 1
        except Exception as e:
            logger.warning(f"[pool_processor] Failed to archive {file_path.name}: {e}")
            errors.append(f"{file_path.name}: {e}")

    result = {
        "success": len(errors) == 0,
        "archived_count": archived_count,
        "kept_count": len(keep_files),
        "errors": errors if errors else None,
    }

    if errors:
        _notify_failure(
            f"Pool Archive Failed: {len(errors)} files",
            f"Failed to archive {len(errors)} memory pool files.\n\nErrors:\n" + "\n".join(errors),
        )

    return result


def process_memory_pool() -> dict:
    """Main entry point: Process all memory_pool files."""
    MEMORY_POOL_PATH.mkdir(parents=True, exist_ok=True)

    config = load_config()

    if not config.get("enabled", False):
        return {"success": False, "error": "memory_pool processing is disabled in config"}

    keep_recent = config.get("keep_recent", 10)
    collection_name = config.get("collection_name", "memory_pool_docs")
    chunk_size = config.get("chunk_size", 1000)
    chunk_overlap = config.get("chunk_overlap", 100)
    extensions = config.get("supported_extensions", [".md", ".txt"])
    archive_path = config.get("archive_path", "memory_pool_archive")

    files = get_pool_files(extensions)

    if not files:
        return {"success": True, "message": "No files in memory_pool to process", "files_processed": 0}

    results = {
        "success": True,
        "files_found": len(files),
        "files_processed": 0,
        "total_chunks": 0,
        "errors": [],
        "processed_files": [],
    }

    for file_path in files:
        result = process_file_to_vectors(file_path, collection_name, chunk_size, chunk_overlap)

        if result["success"]:
            results["files_processed"] += 1
            results["total_chunks"] += result.get("chunks_stored", 0)
            results["processed_files"].append(result["file"])
        else:
            results["errors"].append(f"{file_path.name}: {result.get('error')}")

    archive_result = archive_old_files(keep_recent, archive_path)
    results["archive"] = archive_result

    if results["errors"]:
        results["success"] = False

        error_count = len(results["errors"])
        total_files = results["files_found"]
        error_summary = "\n".join(results["errors"][:10])  # Cap at 10 for readability
        if error_count > 10:
            error_summary += f"\n... and {error_count - 10} more errors"

        _notify_failure(
            f"Pool Processing Failed: {error_count}/{total_files} files",
            f"Memory pool processing encountered {error_count} failures "
            f"out of {total_files} files.\n\n"
            f"Errors:\n{error_summary}\n\n"
            f"Successfully processed: {results['files_processed']}/{total_files}",
        )

    if results["files_processed"] > 0:
        _update_central_and_dashboard()

    json_handler.log_operation(
        "process_memory_pool",
        {
            "files_processed": results["files_processed"],
            "total_chunks": results["total_chunks"],
            "success": results["success"],
        },
    )

    return results


def get_pool_status() -> dict:
    """Get current status of memory_pool."""
    config = load_config()
    extensions = config.get("supported_extensions", [".md", ".txt"])
    files = get_pool_files(extensions)

    collection_count = 0
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        collection_name = config.get("collection_name", "memory_pool_docs")
        if collection_name in [c.name for c in client.list_collections()]:
            collection = client.get_collection(name=collection_name)
            collection_count = collection.count()
    except Exception as e:
        logger.warning(f"[pool_processor] Failed to get collection count: {e}")

    return {
        "enabled": config.get("enabled", False),
        "files_in_pool": len(files),
        "keep_recent": config.get("keep_recent", 10),
        "vectors_stored": collection_count,
        "collection_name": config.get("collection_name", "memory_pool_docs"),
        "newest_file": files[0].name if files else None,
        "oldest_file": files[-1].name if files else None,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status = get_pool_status()
        print(json.dumps(status, indent=2))
    else:
        print("Processing memory_pool...")
        result = process_memory_pool()
        print(json.dumps(result, indent=2))
