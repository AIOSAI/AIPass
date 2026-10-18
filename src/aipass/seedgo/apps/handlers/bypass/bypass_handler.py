# =================== AIPass ====================
# Name: bypass_handler.py
# Description: Bypass Configuration Handler
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""Bypass Configuration Handler"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers import registry_scan


BYPASS_TEMPLATE = {
    "metadata": {"version": "1.0.0", "created": "", "description": "Standards bypass configuration for this branch"},
    "bypass": [],
    "notes": {
        "usage": "Add entries to 'bypass' list to exclude specific violations",
        "example": {
            "file": "apps/modules/logger.py",
            "standard": "cli",
            "lines": [146, 177],
            "reason": "Circular dependency - logger cannot import CLI",
        },
        "fields": {
            "file": "Relative path from branch root (required)",
            "standard": "Standard name: cli, imports, naming, etc. (required)",
            "lines": "Optional - specific line numbers to bypass",
            "functions": "Optional - list of function names for name-scoped bypass (required for unused_function)",
            "reason": "Required - why this bypass exists",
        },
    },
}


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
            registry.get("branches", []),
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


def ensure_seedgo_config(branch_path: str) -> Path:
    """Ensure .seedgo/bypass.json exists for a branch, create if missing."""
    seedgo_dir = Path(branch_path) / ".seedgo"
    bypass_file = seedgo_dir / "bypass.json"

    try:
        seedgo_dir.mkdir(exist_ok=True)

        if not bypass_file.exists():
            template = BYPASS_TEMPLATE.copy()
            template["metadata"]["created"] = datetime.now().isoformat()

            with open(bypass_file, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=2)

            logger.info(f"[bypass_handler] Created {bypass_file}")

        return bypass_file
    except Exception as e:
        logger.error(f"[bypass_handler] Error creating seedgo config: {e}")
        return bypass_file


def load_bypass_rules(branch_path: str) -> List[Dict[str, Any]]:
    """Load bypass rules from branch's .seedgo/bypass.json."""
    bypass_file = ensure_seedgo_config(branch_path)

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


def is_bypassed(file_path: str, branch_path: str, standard: str, line: Optional[int], bypass_rules: List[Dict]) -> bool:
    """
    Check if a specific violation should be bypassed.

    NOT the checkers' matcher (``bypass.utils.is_bypassed``): different parameter
    ORDER, and exact branch-relative match rather than substring. Checkers call utils.
    """
    try:
        rel_path = Path(file_path).relative_to(branch_path).as_posix()
    except ValueError:
        logger.info("File %s not relative to branch %s, using raw path", file_path, branch_path)
        rel_path = Path(file_path).as_posix()

    for rule in bypass_rules:
        rule_file = rule.get("file") or ""
        rule_standard = rule.get("standard") or ""

        # Active only when it names both a file and a standard.
        if not rule_file or rule_file != rel_path:
            continue
        if rule_standard != standard:
            continue

        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None:
            if line in rule_lines:
                return True
        elif not rule_lines:
            return True

    return False
