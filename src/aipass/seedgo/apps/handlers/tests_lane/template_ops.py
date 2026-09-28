# =================== AIPass ====================
# Name: template_ops.py
# Description: Test-template distribution — gold manifest, per-branch receipts, the bump
# Version: 1.1.0
# Created: 2026-09-21
# Modified: 2026-09-27
# =============================================

"""Test-template distribution, on @memory's trinity pattern.

Gold lives in ``seedgo/templates/``: ``templates.json`` carries the versions,
``test_template_v1.md`` is the page, ``readme_update_model.py`` is the model.
Every branch holds a receipt at ``tests/.template_version.json`` recording which
template version its tests were written against. ``receipt_status()`` compares
the two; ``bump()`` writes the receipt and the page.

WHAT IS NEVER DISTRIBUTED: a test file's body. @spawn's update already skips
every ``.py`` for manual review and @memory's push rewrites only the frame
around a branch's own entries — neither overwrites content, and a test file is
code. Three things ship: the page, the model's whereabouts, and the receipt. A
branch's tests stay its own.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

# =============================================================================
# CONSTANTS
# =============================================================================

#: The gold directory: seedgo/templates/, three levels up from handlers/tests_lane/.
GOLD_DIR = module_file(__file__).parent.parent.parent.parent / "templates"
MANIFEST_FILE = "templates.json"
PAGE_FILE = "test_template_v1.md"

#: The model is named in templates.json and read by a human beside the page —
#: this lane never copies it, so no code resolves it.
MODEL_FILE = "readme_update_model.py.txt"

#: What a branch carries. Named like @memory's .trinity/.template_version.json
#: so a reader who knows one lane already knows this one.
RECEIPT_FILE = ".template_version.json"

#: The page's name once it lands in a branch — the file an agent is pointed at.
DISTRIBUTED_PAGE = "TEST_TEMPLATE.md"

#: Announced on @trigger's bus after a bump, named like memory's
#: trinity_template_bumped. The NAME lives here, beside the domain logic; the
#: sending lives in the module layer, because reaching the bus is orchestration.
BUMP_EVENT = "test_template_bumped"

STAMPED_BY = "seedgo tests template bump"


# =============================================================================
# GOLD
# =============================================================================


def manifest_path() -> Path:
    """The gold manifest."""
    return GOLD_DIR / MANIFEST_FILE


def gold_versions() -> Dict[str, str]:
    """The template versions of record, or an empty dict if the manifest is unreadable.

    Every caller treats the empty dict as the failure it is ("missing or
    unreadable") and refuses to compare or stamp against it. json_handler's
    read_json never raises: an unreadable manifest arrives as None.
    """
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


# =============================================================================
# RECEIPTS
# =============================================================================


def receipt_path(branch_path: Path) -> Path:
    """Where one branch's receipt lives."""
    return Path(branch_path) / "tests" / RECEIPT_FILE


def read_receipt(branch_path: Path) -> Optional[Dict[str, str]]:
    """What a branch says it carries, or None when it has no receipt at all.

    None and {} are different answers and both are kept: no receipt means never
    stamped, an empty one means stamped against nothing. json_handler's
    read_json never raises: an unreadable receipt arrives as None and reads here
    as {}, never current, so the next bump restamps it.
    """
    path = receipt_path(branch_path)
    if not path.exists():
        return None
    document = json_handler.read_json(path)
    versions = document.get("template_versions") if isinstance(document, dict) else None
    return versions if isinstance(versions, dict) else {}


def receipt_status() -> Dict:
    """Every branch's receipt against gold.

    Returns:
        ``{"gold": {...}, "branches": [{"branch", "path", "carries", "current"}]}``.
        ``carries`` is None for a branch with no receipt, and a branch with no
        ``tests/`` directory is still listed: unstamped is the honest answer,
        not an omission.
    """
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


# =============================================================================
# BUMP
# =============================================================================


def bump(confirm: bool = False, only: Optional[str] = None) -> Dict:
    """Stamp the fleet, or report what stamping would do.

    Args:
        confirm: False reports and writes nothing. True writes the receipt and
            the page into each branch's ``tests/``.
        only: A single branch name to act on. The default is the whole fleet;
            a bump of every branch at once is the owner's call, so the caller
            has to say so by leaving this unset.

    Returns:
        ``{"dry_run", "gold", "branches": [{"branch", "action", "carries"}]}``.
        ``action`` is one of ``stamped``, ``would-stamp``, ``current``,
        ``no-tests-dir``, ``skipped``, ``failed``. A ``failed`` row also
        carries ``error``, the reason the stamp did not land.
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

    for branch in discovery.discover_branches():
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
            _stamp(branch_path, gold, page)
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


def _stamp(branch_path: Path, gold: Dict[str, str], page: Path) -> None:
    """Write one branch's receipt and its copy of the page.

    Raises:
        OSError: the receipt or the page did not land. bump() records it.
    """
    receipt = {
        "template_versions": dict(gold),
        "stamped": datetime.now().isoformat(timespec="seconds"),
        "stamped_by": STAMPED_BY,
    }
    target = receipt_path(branch_path)
    if not json_handler.write_json(target, receipt):
        raise OSError(f"receipt not written: {target}")
    (branch_path / "tests" / DISTRIBUTED_PAGE).write_text(page.read_text(encoding="utf-8"), encoding="utf-8")
