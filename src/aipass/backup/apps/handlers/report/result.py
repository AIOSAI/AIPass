# =================== AIPass ====================
# Name: result.py
# Description: BackupResult dataclass — typed outcome container for backup runs
# Version: 2.0.0
# Created: 2026-04-16
# Modified: 2026-06-12
# =============================================

"""Backup result dataclass.

Typed container returned by backup modules (snapshot, versioned)
describing what the run did. Consumed by the report formatter.
"""

from dataclasses import dataclass, field

from ..audit import trail


@dataclass
class BackupResult:
    """Outcome of a single backup run."""

    mode: str
    project_root: str = ""
    files_copied: int = 0
    files_checked: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    bytes_copied: int = 0
    duration_seconds: float = 0.0
    backup_path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    critical_errors: list[str] = field(default_factory=list)
    success: bool = True

    def add_error(self, msg: str, *, is_critical: bool = False) -> None:
        """Add an error. Critical errors mark the backup as failed."""
        self.errors.append(msg)
        if is_critical:
            self.critical_errors.append(msg)
            self.success = False

    def add_warning(self, msg: str) -> None:
        """Add a non-critical warning."""
        self.warnings.append(msg)


def new_result(mode: str, project_root: str = "") -> BackupResult:
    """Construct an empty BackupResult for a given mode."""
    trail.log_operation("backup_result_created", {"mode": mode})
    return BackupResult(mode=mode, project_root=project_root)


# =============================================
