# =================== AIPass ====================
# Name: cleanup.py
# Description: Usage data retention and cleanup
# Version: 0.1.4
# Created: 2025-11-16
# Modified: 2026-10-24
# =============================================

"""Usage Data Cleanup Handler"""

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler

DEFAULT_RETENTION_DAYS = 30

# A crashed holder leaves its lock behind; past this age it is broken rather than honoured forever.
LOCK_STALE_SECONDS = 30
LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.02


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


@contextmanager
def store_lock(file_path: Path) -> Iterator[None]:
    """Hold the store's exclusive lock (a sibling .lock file) across one read-modify-write; OSError past the wait."""
    # O_CREAT|O_EXCL rather than fcntl, as host/tokens.py does: this has to work on Windows too.
    lock = file_path.with_name(file_path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError) as e:
            # Windows answers a delete-pending lock with PermissionError: still held, so poll it.
            if isinstance(e, FileExistsError) and _lock_is_stale(lock):
                logger.warning(f"Breaking a stale usage store lock: {lock}")
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise OSError(f"Usage store lock held longer than {LOCK_WAIT_SECONDS}s at {lock}") from e
            time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock.unlink(missing_ok=True)
        except OSError as e:
            # Never raised: a release that throws would mask whatever the body was doing.
            logger.warning(f"Could not remove the usage store lock: {e}")


def _lock_is_stale(lock: Path) -> bool:
    """Whether a held lock is old enough to be broken; a lock gone since the failed create is not."""
    try:
        return time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False


def parse_retention_days(args: List[str]) -> int:
    """The retention days a cleanup command asked for; DEFAULT_RETENTION_DAYS when none, ValueError unless above 0."""
    if not args:
        return DEFAULT_RETENTION_DAYS
    refusal = f"Retention days must be a whole number above 0, got {args[0]!r}"
    try:
        days = int(args[0])
    except ValueError as e:
        logger.warning(f"cleanup refused a non-number for days: {e}")
        raise ValueError(refusal) from e
    if days <= 0:
        # Zero or fewer days would wipe every entry.
        raise ValueError(refusal)
    return days


def cleanup_old_data(data_file_path: Path, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Remove usage data older than retention period; zero or fewer days is refused with ValueError."""
    if retention_days <= 0:
        raise ValueError(f"Retention days must be above 0, got {retention_days}: zero or less would wipe all history")
    try:
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        with store_lock(data_file_path):
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
