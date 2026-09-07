# =================== AIPass ====================
# Name: twins.py
# Description: cross-branch test twins by shape identity, and the residue a merge would destroy
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
CROSS-BRANCH TWINS, GATED ON SHAPE AND NEVER ON FILENAME.

THE MEASUREMENT THAT FORCED THIS MODULE. Five test filenames were stamped into
branch after branch - test_json_handler.py, test_json_durability.py,
test_import_dead_cwd.py, test_cli_routing.py, test_help_flag_safety.py - and
between them they hold over a thousand test functions. Read as filenames they
look like one file copied eighteen times. Read as SHAPES they are not: of the
function names that appear in six or more branches, the overwhelming majority
carry a different body in at least one of them. The families were stamped once
and then every copy evolved.

SO THE CONSOLIDATION UNIT IS (name, body fingerprint), NOT (filename). A merge
keyed on filename collapses every diverged copy into whichever one the merger
happened to open, and the coverage the other seventeen branches grew since the
stamp is gone with no diff that shows it leaving. That is the failure this
report exists to make impossible to commit by accident.

WHAT THE THREE OUTPUTS ARE FOR.

  twin_groups               every (name, fingerprint) identity living in 2+
                            branches. The raw duplication surface.
  consolidation_candidates  the identities spanning 6+ branches. These and only
                            these are put forward, because their shape is the
                            same everywhere it appears.
  residue                   for each stamped family, every test in it that is
                            NOT in a candidate group. This is the important
                            output: it is the list of branch-specific behaviour
                            that a filename-keyed merge would destroy.

THE FINGERPRINT IS SHAPE.PY'S, NOT A SECOND ONE. `shape.fingerprint` already
publishes a statement-kind signature with names and literals dropped, it is
already hashed stably across processes, and the inventory's twins column is
already computed from it. A second fingerprinter here would mean two answers to
one question and a future reader with no way to tell which the artifact used.

THIS PHASE NAMES CANDIDATES AND NOTHING ELSE. It removes no test, edits no
file, and emits no verdict. `assert_publishable` refuses to write a report that
carries no caveats, for the reason the sibling `report.py` refuses one with no
blind spots: a limitation a reader has to go looking for will not be found.

WHY `ranking.delete_language_in` IS RUN OVER THE KEYS AND NOT THE VALUES. The
package's rule is that no published CATEGORY may read as a verdict, and the
keys minted here are a closed set that rule belongs on. The values are not:
one of the five stamped families is literally named `test_import_dead_cwd.py`,
and refusing to publish a report because a real filename contains the word
"dead" is the guard convicting the data it was built to describe.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file
from aipass.seedgo.apps.handlers.test_inventory import collection, ranking, shape

#: Where the report is published. Seedgo's own state directory, never the
#: target's - `.seedgo` is seedgo-owned storage under gateway_boundary.
SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"
REPORT_NAME = "test_twins.json"

ARTIFACT_VERSION = "test-twins/1"
TOOL_VERSION = "1.0.0"

#: An identity has to live in at least this many branches to be duplication at
#: all. Two is the floor because one branch holding two copies of a test is a
#: within-branch matter and this report is about the fleet.
TWIN_BRANCHES = 2

#: An identity has to span at least this many branches before it is put forward
#: for consolidation. Six is the threshold the prior measurement used, and it
#: is deliberately a THIRD of the fleet: below it, "the same test everywhere"
#: is a claim about a handful of branches rather than about the fleet.
CONSOLIDATION_BRANCHES = 6

#: The five filenames that were stamped fleet-wide. Named here as data, because
#: the residue block has to be able to say "this family is absent from this
#: tree" rather than reporting a clean zero for a family it never looked at.
STAMPED_FAMILIES: tuple = (
    "test_json_handler.py",
    "test_json_durability.py",
    "test_import_dead_cwd.py",
    "test_cli_routing.py",
    "test_help_flag_safety.py",
)

#: What this report cannot see. Published beside the numbers, and the writer
#: refuses to publish an empty list.
CAVEATS: tuple = (
    "THE FINGERPRINT DROPS NAMES AND LITERALS. Two tests that assert opposite values through the "
    "same statement shape are one identity here. A candidate group is a list for a human to READ "
    "before merging, never an authorisation to merge unread.",
    "SHAPE IDENTITY IS NOT BEHAVIOURAL IDENTITY. Same statement kinds in the same order can call "
    "different production functions entirely. The gate is strictly stronger than a filename match "
    "and strictly weaker than reading the two bodies.",
    "THE RESIDUE OVER-STATES WHAT MUST SURVIVE AND NEVER UNDER-STATES IT. It is computed against "
    "the candidate groups, so a family test that is genuinely redundant with something outside "
    "those groups still shows up as residue. That is the safe direction and it is the chosen one.",
    "ONE CORPUS RULE, NOT EACH BRANCH'S. Only files under each branch's own tests/ directory are "
    "walked. A branch that keeps tests anywhere else contributes nothing to any count here.",
    "STATIC COLLECTION CANNOT SEE EVERY EXCLUSION. A skipif true on the running host, a "
    "collect_ignore built by a loop, and any -k/-m selection are all invisible. Every one of them "
    "makes this report count MORE tests as running than really do.",
    "A BRANCH IS A DIRECTORY THAT HOLDS TESTS, NOT A REGISTRY ENTRY. Nothing here consults the "
    "citizen registry, so an unregistered directory sitting beside the branches is counted as one.",
    "NOTHING HERE DELETES ANYTHING. This phase names candidates. The decision to remove any test "
    "is a human one taken with the two bodies open, and no count in this file substitutes for it.",
)


# =============================================================================
# THE UNIT
# =============================================================================


@dataclass(frozen=True)
class Occurrence:
    """One test function, tagged with the branch it lives in."""

    branch: str
    relpath: str
    name: str
    fingerprint: str
    nodeid: str

    @property
    def path(self) -> str:
        """The branch-qualified file path, which is what a reader opens."""
        return f"{self.branch}/{self.relpath}"

    @property
    def identity(self) -> Tuple[str, str]:
        """The consolidation unit: the name AND the body shape, never one alone."""
        return (self.name, self.fingerprint)

    @property
    def family(self) -> str:
        """The filename this test lives in, which is how a family is named."""
        return self.relpath.rsplit("/", 1)[-1]


@dataclass
class TwinGroup:
    """One identity and every branch it was found in."""

    name: str
    fingerprint: str
    branches: Tuple[str, ...]
    files: Tuple[str, ...]
    tests: int

    @property
    def branch_count(self) -> int:
        """How many distinct branches carry this identity."""
        return len(self.branches)

    def as_dict(self) -> dict:
        """The group as a publishable block."""
        return {
            "name": self.name,
            "fingerprint": self.fingerprint,
            "branch_count": self.branch_count,
            "branches": list(self.branches),
            "files": list(self.files),
            "tests": self.tests,
        }


# =============================================================================
# THE CORPUS
# =============================================================================


def corpus_rules() -> collection.CorpusRules:
    """The collection rules this report walks, fixed rather than discovered.

    `testpaths` is pinned to the branch's own tests/ directory instead of being
    read from a config file, because the twin comparison is only meaningful if
    every branch is measured under the same rule. A per-branch config would let
    one citizen widen its own corpus and read as more duplicated than the rest
    for a reason that has nothing to do with duplication.
    """
    return collection.CorpusRules(
        testpaths=("tests",),
        norecursedirs=collection.DEFAULT_NORECURSEDIRS,
        python_files=collection.DEFAULT_PYTHON_FILES,
        python_classes=collection.DEFAULT_PYTHON_CLASSES,
        python_functions=collection.DEFAULT_PYTHON_FUNCTIONS,
        config_source="twins.py fixed branch corpus",
        config_note="testpaths is pinned to tests/ so every branch is measured under one rule",
    )


def branch_dirs(root: Path) -> List[Tuple[str, Path]]:
    """Every immediate subdirectory of `root` that holds a tests/ directory.

    A directory with no tests/ is not a branch that contributes nothing - it is
    not a branch at all for this measurement, and counting it would put a zero
    in the denominator of every "how many branches carry this" number.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"twin report needs a directory of branches, got: {root}")

    found = [
        (path.name, path)
        for path in sorted(root.iterdir())
        if path.is_dir() and not path.name.startswith((".", "_")) and (path / "tests").is_dir()
    ]

    if not found:
        raise NotADirectoryError(
            f"no immediate subdirectory of {root} holds a tests/ directory - this is the container "
            f"of branches (the fleet's is <repo>/src/aipass), not the repo root. Refusing rather than "
            f"publishing a zero: a cross-branch report that answers 'no twins' because it was pointed "
            f"one level off is worse than one that fails."
        )

    return found


def occurrences(branches: Sequence[Tuple[str, Path]]) -> Tuple[List[Occurrence], Dict[str, int]]:
    """Every test function under every branch, and the per-tree file counts."""
    rules = corpus_rules()
    found: List[Occurrence] = []
    files = 0

    for name, path in branches:
        collected = collection.collect(path, rules)
        files += len(collected.files)
        for func in collected.functions:
            found.append(
                Occurrence(
                    branch=name,
                    relpath=func.relpath,
                    name=func.name,
                    fingerprint=shape.fingerprint(func.node),
                    nodeid=f"{name}/{func.nodeid}",
                )
            )

    return found, {"files": files, "tests": len(found)}


# =============================================================================
# TWIN GROUPS
# =============================================================================


def twin_groups(found: Sequence[Occurrence], minimum_branches: int = TWIN_BRANCHES) -> List[TwinGroup]:
    """Every identity living in `minimum_branches` or more branches.

    Sorted by branch count descending - the widest spread is the one a reader
    should see first - then by test count, then by name and fingerprint so two
    runs over an unchanged tree publish byte-identical order.
    """
    by_identity: Dict[Tuple[str, str], List[Occurrence]] = defaultdict(list)
    for occurrence in found:
        by_identity[occurrence.identity].append(occurrence)

    groups = [
        _group(identity, members)
        for identity, members in by_identity.items()
        if len({member.branch for member in members}) >= minimum_branches
    ]

    return sorted(groups, key=lambda group: (-group.branch_count, -group.tests, group.name, group.fingerprint))


def _group(identity: Tuple[str, str], members: List[Occurrence]) -> TwinGroup:
    """One identity's members turned into a publishable group."""
    name, fingerprint = identity
    return TwinGroup(
        name=name,
        fingerprint=fingerprint,
        branches=tuple(sorted({member.branch for member in members})),
        files=tuple(sorted({member.path for member in members})),
        tests=len(members),
    )


def consolidation_candidates(groups: Sequence[TwinGroup]) -> List[TwinGroup]:
    """The groups wide enough to put forward, in the order `twin_groups` set.

    Nothing narrower is offered. A shape shared by five branches is still a
    shape that thirteen branches disagree with, and the whole finding behind
    this module is that the disagreement is where the real coverage lives.
    """
    return [group for group in groups if group.branch_count >= CONSOLIDATION_BRANCHES]


# =============================================================================
# THE RESIDUE
# =============================================================================


def residue(found: Sequence[Occurrence], candidates: Sequence[TwinGroup]) -> List[dict]:
    """Per stamped family, every test in it that no candidate group covers.

    This is the block that decides whether a consolidation is safe. Each entry
    is a test that shares a filename with the family and shares its shape with
    nobody at fleet scale - branch-specific behaviour, grown after the stamp,
    with nothing else in the fleet standing behind it.
    """
    covered = {(group.name, group.fingerprint) for group in candidates}
    by_family: Dict[str, List[Occurrence]] = defaultdict(list)
    for occurrence in found:
        if occurrence.family in STAMPED_FAMILIES:
            by_family[occurrence.family].append(occurrence)

    return [_family_block(family, by_family.get(family, []), covered) for family in STAMPED_FAMILIES]


def _family_block(family: str, members: List[Occurrence], covered: set) -> dict:
    """One family's totals and the full list of what a merge would destroy.

    `present` is published rather than inferred from a zero: a family absent
    from the tree and a family every one of whose tests is a candidate both
    report a residue of zero, and they mean opposite things.
    """
    survivors = [member for member in members if member.identity not in covered]

    if not members:
        logger.warning(f"[TWINS] stamped family {family} is absent from this tree; its residue is zero because of that")

    return {
        "family": family,
        "present": bool(members),
        "branches": sorted({member.branch for member in members}),
        "files": sorted({member.path for member in members}),
        "tests": len(members),
        "covered_by_candidates": len(members) - len(survivors),
        "residue": len(survivors),
        "entries": [
            {
                "branch": member.branch,
                "file": member.path,
                "name": member.name,
                "fingerprint": member.fingerprint,
                "nodeid": member.nodeid,
            }
            for member in sorted(survivors, key=lambda member: member.nodeid)
        ],
    }


# =============================================================================
# NAME SPREAD - THE COLUMN THAT PROVES THE GATE IS NEEDED
# =============================================================================


def name_spread(found: Sequence[Occurrence], minimum_branches: int = CONSOLIDATION_BRANCHES) -> dict:
    """How many widespread NAMES keep one shape, and how many have diverged.

    This is the number that decides the whole design. If a name in six-plus
    branches nearly always carried one shape, a filename-keyed merge would be
    close enough to safe. It does not, and this block is the receipt: `diverged`
    counts the names a name-keyed consolidation would have flattened.
    """
    by_name: Dict[str, List[Occurrence]] = defaultdict(list)
    for occurrence in found:
        by_name[occurrence.name].append(occurrence)

    widespread = {
        name: members
        for name, members in by_name.items()
        if len({member.branch for member in members}) >= minimum_branches
    }
    identical = [name for name, members in widespread.items() if len({member.fingerprint for member in members}) == 1]

    return {
        "minimum_branches": minimum_branches,
        "names": len(widespread),
        "tests": sum(len(members) for members in widespread.values()),
        "identical_everywhere": len(identical),
        "diverged": len(widespread) - len(identical),
        "identical_names": sorted(identical),
    }


# =============================================================================
# THE REPORT
# =============================================================================


def build(root: Path) -> dict:
    """The whole twin report for a directory of branches."""
    root = Path(root).resolve()
    branches = branch_dirs(root)
    found, counts = occurrences(branches)
    groups = twin_groups(found)
    candidates = consolidation_candidates(groups)
    families = residue(found, candidates)
    spread = name_spread(found)

    report = {
        "artifact_version": ARTIFACT_VERSION,
        "tool_version": TOOL_VERSION,
        "root": str(root),
        "corpus": corpus_rules().as_dict(),
        "caveats": list(CAVEATS),
        "branches": [name for name, _ in branches],
        "name_spread": spread,
        "twin_groups": [group.as_dict() for group in groups],
        "consolidation_candidates": [group.as_dict() for group in candidates],
        "residue": families,
    }
    report["summary"] = _summary(counts, report, groups, candidates, families, spread)
    return report


def _summary(
    counts: Dict[str, int],
    report: dict,
    groups: Sequence[TwinGroup],
    candidates: Sequence[TwinGroup],
    families: Sequence[dict],
    spread: dict,
) -> dict:
    """The counts a reader checks this run against the last one with."""
    return {
        "branches": len(report["branches"]),
        "files": counts["files"],
        "tests": counts["tests"],
        "twin_groups": len(groups),
        "twin_group_tests": sum(group.tests for group in groups),
        "twin_group_minimum_branches": TWIN_BRANCHES,
        "consolidation_candidates": len(candidates),
        "consolidation_candidate_tests": sum(group.tests for group in candidates),
        "consolidation_minimum_branches": CONSOLIDATION_BRANCHES,
        "widespread_names": spread["names"],
        "widespread_name_tests": spread["tests"],
        "widespread_names_identical_everywhere": spread["identical_everywhere"],
        "widespread_names_diverged": spread["diverged"],
        "stamped_family_tests": sum(family["tests"] for family in families),
        "stamped_family_residue": sum(family["residue"] for family in families),
        "stamped_families_absent": [family["family"] for family in families if not family["present"]],
    }


# =============================================================================
# PUBLICATION
# =============================================================================


def publish(report: dict, directory: Optional[Path] = None) -> Path:
    """Write the report and return the path it landed on."""
    assert_publishable(report)

    directory = Path(directory) if directory else ARTIFACT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / REPORT_NAME
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    json_handler.log_operation(
        "test_twins_published",
        {
            "root": report["root"],
            "candidates": report["summary"]["consolidation_candidates"],
            "residue": report["summary"]["stamped_family_residue"],
            "artifact": str(target),
        },
    )
    logger.info(
        f"[TWINS] published {report['summary']['consolidation_candidates']} consolidation candidates "
        f"and {report['summary']['stamped_family_residue']} residue tests to {target}"
    )
    return target


def assert_publishable(report: dict) -> None:
    """Refuse a report with no caveats, or with verdict vocabulary in a key."""
    if not report.get("caveats"):
        raise ValueError("refusing to publish a twin report that declares no caveats")

    offenders = ranking.delete_language_in(" ".join(sorted(_keys(report))))
    if offenders:
        raise ValueError(f"refusing to publish: delete-family vocabulary in a published key: {offenders}")


def _keys(value, seen: Optional[List[str]] = None) -> List[str]:
    """Every key name the report publishes, at any depth.

    Keys only. The values carry filenames the fleet chose, one of which is
    `test_import_dead_cwd.py`, and a guard that refuses a report because the
    data contains a word is a guard that has started editing the measurement.
    """
    seen = seen if seen is not None else []

    if isinstance(value, dict):
        for key, child in value.items():
            seen.append(str(key))
            _keys(child, seen)
    elif isinstance(value, list):
        for child in value:
            _keys(child, seen)

    return seen
