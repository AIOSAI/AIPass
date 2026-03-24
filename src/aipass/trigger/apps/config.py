# =================== AIPass ====================
# Name: config.py
# Description: Trigger package path configuration
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Trigger package path configuration.

Provides package-relative paths for trigger data directories.
Works in both pip-installed and development environments.
"""

from pathlib import Path
from datetime import datetime, timezone

# Trigger package root: .../aipass/trigger/
TRIGGER_ROOT = Path(__file__).resolve().parents[1]

_CONFIG_LOG = TRIGGER_ROOT / "logs" / "config.log"


def _log_warning(message: str) -> None:
    """Log warning to file (config cannot import prax logger — circular)."""
    try:
        _CONFIG_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_CONFIG_LOG, 'a', encoding='utf-8') as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass  # Meta-logging: cannot log a failure to log

# AIPass package root: .../aipass/
AIPASS_PKG_ROOT = TRIGGER_ROOT.parent


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        _log_warning("CLI console not available, using rich fallback")
        from rich.console import Console
        console = Console()

    console.print()
    console.print("config Module")
    console.print("Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules")
    console.print()
