# =================== AIPass ====================
# Name: json_handler.py
# Description: Canary JSON handler — configured instance of aipass.aipass.shared
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""Canary JSON handler — thin shim over aipass.aipass.shared.json_handler.

Creates a JsonHandler instance configured with canary's json_dir.
All functions are re-exported for backward-compatible imports.

Canary stores nothing anyone depends on — every file this writes is test
data by definition. It exists so the branch exercises the same JSON path
the rest of the fleet does, not because canary has state worth keeping.
"""

from pathlib import Path

from aipass.aipass.shared.json_handler import JsonHandler

_CANARY_ROOT = Path(__file__).resolve().parents[3]
_JSON_DIR = _CANARY_ROOT / "canary_json"

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
