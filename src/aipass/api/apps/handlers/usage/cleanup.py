# =================== AIPass ====================
# Name: cleanup.py
# Description: Usage data retention and cleanup
# Version: 0.1.2
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""Usage Data Cleanup Handler"""

from pathlib import Path

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler

DEFAULT_RETENTION_DAYS = 30


def _read_json(file_path: Path) -> Optional[Dict]:
    """Read a JSON file; None only when it is absent."""
    if not file_path.exists():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(file_path: Path, data: Dict) -> bool:
    """Write a JSON file, creating its parent; True once written.

    Written to a sibling then replaced, so a failed write never leaves a cut store. On Windows the replace
    raises PermissionError while another process holds the store open; the store stays whole.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    sibling = file_path.with_name(file_path.name + ".tmp")
    try:
        sibling.write_text(text, encoding="utf-8")
        sibling.replace(file_path)
    except BaseException:
        sibling.unlink(missing_ok=True)
        raise
    return True


def cleanup_old_data(data_file_path: Path, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Remove usage data older than retention period."""
    try:
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        data = _read_json(data_file_path)
        if not data:
            return 0

        data_content = data.get("data", data)

        old_generations = _identify_old_generations(data_content.get("generation_tracking", {}), cutoff_date)

        if not old_generations:
            return 0

        for gen_id in old_generations:
            del data_content["generation_tracking"][gen_id]

        if "data" in data:
            data["data"] = data_content
            data["timestamp"] = datetime.now().isoformat()

        _write_json(data_file_path, data)

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise

    # The store is cleaned on disk from here on: a failing audit line is logged, never reported as a failed cleanup.
    logger.info(f"Cleaned up {len(old_generations)} generation entries older than {retention_days} days")
    try:
        json_handler.log_operation(
            "usage_cleanup", {"generations_removed": len(old_generations), "retention_days": retention_days}
        )
    except Exception as e:
        logger.warning(f"Cleanup landed but its audit line failed: {e}")

    return len(old_generations)


def _identify_old_generations(generation_tracking: Dict, cutoff_date: datetime) -> List[str]:
    """Identify generation IDs older than cutoff date."""
    old_generations = []

    for gen_id, gen_data in generation_tracking.items():
        try:
            timestamp_str = gen_data.get("timestamp")
            if not timestamp_str:
                old_generations.append(gen_id)
                continue

            gen_date = datetime.fromisoformat(timestamp_str)
            if gen_date < cutoff_date:
                old_generations.append(gen_id)

        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid timestamp for generation {gen_id}, marking for cleanup: {e}")
            old_generations.append(gen_id)

    return old_generations
