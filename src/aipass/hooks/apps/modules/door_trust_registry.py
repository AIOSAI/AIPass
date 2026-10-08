# =================== AIPass ====================
# Name: door_trust_registry.py
# Description: Door: the trusted-project registry, its four verbs and REGISTRY_PATH, for aipass (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/config/trust_registry.py: the trusted external projects."""

from aipass.hooks.apps.handlers.config.trust_registry import (
    REGISTRY_PATH,
    enroll,
    is_trusted,
    read_registry,
    revoke,
)

__all__ = ["enroll", "is_trusted", "read_registry", "revoke", "REGISTRY_PATH"]
