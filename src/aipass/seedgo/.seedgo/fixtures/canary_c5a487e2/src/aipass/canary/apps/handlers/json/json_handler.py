# =================== AIPass ====================
# Name: json_handler.py
# Description: This branch's bound names for the fleet json service (prax-owned)
# Version: 2.0.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Branch JSON handler - the fleet's one json service, bound to this branch.

There is ONE implementation: ``aipass.prax.json_handler`` (DPLAN-0325). This
file binds its public names to a handle for this branch and adds nothing.
It BINDS, never wraps: every name below IS the service's own callable, so the
service resolves the calling module and this branch's ``<branch>_json``
directory itself, per call (``AIPASS_TEST_LOG_DIR`` is honoured there, never
here).

Byte-identical in every branch by design; seedgo checks it by hash. Do not add
functions, constants or branch names here - a branch that needs more owns it
in a module of its own.

The re-exports are lowercase on purpose: they are bound callables, not
constants.
"""

from aipass.prax import json_handler

_h = json_handler.for_module(__file__)

InvalidDocument = json_handler.InvalidDocument
WriteFailed = json_handler.WriteFailed

read_json = _h.read_json
write_json = _h.write_json
validate_json_structure = _h.validate_json_structure
get_json_path = _h.get_json_path
ensure_json_exists = _h.ensure_json_exists
ensure_module_jsons = _h.ensure_module_jsons
load_json = _h.load_json
save_json = _h.save_json
log_operation = _h.log_operation

__all__ = [
    "InvalidDocument",
    "WriteFailed",
    "read_json",
    "write_json",
    "validate_json_structure",
    "get_json_path",
    "ensure_json_exists",
    "ensure_module_jsons",
    "load_json",
    "save_json",
    "log_operation",
]
