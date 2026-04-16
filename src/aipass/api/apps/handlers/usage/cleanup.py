# =================== AIPass ====================
# Name: cleanup.py
# Description: Usage data retention and cleanup
# Version: 0.1.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
Usage Data Cleanup Handler

Manages data retention policies and cleanup operations.
Removes old generation tracking data based on retention rules.
"""

# Infrastructure
from pathlib import Path

# Standard library
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# Default retention period
DEFAULT_RETENTION_DAYS = 30


def _read_json(file_path: Path) -> Optional[Dict]:
    """Read JSON file with error handling."""
    try:
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON from {file_path}: {e}")
        return None


def _write_json(file_path: Path, data: Dict) -> bool:
    """Write JSON file with error handling."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to write JSON to {file_path}: {e}")
        return False


def cleanup_old_data(data_file_path: Path, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """
    Remove usage data older than retention period.

    Args:
        data_file_path: Path to the usage data JSON file
        retention_days: Number of days to retain data (default: 30)

    Returns:
        int: Number of generation entries cleaned up
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        data = _read_json(data_file_path)
        if not data:
            return 0

        # Extract the actual data content (handle wrapper structure)
        data_content = data.get("data", data)

        # Identify and remove old generation tracking entries
        old_generations = _identify_old_generations(data_content.get("generation_tracking", {}), cutoff_date)

        if not old_generations:
            return 0

        for gen_id in old_generations:
            del data_content["generation_tracking"][gen_id]

        # Update wrapper if needed
        if "data" in data:
            data["data"] = data_content
            data["timestamp"] = datetime.now().isoformat()

        _write_json(data_file_path, data)
        logger.info(f"Cleaned up {len(old_generations)} generation entries")
        logger.info(f"Cleaned up {len(old_generations)} generation entries older than {retention_days} days")
        json_handler.log_operation(
            "usage_cleanup", {"generations_removed": len(old_generations), "retention_days": retention_days}
        )

        return len(old_generations)

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return 0


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
