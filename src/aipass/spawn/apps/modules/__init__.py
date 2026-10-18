# =================== AIPass ====================
# Name: __init__.py
# Description: Modules gateway — the public door other branches import through
# Version: 1.1.0
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Spawn's modules package — the gateway other branches import through."""

# Re-exports, never copies: identity is pinned in tests/test_modules_gateway.py.
from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as get_template_dir,
    refuse_legacy_class as refuse_legacy_class,
)
from aipass.spawn.apps.handlers.docs_page import docs_page_template as docs_page_template

__all__ = ["docs_page_template", "get_template_dir", "refuse_legacy_class"]
