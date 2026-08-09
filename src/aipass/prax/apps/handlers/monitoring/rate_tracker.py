# =================== AIPass ====================
# Name: rate_tracker.py
# Description: Log file rate tracking for runaway detection
# Version: 1.2.2
# Created: 2026-07-14
# Modified: 2026-08-08
# =============================================

"""
Rate Tracker — volume-based runaway-log detection.

Tracks byte growth rate per log file in system_logs/. When a file sustains
abnormal growth (lines/min above threshold for consecutive intervals), fires
a ``runaway_log_detected`` event on the trigger event bus.

Orthogonal to medic's content-based ERROR/CRITICAL detection — this catches
rate regardless of log level.

State persists to ``prax_json/rate_tracker_data.json`` so that rates survive
across process restarts and CLI invocations can display meaningful data.
"""

import time
from collections import deque
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.monitoring.branch_detector import detect_branch_from_log

logger = get_direct_logger()

SCAN_INTERVAL = 10.0
AVG_LINE_BYTES = 120

WARNING_LINES_PER_MIN = 100
WARNING_SUSTAINED_INTERVALS = 12  # 12 * 10s = 2 min

CRITICAL_LINES_PER_MIN = 600  # 10/sec * 60
CRITICAL_SUSTAINED_INTERVALS = 6  # 6 * 10s = 1 min

_RATE_HISTORY_SIZE = 30
_WINDOW_INTERVALS = 6

_DATA_FILE = "rate_tracker"


class FileRateState:
    """Per-file tracking state."""

    __slots__ = (
        "last_offset",
        "last_check",
        "rates",
        "warning_sustained",
        "critical_sustained",
        "fired_warning",
        "fired_critical",
    )

    def __init__(self, offset: int, now: float) -> None:
        self.last_offset: int = offset
        self.last_check: float = now
        self.rates: deque = deque(maxlen=_RATE_HISTORY_SIZE)
        self.warning_sustained: int = 0
        self.critical_sustained: int = 0
        self.fired_warning: bool = False
        self.fired_critical: bool = False

    def to_dict(self) -> dict:
        """Serialize to a dict for disk persistence."""
        return {
            "last_offset": self.last_offset,
            "last_check": self.last_check,
            "warning_sustained": self.warning_sustained,
            "critical_sustained": self.critical_sustained,
            "fired_warning": self.fired_warning,
            "fired_critical": self.fired_critical,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileRateState":
        """Restore from a persisted dict."""
        state = cls(d.get("last_offset", 0), d.get("last_check", 0.0))
        state.warning_sustained = d.get("warning_sustained", 0)
        state.critical_sustained = d.get("critical_sustained", 0)
        state.fired_warning = d.get("fired_warning", False)
        state.fired_critical = d.get("fired_critical", False)
        return state


_tracked: Dict[str, FileRateState] = {}

_suppressed_files: set = set()

_logs_dir: Optional[Path] = None

_EVENT_CALLBACK = None

_state_loaded: bool = False


def configure(
    logs_dir: Optional[Path] = None,
    event_callback=None,
    suppressed_files: Optional[set] = None,
) -> None:
    """Inject dependencies from the module layer.

    Args:
        logs_dir: Path to system_logs/ directory to scan.
        event_callback: Callable(event_name, **kwargs) for firing events.
        suppressed_files: Set of log file names to skip during detection.
    """
    global _logs_dir, _EVENT_CALLBACK, _suppressed_files
    if logs_dir is not None:
        _logs_dir = logs_dir
    if event_callback is not None:
        _EVENT_CALLBACK = event_callback
    if suppressed_files is not None:
        _suppressed_files = suppressed_files


def _load_state() -> None:
    """Load persisted tracking state from disk on first scan."""
    global _state_loaded
    if _state_loaded:
        return
    _state_loaded = True

    data = json_handler.load_json(_DATA_FILE, "data")
    if data is None:
        return

    files = data.get("files", {})
    for file_key, state_dict in files.items():
        if not isinstance(state_dict, dict):
            continue
        _tracked[file_key] = FileRateState.from_dict(state_dict)

    count = len(_tracked)
    if count:
        logger.info("[rate_tracker] Loaded %d file states from disk", count)


def _save_state() -> None:
    """Persist current tracking state to disk."""
    files = {}
    for file_key, state in _tracked.items():
        files[file_key] = state.to_dict()

    from datetime import date

    today = date.today().isoformat()
    data = {
        "module_name": _DATA_FILE,
        "created": today,
        "last_updated": today,
        "files": files,
    }
    json_handler.save_json(_DATA_FILE, "data", data)


def scan_rates() -> list:
    """Scan all .log files in system_logs/, update rates, fire events if thresholds met.

    Returns a list of dicts describing each tracked file's current state,
    suitable for display by the log-health command.
    """
    _load_state()

    if _logs_dir is None or not _logs_dir.exists():
        return []

    now = time.time()
    results = []

    current_files = set()
    for log_file in _logs_dir.glob("*.log"):
        file_key = str(log_file)
        current_files.add(file_key)

        if log_file.name in _suppressed_files:
            continue

        try:
            size = log_file.stat().st_size
        except OSError as exc:
            logger.info("[rate_tracker] Cannot stat %s: %s", log_file.name, exc)
            continue

        state = _tracked.get(file_key)
        if state is None:
            _tracked[file_key] = FileRateState(size, now)
            continue

        elapsed = now - state.last_check
        if elapsed < 1.0:
            continue

        if size < state.last_offset:
            # The file shrank: RotatingFileHandler rolled .log -> .log.1 and
            # opened a fresh file, or something truncated it. Bytes written
            # before the roll are no longer observable here, so count the new
            # file's content as this interval's floor (an undercount, which
            # the window average absorbs).
            #
            # Critically, do NOT zero the sustained counters. A rotation is
            # evidence of volume, not of subsidence - and the faster a runaway
            # writes, the sooner it rotates, so resetting here made detection
            # strictly less likely the worse the flood got. The 2026-07-31
            # event-queue firehose ran at ~4090 lines/min (6.8x CRITICAL) and
            # rotated every ~24s, below the 60s CRITICAL needs, so it never
            # fired. Counters still clear on their own via the subsidence
            # branch once the rate actually drops.
            bytes_added = size
        else:
            bytes_added = size - state.last_offset

        lines_estimate = bytes_added / AVG_LINE_BYTES if bytes_added > 0 else 0.0
        lines_per_min = (lines_estimate / elapsed) * 60.0

        state.rates.append((now, lines_per_min))
        state.last_offset = size
        state.last_check = now

        severity = _evaluate_thresholds(state, lines_per_min, file_key, log_file)

        results.append(
            {
                "file": log_file.name,
                "path": file_key,
                "size_kb": round(size / 1024, 1),
                "rate_lines_per_min": round(lines_per_min, 1),
                "warning_sustained": state.warning_sustained,
                "critical_sustained": state.critical_sustained,
                "severity": severity,
                "branch": detect_branch_from_log(file_key),
            }
        )

    stale = [k for k in _tracked if k not in current_files]
    for k in stale:
        del _tracked[k]

    _save_state()
    return results


def _window_average(state: FileRateState) -> float:
    """Average lines/min over the last _WINDOW_INTERVALS entries."""
    if not state.rates:
        return 0.0
    window = list(state.rates)[-_WINDOW_INTERVALS:]
    return sum(r for _, r in window) / len(window)


def _evaluate_thresholds(
    state: FileRateState,
    lines_per_min: float,
    file_key: str,
    log_file: Path,
) -> Optional[str]:
    """Update sustained counters and fire events when thresholds are crossed."""
    severity = None
    effective_rate = max(lines_per_min, _window_average(state))

    if effective_rate >= CRITICAL_LINES_PER_MIN:
        state.critical_sustained += 1
        state.warning_sustained += 1
    elif effective_rate >= WARNING_LINES_PER_MIN:
        state.critical_sustained = 0
        state.warning_sustained += 1
    else:
        if state.fired_warning or state.fired_critical:
            logger.info(
                "[rate_tracker] %s rate subsided (%.0f lines/min avg)",
                log_file.name,
                effective_rate,
            )
        state.warning_sustained = 0
        state.critical_sustained = 0
        state.fired_warning = False
        state.fired_critical = False
        return None

    if state.critical_sustained >= CRITICAL_SUSTAINED_INTERVALS and not state.fired_critical:
        severity = "critical"
        state.fired_critical = True
        duration = state.critical_sustained * SCAN_INTERVAL
        _fire_event(file_key, effective_rate, duration, "critical")
    elif state.warning_sustained >= WARNING_SUSTAINED_INTERVALS and not state.fired_warning:
        severity = "warning"
        state.fired_warning = True
        duration = state.warning_sustained * SCAN_INTERVAL
        _fire_event(file_key, effective_rate, duration, "warning")
    else:
        if state.critical_sustained > 0:
            severity = "rising_critical"
        elif state.warning_sustained > 0:
            severity = "rising_warning"

    return severity


def _fire_event(
    file_path: str,
    rate_lines_per_min: float,
    sustained_duration_sec: float,
    severity: str,
) -> None:
    """Fire runaway_log_detected on the trigger event bus."""
    branch = detect_branch_from_log(file_path)
    logger.warning(
        "[rate_tracker] Runaway log %s: %s is being written at %.0f lines/min, sustained %.0fs "
        "(branch: %s) — at this rate the file rotates quickly, so older entries drop off sooner "
        "than usual. Everything already on disk is intact.",
        severity.upper(),
        Path(file_path).name,
        rate_lines_per_min,
        sustained_duration_sec,
        branch,
    )
    json_handler.log_operation(
        "runaway_detected",
        {
            "file": file_path,
            "rate": rate_lines_per_min,
            "duration": sustained_duration_sec,
            "severity": severity,
            "branch": branch,
        },
    )

    if _EVENT_CALLBACK is not None:
        _EVENT_CALLBACK(
            "runaway_log_detected",
            file_path=file_path,
            rate_lines_per_min=rate_lines_per_min,
            sustained_duration_sec=sustained_duration_sec,
            severity=severity,
            branch=branch,
        )


def _resolve_severity(state: FileRateState) -> Optional[str]:
    """Derive display severity from a file's current state."""
    if state.fired_critical:
        return "critical"
    if state.fired_warning:
        return "warning"
    if state.critical_sustained > 0:
        return "rising_critical"
    if state.warning_sustained > 0:
        return "rising_warning"
    return None


def _file_size(path: str) -> int:
    """Read file size, returning 0 on any OS error."""
    try:
        return Path(path).stat().st_size
    except OSError:
        logger.info("[rate_tracker] Cannot stat %s for snapshot", Path(path).name)
        return 0


def get_snapshot() -> list:
    """Return the current tracking state without scanning (for display only).

    Loads persisted state from disk if not already loaded, so CLI
    invocations can display rates collected by the monitor process.
    """
    _load_state()
    results = []
    for file_key, state in _tracked.items():
        last_rate = state.rates[-1][1] if state.rates else 0.0
        results.append(
            {
                "file": Path(file_key).name,
                "path": file_key,
                "size_kb": round(_file_size(file_key) / 1024, 1),
                "rate_lines_per_min": round(last_rate, 1),
                "warning_sustained": state.warning_sustained,
                "critical_sustained": state.critical_sustained,
                "severity": _resolve_severity(state),
                "branch": detect_branch_from_log(file_key),
            }
        )
    return results
