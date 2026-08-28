# =================== AIPass ====================
# Name: trinity_check.py
# Description: Trinity Memory File Standards Checker
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-27
# =============================================

"""
Trinity Memory File Standards Checker

Enforces the trinity standard (devpulse dropbox/trinity_pattern.md) on the
three in-scope files of every citizen's ``.trinity/``: ``local.json``,
``observations.json`` and ``.template_version.json``.  ``passport.json``
matters here for EXISTENCE only -- passports and compass are separate systems
with their own rules, so nothing inside a passport is read or judged.

This module is the ENGINE: the module contract the audit reads
(``AUDIT_SCOPE``, ``BRANCH_INPUTS``, ``GROUP_WEIGHTS``), the inputs every
group shares (config, gold templates, the three files), the applicability
decision, and the weighted roll-up.  The nine group checkers themselves live
in ``trinity_groups.py`` -- they were split out on 2026-08-27 when this file
crossed the 1500-line architecture cap, a relocation that changed no rule.

The one law
-----------
A field the checker cannot measure is a VIOLATION, never a silent pass.  This
standard exists because the old gate measured unparseable shapes as zero chars
and passed them.  So: a missing, unreadable or invalid file fails every group
that depends on it, loudly and by name; a field of the wrong type is reported
with the type actually found and is never coerced or ``len()``-ed; an
unreadable ``memory.config.json`` fails the Char caps group instead of falling
back to remembered numbers; unreadable gold templates fail the Meta lines
group instead of falling back to a copied-out prose string.  There is no code
path where something unreadable produces a passing check.

Unmeasurable has a THIRD answer, and it is not zero
---------------------------------------------------
Refusing a group is right when the branch is at fault.  It is wrong when the
whole environment cannot carry the evidence: ``.trinity/`` and
``AIPASS_REGISTRY.json`` are both gitignored, so a fresh clone has no memory
files at all, and refusing every group there scored all 18 branches at 0 on
CI -- blaming the fleet for an environment fact.  ``is_clean_checkout()``
detects that case and ``check_branch()`` returns ``not_applicable`` with a
score of ``None``, which ``branch_audit`` leaves out of the gating average
entirely.  0 lies about the branch and 100 lies about the run; ``None`` is the
honest answer.  The detection needs BOTH signals absent -- no registry
anywhere up the tree AND no citizen ``.trinity/`` beside this branch -- so a
live installation that has genuinely lost a branch's memories still fails.

The nine groups and their weights (GROUP_WEIGHTS, sums to 100)
--------------------------------------------------------------
Shape and type weigh heaviest -- they break the machinery that caps, rolls and
archives these files; freshness weighs lightest.  Each group reports its own
0-100 subscore; the standard's score is the weighted mean, rounded, and never
rounded up into a pass.

Per-group subscore rule (proportional where a natural denominator exists,
binary 0/100 otherwise):

* Entry shapes (25) -- proportional over every entry in the four containers.
  A container that is missing, is not a list, or lives in an unreadable file
  counts as one failed unit rather than being skipped.
* Top-level keys (15) -- proportional over 17 fixed sub-rules: eight per file
  (file parses, key set, key order, duplicate keys, document_metadata fields,
  no ``status`` block, document_name, managed_by) plus one cross-file
  managed_by agreement check.  An unreadable file fails all eight of its own.
  ``document_metadata`` is a CLOSED set: any field beyond the declared ones is
  flagged, with ``status`` keeping its own message because the contract
  deletes it specifically.
* Ordering & numbering (12) -- proportional over every entry.
* Char caps (12) -- proportional over every entry; binary 0 when
  memory.config.json cannot be read, because caps are never assumed.
* File set (10) -- proportional over the five canonical names plus one unit
  per stray file or directory found in ``.trinity/``.  A VERSIONED BACKUP is a
  legal resident, not a stray: ``<canonical>.pre<sep><token>`` only, matched on
  shape rather than a suffix list, and deliberately tight enough that a
  torn-write ``.tmp`` stays visible.
* Meta lines & _usage (10) -- proportional over seven byte-match units: four
  ``*_meta`` lines, two ``_usage`` strings, and the ``guidelines`` block of
  observations.json, which is compared byte-for-byte against the gold
  template.  Binary 0 when config or the gold templates cannot be read.
* Receipt (8) -- proportional over six units: file parses, template_versions
  shape, template_versions values, and the three timestamp/actor strings.
* Todos hygiene (5) -- proportional over every todo entry.
* Freshness (3) -- proportional over two units, one per file.

Bypass
------
None, deliberately -- see check_branch().
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
    expected_meta_line,
    is_versioned_backup,
    validate_entry_shape,
)

# The public surface other modules and the test suite reach through this
# module. expected_meta_line, is_versioned_backup and validate_entry_shape now
# live in trinity_groups; they are re-exported here because callers have always
# imported them from the checker and the split must not move their address.
__all__ = [
    "AUDIT_SCOPE",
    "BRANCH_INPUTS",
    "GROUP_WEIGHTS",
    "check_branch",
    "check_branch_info",
    "expected_meta_line",
    "is_clean_checkout",
    "is_versioned_backup",
    "load_memory_config",
    "load_template_prose",
    "validate_entry_shape",
]

AUDIT_SCOPE = "branch_level"

# Ruling 6: this checker scores files OUTSIDE apps/, so the audit cache must
# watch them or a .trinity edit serves a stale score until --full.
BRANCH_INPUTS = (".trinity/*",)

GROUP_WEIGHTS: dict[str, int] = {
    "Entry shapes": 25,
    "Top-level keys": 15,
    "Ordering & numbering": 12,
    "Char caps": 12,
    "File set": 10,
    "Meta lines & _usage": 10,
    "Receipt": 8,
    "Todos hygiene": 5,
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

    Returns a dict with ``data`` (the parsed object or None), ``duplicates``
    (every key seen more than once at any depth -- json.load keeps only the
    last value, so the raw pairs are the only place a duplicate is visible)
    and ``error`` (a reason string, or None on success).  The reason never
    repeats the file name; callers prefix it themselves.
    """
    if not path.is_file():
        return _fail_read("not found")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
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


def _load_templates() -> dict | None:
    """Load both gold templates keyed 'local' / 'observations', or None."""
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    base = memory_dir / "templates"
    loaded: dict[str, dict] = {}
    for key, filename in _TEMPLATE_FILES:
        result = _read_json_file(base / filename)
        if result["error"] is not None:
            logger.warning("trinity_check: gold template %s %s", filename, result["error"])
            return None
        loaded[key] = result["data"]
    return loaded


# =============================================================================
# CONFIG AND GOLD TEMPLATES
# =============================================================================


def load_memory_config() -> dict | None:
    """Load @memory's memory.config.json.

    Returns:
        The parsed config dict, or None when the repo root, the file, or its
        JSON cannot be resolved.  None is a hard failure for the Char caps and
        Meta lines groups -- there is no fallback set of numbers.
    """
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    path = memory_dir / "memory_json" / "custom_config" / "memory.config.json"
    result = _read_json_file(path)
    if result["error"] is not None:
        logger.warning("trinity_check: memory.config.json %s", result["error"])
        return None
    return result["data"]


def load_template_prose(templates: dict | None = None) -> dict | None:
    """Load the per-section prose that the gold templates own.

    Each ``*_meta`` value in a template is ``"{{PLACEHOLDER}} <prose>"``; the
    prose is everything after the placeholder token and its single following
    space.  The prose text is never carried in this module -- an unreadable
    template returns None and fails the Meta lines group loud.

    Args:
        templates: Already-loaded gold templates, so a caller that also needs
            the receipt's gold versions reads the two files once instead of
            twice.  Omit to load them here.

    Returns:
        ``{"todos": ..., "key_learnings": ..., "sessions": ...,
        "observations": ...}`` or None.
    """
    if templates is None:
        templates = _load_templates()
    return _prose_from_templates(templates)


def is_clean_checkout(branch_path: Path) -> bool:
    """Whether this tree is a fresh clone rather than a live installation.

    Both signals must be absent, because either one alone is ambiguous:

      * ``AIPASS_REGISTRY.json`` -- gitignored, so a clone has none. Searched
        upward from the branch, since it lives at the repo root.
      * any ``<fleet>/<branch>/.trinity/`` -- also gitignored. Checked at
        exactly one level down, which is where a citizen's memories live.
        ``spawn/templates/*/.trinity`` IS tracked and does ship, and it sits
        deeper than that, so it correctly does not make a clone look live.

    Requiring both keeps the discrimination conservative: a real installation
    that has lost one branch's .trinity still has the registry, so that stays
    the violation it is.

    Args:
        branch_path: The branch being audited.

    Returns:
        True when no registry and no citizen memories exist anywhere.
    """
    branch_path = Path(branch_path).resolve()
    for parent in [branch_path, *branch_path.parents]:
        if (parent / _REGISTRY_NAME).is_file():
            return False
    fleet = branch_path.parent
    try:
        siblings = list(fleet.iterdir())
    except OSError as exc:
        # Unreadable fleet dir: answer "not a clean checkout", which keeps a
        # missing .trinity a violation. Failing toward the strict answer is
        # right here -- the loose one would silence the standard fleet-wide.
        logger.warning("trinity_check: cannot list %s (%s) -- assuming a live installation", fleet, exc)
        return False
    return not any((sibling / _TRINITY_DIR).is_dir() for sibling in siblings if sibling.is_dir())


def _not_applicable_result(reason: str) -> dict:
    """A refusal that is neither a 0 nor a 100 -- the standard steps out.

    ``not_applicable`` tells branch_audit to leave this standard out of the
    gating average entirely. Scoring 0 would blame the branch for the
    environment; scoring 100 would claim a measurement that never happened.
    """
    return {
        "standard": "TRINITY",
        "score": None,
        "passed": None,
        "not_applicable": True,
        "checks": [{"name": "Measurable", "passed": None, "message": reason}],
    }


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored info lines: one per stray file or directory in .trinity/.

    The strays are also scored under the File set group; this channel exists
    so the names stay visible in the audit output even when the renderer
    truncates the group's failure message.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        One line per stray, the not-applicable announcement on a clean
        checkout, or empty when .trinity/ is clean or absent.
    """
    if is_clean_checkout(Path(branch_path)):
        return [_CLEAN_CHECKOUT_REASON]
    trinity = Path(branch_path) / _TRINITY_DIR
    if not trinity.is_dir():
        return []
    return [f"trinity: stray .trinity/{name}" for name in _stray_names(trinity)]


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def _build_context(branch_path: Path) -> dict:
    """Read every input once: the three files, the config, the gold templates.

    The path is resolved first: Path(".").name is the empty string, so a
    relative branch_path would measure Top-level keys against a branch called
    "" and report correct files as drifted.
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
    """Weighted mean of the nine group subscores, never rounded up to a pass."""
    total = sum(check["score"] * GROUP_WEIGHTS[check["name"]] / 100 for check in checks)
    score = round(total)
    if score >= 100 and any(check["score"] < 100 for check in checks):
        return 99
    return score


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Check one branch's .trinity/ memory files against the trinity standard.

    Nine groups are measured -- file set, top-level keys, entry shapes,
    ordering and numbering, char caps, meta lines and _usage, freshness, todos
    hygiene, and the template version receipt.  Every group reports its own
    0-100 subscore and the standard's score is their weighted mean.

    Nothing here is skipped for being unreadable: a missing file, a broken
    parse, a wrong type or an unreadable config each fail the groups that
    depend on them, by name.

    Args:
        branch_path: Branch root (the directory holding .trinity/).
        bypass_rules: Accepted for interface compatibility ONLY and never
            consulted. The trinity contract's Bypass section reads: "None for
            shape rules, by design -- a bypassable memory standard recreates
            the drift it exists to end. A branch that genuinely needs
            different numbers gets a per-branch entry in @memory's config (the
            one source), not a bypass file." Do not add is_bypassed() here.

    Returns:
        ``{"standard": "TRINITY", "score": int, "passed": bool,
        "checks": [nine group dicts]}``.
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
