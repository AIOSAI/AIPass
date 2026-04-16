# =================== AIPass ====================
# Name: timer.py
# Description: Watchdog Timer Handler — wake-in-N + named duration tracking
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

# Storage choice: .trinity/watchdog_timers.json with atomic write (tmp + rename).
# Devpulse root is resolved by walking upward looking for AIPASS_REGISTRY.json
# (same pattern the agent handler uses to find the repo). Tests override via
# explicit storage_path to avoid touching the real trinity directory.

"""
Watchdog Timer Handler — wake-in-N and named duration tracking.

Public surface:
  parse_duration(duration)       Parse "5m", "30s", "2h", "1h30m", "45"
  format_human(seconds)          Render "5h 3m 12s" / "12m 07s" / "45s"
  wake_in(duration)              Blocking sleep, returns on wake
  timer_start(name, path=None)   Record a named start in .trinity/watchdog_timers.json
  timer_stop(name, path=None)    Stop + persist history entry + return elapsed
  timer_list(path=None)          Active + history snapshot
  timer_report(path=None)        Formatted multi-line session summary
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry


_DURATION_TOKEN_RE = re.compile(r"(\d+)([smh])")
_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}
_STORAGE_FILENAME = "watchdog_timers.json"
_STORAGE_VERSION = 1
_LONG_TIMER_STATUS_INTERVAL = 10.0


def _stderr(msg: str) -> None:
    """Write to stderr so stdout stays clean for callers that capture it."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _find_devpulse_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for AIPASS_REGISTRY.json, then return the devpulse dir."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "AIPASS_REGISTRY.json").exists():
            devpulse_dir = candidate / "src" / "aipass" / "devpulse"
            if devpulse_dir.exists():
                return devpulse_dir
            return candidate
    for candidate in [cur, *cur.parents]:
        if candidate.name == "devpulse":
            return candidate
    return None


def _default_storage_path() -> Path:
    """Resolve `.trinity/watchdog_timers.json` relative to the devpulse root."""
    root = _find_devpulse_root()
    if root is None:
        # Fall back to cwd so callers still get a deterministic path — tests
        # always pass an explicit storage_path so this branch is production-only.
        root = Path.cwd()
    return root / ".trinity" / _STORAGE_FILENAME


def _empty_store() -> dict:
    return {"version": _STORAGE_VERSION, "active": {}, "history": []}


def _load_store(storage_path: Path) -> dict:
    """Load the timer store, returning an empty structure on miss or corruption."""
    if not storage_path.exists():
        return _empty_store()
    try:
        data = json.loads(storage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.timer] could not load %s: %s", storage_path, exc)
        return _empty_store()

    # Tolerate older/partial files rather than crashing a timer operation.
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", _STORAGE_VERSION)
    data.setdefault("active", {})
    data.setdefault("history", [])
    if not isinstance(data["active"], dict):
        data["active"] = {}
    if not isinstance(data["history"], list):
        data["history"] = []
    return data


def _atomic_write(storage_path: Path, data: dict) -> None:
    """Write to a .tmp sibling then rename so concurrent readers never see a half-write."""
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = storage_path.with_suffix(storage_path.suffix + ".tmp")
    try:
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, storage_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError as exc:
                logger.warning("[watchdog.timer] leftover tmp %s: %s", tmp_path, exc)


def parse_duration(duration: str) -> int:
    """Parse a duration string into total seconds.

    Accepts: "5m", "30s", "2h", "1h30m", "45" (bare integer = seconds).

    Raises:
        ValueError: on empty, negative, non-string, or unparseable input.
    """
    if duration is None or not isinstance(duration, str):
        raise ValueError(f"duration must be a string, got {type(duration).__name__}")
    text = duration.strip().lower()
    if not text:
        raise ValueError("duration is empty")
    if text.startswith("-"):
        raise ValueError(f"duration must be non-negative: {duration!r}")

    if text.isdigit():
        return int(text)

    total = 0
    matched_any = False
    cursor = 0
    for match in _DURATION_TOKEN_RE.finditer(text):
        if match.start() != cursor:
            raise ValueError(f"invalid duration: {duration!r}")
        number, unit = match.groups()
        if unit not in _DURATION_UNIT_SECONDS:
            raise ValueError(f"invalid duration unit in {duration!r}")
        total += int(number) * _DURATION_UNIT_SECONDS[unit]
        matched_any = True
        cursor = match.end()

    if not matched_any or cursor != len(text):
        raise ValueError(f"invalid duration: {duration!r}")
    return total


def format_human(seconds: int) -> str:
    """Render a seconds count as ``5h 3m 12s`` / ``12m 07s`` / ``45s``.

    Rules: drop zero higher units; when minutes are present, seconds are
    zero-padded to two digits; hours are never zero-padded.
    """
    if seconds < 0:
        raise ValueError(f"seconds must be non-negative, got {seconds}")
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def wake_in(duration: str) -> dict:
    """Block for ``duration`` then return a wake dict.

    Long timers emit an optional stderr status ping roughly every 10s so
    orchestrators with a console attached can see progress. Short timers
    stay silent so test runs aren't chatty.
    """
    total_seconds = parse_duration(duration)
    started_at = time.monotonic()
    logger.info("[watchdog.timer] wake_in duration=%s total=%ss", duration, total_seconds)
    _stderr(f"[watchdog.timer] sleeping {total_seconds}s ({duration})")

    handle = _registry.register(
        "timer",
        metadata={"duration": duration, "total_seconds": total_seconds},
    )

    try:
        if total_seconds <= _LONG_TIMER_STATUS_INTERVAL:
            time.sleep(total_seconds)
        else:
            remaining = float(total_seconds)
            while remaining > 0:
                chunk = min(_LONG_TIMER_STATUS_INTERVAL, remaining)
                time.sleep(chunk)
                remaining -= chunk
                if remaining > 0:
                    _stderr(f"[watchdog.timer] {int(remaining)}s remaining")

        elapsed = int(time.monotonic() - started_at)
        _stderr(f"[watchdog.timer] woke after {elapsed}s")
        return {
            "woke": True,
            "reason": "timer fired",
            "elapsed": elapsed,
            "duration": duration,
            "state": "woke",
            "handle": handle,
        }
    finally:
        _registry.deregister(handle)


def timer_start(name: str, storage_path: Path | None = None) -> dict:
    """Record a named timer start in the persistent store."""
    if not isinstance(name, str) or not name.strip():
        return {"name": name, "state": "error", "reason": "timer name required"}

    path = storage_path or _default_storage_path()
    store = _load_store(path)
    if name in store["active"]:
        return {"name": name, "state": "error", "reason": "timer already running"}

    now = time.time()
    started_iso = datetime.fromtimestamp(now).isoformat()
    store["active"][name] = {"started_at": started_iso, "started_epoch": now}
    _atomic_write(path, store)
    logger.info("[watchdog.timer] start name=%s", name)
    return {"name": name, "started_at": started_iso, "state": "started"}


def timer_stop(name: str, storage_path: Path | None = None) -> dict:
    """Stop a named timer and persist a history entry."""
    if not isinstance(name, str) or not name.strip():
        return {"name": name, "state": "error", "reason": "timer name required"}

    path = storage_path or _default_storage_path()
    store = _load_store(path)
    if name not in store["active"]:
        return {"name": name, "state": "error", "reason": "timer not running"}

    entry = store["active"].pop(name)
    stopped_epoch = time.time()
    stopped_iso = datetime.fromtimestamp(stopped_epoch).isoformat()
    started_epoch = float(entry.get("started_epoch", stopped_epoch))
    elapsed_seconds = max(0, int(stopped_epoch - started_epoch))

    history_entry = {
        "name": name,
        "started_at": entry.get("started_at"),
        "stopped_at": stopped_iso,
        "started_epoch": started_epoch,
        "stopped_epoch": stopped_epoch,
        "elapsed_seconds": elapsed_seconds,
    }
    store["history"].append(history_entry)
    _atomic_write(path, store)
    logger.info("[watchdog.timer] stop name=%s elapsed=%s", name, elapsed_seconds)

    return {
        "name": name,
        "started_at": entry.get("started_at"),
        "stopped_at": stopped_iso,
        "elapsed_seconds": elapsed_seconds,
        "human": format_human(elapsed_seconds),
        "state": "stopped",
    }


def timer_list(storage_path: Path | None = None) -> dict:
    """Return a snapshot of active + historical timers.

    Active entries include a live ``elapsed_so_far_seconds`` computed against
    ``time.time()`` so callers always see fresh numbers.
    """
    path = storage_path or _default_storage_path()
    store = _load_store(path)
    now = time.time()

    active = []
    for name, entry in sorted(store["active"].items()):
        started_epoch = float(entry.get("started_epoch", now))
        elapsed = max(0, int(now - started_epoch))
        active.append(
            {
                "name": name,
                "started_at": entry.get("started_at"),
                "elapsed_so_far_seconds": elapsed,
                "human": format_human(elapsed),
            }
        )

    history = []
    for entry in store["history"]:
        history.append(
            {
                "name": entry.get("name"),
                "started_at": entry.get("started_at"),
                "stopped_at": entry.get("stopped_at"),
                "elapsed_seconds": entry.get("elapsed_seconds", 0),
                "human": format_human(int(entry.get("elapsed_seconds", 0))),
            }
        )

    return {"active": active, "history": history}


def timer_report(storage_path: Path | None = None) -> str:
    """Return a formatted multi-line session summary suitable for CLI output."""
    snapshot = timer_list(storage_path)
    lines = ["Watchdog Timer Report", "====================="]

    lines.append("Active:")
    if snapshot["active"]:
        for item in snapshot["active"]:
            started = _short_time(item.get("started_at"))
            lines.append(f"  - {item['name']:<15} elapsed {item['human']} (started {started})")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("History (this session):")
    if snapshot["history"]:
        for item in snapshot["history"]:
            started = _short_time(item.get("started_at"))
            stopped = _short_time(item.get("stopped_at"))
            lines.append(f"  - {item['name']:<15} {item['human']:<8} ({started} → {stopped})")
    else:
        lines.append("  (none)")

    total_history = sum(int(item.get("elapsed_seconds", 0)) for item in snapshot["history"])
    total_active = sum(int(item.get("elapsed_so_far_seconds", 0)) for item in snapshot["active"])
    total_all = total_history + total_active
    lines.append("")
    lines.append(
        f"Total tracked: {format_human(total_all)} across "
        f"{len(snapshot['history'])} completed + {len(snapshot['active'])} active"
    )
    return "\n".join(lines)


def _short_time(iso_string: str | None) -> str:
    """Render an ISO timestamp as HH:MM:SS (falls back to the raw string)."""
    if not iso_string:
        return "??:??:??"
    try:
        return datetime.fromisoformat(iso_string).strftime("%H:%M:%S")
    except ValueError as exc:
        logger.info("[watchdog.timer] unparseable iso %r: %s", iso_string, exc)
        return iso_string
