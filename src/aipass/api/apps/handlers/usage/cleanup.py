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
import sys

# Standard library
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


def _read_json(file_path: Path) -> Optional[Dict]:
    """Read JSON file with error handling."""
    try:
        if not file_path.exists():
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        # logger.error(f"Failed to read JSON from {file_path}: {e}")
        return None


def _write_json(file_path: Path, data: Dict) -> bool:
    """Write JSON file with error handling."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        # logger.error(f"Failed to write JSON to {file_path}: {e}")
        return False


def cleanup_old_data(data_file_path: Path, retention_days: int = 30) -> int:
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
        old_generations = _identify_old_generations(
            data_content.get("generation_tracking", {}),
            cutoff_date
        )

        if not old_generations:
            return 0

        for gen_id in old_generations:
            del data_content["generation_tracking"][gen_id]

        # Update wrapper if needed
        if "data" in data:
            data["data"] = data_content
            data["timestamp"] = datetime.now().isoformat()

        _write_json(data_file_path, data)
        # logger.info(f"Cleaned up {len(old_generations)} generation entries")
        logger.info(f"Cleaned up {len(old_generations)} generation entries older than {retention_days} days")
        json_handler.log_operation("usage_cleanup", {"generations_removed": len(old_generations), "retention_days": retention_days})

        return len(old_generations)

    except Exception as e:
        # logger.error(f"Cleanup failed: {e}")
        logger.error(f"Cleanup failed: {e}")
        raise


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

        except (ValueError, TypeError):
            old_generations.append(gen_id)

    return old_generations


def cleanup_daily_totals(data_file_path: Path, retention_days: int = 90) -> int:
    """Remove daily total entries older than retention period."""
    try:
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).date()
        data = _read_json(data_file_path)
        if not data:
            return 0

        data_content = data.get("data", data)
        old_dates = []
        daily_totals = data_content.get("daily_totals", {})

        for date_str in daily_totals.keys():
            try:
                date_obj = datetime.fromisoformat(date_str).date()
                if date_obj < cutoff_date:
                    old_dates.append(date_str)
            except (ValueError, TypeError):
                old_dates.append(date_str)

        if not old_dates:
            return 0

        for date_str in old_dates:
            del data_content["daily_totals"][date_str]

        if "data" in data:
            data["data"] = data_content
            data["timestamp"] = datetime.now().isoformat()

        _write_json(data_file_path, data)
        # logger.info(f"Cleaned up {len(old_dates)} daily total entries")
        logger.info(f"Cleaned up {len(old_dates)} daily total entries older than {retention_days} days")

        return len(old_dates)

    except Exception as e:
        # logger.error(f"Daily totals cleanup failed: {e}")
        logger.error(f"Daily totals cleanup failed: {e}")
        raise


def auto_cleanup(data_file_path: Path, config: Optional[Dict] = None) -> Dict[str, int]:
    """Perform automatic cleanup based on configuration."""
    try:
        gen_retention = config.get("cleanup_old_data_days", 30) if config else 30
        daily_retention = config.get("cleanup_daily_totals_days", 90) if config else 90

        generations_removed = cleanup_old_data(data_file_path, gen_retention)
        daily_totals_removed = cleanup_daily_totals(data_file_path, daily_retention)

        # logger.info(f"Auto cleanup: {generations_removed} generations, {daily_totals_removed} daily totals removed")

        return {
            "generations_removed": generations_removed,
            "daily_totals_removed": daily_totals_removed
        }

    except Exception as e:
        # logger.error(f"Auto cleanup failed: {e}")
        logger.error(f"Auto cleanup failed: {e}")
        raise


def get_cleanup_stats(data_file_path: Path) -> Dict[str, int]:
    """Get statistics about data that could be cleaned up."""
    empty_stats = {
        "total_generations": 0,
        "total_daily_totals": 0,
        "cleanable_generations": 0,
        "cleanable_daily_totals": 0
    }

    try:
        data = _read_json(data_file_path)
        if not data:
            return empty_stats

        data_content = data.get("data", data)
        generation_tracking = data_content.get("generation_tracking", {})
        daily_totals = data_content.get("daily_totals", {})

        # Count cleanable generations (older than 30 days)
        cutoff_30 = datetime.now() - timedelta(days=30)
        cleanable_gens = len(_identify_old_generations(generation_tracking, cutoff_30))

        # Count cleanable daily totals (older than 90 days)
        cutoff_90 = (datetime.now() - timedelta(days=90)).date()
        cleanable_daily = sum(
            1 for date_str in daily_totals.keys()
            if _is_old_date(date_str, cutoff_90)
        )

        return {
            "total_generations": len(generation_tracking),
            "total_daily_totals": len(daily_totals),
            "cleanable_generations": cleanable_gens,
            "cleanable_daily_totals": cleanable_daily
        }

    except Exception as e:
        # logger.error(f"Failed to get cleanup stats: {e}")
        return empty_stats


def _is_old_date(date_str: str, cutoff_date) -> bool:
    """Check if date string is older than cutoff."""
    try:
        date_obj = datetime.fromisoformat(date_str).date()
        return date_obj < cutoff_date
    except (ValueError, TypeError):
        return True
