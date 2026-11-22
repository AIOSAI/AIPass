# =================== AIPass ====================
# Name: bypass_handler.py
# Description: Bypass Configuration Handler
# Version: 1.5.0
# Created: 2026-03-08
# Modified: 2026-11-21
# =============================================

"""Bypass Configuration Handler"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler
from aipass.sentry.apps.handlers import registry_scan
from aipass.sentry.apps.handlers.audit.discovery import registry_branches


def _find_registry() -> Path:
    """Find *_REGISTRY.json — CWD-first for external project support, then __file__ fallback."""
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


def waived_sites(rules: List[Dict[str, Any]]) -> int:
    """How many sites a branch's rules waive: one per pinned line or function, one per whole-file rule.

    A rule naming no file or no standard matches nothing (bypass.utils.matching_rule) and waives nothing.
    """
    return sum(
        len(rule.get("lines") or []) or len(rule.get("functions") or []) or 1
        for rule in rules
        if rule.get("file") and rule.get("standard")
    )


def load_bypass_rules(branch_path: str) -> List[Dict[str, Any]]:
    """Load bypass rules from branch's .sentry/bypass.json; a missing file is no rules, and nothing is written."""
    bypass_file = Path(branch_path) / ".sentry" / "bypass.json"

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


def bypass_file_problem(branch_path: str) -> Optional[str]:
    """Why the branch's .sentry/bypass.json exists but cannot be used, or None when it is absent or well formed.

    load_bypass_rules reads such a file as no rules, so the caller names it rather than score as if waived.
    """
    bypass_file = Path(branch_path) / ".sentry" / "bypass.json"
    if not bypass_file.exists():
        return None
    try:
        content = bypass_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("[bypass_handler] Unreadable bypass.json at %s: %s", bypass_file, exc)
        return f"{bypass_file} is unreadable ({exc})"
    if not content.strip():
        return f"{bypass_file} is empty"
    try:
        config = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("[bypass_handler] Corrupt bypass.json at %s: %s", bypass_file, exc)
        return f"{bypass_file} is not JSON ({exc})"
    if not isinstance(config, dict) or not isinstance(config.get("bypass", []), list):
        return f'{bypass_file} is not a {{"bypass": [...]}} object'
    return None
