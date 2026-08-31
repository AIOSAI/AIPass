# =================== AIPass ====================
# Name: nominators.py
# Description: discovers and runs the pack's static nominators over one corpus
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The static tier's orchestrator. Discovers nominators, parses once, runs each.

THE SHAPE GATE, APPLIED A SECOND TIME. A nominator lives in `<name>_check.py`
beside the adapter, and the audit engine's `discover_checkers()` keeps a
module only if it defines `check_module` or `check_branch`. A nominator
defines `nominate()` and NEITHER of those, so the audit's scoring engine
cannot see it — with zero change to that engine, and without depending on any
manifest flag that CI does not read. This is the same gate that keeps
`adapter.py` invisible, and it is enforced here rather than assumed: a module
in this directory that defines either function is REJECTED with a reason.

ONE PARSE, NINE RULES. Nine nominators over an eighteen-branch fleet would
otherwise parse every test file nine times, and the research budget for the
whole static tier is under four seconds fleet-wide.

A NOMINATOR THAT FAILS PRODUCES A `not_applicable` GROUP WITH THE REASON, and
never an empty `measured` one. This is Law S1 at the group level: a rule that
crashed and a rule that found nothing must never produce the same document.
Ruff's absence is the live case — the linter is not guaranteed present on a
machine measuring an external target, and a group reporting clean because the
tool was missing is exactly the lie this lane exists to stop telling.

CONTRACT 0 (design section 4.2a-bis) BINDS THIS FILE. The static tier may
never be retired on the grounds that execution got good. Mutation's unit of
judgement is the MUTANT, not the TEST, so any healthy test on a symbol masks
every weak one beside it; a per-mutant verdict structurally cannot name a
per-test defect. Measured, not asserted: a MIRROR-EXPECT test survived a
constant mutant while its spelled-out twin killed it, so nothing was reported
at all.
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

#: Where nominators live, and the filename shape that declares one.
PACK_DIR = module_file(__file__).parent
NOMINATOR_GLOB = "*_check.py"

#: What a nominator must expose.
REQUIRED_ATTRIBUTES: tuple = ("GROUP", "SPECIFICATION", "nominate")

#: What a nominator may never expose. Either of these would make the module
#: visible to the audit's file-walk scoring engine.
FORBIDDEN_ATTRIBUTES: tuple = ("check_module", "check_branch")

#: Directories a target keeps its tests in. Searched in order; an unknown
#: external target falls back to the whole tree.
TEST_DIRS: tuple = ("tests", "test")


class NominatorError(Exception):
    """A module in the pack directory that may not be registered as a nominator."""


# =============================================================================
# DISCOVERY
# =============================================================================


def _load(path: Path) -> ModuleType:
    """Import one nominator module, as THE module and not as a copy of it.

    A sibling of this file is imported THROUGH THE PACKAGE, so the object the
    orchestrator runs is the object every other importer already holds. Loading
    the same source by path instead produces a SECOND module with the same
    code: `sys.modules` never sees it, so discovery re-executes all nine on
    every call, and anything that reads a nominator's `SPECIFICATION` through
    the package is reading a different object than the one that ran. Two module
    objects for one rule is the same species of defect as two statements of one
    rule, which is why `render_spec` exists.

    A pack directory that is NOT this package's own is still supported and is
    loaded by path — a second ecosystem ships its own pack, and a pack that
    cannot be imported must not silently disappear.
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

    A rejected module is never silently dropped: a nominator that vanished
    without explanation is how a fleet quietly stops being measured on a
    species it believes is covered.
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


# =============================================================================
# RUNNING
# =============================================================================


def build_corpus(target_root: Path) -> corpus.Corpus:
    """Parse the target's test corpus once, for every nominator to share."""
    scanned = corpus.build(target_root, TEST_DIRS)
    if not scanned.files:
        scanned = corpus.build(target_root)
    return scanned


def _production_limits(module: ModuleType, scanned: corpus.Corpus) -> List[str]:
    """The corpus's unreadable-production count, for rules that read production.

    Only merged for a rule that declares `READS_PRODUCTION`. A rule whose whole
    subject is the test corpus is not made less complete by a production file
    that will not parse, and adding the line anyway would be a limit that is
    not true - which is the same defect as omitting one that is.
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
    """A group document for a nominator that could not run.

    Law S1: not-run is `not_applicable` WITH A REASON, never 0 and never an
    empty `measured`. A rule that crashed and a rule that found nothing must
    never produce the same document.
    """
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

    `target_root` is the COPY, never the real tree (Law M10). The nominators
    only read, but pointing them at the real tree would make the static tier
    the one part of the lane that measured a different program from the rest
    of it — and a rule reading one tree while the gate reads another is a
    measurement nobody can reconcile.
    """
    found, rejections = discover(pack_dir)
    scanned = build_corpus(Path(target_root))
    groups: Dict[str, dict] = {}

    for group, module in sorted(found.items()):
        try:
            rows = list(module.nominate(scanned))
        except Exception as exc:
            # Never converted into an empty measured group. The reason travels
            # into the artifact so a reader can tell a rule that found nothing
            # from a rule that could not look.
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
