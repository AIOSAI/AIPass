# =================== AIPass ====================
# Name: nominators.py
# Description: discovers and runs the pack's static nominators over one corpus
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The static tier's orchestrator. Discovers nominators, parses once, runs each.

A nominator never defines `check_module`/`check_branch`, so `discover_checkers()`
cannot see it; a module defining either is rejected. A failed nominator publishes
`not_applicable` with the reason, never an empty `measured` (Law S1).
"""

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus
from aipass.seedgo.apps.handlers.module_root import module_file

PACK_DIR = module_file(__file__).parent
NOMINATOR_GLOB = "*_check.py"

REQUIRED_ATTRIBUTES: tuple = ("GROUP", "SPECIFICATION", "nominate")

#: Either would make the module visible to the audit's file-walk scoring engine.
FORBIDDEN_ATTRIBUTES: tuple = ("check_module", "check_branch")

#: Searched in order; an unknown external target falls back to the whole tree.
TEST_DIRS: tuple = ("tests", "test")


class NominatorError(Exception):
    """A module in the pack directory that may not be registered as a nominator."""


def _load(path: Path) -> ModuleType:
    """Import one nominator module, as THE module and not as a copy of it.

    Through the package, so the object that runs is the one every importer holds; by path
    makes a second module object. A foreign pack directory is still loaded by path.
    """
    if path.parent == PACK_DIR and __package__:
        return importlib.import_module(f"{__package__}.{path.stem}")

    spec = importlib.util.spec_from_file_location(f"audit_tests_nominator_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise NominatorError(f"{path.name}: could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shape_problems(module: ModuleType) -> List[str]:
    """Every way a module fails the nominator shape, reported at once."""
    problems: List[str] = []

    for attribute in REQUIRED_ATTRIBUTES:
        if not hasattr(module, attribute):
            problems.append(f"missing {attribute}")

    if hasattr(module, "nominate") and not callable(getattr(module, "nominate")):
        problems.append("nominate is not callable")

    for attribute in FORBIDDEN_ATTRIBUTES:
        if hasattr(module, attribute):
            problems.append(
                f"defines {attribute}() - that would make this nominator visible to the audit's "
                f"file-walk scoring engine, which is the shape gate this lane depends on"
            )

    return problems


def discover(pack_dir: Path = PACK_DIR) -> Tuple[Dict[str, ModuleType], List[str]]:
    """Find every nominator in the pack. Returns `(by_group, rejections)`.

    A rejected module is never silently dropped.
    """
    found: Dict[str, ModuleType] = {}
    rejections: List[str] = []

    for path in sorted(pack_dir.glob(NOMINATOR_GLOB)):
        try:
            module = _load(path)
        except Exception as exc:
            logger.warning(f"[AUDIT-TESTS] nominator {path.name} failed to import: {exc}")
            rejections.append(f"{path.name}: failed to import ({type(exc).__name__}: {exc})")
            continue

        problems = shape_problems(module)
        if problems:
            rejections.append(f"{path.name}: {'; '.join(problems)}")
            continue

        group = str(getattr(module, "GROUP"))
        if group in found:
            rejections.append(f"{path.name}: group '{group}' is already claimed")
            continue
        found[group] = module

    if rejections:
        json_handler.log_operation("nominators_rejected", {"count": len(rejections), "rejections": rejections})

    return found, rejections


def declared_groups(pack_dir: Path = PACK_DIR) -> List[str]:
    """The bare group names the static tier contributes, in published order."""
    found, _ = discover(pack_dir)
    return sorted(found)


def build_corpus(target_root: Path) -> corpus.Corpus:
    """Parse the target's test corpus once, for every nominator to share."""
    scanned = corpus.build(target_root, TEST_DIRS)
    if not scanned.files:
        scanned = corpus.build(target_root)
    return scanned


def _production_limits(module: ModuleType, scanned: corpus.Corpus) -> List[str]:
    """The corpus's unreadable-production count, for rules that read production.

    Only for `READS_PRODUCTION` rules: a limit that is not true is the same defect as a missing one.
    """
    if not getattr(module, "READS_PRODUCTION", False):
        return []
    return scanned.production_limits


def _measured_group(module: ModuleType, rows: List[dict], scanned: corpus.Corpus) -> dict:
    """A group document for a nominator that ran."""
    specification = dict(getattr(module, "SPECIFICATION"))
    return {
        "tier": "static",
        "kind": "nominate_only",
        "status": "measured",
        "score": None,
        "rule": specification.get("rule", ""),
        "species": list(specification.get("species", [])),
        "nominations": rows,
        "nomination_count": len(rows),
        "files_scanned": len(scanned.files),
        "units_scanned": scanned.unit_count,
        "unparseable_files": list(scanned.unparseable),
        "flags": list(specification.get("flags", [])),
        "exempts": list(specification.get("exempts", [])),
        "limits": list(specification.get("limits", [])) + _production_limits(module, scanned),
        "evidence": specification.get("evidence", ""),
        "fix": specification.get("fix", ""),
        "note": (
            "NOMINATION, NOT CONVICTION (Law M1). A row here says a test is suspect; it never "
            "says a test is worthless, and the M11 deletion probe that would settle whether a "
            "flagged test is safe to remove is not built in this release."
        ),
    }


def _not_applicable(module: ModuleType, reason: str) -> dict:
    """A group document for a nominator that could not run."""
    specification = dict(getattr(module, "SPECIFICATION", {}))
    return {
        "tier": "static",
        "kind": "nominate_only",
        "status": "not_applicable",
        "reason": reason,
        "score": None,
        "rule": specification.get("rule", ""),
        "species": list(specification.get("species", [])),
        "nominations": [],
        "nomination_count": 0,
    }


def run(target_root: Path, pack_dir: Path = PACK_DIR) -> Dict[str, dict]:
    """Run every discovered nominator over one target. Returns group documents.

    `target_root` is the copy, never the real tree (Law M10).
    """
    found, rejections = discover(pack_dir)
    scanned = build_corpus(Path(target_root))
    groups: Dict[str, dict] = {}

    for group, module in sorted(found.items()):
        try:
            rows = list(module.nominate(scanned))
        except Exception as exc:
            # Never an empty measured group: the reason travels into the artifact.
            logger.warning(f"[AUDIT-TESTS] nominator '{group}' could not run: {type(exc).__name__}: {exc}")
            groups[group] = _not_applicable(module, f"{type(exc).__name__}: {exc}")
            continue
        groups[group] = _measured_group(module, rows, scanned)

    json_handler.log_operation(
        "static_tier_completed",
        {
            "groups": len(groups),
            "files_scanned": len(scanned.files),
            "units_scanned": scanned.unit_count,
            "unparseable": len(scanned.unparseable),
            "nominations": sum(document.get("nomination_count", 0) for document in groups.values()),
            "per_group": {
                group: document.get("nomination_count", document.get("status"))
                for group, document in sorted(groups.items())
            },
            "production_unparseable": len(scanned.production_unparseable),
            "rejections": rejections,
        },
    )
    return groups
