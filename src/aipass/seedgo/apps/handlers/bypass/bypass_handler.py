# =================== AIPass ====================
# Name: bypass_handler.py
# Description: Bypass Configuration Handler
# Version: 1.3.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""Bypass Configuration Handler"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.audit.discovery import registry_branches


def _find_registry() -> Path:
    """Find *_REGISTRY.json — CWD-first for external project support, then __file__ fallback."""
    # A private parent.glob folds case on Windows/macOS and can serve a plan counter as the registry.
    return registry_scan.find_registry()


#: Registries this process could not read, path -> why; get_branch_from_path answers None, never raises,
#: so the checklist and audit print registry_notes() where the verdicts are read.
UNREADABLE_REGISTRIES: Dict[str, str] = {}


def registry_notes() -> List[str]:
    """One line per registry this process failed to read, naming it and why."""
    return [
        f"registry unreadable, so no file was placed in its branch and no branch bypass rule was read: {path} ({why})"
        for path, why in UNREADABLE_REGISTRIES.items()
    ]


def get_branch_from_path(file_path: str) -> Optional[Dict[str, Any]]:
    """Detect which branch a file belongs to using AIPASS_REGISTRY."""
    registry_path: Optional[Path] = None
    try:
        registry_path = _find_registry()
        if not registry_path.exists():
            logger.warning("[bypass_handler] AIPASS_REGISTRY.json not found")
            return None

        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        file_path = str(Path(file_path).resolve())

        registry_dir = registry_path.parent

        def _resolve(raw: str) -> str:
            p = Path(raw)
            if not p.is_absolute():
                p = (registry_dir / p).resolve()
            return str(p)

        # Longest path first so a nested branch wins over its parent.
        branches = sorted(
            registry_branches(registry),
            key=lambda b: len(_resolve(b.get("path", ""))),
            reverse=True,
        )

        for branch in branches:
            branch_path = _resolve(branch.get("path", ""))
            if file_path.startswith(branch_path + "/") or file_path == branch_path:
                return branch

        return None
    except Exception as e:
        logger.error(f"[bypass_handler] Error reading AIPASS_REGISTRY: {e}")
        UNREADABLE_REGISTRIES[str(registry_path or "AIPASS_REGISTRY.json")] = str(e)
        return None


def load_bypass_rules(branch_path: str) -> List[Dict[str, Any]]:
    """Load bypass rules from branch's .seedgo/bypass.json; a missing file is no rules, and nothing is written."""
    bypass_file = Path(branch_path) / ".seedgo" / "bypass.json"

    try:
        if bypass_file.exists():
            content = bypass_file.read_text(encoding="utf-8").strip()
            if not content:
                logger.warning("[bypass_handler] Empty bypass.json at %s — skipping", bypass_file)
                return []
            config = json.loads(content)
            rules = config.get("bypass", [])
            json_handler.log_operation("bypass_rules_loaded", {"branch": branch_path, "count": len(rules)})
            return rules
    except json.JSONDecodeError as e:
        logger.warning("[bypass_handler] Corrupt bypass.json at %s: %s — skipping", bypass_file, e)
    except Exception as e:
        logger.error("[bypass_handler] Error loading bypass rules: %s", e)

    return []
