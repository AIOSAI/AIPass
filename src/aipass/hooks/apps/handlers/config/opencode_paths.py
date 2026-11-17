# =================== AIPass ====================
# Name: opencode_paths.py
# Version: 1.1.0
# Description: Where OpenCode keeps its store and loads the AIPass plugin; the one place these paths are worked out
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-10-28
# Modified: 2026-11-17
# =============================================

"""OpenCode's file locations, read from the environment on every call (tests and seats set it)."""

import os
import sqlite3
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler


def opencode_db_path() -> Path:
    """OpenCode's store: $OPENCODE_DB, else opencode/opencode.db in the XDG data home."""
    if os.environ.get("OPENCODE_DB"):
        return Path(os.environ["OPENCODE_DB"])
    data = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data) / "opencode" / "opencode.db"


def opencode_store() -> sqlite3.Connection:
    """OpenCode's store, read-only, waiting at most 2 s on its writer; each call leaves one json trail entry."""
    db = opencode_db_path()
    json_handler.log_operation("opencode_store", {"db": str(db)})
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=2)


def opencode_plugin_path() -> Path:
    """Where OpenCode loads the user-level plugin: $XDG_CONFIG_HOME, else the home's .config, then opencode/plugins."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opencode" / "plugins" / "aipass.ts"
