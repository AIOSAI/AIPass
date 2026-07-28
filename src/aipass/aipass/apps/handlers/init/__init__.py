# =================== AIPass ====================
# Name: __init__.py
# Description: Init handler package — public API
# Version: 1.0.0
# Created: 2026-05-04
# Modified: 2026-05-04
# =============================================

"""Init handler package — public entry point for bootstrap and scaffold_content."""

from aipass.aipass.apps.handlers.init.bootstrap import (
    _sanitize_name,
    init_project,
    is_projects_child,
    update_project,
)
from aipass.aipass.shared.scaffold_content import (
    global_prompt_md,
    inbox_json,
    prep_md,
    with_source,
)

__all__ = [
    "_sanitize_name",
    "global_prompt_md",
    "inbox_json",
    "init_project",
    "is_projects_child",
    "prep_md",
    "update_project",
    "with_source",
]
