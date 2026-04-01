# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON Handler (Canonical Path)
# Version: 1.0.0
# Created: 2026-02-28
# Modified: 2026-02-28
# =============================================

"""
JSON Handler - Canonical Path

Re-exports json_handler functions from json_utils/ to satisfy
the seedgo architecture standard requiring apps/handlers/json/json_handler.py.
"""

from pathlib import Path

# Infrastructure paths (package-relative)
_AI_MAIL_ROOT = Path(__file__).resolve().parents[3]  # ai_mail/
AI_MAIL_JSON_DIR = _AI_MAIL_ROOT / "ai_mail_json"

from aipass.ai_mail.apps.handlers.json_utils.json_handler import (  # noqa: F401
    load_json,
    save_json,
    ensure_json_exists,
    get_json_path,
    log_operation,
)
