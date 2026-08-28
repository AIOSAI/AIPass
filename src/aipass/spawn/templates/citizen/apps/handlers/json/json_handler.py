# =================== AIPass ====================
# Name: json_handler.py
# Description: {{BRANCHNAME}} JSON handler — configured instance of aipass.aipass.shared
# Version: 1.0.0
# Created: {{DATE}}
# Modified: {{DATE}}
# =============================================

"""{{BRANCHNAME}} JSON handler — thin shim over aipass.aipass.shared.json_handler.

Creates a JsonHandler instance configured with {{BRANCH}}'s json_dir.
All functions are re-exported for backward-compatible imports.

The re-exports below are deliberately lowercase: they are bound-method
aliases, not constants, and PEP 8 names callables in lowercase. Seedgo's
naming standard reads any module-level assignment that is not a call or an
import as a constant, so it flags them - .seedgo/bypass.json carries the
entry that says so. Do not rename these to UPPER_CASE to silence it; that
would make the shim lie about what these names are.
"""

from pathlib import Path

from aipass.aipass.shared.json_handler import JsonHandler

_BRANCH_ROOT = Path(__file__).resolve().parents[3]
_JSON_DIR = _BRANCH_ROOT / "{{BRANCH}}_json"

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
