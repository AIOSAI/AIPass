# =================== AIPass ====================
# Name: trinity_check.py
# Description: Trinity Memory File Standards Checker
# Version: 1.3.1
# Created: 2026-08-25
# Modified: 2026-10-24
# =============================================

"""
Trinity Memory File Standards Checker

``passport.json`` matters for EXISTENCE only: nothing inside a passport is read or judged.

Reference: trinity.md
"""

import json
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.trinity_groups import (
    all_groups,
    _LOCAL_NAME,
    _OBSERVATIONS_NAME,
    _RECEIPT_NAME,
    _TEMPLATE_FILES,
    _TRINITY_DIR,
    _gold_versions_from_templates,
    _guidelines_from_templates,
    _memory_dir,
    _prose_from_templates,
    _stray_names,
    _usage_from_templates,
    entry_shapes,
    expected_meta_line,
    is_versioned_backup,
    validate_entry_shape,
)

# Re-exported from trinity_groups so callers' import address never moves.
__all__ = [
    "AUDIT_SCOPE",
    "BRANCH_INPUTS",
    "GROUP_WEIGHTS",
    "check_branch",
    "check_branch_info",
    "entry_shapes",
    "expected_meta_line",
    "external_inputs",
    "is_clean_checkout",
    "is_versioned_backup",
    "load_memory_config",
    "load_template_prose",
    "validate_entry_shape",
]

# APPLIES_TO: scores .trinity/, not Python.
APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"

# Scored files live OUTSIDE apps/: unwatched, a .trinity edit serves a stale score until --full.
BRANCH_INPUTS = (".trinity/*",)

GROUP_WEIGHTS: dict[str, int] = {
    "Entry shapes": 30,
    "Top-level keys": 15,
    "Ordering & numbering": 12,
    "Char caps": 12,
    "File set": 10,
    "Meta lines & _usage": 10,
    "Receipt": 8,
    "Freshness": 3,
}
_REGISTRY_NAME = "AIPASS_REGISTRY.json"

_CLEAN_CHECKOUT_REASON = (
    "trinity: NOT MEASURED -- this tree is a clean checkout (no AIPASS_REGISTRY.json and no "
    "citizen .trinity/ anywhere). Memories are gitignored by design, so a fresh clone carries "
    "none. Not scored and not gating for this run; a live installation missing .trinity is "
    "still a violation."
)


def _pairs_hook(duplicates: list[str]):
    """Build an object_pairs_hook that records every repeated key it sees."""

    def hook(pairs: list) -> dict:
        """Build the object from *pairs*, appending each repeated key seen."""
        seen: set[str] = set()
        for key, _value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    return hook


def _fail_read(reason: str) -> dict:
    """Build the failed shape of a _read_json_file result."""
    return {"data": None, "duplicates": [], "error": reason}


def _read_json_file(path: Path) -> dict:
    """Read one JSON object, recording duplicate keys.

    Duplicates show only in the raw pairs (json.load keeps the last); callers prefix ``error``.
    """
    if not path.is_file():
        return _fail_read("not found")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("trinity_check: cannot read %s: %s", path, exc)
        return _fail_read(f"unreadable ({exc})")

    duplicates: list[str] = []
    try:
        data = json.loads(raw, object_pairs_hook=_pairs_hook(duplicates))
    except ValueError as exc:
        logger.warning("trinity_check: %s is not valid JSON: %s", path, exc)
        return _fail_read(f"not valid JSON ({exc})")

    if not isinstance(data, dict):
        return _fail_read(f"top level must be an object, found {type(data).__name__}")
    return {"data": data, "duplicates": duplicates, "error": None}


def _templates_dir(memory_dir: Path) -> Path:
    """Where @memory keeps the gold templates -- the one spelling the loader and the cache share."""
    return memory_dir / "templates"


def _config_path(memory_dir: Path) -> Path:
    """Where @memory keeps memory.config.json -- the one spelling the loader and the cache share."""
    return memory_dir / "memory_json" / "custom_config" / "memory.config.json"


def external_inputs() -> list[Path]:
    """The files OUTSIDE this branch whose content decides the score.

    The audit cache watches these, so a @memory config or template edit re-scores every branch.
    """
    memory_dir = _memory_dir()
    if memory_dir is None:
        return []
    candidates = [_config_path(memory_dir), *(_templates_dir(memory_dir) / name for _key, name in _TEMPLATE_FILES)]
    return [path for path in candidates if path.is_file()]


def _load_templates() -> dict | None:
    """Load both gold templates keyed 'local' / 'observations', or None."""
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    base = _templates_dir(memory_dir)
    loaded: dict[str, dict] = {}
    for key, filename in _TEMPLATE_FILES:
        result = _read_json_file(base / filename)
        if result["error"] is not None:
            logger.warning("trinity_check: gold template %s %s", filename, result["error"])
            return None
        loaded[key] = result["data"]
    return loaded


def load_memory_config() -> dict | None:
    """Load @memory's memory.config.json."""
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    path = _config_path(memory_dir)
    result = _read_json_file(path)
    if result["error"] is not None:
        logger.warning("trinity_check: memory.config.json %s", result["error"])
        return None
    return result["data"]


def load_template_prose(templates: dict | None = None) -> dict | None:
    """Load the per-section prose that the gold templates own."""
    if templates is None:
        templates = _load_templates()
    return _prose_from_templates(templates)


def is_clean_checkout(branch_path: Path) -> bool:
    """Whether this tree is a fresh clone rather than a live installation.

    Both gitignored signals must be absent, so a live install that lost one .trinity/
    still fails; the tracked ``spawn/templates/*/.trinity`` sits deeper and must not count.
    """
    branch_path = Path(branch_path).resolve()
    for parent in [branch_path, *branch_path.parents]:
        if (parent / _REGISTRY_NAME).is_file():
            return False
    fleet = branch_path.parent
    try:
        siblings = list(fleet.iterdir())
    except OSError as exc:
        # Fail toward the strict answer: "clean checkout" here would silence the standard fleet-wide.
        logger.warning("trinity_check: cannot list %s (%s) -- assuming a live installation", fleet, exc)
        return False
    return not any((sibling / _TRINITY_DIR).is_dir() for sibling in siblings if sibling.is_dir())


def _not_applicable_result(reason: str) -> dict:
    """A refusal that is neither a 0 nor a 100 -- the standard steps out."""
    return {
        "standard": "TRINITY",
        "score": None,
        "passed": None,
        "not_applicable": True,
        "checks": [{"name": "Measurable", "passed": None, "message": reason}],
    }


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored info lines: one per stray file or directory in .trinity/.

    Also scored under File set; this keeps the names visible when that message truncates.
    """
    if is_clean_checkout(Path(branch_path)):
        return [_CLEAN_CHECKOUT_REASON]
    trinity = Path(branch_path) / _TRINITY_DIR
    if not trinity.is_dir():
        return []
    return [f"trinity: stray .trinity/{name}" for name in _stray_names(trinity)]


def _build_context(branch_path: Path) -> dict:
    """Read every input once: the three files, the config, the gold templates.

    Resolved first: Path(".").name is "", which would report correct files as drifted.
    """
    branch_path = branch_path.resolve()
    trinity = branch_path / _TRINITY_DIR
    templates = _load_templates()
    return {
        "branch": branch_path.name,
        "trinity": trinity,
        "local": _read_json_file(trinity / _LOCAL_NAME),
        "observations": _read_json_file(trinity / _OBSERVATIONS_NAME),
        "receipt": _read_json_file(trinity / _RECEIPT_NAME),
        "config": load_memory_config(),
        "prose": load_template_prose(templates),
        "usage": _usage_from_templates(templates),
        "guidelines": _guidelines_from_templates(templates),
        "gold_versions": _gold_versions_from_templates(templates),
    }


def _weighted_score(checks: list) -> int:
    """Weighted mean of the eight group subscores, never rounded up to a pass."""
    total = sum(check["score"] * GROUP_WEIGHTS[check["name"]] / 100 for check in checks)
    score = round(total)
    if score >= 100 and any(check["score"] < 100 for check in checks):
        return 99
    return score


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Check one branch's .trinity/ memory files against the trinity standard.

    ``bypass_rules`` is accepted for interface compatibility and never consulted:
    the trinity contract has no bypass by design. Do not add is_bypassed() here.
    """
    if is_clean_checkout(Path(branch_path)):
        logger.info("trinity_check: %s -- clean checkout, standard not applicable", branch_path)
        return _not_applicable_result(_CLEAN_CHECKOUT_REASON)

    ctx = _build_context(Path(branch_path))
    checks = all_groups(ctx)
    score = _weighted_score(checks)

    result = {
        "standard": "TRINITY",
        "score": score,
        "passed": score == 100,
        "checks": checks,
    }
    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": "trinity"},
    )
    return result
