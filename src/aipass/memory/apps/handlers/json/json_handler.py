# =================== AIPass ====================
# Name: json_handler.py
# Description: Memory JSON handler — configured instance of aipass.aipass.shared
# Version: 3.0.0
# Created: 2026-03-17
# Modified: 2026-06-14
# =============================================

"""Memory JSON handler — thin shim over aipass.aipass.shared.json_handler.

Creates a JsonHandler instance configured with memory's json_dir.
All functions are re-exported for backward-compatible imports.
"""

from aipass.aipass.shared.json_handler import JsonHandler
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parents[3]
_JSON_DIR = _MEMORY_ROOT / "memory_json"

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
