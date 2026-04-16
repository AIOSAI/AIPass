# =================== AIPass ====================
# Name: normalize.py
# Description: Memory File Schema Normalizer
# Version: 0.2.0
# Created: 2026-01-22
# Modified: 2026-03-06
# =============================================

"""
Memory File Schema Normalizer

Fixes inconsistent schema in memory JSON files:
1. Moves root-level 'limits' into document_metadata.limits
2. Removes redundant root-level 'status'
3. Removes auto_compress_at (redundant with max_lines)
4. Ensures document_metadata.status has current_lines

Supports two schema versions:
  v1 (schema_version <2.0.0): { "limits": { "max_lines": N } }
  v2 (schema_version >=2.0.0): { "limits": { "max_sessions": N, "max_key_learnings": N,
      "session_summary_max_chars": N, "learning_value_max_chars": N } }
"""

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def normalize_memory_file(file_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    Normalize schema for a single memory file.

    Args:
        file_path: Path to memory JSON file
        dry_run: If True, report changes without writing

    Returns:
        Dict with success status and changes made
    """
    if not file_path.exists():
        return {'success': False, 'error': f"File not found: {file_path}"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[normalize] Failed to read {file_path}: {e}")
        return {'success': False, 'error': f"Failed to read: {e}"}

    changes = []

    # Ensure document_metadata exists
    if 'document_metadata' not in data:
        data['document_metadata'] = {}
        changes.append("Created document_metadata")

    metadata = data['document_metadata']

    # 1. Move root 'limits' into document_metadata.limits
    if 'limits' in data and 'limits' not in metadata:
        metadata['limits'] = data.pop('limits')
        changes.append("Moved root 'limits' into document_metadata")
    elif 'limits' in data and 'limits' in metadata:
        # Both exist - merge, preferring document_metadata values
        root_limits = data.pop('limits')
        for key, val in root_limits.items():
            if key not in metadata['limits']:
                metadata['limits'][key] = val
        changes.append("Merged root 'limits' into document_metadata.limits")

    # 2. Remove root 'status' (redundant)
    if 'status' in data:
        root_status = data.pop('status')
        # If document_metadata.status doesn't have current_lines, copy it
        if 'status' not in metadata:
            metadata['status'] = {}
        if 'current_lines' not in metadata['status'] and 'current_lines' in root_status:
            metadata['status']['current_lines'] = root_status['current_lines']
        changes.append("Removed redundant root 'status'")

    # 3. Remove auto_compress_at from document_metadata.status (redundant with max_lines)
    if 'status' in metadata and 'auto_compress_at' in metadata['status']:
        del metadata['status']['auto_compress_at']
        changes.append("Removed redundant 'auto_compress_at'")

    # 4. Remove unused limits fields (max_word_count, max_token_count - no code uses these)
    # Preserve v2 fields: max_sessions, max_key_learnings, session_summary_max_chars, learning_value_max_chars,
    # max_observations, max_lines, note
    if 'limits' in metadata:
        for unused_field in ['max_word_count', 'max_token_count']:
            if unused_field in metadata['limits']:
                del metadata['limits'][unused_field]
                changes.append(f"Removed unused '{unused_field}'")

    # 4. Ensure status has required fields
    if 'status' not in metadata:
        metadata['status'] = {}

    if 'current_lines' not in metadata['status']:
        # Count actual lines
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                metadata['status']['current_lines'] = len(f.readlines())
            changes.append("Added current_lines count")
        except Exception as e:
            logger.warning(f"[normalize] Failed to count lines in {file_path}: {e}")

    if 'last_health_check' not in metadata['status']:
        metadata['status']['last_health_check'] = datetime.now().strftime("%Y-%m-%d")
        changes.append("Added last_health_check")

    # Write if changes made and not dry run
    if changes and not dry_run:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"[normalize] Failed to write {file_path}: {e}")
            return {'success': False, 'error': f"Failed to write: {e}"}

    json_handler.log_operation("normalize_memory_file", {"file": file_path.name, "changes": len(changes), "success": True})

    return {
        'success': True,
        'file': str(file_path),
        'changes': changes,
        'dry_run': dry_run
    }


def normalize_all_memory_files(dry_run: bool = False) -> Dict[str, Any]:
    """
    Normalize schema for all memory files in AIPASS_REGISTRY.

    Args:
        dry_run: If True, report changes without writing

    Returns:
        Dict with statistics
    """
    # Read registry
    registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"

    if not registry_path.exists():
        return {'success': False, 'error': "AIPASS_REGISTRY.json not found"}

    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
            branches = registry.get('branches', [])
    except Exception as e:
        logger.warning(f"[normalize] Failed to read registry: {e}")
        return {'success': False, 'error': f"Failed to read registry: {e}"}

    results = {
        'success': True,
        'files_checked': 0,
        'files_modified': 0,
        'dry_run': dry_run,
        'details': []
    }

    for branch in branches:
        branch_path = Path(branch.get('path', ''))
        branch_name = branch.get('name', '').upper()

        if not branch_path.exists():
            continue

        # Check both file types
        for memory_type in ['local', 'observations']:
            file_name = f"{branch_name}.{memory_type}.json"
            file_path = branch_path / file_name

            if not file_path.exists():
                continue

            results['files_checked'] += 1
            result = normalize_memory_file(file_path, dry_run=dry_run)

            if result['success'] and result.get('changes'):
                results['files_modified'] += 1
                results['details'].append({
                    'file': file_name,
                    'changes': result['changes']
                })

    return results


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Normalize memory file schema")
    parser.add_argument('--dry-run', action='store_true', help="Report changes without writing")
    parser.add_argument('--file', type=str, help="Normalize single file")
    args = parser.parse_args()

    if args.file:
        result = normalize_memory_file(Path(args.file), dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    else:
        result = normalize_all_memory_files(dry_run=args.dry_run)
        print(f"Files checked: {result['files_checked']}")
        print(f"Files modified: {result['files_modified']}")
        if result['details']:
            print("\nChanges:")
            for detail in result['details']:
                print(f"  {detail['file']}:")
                for change in detail['changes']:
                    print(f"    - {change}")
