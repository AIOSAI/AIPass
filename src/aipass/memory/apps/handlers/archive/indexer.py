# =================== AIPass ====================
# Name: indexer.py
# Description: Code Archive Indexer
# Version: 0.2.0
# Created: 2025-11-27
# Modified: 2026-03-06
# =============================================

"""
Code Archive Indexer

Indexes Python files in code_archive directory:
1. Scans for .py files
2. Extracts docstrings and metadata
3. Creates/updates index.json catalog

No vectorization - just a searchable catalog.
"""

import ast
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

logger = get_system_logger()

# Paths resolved relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
CODE_ARCHIVE_PATH = _MEMORY_ROOT / "code_archive"
INDEX_PATH = CODE_ARCHIVE_PATH / "index.json"


def extract_file_info(file_path: Path) -> Dict[str, Any]:
    """
    Extract metadata from a Python file.

    Args:
        file_path: Path to Python file

    Returns:
        Dict with filename, docstring, functions, classes
    """
    try:
        content = file_path.read_text(encoding='utf-8')

        # Parse AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {
                'filename': file_path.name,
                'path': str(file_path.relative_to(CODE_ARCHIVE_PATH)),
                'docstring': None,
                'error': 'Syntax error - could not parse',
                'size': file_path.stat().st_size,
                'indexed_at': datetime.now().isoformat()
            }

        # Get module docstring
        docstring = ast.get_docstring(tree)

        # Get function and class names
        functions = []
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)

        return {
            'filename': file_path.name,
            'path': str(file_path.relative_to(CODE_ARCHIVE_PATH)),
            'docstring': docstring[:200] + '...' if docstring and len(docstring) > 200 else docstring,
            'functions': functions[:10],  # Limit to first 10
            'classes': classes[:10],
            'size': file_path.stat().st_size,
            'lines': len(content.splitlines()),
            'indexed_at': datetime.now().isoformat()
        }
    except Exception as e:
        return {
            'filename': file_path.name,
            'path': str(file_path),
            'error': str(e),
            'indexed_at': datetime.now().isoformat()
        }


def get_archive_files() -> List[Path]:
    """
    Get all Python files in code_archive.

    Returns:
        List of Path objects for all .py files
    """
    if not CODE_ARCHIVE_PATH.exists():
        return []

    files = list(CODE_ARCHIVE_PATH.rglob('*.py'))
    # Exclude __init__.py files
    files = [f for f in files if f.name != '__init__.py']
    return sorted(files)


def load_index() -> Dict[str, Any]:
    """
    Load existing index.json or create empty structure.

    Returns:
        Index dict with metadata and files
    """
    if INDEX_PATH.exists():
        try:
            with open(INDEX_PATH) as f:
                return json.load(f)
        except Exception:
            pass

    return {
        'metadata': {
            'name': 'Code Archive Index',
            'description': 'Catalog of archived Python modules from old system',
            'created': datetime.now().isoformat(),
            'last_updated': None,
            'total_files': 0
        },
        'categories': {},
        'files': {}
    }


def save_index(index: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save index.json.

    Args:
        index: Index dict to save

    Returns:
        Dict with success status
    """
    try:
        index['metadata']['last_updated'] = datetime.now().isoformat()
        index['metadata']['total_files'] = len(index['files'])

        with open(INDEX_PATH, 'w') as f:
            json.dump(index, f, indent=2)

        return {'success': True}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def build_index() -> Dict[str, Any]:
    """
    Build complete index from scratch.

    Scans all Python files and creates full index.json.

    Returns:
        Dict with success status and stats
    """
    files = get_archive_files()

    if not files:
        return {
            'success': True,
            'message': 'No files to index',
            'files_indexed': 0
        }

    index = load_index()
    categories = {}

    for file_path in files:
        info = extract_file_info(file_path)

        # Use relative path as key
        key = info['path']
        index['files'][key] = info

        # Track categories (subdirectories)
        category = file_path.parent.name
        if category != 'code_archive':
            if category not in categories:
                categories[category] = []
            categories[category].append(info['filename'])

    index['categories'] = categories

    save_result = save_index(index)

    if not save_result['success']:
        return save_result

    return {
        'success': True,
        'files_indexed': len(files),
        'categories': list(categories.keys())
    }


def check_for_new_files() -> Dict[str, Any]:
    """
    Sync index with actual files.

    Adds new files, removes deleted files from index.

    Returns:
        Dict with changes made
    """
    index = load_index()
    current_files = get_archive_files()

    indexed_paths = set(index.get('files', {}).keys())
    current_paths = {str(f.relative_to(CODE_ARCHIVE_PATH)) for f in current_files}

    new_files = current_paths - indexed_paths
    deleted_files = indexed_paths - current_paths

    if not new_files and not deleted_files:
        return {
            'success': True,
            'new_files': 0,
            'deleted_files': 0,
            'action': 'none'
        }

    # Index new files
    for rel_path in new_files:
        file_path = CODE_ARCHIVE_PATH / rel_path
        if file_path.exists():
            info = extract_file_info(file_path)
            index['files'][rel_path] = info

            # Update category
            category = file_path.parent.name
            if category != 'code_archive':
                if category not in index['categories']:
                    index['categories'][category] = []
                if info['filename'] not in index['categories'][category]:
                    index['categories'][category].append(info['filename'])

    # Remove deleted files from index
    for rel_path in deleted_files:
        if rel_path in index['files']:
            filename = index['files'][rel_path].get('filename')
            del index['files'][rel_path]

            # Clean up category
            for cat, files in index['categories'].items():
                if filename in files:
                    files.remove(filename)

    # Rebuild categories from current files
    index['categories'] = {}
    for rel_path, info in index['files'].items():
        file_path = CODE_ARCHIVE_PATH / rel_path
        category = file_path.parent.name
        if category != 'code_archive':
            if category not in index['categories']:
                index['categories'][category] = []
            if info['filename'] not in index['categories'][category]:
                index['categories'][category].append(info['filename'])

    save_index(index)

    log_operation("index_sync", {"new_files": len(new_files), "deleted_files": len(deleted_files), "success": True})

    return {
        'success': True,
        'new_files': len(new_files),
        'deleted_files': len(deleted_files),
        'files_added': list(new_files) if new_files else None,
        'files_removed': list(deleted_files) if deleted_files else None,
        'action': 'synced'
    }


def get_index_status() -> Dict[str, Any]:
    """
    Get current index status.

    Returns:
        Dict with file counts, categories, last update
    """
    index = load_index()
    current_files = get_archive_files()

    indexed_count = len(index.get('files', {}))
    current_count = len(current_files)

    return {
        'indexed_files': indexed_count,
        'current_files': current_count,
        'unindexed': current_count - indexed_count if current_count > indexed_count else 0,
        'categories': list(index.get('categories', {}).keys()),
        'last_updated': index.get('metadata', {}).get('last_updated')
    }


# Standalone execution
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == 'status':
            status = get_index_status()
            print(json.dumps(status, indent=2))

        elif cmd == 'build':
            print("Building index...")
            result = build_index()
            print(json.dumps(result, indent=2))

        elif cmd == 'check':
            result = check_for_new_files()
            print(json.dumps(result, indent=2))

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: indexer.py [status|build|check]")
    else:
        print("Usage: indexer.py [status|build|check]")
        print("  status - Show index status")
        print("  build  - Build complete index from scratch")
        print("  check  - Check for and index new files")
