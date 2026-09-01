# =================== AIPass ====================
# Name: json_handler.py
# Description: Spawn JSON handler — configured instance of aipass.aipass.shared
# Version: 3.0.0
# Created: 2026-03-07
# Modified: 2026-06-10
# =============================================

"""Spawn JSON handler — thin shim over aipass.aipass.shared.json_handler.

Creates a JsonHandler instance configured with spawn's json_dir.
All functions are re-exported for backward-compatible imports.
"""

from pathlib import Path

from aipass.aipass.shared.json_handler import JsonHandler

# NOT resolve(): this runs at IMPORT time, and ntpath.realpath calls os.getcwd()
# unconditionally — not only for a relative path, the way posixpath does — so
# resolve() here is a cwd read that takes the whole branch down on Windows when
# the working directory is gone (Windows CI, 2026-08-31; @memory raised the
# wider species). __file__ has been absolute since 3.9, so the only thing
# resolve() added was symlink normalisation of a path that is used solely to
# build a directory for file I/O and is never compared against another path —
# a symlink resolves identically at the OS level. Guarding it with try/except
# would work too, but not needing the call is better than surviving it.
_SPAWN_ROOT = Path(__file__).parents[3]
_JSON_DIR = _SPAWN_ROOT / "spawn_json"

_handler = JsonHandler(json_dir=_JSON_DIR)

MAX_LOG_ENTRIES = JsonHandler.MAX_LOG_ENTRIES

read_json = _handler.read_json
write_json = _handler.write_json
validate_json_structure = _handler.validate_json_structure
get_json_path = _handler.get_json_path
ensure_json_exists = _handler.ensure_json_exists
ensure_module_jsons = _handler.ensure_module_jsons
load_json = _handler.load_json
save_json = _handler.save_json
log_operation = _handler.log_operation
_create_default = _handler._create_default
