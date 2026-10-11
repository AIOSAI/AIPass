# =================== AIPass ====================
# Name: door_owner.py
# Description: Door: spawn's registry owner check, published for devpulse's owner guard (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/registry.py: the project owner and the registry it is read from."""

from aipass.spawn.apps.handlers.registry import find_registry, get_owner, is_owner, registry_is_writable_document

__all__ = ["is_owner", "get_owner", "find_registry", "registry_is_writable_document"]
