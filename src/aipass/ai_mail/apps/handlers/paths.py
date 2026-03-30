# =================== AIPass ====================
# Name: paths.py
# Description: Shared path utilities for ai_mail handlers
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""
Shared path utilities for ai_mail handlers.

Provides repo root discovery used across all handler files.
Consolidated from 8 identical copies per DPLAN-0036 audit.
"""

from pathlib import Path

from aipass.ai_mail.apps.handlers.json import json_handler


def find_repo_root() -> Path:
    """Walk up from this file to find AIPASS_REGISTRY.json (repo root)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    json_handler.log_operation("paths_introspection")
    console.print("\n" + "=" * 70)
    console.print("PATHS UTILITY")
    console.print("=" * 70)
    console.print(f"\nRepo root: {find_repo_root()}")
    console.print("\nFunctions provided:")
    console.print("  - find_repo_root() -> Path")
    console.print()
