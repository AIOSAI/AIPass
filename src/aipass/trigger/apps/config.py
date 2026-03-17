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

# Trigger package root: .../aipass/trigger/
TRIGGER_ROOT = Path(__file__).resolve().parents[1]

# AIPass package root: .../aipass/
AIPASS_PKG_ROOT = TRIGGER_ROOT.parent


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("config Module")
    console.print("Path constants — TRIGGER_ROOT and AIPASS_PKG_ROOT used by all trigger modules")
    console.print()
