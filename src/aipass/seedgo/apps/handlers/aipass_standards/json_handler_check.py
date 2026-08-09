# =================== AIPass ====================
# Name: json_handler_check.py
# Description: JSON Handler Integrity Standards Checker
# Version: 1.1.0
# Created: 2026-06-14
# Modified: 2026-08-07
# =============================================

"""
JSON Handler Integrity Standards Checker

Validates that every branch's apps/handlers/json/json_handler.py is a
canonical handler capable of creating the full config/data/log triplet.
Catches silent drift where a branch forks a stripped log-only handler
that passes json_structure (code wiring) but cannot create config or
data files.

Two checks:
1. Handler capability — shared shim import OR triplet-creating surface
   (ensure_module_jsons / ensure_json_exists).
2. Disk triplet completeness — bidirectional: any one of
   {module}_config.json / _data.json / _log.json on disk implies the
   other two must exist. A hand-written config with no log sibling is a
   gap, not an invisible file.

Score: percentage of passed checks. Pass threshold: 75%.
"""

import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

_TRIPLET_KINDS = ("config", "data", "log")

_TRIPLET_RE = re.compile(r"^(?P<stem>.+)_(?P<kind>config|data|log)\.json$")

_SHARED_IMPORT_MARKERS = (
    "from aipass.aipass.shared.json_handler import",
    "from aipass.aipass.shared import",
)

_TRIPLET_SURFACE_MARKERS = (
    "def ensure_module_jsons",
    "def ensure_json_exists",
    "ensure_json_exists",
    "ensure_module_jsons",
)


def _read_handler(branch_path: Path) -> str | None:
    handler = branch_path / "apps" / "handlers" / "json" / "json_handler.py"
    if not handler.exists():
        return None
    try:
        return handler.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("json_handler_check: cannot read handler: %s", exc)
        return None


def _has_shared_import(content: str) -> bool:
    for marker in _SHARED_IMPORT_MARKERS:
        if marker in content:
            return True
    return False


def _has_triplet_surface(content: str) -> bool:
    has_ensure_module = False
    has_ensure_exists = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "ensure_module_jsons" in stripped:
            has_ensure_module = True
        if "ensure_json_exists" in stripped:
            has_ensure_exists = True
    return has_ensure_module or has_ensure_exists


def _collect_triplet_members(json_dir: Path) -> dict[str, set[str]]:
    """Map each module stem to the triplet members present on disk.

    Any {stem}_config.json / {stem}_data.json / {stem}_log.json counts as
    evidence the module exists, so a config with no log sibling is just as
    visible as a log with no config.
    """
    members: dict[str, set[str]] = {}
    for path in sorted(json_dir.glob("*.json")):
        match = _TRIPLET_RE.match(path.name)
        if match is None:
            continue
        members.setdefault(match.group("stem"), set()).add(match.group("kind"))
    return members


def _check_disk_triplets(branch_path: Path, bypass_rules: list | None = None) -> dict:
    branch_name = branch_path.name
    json_dir = branch_path / f"{branch_name}_json"

    if not json_dir.is_dir():
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"No {branch_name}_json/ directory (no JSON activity)",
        }

    members = _collect_triplet_members(json_dir)
    if not members:
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"{branch_name}_json/ exists but has no triplet files",
        }

    missing = []
    for stem, present in sorted(members.items()):
        absent = [
            kind
            for kind in _TRIPLET_KINDS
            if kind not in present
            and not is_bypassed(f"{branch_name}_json/{stem}_{kind}.json", "json_handler", bypass_rules=bypass_rules)
        ]
        if absent:
            missing.append(f"{stem} (missing {', '.join(absent)})")

    if not missing:
        return {
            "name": "Disk triplet completeness",
            "passed": True,
            "message": f"All {len(members)} modules have complete triplets",
        }

    return {
        "name": "Disk triplet completeness",
        "passed": False,
        "message": (
            f"{len(missing)}/{len(members)} modules missing triplet files: "
            + "; ".join(missing[:5])
            + ("..." if len(missing) > 5 else "")
        ),
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check that a branch's json_handler.py is canonical.

    Verifies the handler either wires the shared JsonHandler or exposes
    the full triplet-creating surface (ensure_module_jsons / ensure_json_exists).
    Also checks on-disk triplet completeness.
    """
    bp = Path(branch_path)

    if is_bypassed(branch_path, "json_handler", bypass_rules=bypass_rules):
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "JSON_HANDLER",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "json_handler"},
        )
        return result

    checks = []
    content = _read_handler(bp)

    if content is None:
        checks.append(
            {
                "name": "Handler exists",
                "passed": False,
                "message": ("apps/handlers/json/json_handler.py not found — branch has no JSON handler"),
            }
        )
    else:
        checks.append(
            {
                "name": "Handler exists",
                "passed": True,
                "message": "apps/handlers/json/json_handler.py present",
            }
        )

        shared = _has_shared_import(content)
        triplet = _has_triplet_surface(content)

        if shared:
            checks.append(
                {
                    "name": "Handler capability",
                    "passed": True,
                    "message": "Wires shared JsonHandler (canonical shim)",
                }
            )
        elif triplet:
            checks.append(
                {
                    "name": "Handler capability",
                    "passed": True,
                    "message": ("Standalone with triplet surface (ensure_module_jsons / ensure_json_exists)"),
                }
            )
        else:
            checks.append(
                {
                    "name": "Handler capability",
                    "passed": False,
                    "message": (
                        "Log-only fork — missing ensure_module_jsons and "
                        "ensure_json_exists. Cannot create config/data "
                        "triplet files. Migrate to shared shim: "
                        "'from aipass.aipass.shared.json_handler import "
                        "JsonHandler'"
                    ),
                }
            )

    checks.append(_check_disk_triplets(bp, bypass_rules=bypass_rules))

    passed_count = sum(1 for c in checks if c["passed"])
    total = len(checks)
    score = int(passed_count / total * 100) if total else 0

    result = {
        "passed": score >= 75,
        "checks": checks,
        "score": score,
        "standard": "JSON_HANDLER",
    }

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "json_handler",
        },
    )
    return result
