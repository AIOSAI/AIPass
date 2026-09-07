# =================== AIPass ====================
# Name: cycle.py
# Description: the shadow-cycle document - three passes reduced to one screen, and published
# Version: 1.0.0
# Created: 2026-09-02
# Modified: 2026-09-02
# =============================================

"""
ONE DOCUMENT AND ONE SCREEN, BUILT FROM THE SAME NUMBERS.

Three passes run in a cycle - the v5 shadow score, the ranked test inventory,
the cross-branch twin census - and each already publishes its own artifact.
What did not exist was the joining document: the small file that says which
three runs belong to the same week, and where each one's evidence is.

THE MAIL CARRIES PATHS, NEVER THE REPORT. The twin report alone is half a
megabyte and the inventory's row file is twenty-eight; the whole point of the
cycle is that a reader can decide from one screen whether this week is worth
opening. `one_screen` renders exactly what is mailed and exactly what the verb
prints, from the document, so the console and the inbox can never disagree
about a number - a second renderer is a second answer.

WHY THE SUMMARY IS PUBLISHED AS WELL AS SENT. Mail is delivered once and read
by one recipient. `.seedgo/shadow_cycle.json` is the record the NEXT cycle is
compared against, and it holds the machine-readable form of every headline
count, so a later reader can diff two weeks without parsing prose.

REFUSES TO PUBLISH WITHOUT ITS CAVEATS, the same rule its two sibling reports
carry: a limitation a reader has to go looking for will not be found, and the
loudest thing this document must say is that the score in its first block gates
nothing at all.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.module_root import module_file

MODULE_NAME = "shadow_cycle.cycle"

#: Seedgo's own state directory - never the measured tree's. `.seedgo` is
#: seedgo-owned storage under the gateway_boundary standard.
SEEDGO_ROOT = module_file(__file__).parents[3]
ARTIFACT_DIR = SEEDGO_ROOT / ".seedgo"

#: The joining document one cycle publishes.
DOCUMENT_NAME = "shadow_cycle.json"

#: The shadow score's complete result set. The PACK is in the name so a cycle
#: run against a second pack can never overwrite the first one's evidence -
#: the same rule `last_audit_{branch}.json` follows for scope.
SCORE_NAME = "shadow_cycle_score_{pack}.json"

ARTIFACT_VERSION = "shadow-cycle/1"
TOOL_VERSION = "1.0.0"

#: What this document is not, published beside the numbers. The writer refuses
#: an empty list, so no cycle can ever be quoted without them.
CAVEATS: tuple = (
    "THE SCORE IN BLOCK 1 GATES NOTHING. The pytest_quality pack declares itself a SHADOW "
    "pack: it is measured weekly so its numbers can be diffed against the calibrated v4 "
    "triage, and until that diff is ruled on, no branch passes or fails on it.",
    "THREE PASSES, THREE CORPUS DEFINITIONS. The score walks the checker pack's file scope, "
    "the inventory walks the repo-root pytest config, and the twin census walks immediate "
    "children of the aipass package. Their test counts are not expected to match, and a "
    "difference between them is not a finding.",
    "THE COUNTS ARE A SERIES, NOT A VERDICT. One cycle in isolation says almost nothing; the "
    "instrument is the WEEK-ON-WEEK difference. Nothing in this document authorises deleting, "
    "merging or rewriting a single test.",
    "A SHADOW RUN EVICTS THE AIPASS-PACK AUDIT CACHE. The incremental cache is keyed on branch "
    "name while its validity stamp includes the pack, so the next `audit aipass` after a cycle "
    "is a cold full scan - slower, never wrong.",
)


# =============================================================================
# PATHS
# =============================================================================


def document_path(directory: Optional[Path] = None) -> Path:
    """Where the joining document is written."""
    return (Path(directory) if directory else ARTIFACT_DIR) / DOCUMENT_NAME


def score_artifact_path(pack: str, directory: Optional[Path] = None) -> Path:
    """Where one pack's complete shadow result set is written."""
    return (Path(directory) if directory else ARTIFACT_DIR) / SCORE_NAME.format(pack=pack)


# =============================================================================
# THE BLOCKS
# =============================================================================


def inventory_block(summary: dict, paths: Dict[str, Path]) -> dict:
    """The ranked-inventory headline counts and where its three files landed."""
    corpus = summary["corpus_definition"]
    return {
        "root": summary["run_identity"]["root"],
        "head": summary["run_identity"]["head"],
        "functions": corpus["functions_found"],
        "files": corpus["files_matched"],
        "functions_that_run": corpus["functions_that_run"],
        "functions_that_never_run": corpus["functions_that_never_run"],
        "assertion_shape": dict(summary["assertion_shape"]["counts"]),
        "artifacts": {name: str(path) for name, path in paths.items()},
    }


def twins_block(report: dict, artifact: Path) -> dict:
    """The twin census headline counts, residue included, and its artifact."""
    summary = report["summary"]
    return {
        "container": report["root"],
        "branches": summary["branches"],
        "tests": summary["tests"],
        "twin_groups": summary["twin_groups"],
        "consolidation_candidates": summary["consolidation_candidates"],
        "consolidation_candidate_tests": summary["consolidation_candidate_tests"],
        "stamped_family_tests": summary["stamped_family_tests"],
        "stamped_family_residue": summary["stamped_family_residue"],
        "artifact": str(artifact),
    }


def build(score: dict, inventory: dict, twins: dict, elapsed: float, now: Optional[float] = None) -> dict:
    """The whole cycle as one document, ready to publish and to render."""
    stamped = now if now is not None else time.time()
    return {
        "artifact_version": ARTIFACT_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at_epoch": int(stamped),
        "generated_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(stamped)),
        "elapsed_seconds": round(elapsed, 1),
        "caveats": list(CAVEATS),
        "shadow_score": score,
        "test_inventory": inventory,
        "twins": twins,
    }


# =============================================================================
# PUBLICATION
# =============================================================================


def publish(document: dict, directory: Optional[Path] = None) -> Path:
    """Write the joining document and return the path it landed on."""
    assert_publishable(document)

    target = document_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")

    json_handler.log_operation(
        "shadow_cycle_published",
        {
            "pack": document["shadow_score"]["pack"],
            "average": document["shadow_score"]["average"],
            "functions": document["test_inventory"]["functions"],
            "candidates": document["twins"]["consolidation_candidates"],
            "artifact": str(target),
        },
        module_name=MODULE_NAME,
    )
    logger.info(f"[SHADOW_CYCLE] published the cycle document to {target}")
    return target


def assert_publishable(document: dict) -> None:
    """Refuse a cycle that declares no caveats, or one whose score claims to gate.

    Both refusals are about the same sentence. The first block of this document
    is a fleet-wide compliance percentage, and a percentage published without
    the word SHADOW beside it will be read as a gate by the next person who
    quotes it.
    """
    if not document.get("caveats"):
        raise ValueError("refusing to publish a shadow cycle that declares no caveats")

    if document.get("shadow_score", {}).get("gating") is not False:
        raise ValueError("refusing to publish a shadow cycle whose score does not declare itself non-gating")


# =============================================================================
# THE ONE SCREEN
# =============================================================================


def subject(document: dict) -> str:
    """The mail subject: the date and the three numbers worth a glance."""
    score = document["shadow_score"]
    return (
        f"Shadow cycle {document['generated_at']} - {score['pack']} {score['average']}% shadow, "
        f"{document['test_inventory']['functions']} tests, "
        f"{document['twins']['consolidation_candidates']} consolidation candidates"
    )


def one_screen(document: dict) -> str:
    """The whole cycle as plain text: headline counts and artifact paths only.

    Plain text with no Rich markup, because the same string is printed to a
    console AND handed to ai_mail, and a body that renders in one and shows its
    tags in the other is two outputs pretending to be one.
    """
    lines: List[str] = [
        f"SHADOW CYCLE - {document['generated_at']} - {document['elapsed_seconds']:.0f}s",
        "",
        "Three measurement passes over the fleet. Nothing here gates anything.",
        "",
    ]
    lines.extend(_score_lines(document["shadow_score"]))
    lines.append("")
    lines.extend(_inventory_lines(document["test_inventory"]))
    lines.append("")
    lines.extend(_twins_lines(document["twins"]))
    lines.append("")
    lines.append(f"cycle document : {document_path()}")
    lines.append("")
    lines.append("FYI only. It authorises nothing - the artifacts above are the evidence.")
    return "\n".join(lines)


def _score_lines(score: dict) -> List[str]:
    """Block 1 - the shadow score, with the word SHADOW on the heading itself."""
    weakest = " . ".join(f"{name} {value}%" for name, value in score["weakest_standards"])
    attention = (
        " . ".join(f"{name} {value}%" for name, value in score["branches_below_attention"])
        or f"none under {score['attention_below']}%"
    )
    return [
        f"1. V5 SHADOW SCORE - pack {score['pack']}, SCORING NOT GATING",
        f"   {score['branches']} branches, {score['standards']} standards, fleet average {score['average']}%",
        f"   weakest    : {weakest}",
        f"   attention  : {attention}",
        f"   artifact   : {score['artifact']}",
    ]


def _inventory_lines(inventory: dict) -> List[str]:
    """Block 2 - the ranked inventory, and the three files it publishes."""
    counts = inventory["assertion_shape"]
    shapes = " . ".join(f"{name} {counts[name]}" for name in sorted(counts))
    artifacts = inventory["artifacts"]
    return [
        "2. TEST INVENTORY - every test function, ranked for READING",
        f"   {inventory['functions']} functions in {inventory['files']} files",
        f"   {inventory['functions_that_run']} run . {inventory['functions_that_never_run']} never do",
        f"   shape      : {shapes}",
        f"   summary    : {artifacts.get('summary')}",
        f"   readable   : {artifacts.get('readable')}",
        f"   rows       : {artifacts.get('rows')}",
    ]


def _twins_lines(twins: dict) -> List[str]:
    """Block 3 - the twin census, residue first among equals."""
    return [
        "3. TWINS - cross-branch identities, keyed on SHAPE and never on filename",
        f"   {twins['tests']} test functions over {twins['branches']} branches",
        f"   {twins['consolidation_candidates']} consolidation candidates "
        f"({twins['consolidation_candidate_tests']} tests) - these and ONLY these",
        f"   residue    : {twins['stamped_family_residue']} of {twins['stamped_family_tests']} "
        f"stamped-family tests a filename-keyed merge would destroy",
        f"   artifact   : {twins['artifact']}",
    ]
