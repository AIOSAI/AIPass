# =================== AIPass ====================
# Name: trail.py
# Description: JSONL trail logger for code that cannot log through prax
# Version: 1.1.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""PRAX trail, door two: a JSONL logger for code on the watched event path; stdlib plus the writer, every failure raises."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Union

from aipass.prax.apps.handlers.logging.jsonl_writer import append_jsonl

_RESERVED = ("ts", "level", "msg")

PRAX_LOGS = Path(__file__).resolve().parents[3] / "logs"  # logging/ -> handlers/ -> apps/ -> prax/


class TrailLogger:
    """Appends `{"ts", "level", "msg", **fields}` lines to one validated `.jsonl` path."""

    def __init__(self, path: Union[str, Path]) -> None:
        path = Path(path)
        # The log watcher reads only *.log; a .jsonl trail is never fed back into it.
        if path.suffix != ".jsonl":
            raise ValueError(f"trail path must end in .jsonl: {path}")
        if path.parent.name != "logs":
            raise ValueError(f"trail path must sit in the caller's logs/ directory: {path}")
        self.path = path

    def _emit(self, level: str, message: str, fields: dict) -> None:
        """Append one line; a reserved field name or a failed write raises."""
        clash = sorted(set(fields) & set(_RESERVED))
        if clash:
            raise ValueError(f"trail fields may not overwrite {clash}")
        append_jsonl(self.path, {"ts": datetime.now().isoformat(), "level": level, "msg": message, **fields})

    def debug(self, message: str, **fields: Any) -> None:
        """Record a DEBUG line on the trail."""
        self._emit("DEBUG", message, fields)

    def info(self, message: str, **fields: Any) -> None:
        """Record an INFO line on the trail."""
        self._emit("INFO", message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        """Record a WARNING line on the trail."""
        self._emit("WARNING", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        """Record an ERROR line on the trail."""
        self._emit("ERROR", message, fields)


def trail(path: Union[str, Path]) -> TrailLogger:
    """Build a trail logger writing to *path*, which must be `<caller>/logs/<name>.jsonl`."""
    return TrailLogger(path)


class PraxTrail(TrailLogger):
    """Prax's own diagnostics on `prax/logs/<module>.jsonl`, for files that build or sit under door one."""

    def __init__(self, module: str) -> None:
        self.module = module

    @property
    def path(self) -> Path:
        """Resolved per line: a test's late AIPASS_TEST_LOG_DIR must still keep it off the live logs."""
        test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
        logs = Path(test_dir) / "prax" / "logs" if test_dir else PRAX_LOGS
        return logs / f"{self.module}.jsonl"
