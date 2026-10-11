# =================== AIPass ====================
# Name: door_class_registry.py
# Description: Door: spawn's citizen classes and their template dirs, published for aipass and seedgo (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/class_registry.py: the citizen classes, their refusals and their template dirs."""

from aipass.spawn.apps.handlers.class_registry import (
    CITIZEN_CLASSES,
    FORBIDDEN_CLASSES,
    LEGACY_CLASSES,
    get_available_classes,
    get_template_dir,
    refuse_legacy_class,
    refuse_retired_or_forbidden,
    validate_class,
)

__all__ = [
    "CITIZEN_CLASSES",
    "FORBIDDEN_CLASSES",
    "LEGACY_CLASSES",
    "get_available_classes",
    "get_template_dir",
    "refuse_legacy_class",
    "refuse_retired_or_forbidden",
    "validate_class",
]
