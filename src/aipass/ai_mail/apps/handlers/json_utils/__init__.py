"""
JSON Handlers Module - AI_MAIL Branch

Provides JSON handling capabilities for AI_MAIL modules.
"""

from .json_handler import (
    load_json,
    save_json,
    log_operation,
    increment_counter,
    update_data_metrics,
    ensure_module_jsons,
)

__all__ = ["load_json", "save_json", "log_operation", "increment_counter", "update_data_metrics", "ensure_module_jsons"]
