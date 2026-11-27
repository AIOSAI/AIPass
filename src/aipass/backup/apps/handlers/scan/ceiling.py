# =================== AIPass ====================
# Name: ceiling.py
# Description: Per-run size/file-count ceiling — refuses runaway backups loudly
# Version: 1.2.0
# Created: 2026-08-20
# Modified: 2026-11-26
# =============================================

"""Per-run backup ceiling, two layers.

A run far larger than expected is an ignore-pattern miss, not a big project: it is
refused before any copying, naming the directories to add to .backupignore. First
the run is compared with the last good run (growth ratio), then with the absolute walls.
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field

from aipass.prax import logger

from ..audit import trail

DEFAULT_MAX_FILES = 100_000
DEFAULT_MAX_TOTAL_GB = 10
DEFAULT_GROWTH_RATIO = 3

# Deep enough to name "app/src-tauri/target", shallow enough to paste into .backupignore.
_OFFENDER_DEPTH = 3
_OFFENDER_LIMIT = 5

_BYTES_PER_GB = 1024**3


@dataclass
class CeilingBreach:
    """A refused run: which ceiling broke, by how much, and who caused it."""

    reason: str
    measured: int
    limit: int | float
    config_key: str
    offenders: list[tuple[str, int, int]] = field(default_factory=list)
    baseline: int = 0

    def summary(self) -> str:
        """One-line statement of what broke."""
        if self.reason == "unmeasured":
            return f"{self.offenders[0][0]} could not be measured, so the run's size cannot be checked"
        if self.reason in ("file_growth", "size_growth"):
            times = f"{self.measured / self.baseline:.1f}x"
            if self.reason == "file_growth":
                return f"{self.measured:,} files is {times} the last run's {self.baseline:,}"
            return f"{_size(self.measured)} is {times} the last run's {_size(self.baseline)}"
        if self.reason == "file_count":
            return f"{self.measured:,} files exceeds the {self.limit:,}-file ceiling"
        measured_gb = self.measured / _BYTES_PER_GB
        return f"{measured_gb:.1f}GB exceeds the {self.limit}GB ceiling"

    def detail_lines(self) -> list[str]:
        """Operator-facing lines naming the offenders and the way out."""
        if self.reason == "unmeasured":
            return ["Make the file readable or add it to .backupignore, then re-run."]
        lines: list[str] = []
        if self.offenders:
            lines.append("Largest directories in this run:")
            for rel_dir, count, size in self.offenders:
                sized = f" / {size / _BYTES_PER_GB:.1f}GB" if size else ""
                lines.append(f"  {rel_dir}  —  {count:,} files{sized}")
        lines.append("Add the build-artifact directories above to .backupignore, then re-run.")
        really = "grew" if self.config_key == "max_growth_ratio" else "is this large"
        lines.append(f"If the project really {really}, raise '{self.config_key}' in .backup/config.json (0 disables).")
        return lines


def _size(n: int) -> str:
    """Bytes as GB, or MB below one GB, so a small project's growth reads as more than 0.0GB."""
    if n >= _BYTES_PER_GB:
        return f"{n / _BYTES_PER_GB:.1f}GB"
    return f"{n / 1024**2:.1f}MB"


def _offender_key(rel_path: str) -> str:
    """Collapse a relative file path to its reporting directory."""
    parts = rel_path.split("/")[:-1]
    if not parts:
        return "."
    return "/".join(parts[:_OFFENDER_DEPTH])


def _top_offenders(
    files: list[tuple[str, str]],
    sizes: dict[str, int] | None,
) -> list[tuple[str, int, int]]:
    """Rank reporting directories by file count (bytes when already measured)."""
    counts: dict[str, int] = defaultdict(int)
    byte_totals: dict[str, int] = defaultdict(int)

    for _abs_path, rel_path in files:
        key = _offender_key(rel_path)
        counts[key] += 1
        if sizes is not None:
            byte_totals[key] += sizes.get(rel_path, 0)

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [(key, count, byte_totals.get(key, 0)) for key, count in ranked[:_OFFENDER_LIMIT]]


def _refuse(reason: str, measured: int, limit: int | float, config_key: str, offenders: list, base: int = 0):
    """Build, log and answer one CeilingBreach."""
    breach = CeilingBreach(reason, measured, limit, config_key, offenders, base)
    _log_breach(breach)
    return breach


def check_ceiling(
    files: list[tuple[str, str]],
    config: dict,
    baseline: dict | None = None,
) -> CeilingBreach | None:
    """Measure a filtered file set against the last good run, then the walls; a CeilingBreach refuses the run.

    baseline is load_baseline()'s answer: None (no good run yet) leaves only the absolute walls.
    """
    max_files = config.get("max_backup_files", DEFAULT_MAX_FILES)
    max_gb = config.get("max_backup_size_gb", DEFAULT_MAX_TOTAL_GB)
    ratio = config.get("max_growth_ratio", DEFAULT_GROWTH_RATIO)
    base_files = baseline["files"] if ratio and baseline else 0
    base_bytes = baseline["bytes"] if ratio and baseline else 0

    # Counts first: they are free, and the byte pass would stat the very tree being refused.
    if base_files and len(files) > ratio * base_files:
        return _refuse("file_growth", len(files), ratio, "max_growth_ratio", _top_offenders(files, None), base_files)

    if max_files and len(files) > max_files:
        breach = CeilingBreach(
            reason="file_count",
            measured=len(files),
            limit=max_files,
            config_key="max_backup_files",
            offenders=_top_offenders(files, None),
        )
        _log_breach(breach)
        return breach

    if not (max_gb or base_bytes):
        return None

    sizes: dict[str, int] = {}
    total = 0
    for abs_path, rel_path in files:
        try:
            size = os.path.getsize(abs_path)
        except FileNotFoundError as e:
            # A file that vanished since the filter has nothing left to copy; never abort over a live tree.
            logger.info(f"[backup] Ceiling measure skipped {rel_path}: {e}")
            continue
        except OSError as e:
            # Unmeasured bytes could hide a runaway: the gate refuses rather than pass blind.
            breach = CeilingBreach(
                reason="unmeasured",
                measured=0,
                limit=max_gb,
                config_key="max_backup_size_gb",
                offenders=[(f"{rel_path} ({e})", 0, 0)],
            )
            _log_breach(breach)
            return breach
        sizes[rel_path] = size
        total += size

    if base_bytes and total > ratio * base_bytes:
        return _refuse("size_growth", total, ratio, "max_growth_ratio", _top_offenders(files, sizes), base_bytes)

    if max_gb and total > max_gb * _BYTES_PER_GB:
        breach = CeilingBreach(
            reason="total_size",
            measured=total,
            limit=max_gb,
            config_key="max_backup_size_gb",
            offenders=_top_offenders(files, sizes),
        )
        _log_breach(breach)
        return breach

    return None


def _log_breach(breach: CeilingBreach) -> None:
    """Record a refusal in the ops log and the branch log."""
    trail.log_operation(
        "ceiling_breach",
        {
            "reason": breach.reason,
            "measured": breach.measured,
            "limit": breach.limit,
            "offenders": [list(o) for o in breach.offenders],
        },
    )
    logger.error(f"[backup] Run refused — {breach.summary()}")
