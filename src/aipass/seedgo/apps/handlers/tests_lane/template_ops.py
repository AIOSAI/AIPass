# =================== AIPass ====================
# Name: template_ops.py
# Description: Test-template distribution — gold manifest, per-branch receipts, the bump
# Version: 1.2.1
# Created: 2026-09-21
# Modified: 2026-10-24
# =============================================

"""Test-template distribution, on @memory's trinity pattern.

A test file's body is never distributed: the page, the model's name and the receipt ship.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file


GOLD_DIR = module_file(__file__).parent.parent.parent.parent / "templates"
MANIFEST_FILE = "templates.json"
PAGE_FILE = "test_template_v1.md"

#: Read by a human beside the page; this lane never copies it, so no code resolves it.
MODEL_FILE = "readme_update_model.py.txt"

RECEIPT_FILE = ".template_version.json"

DISTRIBUTED_PAGE = "TEST_TEMPLATE.md"

#: Only the name lives here; the sending is in the module layer (reaching the bus is orchestration).
BUMP_EVENT = "test_template_bumped"

STAMPED_BY = "seedgo tests template bump"


def manifest_path() -> Path:
    """The gold manifest."""
    return GOLD_DIR / MANIFEST_FILE


def gold_versions() -> Dict[str, str]:
    """The template versions of record, or an empty dict if the manifest is unreadable."""
    path = manifest_path()
    if not path.exists():
        logger.info("Gold manifest missing at %s", path)
        return {}
    document = json_handler.read_json(path)
    versions = document.get("template_versions") if isinstance(document, dict) else None
    return versions if isinstance(versions, dict) else {}


def page_path() -> Path:
    """The v1 page — the text a branch receives."""
    return GOLD_DIR / PAGE_FILE


def receipt_path(branch_path: Path) -> Path:
    """Where one branch's receipt lives."""
    return Path(branch_path) / "tests" / RECEIPT_FILE


def read_receipt(branch_path: Path) -> Optional[Dict[str, str]]:
    """What a branch says it carries, or None when it has no receipt at all.

    None is never stamped; {} (empty or unreadable) is never current, so the next bump restamps.
    """
    path = receipt_path(branch_path)
    if not path.exists():
        return None
    document = json_handler.read_json(path)
    versions = document.get("template_versions") if isinstance(document, dict) else None
    return versions if isinstance(versions, dict) else {}


def receipt_status() -> Dict:
    """Every branch's receipt against gold."""
    gold = gold_versions()
    rows: List[Dict] = []
    for branch in discovery.discover_branches():
        carries = read_receipt(Path(branch["path"]))
        rows.append(
            {
                "branch": branch["name"].lower(),
                "path": branch["path"],
                "carries": carries,
                "current": carries == gold and bool(gold),
            }
        )
    return {"gold": gold, "branches": rows}


def bump(confirm: bool = False, only: Optional[str] = None) -> Dict:
    """Stamp the fleet, or report what stamping would do.

    ``only`` unset means the whole fleet, so a fleet bump has to be asked for.
    """
    gold = gold_versions()
    page = page_path()
    outcome: Dict = {"dry_run": not confirm, "gold": gold, "branches": []}

    if not gold:
        outcome["error"] = f"no gold versions: {manifest_path()} is missing or unreadable"
        return outcome
    if not page.exists():
        outcome["error"] = f"no page to distribute: {page} is missing"
        return outcome
    # Read once, before any branch: a per-branch read that raised left the fleet half stamped.
    try:
        page_text = page.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("Gold page unreadable, nothing stamped: %s: %s", page, exc)
        outcome["error"] = f"page unreadable: {page}: {exc}"
        return outcome

    branches = discovery.discover_branches()
    if only is not None and only.lstrip("@").lower() not in {b["name"].lower() for b in branches}:
        outcome["error"] = f"no registered branch named {only}: nothing to stamp"
        return outcome

    for branch in branches:
        name = branch["name"].lower()
        if only is not None and name != only.lstrip("@").lower():
            outcome["branches"].append({"branch": name, "action": "skipped", "carries": None})
            continue

        branch_path = Path(branch["path"])
        carries = read_receipt(branch_path)
        if carries == gold:
            outcome["branches"].append({"branch": name, "action": "current", "carries": carries})
            continue
        if not (branch_path / "tests").is_dir():
            outcome["branches"].append({"branch": name, "action": "no-tests-dir", "carries": carries})
            continue
        if not confirm:
            outcome["branches"].append({"branch": name, "action": "would-stamp", "carries": carries})
            continue

        try:
            _stamp(branch_path, gold, page_text)
        except OSError as exc:
            logger.error("Could not stamp %s: %s", branch_path, exc)
            outcome["branches"].append({"branch": name, "action": "failed", "carries": carries, "error": str(exc)})
            continue
        outcome["branches"].append({"branch": name, "action": "stamped", "carries": carries})

    json_handler.log_operation(
        "test_template_bump",
        {"dry_run": not confirm, "only": only, "branches": len(outcome["branches"])},
    )
    return outcome


def _stamp(branch_path: Path, gold: Dict[str, str], page_text: str) -> None:
    """Write one branch's copy of the page, then its receipt.

    The receipt goes last: a page that failed after its receipt would read current for ever.
    """
    (branch_path / "tests" / DISTRIBUTED_PAGE).write_text(page_text, encoding="utf-8")
    receipt = {
        "template_versions": dict(gold),
        "stamped": datetime.now().isoformat(timespec="seconds"),
        "stamped_by": STAMPED_BY,
    }
    target = receipt_path(branch_path)
    if not json_handler.write_json(target, receipt):
        raise OSError(f"receipt not written: {target}")
